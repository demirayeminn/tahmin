"""
advanced_analytics.py — Faz 7 ileri analizler.

Üretilen çıktılar:
- lifecycle_analysis.parquet : yaşam döngüsü + churn + rampa özeti
- weekday_pattern.parquet    : barkod bazlı gün-özel talep paterni
- holiday_impact.parquet     : resmi tatil etkisi + anomali çakışması
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    ANOMALY_CALENDAR_PARQUET,
    CHURN_GUN_ESIK,
    CLEAN_ORDERS_PARQUET,
    DAILY_DEMAND_PARQUET,
    HOLIDAY_IMPACT_PARQUET,
    LIFECYCLE_ANALYSIS_PARQUET,
    LIFECYCLE_BUYUME_ORAN,
    LIFECYCLE_DUSUS_ORAN,
    LIFECYCLE_YENI_GUN,
    LOG_FORMAT,
    LOG_LEVEL,
    PRODUCT_MASTER_PARQUET,
    RAMPA_HIZLI_ESIK,
    RAMPA_ILK_GUN,
    RAMPA_YAVAS_ESIK,
    RESMI_TATIL_AY_GUN,
    WEEKDAY_PATTERN_PARQUET,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

HAFTA_GUNLERI_TR: dict[int, str] = {
    0: "Pazartesi",
    1: "Sali",
    2: "Carsamba",
    3: "Persembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar",
}


def _yukle_daily() -> pd.DataFrame:
    if not DAILY_DEMAND_PARQUET.exists():
        raise FileNotFoundError(f"daily_demand bulunamadı: {DAILY_DEMAND_PARQUET}")
    daily = pd.read_parquet(DAILY_DEMAND_PARQUET)
    daily["tarih"] = pd.to_datetime(daily["tarih"])
    return daily


def _yukle_master() -> pd.DataFrame:
    if not PRODUCT_MASTER_PARQUET.exists():
        raise FileNotFoundError(f"product_master bulunamadı: {PRODUCT_MASTER_PARQUET}")
    return pd.read_parquet(PRODUCT_MASTER_PARQUET)


def _hesapla_lifecycle_churn_rampa(master: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    son_tarih = daily["tarih"].max()
    grp = daily.groupby("barkod", as_index=False)

    ozet = grp.agg(
        ilk_satis_tarihi=("tarih", "min"),
        son_satis_tarihi=("tarih", "max"),
        toplam_gun=("tarih", "nunique"),
        toplam_adet=("adet", "sum"),
    )

    son30_bas = son_tarih - pd.Timedelta(days=30)
    onceki30_bas = son_tarih - pd.Timedelta(days=60)

    son30 = (
        daily.loc[daily["tarih"] >= son30_bas]
        .groupby("barkod", as_index=False)["adet"]
        .sum()
        .rename(columns={"adet": "son_30_gun_adet"})
    )
    onceki30 = (
        daily.loc[(daily["tarih"] >= onceki30_bas) & (daily["tarih"] < son30_bas)]
        .groupby("barkod", as_index=False)["adet"]
        .sum()
        .rename(columns={"adet": "onceki_30_gun_adet"})
    )

    ozet = ozet.merge(son30, on="barkod", how="left").merge(onceki30, on="barkod", how="left")
    ozet[["son_30_gun_adet", "onceki_30_gun_adet"]] = ozet[["son_30_gun_adet", "onceki_30_gun_adet"]].fillna(0)

    ozet["satis_yasi_gun"] = (son_tarih - ozet["ilk_satis_tarihi"]).dt.days
    ozet["son_satis_uzaklik_gun"] = (son_tarih - ozet["son_satis_tarihi"]).dt.days

    ozet["trend_orani"] = np.where(
        ozet["onceki_30_gun_adet"] > 0,
        ozet["son_30_gun_adet"] / ozet["onceki_30_gun_adet"],
        np.nan,
    )

    ozet["lifecycle_stage"] = np.select(
        [
            ozet["satis_yasi_gun"] <= LIFECYCLE_YENI_GUN,
            ozet["trend_orani"] >= LIFECYCLE_BUYUME_ORAN,
            ozet["trend_orani"] <= LIFECYCLE_DUSUS_ORAN,
        ],
        ["launch", "growth", "decline"],
        default="mature",
    )

    ozet["churned_sku"] = ozet["son_satis_uzaklik_gun"] > CHURN_GUN_ESIK

    # Rampa analizi: ilk N gündeki günlük ortalama / genel günlük ortalama
    ilk_n = (
        daily.merge(ozet[["barkod", "ilk_satis_tarihi"]], on="barkod", how="left")
        .assign(gun_farki=lambda x: (x["tarih"] - x["ilk_satis_tarihi"]).dt.days)
        .loc[lambda x: x["gun_farki"].between(0, RAMPA_ILK_GUN - 1)]
        .groupby("barkod", as_index=False)["adet"]
        .mean()
        .rename(columns={"adet": "ilk_donem_gunluk_ort"})
    )

    genel = (
        daily.groupby("barkod", as_index=False)["adet"]
        .mean()
        .rename(columns={"adet": "genel_gunluk_ort"})
    )

    ozet = ozet.merge(ilk_n, on="barkod", how="left").merge(genel, on="barkod", how="left")
    ozet[["ilk_donem_gunluk_ort", "genel_gunluk_ort"]] = ozet[["ilk_donem_gunluk_ort", "genel_gunluk_ort"]].fillna(0)

    ozet["rampa_orani"] = np.where(
        ozet["genel_gunluk_ort"] > 0,
        ozet["ilk_donem_gunluk_ort"] / ozet["genel_gunluk_ort"],
        np.nan,
    )
    ozet["rampa_seviyesi"] = np.select(
        [
            ozet["rampa_orani"] >= RAMPA_HIZLI_ESIK,
            ozet["rampa_orani"] <= RAMPA_YAVAS_ESIK,
        ],
        ["hizli", "yavas"],
        default="normal",
    )

    cols = [
        "barkod",
        "lifecycle_stage",
        "churned_sku",
        "ilk_satis_tarihi",
        "son_satis_tarihi",
        "son_satis_uzaklik_gun",
        "trend_orani",
        "rampa_orani",
        "rampa_seviyesi",
    ]

    bilgi_kolonlari = [c for c in ["barkod", "kanonik_ad", "abc_sinifi", "kategori", "marka"] if c in master.columns]
    cikti = master[bilgi_kolonlari].merge(ozet[cols], on="barkod", how="left")
    return cikti


def _hesapla_weekday_pattern(daily: pd.DataFrame) -> pd.DataFrame:
    work = daily.copy()
    work["hafta_gunu_no"] = work["tarih"].dt.weekday
    work["hafta_gunu"] = work["hafta_gunu_no"].map(HAFTA_GUNLERI_TR)

    ort = (
        work.groupby(["barkod", "hafta_gunu_no", "hafta_gunu"], as_index=False)["adet"]
        .mean()
        .rename(columns={"adet": "gunluk_ort_adet"})
    )
    sku_ort = (
        work.groupby("barkod", as_index=False)["adet"]
        .mean()
        .rename(columns={"adet": "sku_genel_ort"})
    )
    out = ort.merge(sku_ort, on="barkod", how="left")
    out["gun_endeks"] = np.where(out["sku_genel_ort"] > 0, out["gunluk_ort_adet"] / out["sku_genel_ort"], np.nan)
    out = out.sort_values(["barkod", "hafta_gunu_no"]).reset_index(drop=True)
    return out


def _hesapla_tatil_etkisi(daily: pd.DataFrame) -> pd.DataFrame:
    work = daily.copy()
    work["ay_gun"] = work["tarih"].dt.strftime("%m-%d")
    work["resmi_tatil_mi"] = work["ay_gun"].isin(RESMI_TATIL_AY_GUN)

    tatil_ozet = (
        work.groupby("resmi_tatil_mi", as_index=False)["adet"]
        .mean()
        .rename(columns={"adet": "ortalama_adet"})
    )
    tatil = tatil_ozet.loc[tatil_ozet["resmi_tatil_mi"], "ortalama_adet"]
    normal = tatil_ozet.loc[~tatil_ozet["resmi_tatil_mi"], "ortalama_adet"]
    tatil_ort = float(tatil.iloc[0]) if not tatil.empty else 0.0
    normal_ort = float(normal.iloc[0]) if not normal.empty else 0.0
    etki_orani = tatil_ort / normal_ort if normal_ort > 0 else np.nan

    anomali_tatil_sayisi = 0
    if ANOMALY_CALENDAR_PARQUET.exists():
        anom = pd.read_parquet(ANOMALY_CALENDAR_PARQUET)
        anom["tarih"] = pd.to_datetime(anom["tarih"])
        anom["ay_gun"] = anom["tarih"].dt.strftime("%m-%d")
        anomali_tatil_sayisi = int(anom["ay_gun"].isin(RESMI_TATIL_AY_GUN).sum())

    return pd.DataFrame(
        [
            {
                "tatil_gunluk_ort_adet": tatil_ort,
                "normal_gunluk_ort_adet": normal_ort,
                "tatil_etki_orani": etki_orani,
                "tatil_anomali_cakisimi": anomali_tatil_sayisi,
                "resmi_tatil_sayisi": len(RESMI_TATIL_AY_GUN),
            }
        ]
    )


def calistir() -> None:
    """Faz 7 ileri analiz çıktıları üretir."""
    daily = _yukle_daily()
    master = _yukle_master()

    lifecycle = _hesapla_lifecycle_churn_rampa(master=master, daily=daily)
    weekday = _hesapla_weekday_pattern(daily=daily)
    holiday = _hesapla_tatil_etkisi(daily=daily)

    LIFECYCLE_ANALYSIS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    lifecycle.to_parquet(LIFECYCLE_ANALYSIS_PARQUET, index=False)
    weekday.to_parquet(WEEKDAY_PATTERN_PARQUET, index=False)
    holiday.to_parquet(HOLIDAY_IMPACT_PARQUET, index=False)

    log.info("Faz 7 tamamlandı: lifecycle=%s, weekday=%s, holiday=%s", len(lifecycle), len(weekday), len(holiday))


if __name__ == "__main__":
    calistir()
