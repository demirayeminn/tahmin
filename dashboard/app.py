"""
app.py — Streamlit dashboard giris noktasi.

Calistirmak icin:
  cd C:/Users/Emin/Desktop/Ev-tahmin
  streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="Stok Takip Sistemi",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.markdown("## Stok Takip Sistemi")
st.sidebar.info(
    "Veri araligi: **Eyl 2025 - Sub 2026**\n\n"
    "Urun sayisi: **344 SKU**\n\n"
    "Siparis sayisi: **113.310**"
)

pg = st.navigation([
    st.Page("pages/01_yonetici_ozet.py", title="Stok Takip"),
    st.Page("pages/06_alarm.py",         title="Alarm Listesi"),
])

pg.run()
