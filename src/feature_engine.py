"""
feature_engine.py — Zaman serisi özellikleri (lag, rolling, takvim).

Çıktı: daily_demand üzerine eklenen özellik sütunları.
Forecasting modelleri bu modülü doğrudan kullanmaz; ileriki ML katmanı için hazırdır.
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import LOG_FORMAT, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

# Lag ve rolling pencere boyutları (gün)
LAG_GUNLER: list[int] = [7, 14, 28]
ROLLING_PENCERELER: list[int] = [7, 14, 30]


def lag_ozellikleri_ekle(df: pd.DataFrame) -> pd.DataFrame:
    """
    Her barkod için geçmiş adet lag'larını ekler.

    Args:
        df: 'barkod', 'tarih', 'adet' sütunlu günlük talep DataFrame.

    Returns:
        lag_{n} sütunları eklenmiş DataFrame.
    """
    df = df.sort_values(["barkod", "tarih"]).copy()
    for lag in LAG_GUNLER:
        df[f"lag_{lag}"] = df.groupby("barkod")["adet"].shift(lag)
    log.debug("Lag özellikleri eklendi: %s", [f"lag_{l}" for l in LAG_GUNLER])
    return df


def rolling_ozellikleri_ekle(df: pd.DataFrame) -> pd.DataFrame:
    """
    Her barkod için kayan pencere ortalama ve standart sapma ekler.

    Args:
        df: 'barkod', 'tarih', 'adet' sütunlu günlük talep DataFrame.

    Returns:
        rolling_mean_{n} ve rolling_std_{n} sütunları eklenmiş DataFrame.
    """
    df = df.sort_values(["barkod", "tarih"]).copy()
    for pencere in ROLLING_PENCERELER:
        grouped = df.groupby("barkod")["adet"]
        df[f"rolling_mean_{pencere}"] = grouped.transform(
            lambda x: x.shift(1).rolling(pencere, min_periods=1).mean()
        )
        df[f"rolling_std_{pencere}"] = grouped.transform(
            lambda x: x.shift(1).rolling(pencere, min_periods=2).std().fillna(0)
        )
    log.debug("Rolling özellikler eklendi. Pencereler: %s gün", ROLLING_PENCERELER)
    return df


def takvim_ozellikleri_ekle(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takvim bazlı özellikler ekler: haftanın günü, ay, çeyrek, yılın haftası,
    ay başı/sonu flag'ları.

    Args:
        df: 'tarih' sütunu olan DataFrame.

    Returns:
        Takvim sütunları eklenmiş DataFrame.
    """
    df = df.copy()
    t = df["tarih"]
    df["gun_adi"] = t.dt.day_name()          # Monday, Tuesday...
    df["hafta_gunu"] = t.dt.dayofweek        # 0=Pzt, 6=Paz
    df["ay_gunu"] = t.dt.day
    df["ceyrek"] = t.dt.quarter
    df["yil"] = t.dt.year
    df["ay_basi"] = (df["ay_gunu"] == 1).astype(int)
    df["ay_sonu"] = (df["ay_gunu"] == t.dt.days_in_month).astype(int)
    log.debug("Takvim özellikleri eklendi.")
    return df


def ozellikleri_hazirla(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tüm özellikleri sırasıyla uygular.

    Args:
        df: Günlük talep DataFrame (clean_orders'dan üretilmiş).

    Returns:
        Tüm özelliklerle zenginleştirilmiş DataFrame.
    """
    df = lag_ozellikleri_ekle(df)
    df = rolling_ozellikleri_ekle(df)
    df = takvim_ozellikleri_ekle(df)
    log.info("Feature engineering tamamlandı. Sütun sayısı: %d", len(df.columns))
    return df
