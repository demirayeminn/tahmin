"""07_ileri_analiz.py — Faz 7 ileri analiz ekranı."""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dashboard._veri import excel_indirme_butonu, holiday_impact, lifecycle, sidebar_filtreler, weekday_pattern

st.set_page_config(page_title="İleri Analiz", page_icon="🧭", layout="wide")
st.title("🧭 Faz 7 — İleri Analizler")

lifecycle_df = lifecycle()
weekday_df = weekday_pattern()
holiday_df = holiday_impact()

if lifecycle_df.empty:
    st.warning("Faz 7 çıktısı bulunamadı. Önce `python -m src.advanced_analytics` çalıştırın.")
    st.stop()

abc_dummy = pd.DataFrame({"abc_sinifi": ["A", "B", "C"]})
secili_abc, _, _, arama = sidebar_filtreler(abc_dummy)

if "abc_sinifi" in lifecycle_df.columns:
    filtreli = lifecycle_df[lifecycle_df["abc_sinifi"].isin(secili_abc)]
else:
    filtreli = lifecycle_df.copy()

if arama:
    arama_l = arama.lower()
    filtreli = filtreli[
        filtreli["kanonik_ad"].fillna("").str.lower().str.contains(arama_l)
        | filtreli["barkod"].astype(str).str.contains(arama, na=False)
    ]

col1, col2, col3 = st.columns(3)
col1.metric("Toplam SKU", len(filtreli))
col2.metric("Churned SKU", int(filtreli["churned_sku"].fillna(False).sum()))
col3.metric("Decline Aşaması", int((filtreli["lifecycle_stage"] == "decline").sum()))

st.markdown("### Yaşam Döngüsü Dağılımı")
fig_life = px.histogram(
    filtreli,
    x="lifecycle_stage",
    color="lifecycle_stage",
    category_orders={"lifecycle_stage": ["launch", "growth", "mature", "decline"]},
)
st.plotly_chart(fig_life, use_container_width=True)

st.markdown("### Rampa Seviyesi Dağılımı")
fig_rampa = px.histogram(filtreli, x="rampa_seviyesi", color="rampa_seviyesi")
st.plotly_chart(fig_rampa, use_container_width=True)

st.markdown("### Gün-Özel Talep Pattern")
if weekday_df.empty:
    st.info("weekday_pattern verisi yok.")
else:
    pivot = weekday_df.pivot_table(
        index="barkod",
        columns="hafta_gunu",
        values="gun_endeks",
        aggfunc="mean",
    )
    st.dataframe(weekday_df.sort_values(["barkod", "hafta_gunu_no"]).reset_index(drop=True), use_container_width=True)
    if not pivot.empty:
        fig_heat = px.imshow(pivot.fillna(0), aspect="auto", labels={"color": "Gün Endeks"})
        st.plotly_chart(fig_heat, use_container_width=True)

st.markdown("### Tatil Etkisi Özeti")
if holiday_df.empty:
    st.info("holiday_impact verisi yok.")
else:
    st.dataframe(holiday_df, use_container_width=True)

st.markdown("### Lifecycle Detay Tablosu")
st.dataframe(
    filtreli.sort_values(["churned_sku", "son_satis_uzaklik_gun"], ascending=[False, False]).reset_index(drop=True),
    use_container_width=True,
)
excel_indirme_butonu(filtreli, dosya_adi="faz7_lifecycle.xlsx", etiket="Lifecycle Excel İndir")
