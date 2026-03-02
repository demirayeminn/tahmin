"""
reorder.py — Satın alma önerisi + Days of Supply hesaplama.

REF-06 formülleri:
  hedef_stok     = günlük_ort_talep × hedef_gün + güvenlik_stoğu
  güvenlik_stoğu = z_score × std_talep × sqrt(lead_time + review_period)
  öneri          = hedef_stok - mevcut_stok

REF-10 iş kuralları:
  A → z=1.88 (%97) | B → z=1.65 (%95) | C → z=1.28 (%90)
  Pasif SKU (son 30 gün satış=0) → öneri=0, uyarı
  Yeni SKU (<30 gün satış verisi) → basit ortalama + geniş band

Çıktı (T4): barkod, kanonik_ad, abc_sinifi, gunluk_ort, hedef_gun,
            onerilen_stok, guvenlik_stok, beklenen_tukenme_gun, risk_bandi
"""

import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    DATA_PROCESSED_DIR,
    HEDEF_GUN,
    LEAD_TIME_GUN,
    LOG_FORMAT,
    LOG_LEVEL,
    MEVCUT_STOK_VARSAYIM,
    MIN_SATIS_GUN,
    REVIEW_PERIOD_GUN,
    SERVIS_SEVIYE,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

# Çıktı dosyası
REORDER_PARQUET = DATA_PROCESSED_DIR / "reorder.parquet"

# Risk bandı eşikleri (gün cinsinden)
RISK_KIRMIZI_GUN: int = 7
RISK_TURUNCU_GUN: int = 30


def _gunluk_istatistik(
    daily: pd.DataFrame,
    barkod: str,
    pencere_gun: int = 90,
) -> tuple[float, float, int]:
    """
    Verilen barkod için son `pencere_gun` günün günlük talep ortalaması ve
    standart sapmasını hesaplar.

    Args:
        daily: Günlük talep DataFrame.
        barkod: İlgilenilen barkod.
        pencere_gun: Kaç günlük geçmişe bakılacak.

    Returns:
        (gunluk_ort, std_talep, satis_gun_sayisi)
    """
    sku = daily[daily["barkod"] == barkod].sort_values("tarih")
    if sku.empty:
        return 0.0, 0.0, 0

    son_tarih = sku["tarih"].max()
    son_pencere = sku[sku["tarih"] >= son_tarih - pd.Timedelta(days=pencere_gun)]

    adet = son_pencere["adet"].to_numpy(dtype=float)
    # Sadece pozitif günler üzerinden std (intermittent talep için daha anlamlı)
    pozitif = adet[adet > 0]
    satis_gun_sayisi = len(pozitif)

    # Günlük ortalama: tüm günler (0 dahil) — gerçekçi sipariş planı için
    gunluk_ort = float(adet.mean()) if len(adet) > 0 else 0.0
    # Std: pozitif günler (dispersiyon), yoksa genel std
    std_talep = float(pozitif.std()) if len(pozitif) > 1 else float(adet.std()) if len(adet) > 1 else 0.0

    return gunluk_ort, std_talep, satis_gun_sayisi


def _risk_bandi(beklenen_gun: float) -> str:
    """Beklenen tükenme gününe göre risk bandı belirle."""
    if beklenen_gun <= RISK_KIRMIZI_GUN:
        return "Kırmızı"
    elif beklened_gun <= RISK_TURUNCU_GUN:
        return "Turuncu"
    return "Yeşil"


def _risk_bandi(beklenen_gun: float) -> str:
    """Beklenen tükenme gününe göre risk bandı belirle."""
    if beklenen_gun <= RISK_KIRMIZI_GUN:
        return "Kırmızı"
    elif beklenen_gun <= RISK_TURUNCU_GUN:
        return "Turuncu"
    return "Yeşil"


def satin_alma_onerisi_hesapla(
    master: pd.DataFrame,
    daily: pd.DataFrame,
    kaydet: bool = True,
) -> pd.DataFrame:
    """
    Her SKU için satın alma önerisi hesaplar (T4 formatı).

    Args:
        master: Ürün master (abc_sinifi, talep_tipi, aktif sütunları gerekli).
        daily:  Günlük talep DataFrame.
        kaydet: True ise parquet kaydeder.

    Returns:
        T4 formatlı satın alma önerisi DataFrame.
    """
    # VARSAYIM: Mevcut stok bilinmiyor → 0 kabul edilir
    mevcut_stok = MEVCUT_STOK_VARSAYIM

    kayit_listesi: list[dict] = []

    for _, satir in master.iterrows():
        barkod = str(satir["barkod"])
        kanonik_ad = str(satir.get("kanonik_ad", ""))
        abc = str(satir.get("abc_sinifi", "C"))
        talep_tipi = str(satir.get("talep_tipi", "yeni"))
        aktif = bool(satir.get("aktif", False))

        gunluk_ort, std_talep, satis_gun = _gunluk_istatistik(daily, barkod)

        # REF-10: Pasif SKU → öneri = 0
        if not aktif:
            kayit_listesi.append({
                "barkod": barkod,
                "kanonik_ad": kanonik_ad,
                "abc_sinifi": abc,
                "talep_tipi": talep_tipi,
                "gunluk_ort": 0.0,
                "std_talep": 0.0,
                "hedef_gun": HEDEF_GUN,
                "guvenlik_stok": 0.0,
                "hedef_stok": 0.0,
                "mevcut_stok": mevcut_stok,
                "onerilen_stok": 0.0,
                "beklenen_tukenme_gun": 0.0,
                "risk_bandi": "Gri",
                "uyari": "Pasif SKU — son 30 gün satış yok",
            })
            continue

        # REF-10: Yeni SKU → basit ortalama (geniş band zaten yeni_sku modelinde)
        if talep_tipi == "yeni" or satis_gun < MIN_SATIS_GUN:
            z = SERVIS_SEVIYE.get(abc, SERVIS_SEVIYE["C"])
            uyari = "Yeni/az veri — geniş güvenlik stoğu uygulandı"
        else:
            z = SERVIS_SEVIYE.get(abc, SERVIS_SEVIYE["C"])
            uyari = ""

        # REF-06 formülü
        guvenlik_stok = z * std_talep * math.sqrt(LEAD_TIME_GUN + REVIEW_PERIOD_GUN)
        hedef_stok = gunluk_ort * HEDEF_GUN + guvenlik_stok
        onerilen_stok = max(hedef_stok - mevcut_stok, 0.0)

        # Days of supply: mevcut_stok / günlük_ort (mevcut=0 → 0 gün)
        beklenen_tukenme = mevcut_stok / gunluk_ort if gunluk_ort > 0 else 0.0

        # Risk bandı: öneri verilmezse stok_sıfır → kırmızı
        risk = _risk_bandi(beklenen_tukenme)

        kayit_listesi.append({
            "barkod": barkod,
            "kanonik_ad": kanonik_ad,
            "abc_sinifi": abc,
            "talep_tipi": talep_tipi,
            "gunluk_ort": round(gunluk_ort, 4),
            "std_talep": round(std_talep, 4),
            "hedef_gun": HEDEF_GUN,
            "guvenlik_stok": round(guvenlik_stok, 2),
            "hedef_stok": round(hedef_stok, 2),
            "mevcut_stok": float(mevcut_stok),
            "onerilen_stok": round(onerilen_stok, 2),
            "beklenen_tukenme_gun": round(beklenen_tukenme, 1),
            "risk_bandi": risk,
            "uyari": uyari,
        })

    df = pd.DataFrame(kayit_listesi)
    df = df.sort_values(["abc_sinifi", "onerilen_stok"], ascending=[True, False])

    log.info(
        "Satın alma önerisi hazır. SKU: %d | Risk dağılımı:\n%s",
        len(df),
        df["risk_bandi"].value_counts().to_string(),
    )

    if kaydet:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(REORDER_PARQUET, index=False)
        log.info("Kaydedildi: %s", REORDER_PARQUET)

    return df


def faz3_reorder_excel_sayfa(
    reorder: pd.DataFrame,
) -> pd.DataFrame:
    """T4 formatında Türkçe başlıklı DataFrame döndürür (Excel sayfası için)."""
    return reorder.rename(columns={
        "barkod": "Barkod",
        "kanonik_ad": "Ürün Adı",
        "abc_sinifi": "ABC Sınıfı",
        "talep_tipi": "Talep Tipi",
        "gunluk_ort": "Günlük Ort. Adet",
        "std_talep": "Std. Sapma",
        "hedef_gun": "Hedef Gün",
        "guvenlik_stok": "Güvenlik Stoğu",
        "hedef_stok": "Hedef Stok",
        "mevcut_stok": "Mevcut Stok",
        "onerilen_stok": "Önerilen Sipariş Adedi",
        "beklened_tukenme_gun": "Beklenen Tükenme (gün)",
        "beklenen_tukenme_gun": "Beklenen Tükenme (gün)",
        "risk_bandi": "Risk Bandı",
        "uyari": "Uyarı",
    })


# ─── Script olarak çalıştırma ─────────────────────────────────────────────────
if __name__ == "__main__":
    master = pd.read_parquet(DATA_PROCESSED_DIR / "product_master.parquet")
    daily = pd.read_parquet(DATA_PROCESSED_DIR / "daily_demand.parquet")
    reorder = satin_alma_onerisi_hesapla(master, daily)
    print(reorder[["barkod", "abc_sinifi", "onerilen_stok", "risk_bandi"]].head(10).to_string())
