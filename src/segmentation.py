"""
segmentation.py — ABC sınıflandırma, talep tipi tespiti ve SKU sağlık skoru.

REF-03:
  ABC  → adet bazlı kümülatif %80/%95/%100
  Talep tipi → CV (coefficient of variation) + ADI (average demand interval)
  SKU Sağlık Skoru → 0-100 arası bileşik skor
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
    ADI_ESIK,
    CV_ESIK,
    LOG_FORMAT,
    LOG_LEVEL,
    MIN_SATIS_GUN,
    PRODUCT_MASTER_PARQUET,
    SAGLIK_AGIRLIK,
    DATA_PROCESSED_DIR,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)


# ─── ABC Sınıflandırma ───────────────────────────────────────────────────────

def abc_siniflandir(master: pd.DataFrame) -> pd.DataFrame:
    """
    Adet bazlı ABC sınıflandırması uygular.

    A: kümülatif %80 | B: %80-95 | C: %95-100

    Args:
        master: 'toplam_adet' sütunu olan ürün master DataFrame'i.

    Returns:
        'abc_sinifi' sütunu eklenmiş DataFrame.
    """
    df = master.copy()
    df = df.sort_values("toplam_adet", ascending=False)
    df["_kumulatif_pay"] = df["toplam_adet"].cumsum() / df["toplam_adet"].sum()

    def _sinif(pay: float) -> str:
        if pay <= ABC_A_ESIK:
            return "A"
        elif pay <= ABC_B_ESIK:
            return "B"
        return "C"

    df["abc_sinifi"] = df["_kumulatif_pay"].apply(_sinif)
    df = df.drop(columns=["_kumulatif_pay"])

    dagilim = df["abc_sinifi"].value_counts().to_dict()
    log.info("ABC dağılımı: %s", dagilim)
    return df


# ─── Talep Tipi Tespiti ───────────────────────────────────────────────────────

def _hesapla_cv_adi(
    daily: pd.DataFrame,
    barkod: str,
) -> tuple[float, float, int]:
    """
    Bir barkod için CV ve ADI hesaplar.

    Args:
        daily: Tüm barkodların günlük talep verisi.
        barkod: İlgilenilen barkod.

    Returns:
        (CV, ADI, satis_gun_sayisi)
    """
    sku = daily[daily["barkod"] == barkod]["adet"]
    satis_gun_sayisi = (sku > 0).sum()

    if satis_gun_sayisi == 0:
        return np.nan, np.nan, 0

    pozitif = sku[sku > 0]
    cv = pozitif.std() / pozitif.mean() if pozitif.mean() > 0 else 0.0

    # ADI: pozitif satış günleri arası ortalama aralık
    # Toplam gün / pozitif satış gün sayısı
    toplam_gun = len(sku)
    adi = toplam_gun / satis_gun_sayisi if satis_gun_sayisi > 0 else np.nan

    return float(cv), float(adi), int(satis_gun_sayisi)


def _talep_tipi_siniflandir(cv: float, adi: float, satis_gun: int) -> str:
    """
    CV ve ADI değerlerine göre Syntetos-Boylan talep tipi döndür.

    Tipler:
      duzensiz  → CV ≥ CV_ESIK, ADI < ADI_ESIK  (erratic)
      aralikli  → CV < CV_ESIK, ADI ≥ ADI_ESIK  (intermittent)
      toplu     → CV ≥ CV_ESIK, ADI ≥ ADI_ESIK  (lumpy)
      duzgun    → CV < CV_ESIK, ADI < ADI_ESIK  (smooth)
      yeni      → satis_gun < MIN_SATIS_GUN
    """
    if satis_gun < MIN_SATIS_GUN:
        return "yeni"
    if np.isnan(cv) or np.isnan(adi):
        return "yeni"

    if cv < CV_ESIK and adi < ADI_ESIK:
        return "duzgun"
    elif cv < CV_ESIK and adi >= ADI_ESIK:
        return "aralikli"
    elif cv >= CV_ESIK and adi >= ADI_ESIK:
        return "toplu"
    else:  # cv >= CV_ESIK and adi < ADI_ESIK
        return "duzensiz"


def talep_tipi_ekle(master: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """
    Her SKU için CV, ADI hesaplayıp 'talep_tipi' sütunu ekler.

    Args:
        master: Ürün master DataFrame'i.
        daily: Günlük talep DataFrame'i (clean_orders'dan üretilmiş).

    Returns:
        'talep_tipi', 'cv', 'adi' sütunları eklenmiş master DataFrame.
    """
    sonuclar = []
    for barkod in master["barkod"]:
        cv, adi, satis_gun = _hesapla_cv_adi(daily, barkod)
        talep_tipi = _talep_tipi_siniflandir(cv, adi, satis_gun)
        sonuclar.append({"barkod": barkod, "cv": cv, "adi": adi, "talep_tipi": talep_tipi})

    meta_df = pd.DataFrame(sonuclar)
    master = master.merge(meta_df, on="barkod", how="left")

    dagilim = master["talep_tipi"].value_counts().to_dict()
    log.info("Talep tipi dağılımı: %s", dagilim)
    return master


# ─── SKU Sağlık Skoru ─────────────────────────────────────────────────────────

def _skor_satis_trendi(daily: pd.DataFrame, barkod: str) -> float:
    """Son 30 gün / önceki 30 gün adet oranını 0-1 bandına normalize et."""
    sku = daily[daily["barkod"] == barkod].sort_values("tarih")
    if sku.empty:
        return 0.0
    son_tarih = sku["tarih"].max()
    son30 = sku[sku["tarih"] >= son_tarih - pd.Timedelta(days=30)]["adet"].sum()
    onceki30 = sku[
        (sku["tarih"] >= son_tarih - pd.Timedelta(days=60))
        & (sku["tarih"] < son_tarih - pd.Timedelta(days=30))
    ]["adet"].sum()

    if onceki30 == 0:
        return 0.5  # Önceki dönem veri yok → nötr
    oran = son30 / onceki30
    # 1.0 oranı = tam istikrar = 1.0 skor; 0 = tamamen düşüş; 2+ = büyüme (1.0 üst limit)
    return float(min(oran / 2.0, 1.0))


def _skor_alias(alias_sayisi: int) -> float:
    """Az alias → iyi. 1 alias = 1.0, her +1 alias = -0.1 (min 0.0)."""
    return max(0.0, 1.0 - 0.1 * (alias_sayisi - 1))


def _skor_duzensizlik(cv: float) -> float:
    """Düşük CV → daha düzenli → daha yüksek skor. CV=0 → 1.0, CV=2 → 0.0."""
    if np.isnan(cv):
        return 0.5
    return max(0.0, 1.0 - cv / 2.0)


def _skor_son30_aktiflik(aktif: bool) -> float:
    """Son 30 günde satış var mı?"""
    return 1.0 if aktif else 0.0


def _skor_negatif_adet(clean_orders: pd.DataFrame, barkod: str) -> float:
    """Toplam kayıt içinde anormal_adet oranına göre skor."""
    sku = clean_orders[clean_orders["barkod"] == barkod]
    if sku.empty:
        return 0.5
    anormal_oran = sku["anormal_adet"].sum() / len(sku)
    return max(0.0, 1.0 - anormal_oran * 2)


def sku_saglik_skoru_ekle(
    master: pd.DataFrame,
    daily: pd.DataFrame,
    clean_orders: pd.DataFrame,
) -> pd.DataFrame:
    """
    Her SKU için 0-100 arası bileşik sağlık skoru hesaplar.

    Ağırlıklar config.py / SAGLIK_AGIRLIK'tan alınır.

    Args:
        master: ABC + talep tipi eklenmiş ürün master DataFrame.
        daily: Günlük talep DataFrame.
        clean_orders: Ham temiz sipariş DataFrame.

    Returns:
        'sku_saglik_skoru' sütunu eklenmiş master DataFrame.
    """
    w = SAGLIK_AGIRLIK
    skorlar = []

    for _, satir in master.iterrows():
        barkod = satir["barkod"]
        s_trend = _skor_satis_trendi(daily, barkod)
        s_alias = _skor_alias(int(satir.get("alias_sayisi", 1)))
        s_duz = _skor_duzensizlik(float(satir.get("cv", np.nan)))
        s_aktif = _skor_son30_aktiflik(bool(satir.get("aktif", False)))
        s_neg = _skor_negatif_adet(clean_orders, barkod)

        skor = (
            w["satis_trendi"] * s_trend
            + w["alias_sayisi"] * s_alias
            + w["duzensizlik"] * s_duz
            + w["son30_aktiflik"] * s_aktif
            + w["negatif_adet"] * s_neg
        )
        skorlar.append({"barkod": barkod, "sku_saglik_skoru": round(skor * 100, 1)})

    skor_df = pd.DataFrame(skorlar)
    master = master.merge(skor_df, on="barkod", how="left")
    log.info(
        "SKU sağlık skoru eklendi. Ort: %.1f | Min: %.1f | Max: %.1f",
        master["sku_saglik_skoru"].mean(),
        master["sku_saglik_skoru"].min(),
        master["sku_saglik_skoru"].max(),
    )
    return master


# ─── Ana Fonksiyon ───────────────────────────────────────────────────────────

def segmente_et(
    master: pd.DataFrame,
    daily: pd.DataFrame,
    clean_orders: pd.DataFrame,
    kaydet: bool = True,
) -> pd.DataFrame:
    """
    Ürün master'a ABC, talep tipi ve SKU sağlık skoru ekler.
    Sonucu parquet olarak kaydeder.

    Args:
        master: data_loader çıktısı ürün master seed.
        daily: Günlük talep DataFrame.
        clean_orders: Temiz sipariş DataFrame.
        kaydet: True ise PRODUCT_MASTER_PARQUET'a kaydeder.

    Returns:
        Tam master DataFrame (T1 formatı).
    """
    log.info("Segmentasyon başlıyor. SKU sayısı: %d", len(master))

    master = abc_siniflandir(master)
    master = talep_tipi_ekle(master, daily)
    master = sku_saglik_skoru_ekle(master, daily, clean_orders)

    # T1 sütun sırası (REF-08)
    t1_kolonlar = [
        "barkod", "kanonik_ad", "alias_listesi", "alias_sayisi",
        "ilk_satis_tarihi", "son_satis_tarihi",
        "toplam_adet", "toplam_siparis", "gunluk_ort_adet",
        "abc_sinifi", "talep_tipi", "aktif", "sku_saglik_skoru",
        "cv", "adi",
    ]
    # Eksik sütunları atla (hata vermemek için)
    mevcut = [k for k in t1_kolonlar if k in master.columns]
    master = master[mevcut]

    if kaydet:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        master.to_parquet(PRODUCT_MASTER_PARQUET, index=False)
        log.info("Kaydedildi: %s", PRODUCT_MASTER_PARQUET)

    return master


# ─── Script olarak çalıştırma ─────────────────────────────────────────────────
if __name__ == "__main__":
    from src.data_loader import yukle_ve_temizle, gunluk_talep_olustur

    clean_orders, master_seed = yukle_ve_temizle()
    daily = gunluk_talep_olustur(clean_orders)
    master = segmente_et(master_seed, daily, clean_orders)

    print("\n=== Segmentasyon Özeti ===")
    print(master[["abc_sinifi", "talep_tipi"]].value_counts().to_string())
    print(f"\nOrtalama SKU sağlık skoru: {master['sku_saglik_skoru'].mean():.1f}")
