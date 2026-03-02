"""
_veri.py — Dashboard sayfaları için ortak @st.cache_data veri yükleyiciler.
"""

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import DATA_PROCESSED_DIR


@st.cache_data
def master() -> pd.DataFrame:
    return pd.read_parquet(DATA_PROCESSED_DIR / "product_master.parquet")


@st.cache_data
def daily() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PROCESSED_DIR / "daily_demand.parquet")
    df["tarih"] = pd.to_datetime(df["tarih"])
    return df


@st.cache_data
def forecast() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PROCESSED_DIR / "forecast_results.parquet")
    df["tarih"] = pd.to_datetime(df["tarih"])
    return df


@st.cache_data
def reorder() -> pd.DataFrame:
    return pd.read_parquet(DATA_PROCESSED_DIR / "reorder.parquet")


@st.cache_data
def anomaly_events() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PROCESSED_DIR / "anomaly_events.parquet")
    df["baslangic_tarih"] = pd.to_datetime(df["baslangic_tarih"])
    df["bitis_tarih"] = pd.to_datetime(df["bitis_tarih"])
    return df


@st.cache_data
def anomaly_calendar() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PROCESSED_DIR / "anomaly_calendar.parquet")
    df["tarih"] = pd.to_datetime(df["tarih"])
    return df


@st.cache_data
def basket_rules() -> pd.DataFrame:
    return pd.read_parquet(DATA_PROCESSED_DIR / "basket_rules.parquet")


@st.cache_data(ttl=300)
def alarms() -> pd.DataFrame:
    p = DATA_PROCESSED_DIR / "alarms.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame()


@st.cache_data(ttl=300)
def stock_history() -> pd.DataFrame:
    """Birikimli stok geçmişi (her Entegra çekiminde bir snapshot)."""
    p = DATA_PROCESSED_DIR / "stock_history.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        df["tarih"] = pd.to_datetime(df["tarih"])
        return df
    return pd.DataFrame()


# ─── Ana tablo (açılış sayfası) ───────────────────────────────────────────────

@st.cache_data
def ana_tablo() -> pd.DataFrame:
    """
    Açılış sayfası için ana özet tablo.

    Kolonlar:
      Barkod, Ürün Adı, ABC, Mevcut Stok, Kalan Gün, Durum,
      1 Ay Alım Önerisi, 2 Ay Alım Önerisi, 3 Ay Alım Önerisi,
      50 Gün Tahmin Satış

    Formüller:
      X ay alım önerisi = max(0, gunluk_ort × (X*30) + guvenlik_stok - mevcut_stok)
      50 gün tahmin     = gunluk_ort × 50
      Kalan gün         = mevcut_stok / gunluk_ort  (sıfır ise None)
    """
    r = pd.read_parquet(DATA_PROCESSED_DIR / "reorder.parquet")

    df = pd.DataFrame()
    df["Barkod"] = r["barkod"]
    df["Ürün Adı"] = r["kanonik_ad"]
    df["ABC"] = r["abc_sinifi"]
    df["Mevcut Stok"] = r["mevcut_stok"].fillna(0).astype(int)

    g = r["gunluk_ort"].fillna(0)
    s = r["guvenlik_stok"].fillna(0)
    m = df["Mevcut Stok"].astype(float)

    df["1 Ay Alım Önerisi"] = np.maximum(0, g * 30 + s - m).round().astype(int)
    df["2 Ay Alım Önerisi"] = np.maximum(0, g * 60 + s - m).round().astype(int)
    df["3 Ay Alım Önerisi"] = np.maximum(0, g * 90 + s - m).round().astype(int)
    df["50 Gün Tahmin Satış"] = (g * 50).round().astype(int)

    # Kalan gün
    kalan = np.where(g > 0, m / g, np.nan)
    df["Kalan Gün"] = np.where(np.isnan(kalan), None, np.round(kalan, 1))

    # Pasif kontrolü: sadece "Pasif SKU" uyarisini tasiyanlar pasif
    # "Yeni/az veri" uyarisi tasiyanlar aktif urun, Pasif degil
    pasif_mask = r["uyari"].str.contains("Pasif SKU", na=False) if "uyari" in r.columns else pd.Series(False, index=r.index)

    # Durum
    def _durum(row: pd.Series) -> str:
        if pasif_mask.iloc[row.name]:
            return "Pasif"
        stok = row["Mevcut Stok"]
        kalan_val = row["Kalan Gün"]
        if stok == 0:
            return "Stok Yok"
        if kalan_val is None:
            return "Yeterli"
        if kalan_val <= 7:
            return "Kritik"
        if kalan_val <= 30:
            return "Uyari"
        return "Yeterli"

    df["Durum"] = df.apply(_durum, axis=1)

    # Sıralama: Stok Yok → Kritik → Uyarı → Yeterli → Pasif
    sira = {"Stok Yok": 0, "Kritik": 1, "Uyari": 2, "Yeterli": 3, "Pasif": 4}
    df["_sira"] = df["Durum"].map(sira).fillna(9)
    df["_kalan_sort"] = pd.to_numeric(df["Kalan Gün"], errors="coerce")
    df = df.sort_values(["_sira", "_kalan_sort"]).drop(columns=["_sira", "_kalan_sort"])
    df = df.reset_index(drop=True)

    return df


# ─── Yardımcı araçlar ─────────────────────────────────────────────────────────

def sidebar_filtreler(
    master_df: pd.DataFrame,
) -> tuple[list[str], list[str] | None, list[str] | None, str | None]:
    """
    Sidebar'da ABC, kategori, marka filtresi ve ürün arama döndürür.
    Returns: (secili_abc, secili_kategori, secili_marka, arama_metni)
    """
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Filtreler")

    abc_secim = st.sidebar.multiselect(
        "ABC Sinifi",
        options=["A", "B", "C"],
        default=["A", "B", "C"],
    )

    kategori_secim = None
    if "kategori" in master_df.columns and master_df["kategori"].notna().any():
        kat_list = sorted(master_df["kategori"].dropna().unique().tolist())
        kategori_secim = st.sidebar.multiselect("Kategori", options=kat_list, default=kat_list)

    marka_secim = None
    if "marka" in master_df.columns and master_df["marka"].notna().any():
        marka_list = sorted(master_df["marka"].dropna().unique().tolist())
        marka_secim = st.sidebar.multiselect("Marka", options=marka_list, default=marka_list)

    arama = st.sidebar.text_input("Urun Ara (ad veya barkod)")
    return abc_secim, kategori_secim, marka_secim, arama if arama else None


def excel_indirme_butonu(df: pd.DataFrame, dosya_adi: str, etiket: str = "Excel Indir"):
    """DataFrame'i Excel'e cevirip Streamlit indirme butonu dondurur."""
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    st.download_button(
        label=etiket,
        data=buf,
        file_name=dosya_adi,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
