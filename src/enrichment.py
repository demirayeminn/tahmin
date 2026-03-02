"""
enrichment.py — Entegra verisiyle product_master ve reorder tablolarını zenginleştir.

REF-13 zenginleştirme kuralları:
  - JOIN: product_master.barkod == entegra.barkod
  - Eşleşmeyen sipariş barkodları → entegra_eslesme=False flag
  - Eşleşmeyen Entegra ürünleri → "satışı olmayan stok" raporu
  - mevcut_stok 0 olan aktif ürünler → stok_out_flag=True
  - product_master.parquet güncellenir (yeni kolonlar eklenir, eskiler korunur)
  - Reorder tablosu gerçek mevcut_stok ile yeniden hesaplanır

REF-03 ABC v2 (ciro bazlı):
  - ciro = toplam_adet × alis_fiyati
  - abc_ciro: A=%80, B=%95, C=%100 (kümülatif ciro bazlı)
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    ABC_A_ESIK,
    ABC_B_ESIK,
    DATA_PROCESSED_DIR,
    HEDEF_GUN,
    LEAD_TIME_GUN,
    LOG_FORMAT,
    LOG_LEVEL,
    REVIEW_PERIOD_GUN,
    SERVIS_SEVIYE,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

REORDER_PARQUET = DATA_PROCESSED_DIR / "reorder.parquet"
PRODUCT_MASTER_PARQUET = DATA_PROCESSED_DIR / "product_master.parquet"


# ─── ABC v2: ciro bazlı ──────────────────────────────────────────────────────

def _hesapla_abc_ciro(df: pd.DataFrame) -> pd.Series:
    """
    Ciro bazlı ABC sınıflaması.
    df'de 'ciro' kolonu olmalı.
    """
    df_s = df[["barkod", "ciro"]].copy().sort_values("ciro", ascending=False)
    df_s["kumulatif_oran"] = df_s["ciro"].cumsum() / df_s["ciro"].sum()
    df_s["abc_ciro"] = "C"
    df_s.loc[df_s["kumulatif_oran"] <= ABC_A_ESIK, "abc_ciro"] = "A"
    df_s.loc[
        (df_s["kumulatif_oran"] > ABC_A_ESIK) & (df_s["kumulatif_oran"] <= ABC_B_ESIK),
        "abc_ciro",
    ] = "B"
    return df_s.set_index("barkod")["abc_ciro"]


# ─── Reorder yeniden hesaplama (gerçek stok ile) ─────────────────────────────

def _reorder_yeniden_hesapla(reorder_df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mevcut reorder tablosunu gerçek mevcut_stok değerleriyle günceller.
    REF-06 formülleri uygulanır.
    """
    stok_map = master_df.set_index("barkod")["mevcut_stok"].to_dict()
    z_map = master_df.set_index("barkod")["abc_sinifi"].map(SERVIS_SEVIYE).to_dict()

    df = reorder_df.copy()

    def _hesapla_satir(row: pd.Series) -> pd.Series:
        barkod = row["barkod"]
        gunluk_ort = row.get("gunluk_ort", 0)
        std_talep = row.get("std_talep", 0) if "std_talep" in row else 0
        mevcut = stok_map.get(barkod, 0)
        z = z_map.get(barkod, 1.28)
        abc = master_df.set_index("barkod")["abc_sinifi"].get(barkod, "C")

        guvenlik = z * std_talep * np.sqrt(LEAD_TIME_GUN + REVIEW_PERIOD_GUN)
        hedef = gunluk_ort * HEDEF_GUN + guvenlik
        oneri = max(0, hedef - mevcut)
        kalan_gun = (mevcut / gunluk_ort) if gunluk_ort > 0 else None

        return pd.Series(
            {
                "mevcut_stok": mevcut,
                "onerilen_stok": round(oneri),
                "guvenlik_stok": round(guvenlik, 1),
                "beklenen_tukenme_gun": round(kalan_gun, 1) if kalan_gun is not None else None,
            }
        )

    yeni = df.apply(_hesapla_satir, axis=1)
    df["mevcut_stok"] = yeni["mevcut_stok"]
    df["onerilen_stok"] = yeni["onerilen_stok"]
    df["guvenlik_stok"] = yeni["guvenlik_stok"]
    df["beklenen_tukenme_gun"] = yeni["beklenen_tukenme_gun"]

    # Risk bandı güncelle
    def _risk(row: pd.Series) -> str:
        if not row.get("aktif", True):
            return "Gri"
        kalan = row.get("beklenen_tukenme_gun")
        if kalan is None:
            return "Yeşil"
        if kalan <= 7:
            return "Kırmızı"
        if kalan <= 30:
            return "Turuncu"
        return "Yeşil"

    df["risk_bandi"] = df.apply(_risk, axis=1)
    return df


# ─── Ana zenginleştirme fonksiyonu ────────────────────────────────────────────

def zenginlestir(entegra_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Entegra verisiyle product_master ve reorder tablolarını zenginleştirir.

    Args:
        entegra_df: entegra_api.cek_entegra_urunleri() çıktısı.

    Returns:
        dict: {'master': DataFrame, 'reorder': DataFrame, 'satissiz_stok': DataFrame}
    """
    if entegra_df.empty:
        log.error("Entegra verisi boş. Zenginleştirme atlandı.")
        return {}

    master = pd.read_parquet(PRODUCT_MASTER_PARQUET)
    reorder = pd.read_parquet(REORDER_PARQUET)

    # Daha onceki calismalardan kalan *_entegra kolonlarini temizle
    entegra_suffix_cols = [c for c in master.columns if c.endswith("_entegra")]
    if entegra_suffix_cols:
        master = master.drop(columns=entegra_suffix_cols)

    log.info("product_master: %d SKU | Entegra: %d ürün", len(master), len(entegra_df))

    # ── JOIN ──────────────────────────────────────────────────────────────────
    entegra_cols = [
        "barkod", "mevcut_stok", "alis_fiyati", "kategori", "marka",
        "entegra_urun_adi", "ilan_durumu", "kritik_stok_miktari",
        "trendyol_fiyat", "hb_fiyat", "entegra_son_guncelleme",
    ]
    entegra_mevcut = [c for c in entegra_cols if c in entegra_df.columns]
    e = entegra_df[entegra_mevcut].drop_duplicates("barkod")

    master = master.merge(e, on="barkod", how="left", suffixes=("", "_entegra"))

    # Eşleşme flag'i
    master["entegra_eslesme"] = master["entegra_son_guncelleme"].notna()

    # Eşleşmeyen Entegra ürünleri → "satışı olmayan stok"
    eslesmeyen_mask = ~e["barkod"].isin(master["barkod"])
    satissiz_stok = e[eslesmeyen_mask].copy()
    log.info(
        "Eşleşen: %d | Eşleşmeyen sipariş barkodu: %d | Satışı olmayan Entegra stok: %d",
        master["entegra_eslesme"].sum(),
        (~master["entegra_eslesme"]).sum(),
        len(satissiz_stok),
    )

    # mevcut_stok varsayım fallback
    if "mevcut_stok" not in master.columns:
        master["mevcut_stok"] = 0
    master["mevcut_stok"] = master["mevcut_stok"].fillna(0).astype(int)

    # Stok-out flag: aktif + stok=0
    master["stok_out_flag"] = (master["aktif"] == True) & (master["mevcut_stok"] == 0)

    # ── Ciro hesapla ──────────────────────────────────────────────────────────
    fiyat_kol = None
    for k in ["alis_fiyati", "trendyol_fiyat", "hb_fiyat"]:
        if k in master.columns and master[k].gt(0).any():
            fiyat_kol = k
            break

    if fiyat_kol:
        master["ciro"] = master["toplam_adet"] * master[fiyat_kol].fillna(0)
        abc_ciro = _hesapla_abc_ciro(master)
        master["abc_ciro"] = master["barkod"].map(abc_ciro)
        log.info("ABC v2 (ciro) hesaplandı, fiyat kolonu: %s", fiyat_kol)
    else:
        master["ciro"] = 0.0
        master["abc_ciro"] = master.get("abc_sinifi", "C")
        log.warning("Fiyat bilgisi bulunamadı. abc_ciro = abc_sinifi (adet bazlı) kullanılıyor.")

    # ── kalan_gun hesapla ─────────────────────────────────────────────────────
    master["kalan_gun"] = master.apply(
        lambda r: round(r["mevcut_stok"] / r["gunluk_ort_adet"], 1)
        if r["gunluk_ort_adet"] > 0 else None,
        axis=1,
    )

    # ── Kaydet ────────────────────────────────────────────────────────────────
    master.to_parquet(PRODUCT_MASTER_PARQUET, index=False)
    log.info("product_master.parquet güncellendi: %d satır", len(master))

    # ── Reorder yeniden hesapla ───────────────────────────────────────────────
    reorder_yeni = _reorder_yeniden_hesapla(reorder, master)
    reorder_yeni.to_parquet(REORDER_PARQUET, index=False)
    log.info("reorder.parquet güncellendi (gerçek stok ile): %d satır", len(reorder_yeni))

    return {
        "master": master,
        "reorder": reorder_yeni,
        "satissiz_stok": satissiz_stok,
    }


if __name__ == "__main__":
    from src.entegra_api import yukle_entegra_urunleri

    entegra_df = yukle_entegra_urunleri()
    if entegra_df.empty:
        print("Önce `python -m src.entegra_api` çalıştırın.")
    else:
        sonuc = zenginlestir(entegra_df)
        print(sonuc["master"][["barkod", "kanonik_ad", "mevcut_stok", "abc_ciro", "kalan_gun"]].head(10))
        print(f"\nSatışı olmayan Entegra stok: {len(sonuc['satissiz_stok'])} ürün")
