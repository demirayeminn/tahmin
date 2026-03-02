"""
alarm.py — Alarm motoru.

REF-14 mantığı:
  kalan_gun = mevcut_stok / gunluk_tahmin_talep
  - gunluk_tahmin_talep == 0 → alarm yok (satış beklenmez)
  - mevcut_stok == 0 AND aktif → 🔴 "STOK BİTMİŞ"
  - Eşikler ABC sınıfına göre ayarlı (ALARM_ESIK config'den)

Çıktı (T8): barkod, kanonik_ad, abc_sinifi, kategori, marka,
            mevcut_stok, gunluk_tahmin, kalan_gun, alarm_seviye,
            onerilen_siparis, son_guncelleme
"""

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    ALARM_ESIK,
    ALARMS_PARQUET,
    DATA_OUTPUTS_DIR,
    DATA_PROCESSED_DIR,
    FAZ6_EXCEL,
    LOG_FORMAT,
    LOG_LEVEL,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

FORECAST_PARQUET = DATA_PROCESSED_DIR / "forecast_results.parquet"
REORDER_PARQUET = DATA_PROCESSED_DIR / "reorder.parquet"
PRODUCT_MASTER_PARQUET = DATA_PROCESSED_DIR / "product_master.parquet"


# ─── Alarm seviyesi hesaplama ─────────────────────────────────────────────────

def _alarm_seviye(abc: str, kalan_gun: float | None, mevcut_stok: int, aktiflik: bool) -> str:
    """
    ABC sınıfı + kalan gün → alarm seviyesi döndürür.
    Returns: 'kritik' | 'uyarı' | 'izle' | 'normal' | 'pasif' | 'stok_bitmis'
    """
    if not aktiflik:
        return "pasif"
    if mevcut_stok == 0 and aktiflik:
        return "stok_bitmis"
    if kalan_gun is None:
        return "normal"  # tahmin=0, satış beklenmiyor

    esik = ALARM_ESIK.get(abc, ALARM_ESIK["C"])
    if kalan_gun <= esik["kritik"]:
        return "kritik"
    if kalan_gun <= esik["uyari"]:
        return "uyarı"
    if kalan_gun <= esik["izle"]:
        return "izle"
    return "normal"


def _alarm_emoji(seviye: str) -> str:
    return {
        "kritik": "🔴",
        "stok_bitmis": "🔴",
        "uyarı": "🟠",
        "izle": "🟡",
        "normal": "🟢",
        "pasif": "⚫",
    }.get(seviye, "")


# ─── Ana alarm hesaplama ──────────────────────────────────────────────────────

def hesapla_alarmlar() -> pd.DataFrame:
    """
    T8 alarm tablosunu oluşturur ve parquet + Excel'e kaydeder.

    Returns:
        pd.DataFrame: T8 alarm tablosu.
    """
    master = pd.read_parquet(PRODUCT_MASTER_PARQUET)
    reorder = pd.read_parquet(REORDER_PARQUET)

    # Günlük tahmin: reorder tablosundan gunluk_ort al (en son gerçek tahminden)
    # Forecast tablosu varsa oradan da alınabilir; şimdilik reorder'daki gunluk_ort kullanılıyor
    reorder_cols = ["barkod", "gunluk_ort", "onerilen_stok", "mevcut_stok"]
    r_mevcut = [c for c in reorder_cols if c in reorder.columns]
    reorder_slim = reorder[r_mevcut].copy()

    # Master ile birleştir
    merge_cols = ["barkod", "kanonik_ad", "abc_sinifi"]
    # aktif sütunu product_master'da "aktif" adıyla var
    if "aktif" in master.columns:
        merge_cols.append("aktif")
    # Entegra'dan gelen opsiyonel kolonlar
    for opt in ["kategori", "marka", "abc_ciro", "entegra_son_guncelleme"]:
        if opt in master.columns:
            merge_cols.append(opt)

    df = master[merge_cols].merge(reorder_slim, on="barkod", how="left")

    # gunluk_tahmin → reorder'daki gunluk_ort
    df["gunluk_tahmin"] = df["gunluk_ort"].fillna(0)

    # mevcut_stok: Entegra yoksa 0
    if "mevcut_stok" not in df.columns:
        df["mevcut_stok"] = 0
    df["mevcut_stok"] = df["mevcut_stok"].fillna(0).astype(int)

    # kalan_gun hesapla
    df["kalan_gun"] = df.apply(
        lambda r: round(r["mevcut_stok"] / r["gunluk_tahmin"], 1)
        if r["gunluk_tahmin"] > 0 else None,
        axis=1,
    )

    # Alarm seviyesi
    df["alarm_seviye"] = df.apply(
        lambda r: _alarm_seviye(
            abc=r.get("abc_sinifi", "C"),
            kalan_gun=r["kalan_gun"],
            mevcut_stok=r["mevcut_stok"],
            aktiflik=bool(r.get("aktif", True)),
        ),
        axis=1,
    )
    df["alarm_emoji"] = df["alarm_seviye"].map(_alarm_emoji)

    # Önerilen sipariş: reorder tablosundan
    df["onerilen_siparis"] = df.get("onerilen_stok", 0).fillna(0).astype(int)

    # Son güncelleme
    if "entegra_son_guncelleme" in df.columns:
        df["son_guncelleme"] = df["entegra_son_guncelleme"]
    else:
        df["son_guncelleme"] = pd.Timestamp.now().floor("s")

    # Kolon seçimi (T8)
    t8_cols = [
        "barkod", "kanonik_ad", "abc_sinifi",
        "kategori", "marka",
        "mevcut_stok", "gunluk_tahmin", "kalan_gun",
        "alarm_seviye", "alarm_emoji", "onerilen_siparis", "son_guncelleme",
    ]
    t8_mevcut = [c for c in t8_cols if c in df.columns]
    alarms = df[t8_mevcut].copy()

    # Sıralama: alarm_seviye önce (kritik başta), sonra kalan_gun artan
    seviye_sira = {"stok_bitmis": 0, "kritik": 1, "uyarı": 2, "izle": 3, "normal": 4, "pasif": 5}
    alarms["_sira"] = alarms["alarm_seviye"].map(seviye_sira).fillna(9)
    alarms = alarms.sort_values(["_sira", "kalan_gun"], ascending=[True, True]).drop(columns="_sira")
    alarms = alarms.reset_index(drop=True)

    # Özet log
    ozet = alarms["alarm_seviye"].value_counts()
    log.info(
        "Alarm özeti: stok_bitmis=%d, kritik=%d, uyarı=%d, izle=%d, normal=%d, pasif=%d",
        ozet.get("stok_bitmis", 0),
        ozet.get("kritik", 0),
        ozet.get("uyarı", 0),
        ozet.get("izle", 0),
        ozet.get("normal", 0),
        ozet.get("pasif", 0),
    )

    # Kaydet
    ALARMS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    alarms.to_parquet(ALARMS_PARQUET, index=False)
    log.info("Alarm tablosu kaydedildi: %s (%d satır)", ALARMS_PARQUET, len(alarms))

    _excel_kaydet(alarms)
    return alarms


def _excel_kaydet(alarms: pd.DataFrame) -> None:
    """Alarm tablosunu Excel'e kaydeder (faz6_alarm_raporu.xlsx)."""
    DATA_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(FAZ6_EXCEL, engine="xlsxwriter") as writer:
        alarms.to_excel(writer, index=False, sheet_name="Alarm Raporu")
        ws = writer.sheets["Alarm Raporu"]
        ws.set_column(0, len(alarms.columns) - 1, 18)
    log.info("Alarm Excel kaydedildi: %s", FAZ6_EXCEL)


# ─── Kritik alarmları filtrele ────────────────────────────────────────────────

def kritik_alarmlar(alarms: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Parquet'ten okur (veya parametre alır), kritik + stok_bitmis filtreler.
    notifier.py tarafından kullanılır.
    """
    if alarms is None:
        if not ALARMS_PARQUET.exists():
            return pd.DataFrame()
        alarms = pd.read_parquet(ALARMS_PARQUET)
    return alarms[alarms["alarm_seviye"].isin(["kritik", "stok_bitmis"])].copy()


def uyari_alarmlar(alarms: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uyarı seviyesindeki alarmları döner."""
    if alarms is None:
        if not ALARMS_PARQUET.exists():
            return pd.DataFrame()
        alarms = pd.read_parquet(ALARMS_PARQUET)
    return alarms[alarms["alarm_seviye"] == "uyarı"].copy()


if __name__ == "__main__":
    df = hesapla_alarmlar()
    print(df[["barkod", "kanonik_ad", "alarm_seviye", "kalan_gun", "onerilen_siparis"]].head(20))
