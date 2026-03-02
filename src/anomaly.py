"""
anomaly.py — Anomali algılama, stok-out flag ve kampanya proxy tespiti.

REF-07 yöntemleri:
  1. Z-score (rolling)  : spike / düşüş (rolling mean/std penceresi üzerinden)
  2. Zero-sales run      : aktif ürün + ani sıfır satış dizisi → "Olası stok-out"
  3. Change point        : kısa/uzun EWM oranı üzerinden trend kırılması
  4. Kampanya proxy      : z-score > Z_KAMPANYA_ESIK → "kampanya_benzeri"

Çıktılar:
  T6 — Anomali/Olay   : barkod, kanonik_ad, baslangic_tarih, bitis_tarih,
                        olay_tipi, siddet, olasi_aciklama, guven_seviyesi
  T7 — Aykırı Takvim : tarih, etkilenen_sku_sayisi, olay_tipi, toplam_anomali_adet
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    ADI_ESIK,
    DATA_PROCESSED_DIR,
    LOG_FORMAT,
    LOG_LEVEL,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

# Çıktı dosyaları
ANOMALY_EVENTS_PARQUET = DATA_PROCESSED_DIR / "anomaly_events.parquet"
ANOMALY_CALENDAR_PARQUET = DATA_PROCESSED_DIR / "anomaly_calendar.parquet"

# Anomali parametreleri
ROLLING_PENCERE: int = 14           # Z-score hesabı için kayan pencere (gün)
Z_SPIKE_ESIK: float = 2.5           # Spike/düşüş için z-score eşiği
Z_KAMPANYA_ESIK: float = 2.0        # Kampanya proxy için z-score eşiği
SIFIR_RUN_CARPAN: float = 3.0       # Zero-run: ADI × bu çarpan gün = eşik
SIFIR_RUN_MIN: int = 7              # Minimum sıfır koşusu (gün)
EWM_KISA_SPAN: int = 7              # Change point kısa EWM (gün)
EWM_UZUN_SPAN: int = 28             # Change point uzun EWM (gün)
CHANGE_POINT_ORAN_UST: float = 1.7  # Kısa/uzun > bu oran → artış trendi kırılması
CHANGE_POINT_ORAN_ALT: float = 0.5  # Kısa/uzun < bu oran → düşüş trendi kırılması
MIN_AKTIF_GUN: int = 14             # Analiz için minimum aktif gün


def _z_score_serisi(seri: pd.Series, pencere: int = ROLLING_PENCERE) -> pd.Series:
    """Kayan pencere üzerinden z-score hesapla."""
    ort = seri.rolling(pencere, min_periods=max(2, pencere // 2)).mean()
    std = seri.rolling(pencere, min_periods=max(2, pencere // 2)).std()
    # std = 0 olduğunda bölme hatası önle
    std = std.replace(0, np.nan)
    return (seri - ort) / std


def _spike_anomalileri_bul(
    sku_daily: pd.DataFrame,
    barkod: str,
    kanonik_ad: str,
) -> list[dict]:
    """
    Z-score > Z_SPIKE_ESIK → spike (artış anomalisi)
    Z-score < -Z_SPIKE_ESIK → düşüş anomalisi

    Her anomali ayrı bir T6 satırı olarak döner.
    """
    adet = sku_daily["adet"].astype(float)
    z = _z_score_serisi(adet)
    tarihler = sku_daily["tarih"]

    kayitlar = []

    spike_mask = z > Z_SPIKE_ESIK
    for tarih, z_val, adet_val in zip(
        tarihler[spike_mask], z[spike_mask], adet[spike_mask]
    ):
        kayitlar.append({
            "barkod": barkod,
            "kanonik_ad": kanonik_ad,
            "baslangic_tarih": tarih,
            "bitis_tarih": tarih,
            "olay_tipi": "spike",
            "siddet": round(float(z_val), 2),
            "olasi_aciklama": f"Ani talep artışı — z={z_val:.1f}, adet={adet_val:.0f}",
            "guven_seviyesi": "ORTA",
        })

    dusus_mask = z < -Z_SPIKE_ESIK
    for tarih, z_val, adet_val in zip(
        tarihler[dusus_mask], z[dusus_mask], adet[dusus_mask]
    ):
        kayitlar.append({
            "barkod": barkod,
            "kanonik_ad": kanonik_ad,
            "baslangic_tarih": tarih,
            "bitis_tarih": tarih,
            "olay_tipi": "dusus",
            "siddet": round(float(abs(z_val)), 2),
            "olasi_aciklama": f"Ani talep düşüşü — z={z_val:.1f}, adet={adet_val:.0f}",
            "guven_seviyesi": "ORTA",
        })

    return kayitlar


def _kampanya_gunleri_bul(
    sku_daily: pd.DataFrame,
    barkod: str,
    kanonik_ad: str,
) -> list[dict]:
    """
    z-score > Z_KAMPANYA_ESIK olan günleri 'kampanya_benzeri' olarak işaretle.
    """
    adet = sku_daily["adet"].astype(float)
    z = _z_score_serisi(adet)
    tarihler = sku_daily["tarih"]

    mask = z > Z_KAMPANYA_ESIK
    kayitlar = []
    for tarih, z_val, adet_val in zip(tarihler[mask], z[mask], adet[mask]):
        kayitlar.append({
            "barkod": barkod,
            "kanonik_ad": kanonik_ad,
            "baslangic_tarih": tarih,
            "bitis_tarih": tarih,
            "olay_tipi": "kampanya_benzeri",
            "siddet": round(float(z_val), 2),
            "olasi_aciklama": f"Kampanya/promosyon benzeri artış — z={z_val:.1f}",
            "guven_seviyesi": "DÜŞÜK",
        })
    return kayitlar


def _sifir_run_anomalileri_bul(
    sku_daily: pd.DataFrame,
    barkod: str,
    kanonik_ad: str,
    adi: float,
) -> list[dict]:
    """
    Aktif bir SKU'da ardışık sıfır satış dizisi (zero-sales run) tespiti.
    Eşik: max(SIFIR_RUN_MIN, ADI × SIFIR_RUN_CARPAN) gün.

    Bu durum "Olası stok-out" olarak işaretlenir (kesinlik DÜŞÜK).
    """
    esik_gun = max(SIFIR_RUN_MIN, int(adi * SIFIR_RUN_CARPAN) if not np.isnan(adi) else SIFIR_RUN_MIN)

    adet = sku_daily["adet"].to_numpy(dtype=float)
    tarihler = sku_daily["tarih"].to_numpy()
    n = len(adet)

    kayitlar = []
    i = 0
    while i < n:
        if adet[i] == 0:
            j = i
            while j < n and adet[j] == 0:
                j += 1
            run_uzunluk = j - i
            if run_uzunluk >= esik_gun:
                kayitlar.append({
                    "barkod": barkod,
                    "kanonik_ad": kanonik_ad,
                    "baslangic_tarih": pd.Timestamp(tarihler[i]),
                    "bitis_tarih": pd.Timestamp(tarihler[j - 1]),
                    "olay_tipi": "olasi_stok_out",
                    "siddet": float(run_uzunluk),
                    "olasi_aciklama": (
                        f"{run_uzunluk} gün ardışık sıfır satış "
                        f"(eşik={esik_gun} gün, ADI≈{adi:.1f})"
                    ),
                    "guven_seviyesi": "DÜŞÜK",
                })
            i = j
        else:
            i += 1

    return kayitlar


def _change_point_bul(
    sku_daily: pd.DataFrame,
    barkod: str,
    kanonik_ad: str,
) -> list[dict]:
    """
    Kısa EWM / uzun EWM oranına bakarak trend kırılma noktaları tespit eder.
    Art arda 3+ gün eşik aşılırsa olay olarak kayıt edilir.
    """
    adet = sku_daily["adet"].astype(float).replace(0, np.nan)
    ort = adet.fillna(0)

    ewm_kisa = ort.ewm(span=EWM_KISA_SPAN, adjust=False).mean()
    ewm_uzun = ort.ewm(span=EWM_UZUN_SPAN, adjust=False).mean()

    # Oran hesabı (sıfır bölme önlemi)
    oran = ewm_kisa / ewm_uzun.replace(0, np.nan)
    tarihler = sku_daily["tarih"]

    kayitlar = []

    def _bloklari_bul(mask: pd.Series, olay_tipi: str, aciklama_sablonu: str):
        """Art arda True olan satırları grupla."""
        in_blok = False
        blok_bas = None
        for idx, (tarih, val) in enumerate(zip(tarihler, mask)):
            if val and not in_blok:
                in_blok = True
                blok_bas = tarih
            elif not val and in_blok:
                in_blok = False
                blok_bitis = tarihler.iloc[idx - 1]
                gun_sayisi = (blok_bitis - blok_bas).days + 1
                if gun_sayisi >= 3:
                    kayitlar.append({
                        "barkod": barkod,
                        "kanonik_ad": kanonik_ad,
                        "baslangic_tarih": blok_bas,
                        "bitis_tarih": blok_bitis,
                        "olay_tipi": olay_tipi,
                        "siddet": round(float(oran[mask].mean()), 2) if mask.any() else 1.0,
                        "olasi_aciklama": aciklama_sablonu.format(gun=gun_sayisi),
                        "guven_seviyesi": "DÜŞÜK",
                    })
        if in_blok:
            blok_bitis = tarihler.iloc[-1]
            gun_sayisi = (blok_bitis - blok_bas).days + 1
            if gun_sayisi >= 3:
                kayitlar.append({
                    "barkod": barkod,
                    "kanonik_ad": kanonik_ad,
                    "baslangic_tarih": blok_bas,
                    "bitis_tarih": blok_bitis,
                    "olay_tipi": olay_tipi,
                    "siddet": 1.0,
                    "olasi_aciklama": aciklama_sablonu.format(gun=gun_sayisi),
                    "guven_seviyesi": "DÜŞÜK",
                })

    artis_mask = oran > CHANGE_POINT_ORAN_UST
    dusus_mask = oran < CHANGE_POINT_ORAN_ALT

    _bloklari_bul(artis_mask.fillna(False), "trend_artis", "Yukarı trend kırılması — {gun} gün sürdü")
    _bloklari_bul(dusus_mask.fillna(False), "trend_dusus", "Aşağı trend kırılması — {gun} gün sürdü")

    return kayitlar


# ─── Ana Fonksiyonlar ─────────────────────────────────────────────────────────

def anomali_tespit_et(
    master: pd.DataFrame,
    daily: pd.DataFrame,
    kaydet: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Tüm aktif SKU'lar için anomali tespiti yapar.

    Args:
        master: Ürün master (aktif, talep_tipi, adi sütunları).
        daily:  Günlük talep DataFrame.
        kaydet: True ise parquet kaydeder.

    Returns:
        (anomaly_events_df, anomaly_calendar_df)
        T6 ve T7 formatlarında.
    """
    log.info("Anomali tespiti başlıyor. SKU: %d", len(master))

    tum_olaylar: list[dict] = []

    for _, satir in master.iterrows():
        barkod = str(satir["barkod"])
        kanonik_ad = str(satir.get("kanonik_ad", barkod))
        aktif = bool(satir.get("aktif", False))
        adi = float(satir.get("adi", ADI_ESIK)) if not pd.isna(satir.get("adi", np.nan)) else ADI_ESIK

        sku_daily = daily[daily["barkod"] == barkod].sort_values("tarih").reset_index(drop=True)

        if len(sku_daily) < MIN_AKTIF_GUN:
            continue

        # 1. Spike / düşüş anomalileri
        tum_olaylar.extend(_spike_anomalileri_bul(sku_daily, barkod, kanonik_ad))

        # 2. Kampanya proxy (aktif olmak zorunda değil, geçmişte de olabilir)
        tum_olaylar.extend(_kampanya_gunleri_bul(sku_daily, barkod, kanonik_ad))

        # 3. Zero-sales run (sadece aktif SKU'larda stok-out anlamlı)
        if aktif:
            tum_olaylar.extend(_sifir_run_anomalileri_bul(sku_daily, barkod, kanonik_ad, adi))

        # 4. Change point
        tum_olaylar.extend(_change_point_bul(sku_daily, barkod, kanonik_ad))

    # ─── T6: Anomali/Olay tablosu ─────────────────────────────────────────────
    if tum_olaylar:
        events_df = pd.DataFrame(tum_olaylar)
        events_df["baslangic_tarih"] = pd.to_datetime(events_df["baslangic_tarih"])
        events_df["bitis_tarih"] = pd.to_datetime(events_df["bitis_tarih"])
        events_df = events_df.sort_values(["baslangic_tarih", "barkod"])
    else:
        events_df = pd.DataFrame(columns=[
            "barkod", "kanonik_ad", "baslangic_tarih", "bitis_tarih",
            "olay_tipi", "siddet", "olasi_aciklama", "guven_seviyesi",
        ])

    # ─── T7: Aykırı Günler Takvimi ────────────────────────────────────────────
    if not events_df.empty:
        # Olay başlangıç tarihine göre pivot
        # Spike ve kampanya için günlük adet toplanır
        gunluk_olaylar = []
        for _, olay in events_df.iterrows():
            # Sadece tek günlük olaylar (spike/kampanya) için adet hesaplanabilir
            if olay["baslangic_tarih"] == olay["bitis_tarih"]:
                sku_gun = daily[
                    (daily["barkod"] == olay["barkod"])
                    & (daily["tarih"] == olay["baslangic_tarih"])
                ]
                toplam_adet = float(sku_gun["adet"].sum()) if not sku_gun.empty else 0.0
            else:
                toplam_adet = 0.0

            gunluk_olaylar.append({
                "tarih": olay["baslangic_tarih"],
                "olay_tipi": olay["olay_tipi"],
                "barkod": olay["barkod"],
                "toplam_adet": toplam_adet,
            })

        cal_raw = pd.DataFrame(gunluk_olaylar)
        cal_raw["tarih"] = pd.to_datetime(cal_raw["tarih"]).dt.normalize()

        calendar_df = (
            cal_raw.groupby(["tarih", "olay_tipi"])
            .agg(
                etkilenen_sku_sayisi=("barkod", "nunique"),
                toplam_anomali_adet=("toplam_adet", "sum"),
            )
            .reset_index()
            .sort_values(["tarih", "olay_tipi"])
        )
    else:
        calendar_df = pd.DataFrame(columns=[
            "tarih", "etkilenen_sku_sayisi", "olay_tipi", "toplam_anomali_adet"
        ])

    olay_dagilimi = events_df["olay_tipi"].value_counts().to_dict() if not events_df.empty else {}
    log.info(
        "Anomali tespiti tamamlandı. Toplam olay: %d\nDağılım: %s",
        len(events_df), olay_dagilimi,
    )

    if kaydet:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        events_df.to_parquet(ANOMALY_EVENTS_PARQUET, index=False)
        calendar_df.to_parquet(ANOMALY_CALENDAR_PARQUET, index=False)
        log.info("Kaydedildi: %s | %s", ANOMALY_EVENTS_PARQUET, ANOMALY_CALENDAR_PARQUET)

    return events_df, calendar_df


# ─── Excel Yardımcıları ───────────────────────────────────────────────────────

def t6_turkce(events_df: pd.DataFrame) -> pd.DataFrame:
    """T6 DataFrame'ini Türkçe başlıklı hale getirir."""
    return events_df.rename(columns={
        "barkod": "Barkod",
        "kanonik_ad": "Ürün Adı",
        "baslangic_tarih": "Başlangıç Tarihi",
        "bitis_tarih": "Bitiş Tarihi",
        "olay_tipi": "Olay Tipi",
        "siddet": "Şiddet",
        "olasi_aciklama": "Olası Açıklama",
        "guven_seviyesi": "Güven Seviyesi",
    })


def t7_turkce(calendar_df: pd.DataFrame) -> pd.DataFrame:
    """T7 DataFrame'ini Türkçe başlıklı hale getirir."""
    return calendar_df.rename(columns={
        "tarih": "Tarih",
        "etkilenen_sku_sayisi": "Etkilenen SKU Sayısı",
        "olay_tipi": "Olay Tipi",
        "toplam_anomali_adet": "Toplam Anomali Adedi",
    })


# ─── Script olarak çalıştırma ─────────────────────────────────────────────────
if __name__ == "__main__":
    master = pd.read_parquet(DATA_PROCESSED_DIR / "product_master.parquet")
    daily = pd.read_parquet(DATA_PROCESSED_DIR / "daily_demand.parquet")
    events, calendar = anomali_tespit_et(master, daily)
    print(f"Anomali olayı: {len(events)}")
    print(events["olay_tipi"].value_counts().to_string())
    print(f"\nTakvim günü: {len(calendar)}")
