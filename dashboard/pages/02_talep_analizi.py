"""
02_talep_analizi.py — Ürün bazlı talep analizi ve tahmin grafiği.

İçerik (REF-09):
  - Ürün seçici (arama destekli)
  - Günlük zaman serisi + tahmin (14/30/60 gün) + 30 günlük MA overlay
  - Haftalık ve aylık toplam bar grafik
  - Hafta içi / hafta sonu karşılaştırması
  - İndirme butonu
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import (
    daily,
    excel_indirme_butonu,
    forecast,
    master,
    sidebar_filtreler,
)
from src.config import RENK_PALETI

st.set_page_config(page_title="Talep Analizi", page_icon="📈", layout="wide")
st.title("📈 Talep Analizi")

# ─── Veri ─────────────────────────────────────────────────────────────────────
m = master()
d = daily()
f = forecast()

abc_secim, kat_secim, marka_secim, _ = sidebar_filtreler(m)
m_filtre = m[m["abc_sinifi"].isin(abc_secim)]

# ─── Ürün Seçici ──────────────────────────────────────────────────────────────
secenekler = (
    m_filtre[["barkod", "kanonik_ad", "abc_sinifi"]]
    .assign(etiket=lambda x: x["abc_sinifi"] + " | " + x["barkod"] + " — " + x["kanonik_ad"].str[:40])
    .sort_values("abc_sinifi")
)

secim = st.selectbox(
    "Ürün Seçin",
    options=secenekler["barkod"].tolist(),
    format_func=lambda b: secenekler.set_index("barkod").loc[b, "etiket"],
)

if not secim:
    st.info("Lütfen bir ürün seçin.")
    st.stop()

ad = m.set_index("barkod").loc[secim, "kanonik_ad"]
abc = m.set_index("barkod").loc[secim, "abc_sinifi"]
tip = m.set_index("barkod").loc[secim, "talep_tipi"]
saglik = m.set_index("barkod").loc[secim, "sku_saglik_skoru"]

st.markdown(f"**{ad}** &nbsp;|&nbsp; ABC: `{abc}` &nbsp;|&nbsp; Talep Tipi: `{tip}` &nbsp;|&nbsp; Sağlık: `{saglik:.0f}/100`")

# ─── SKU Verisi ───────────────────────────────────────────────────────────────
sku_d = d[d["barkod"] == secim].sort_values("tarih")
sku_f14 = f[(f["barkod"] == secim) & (f["tahmin_horizon"] == 14)].sort_values("tarih")
sku_f30 = f[(f["barkod"] == secim) & (f["tahmin_horizon"] == 30)].sort_values("tarih")
sku_f60 = f[(f["barkod"] == secim) & (f["tahmin_horizon"] == 60)].sort_values("tarih")

# 30 günlük MA
sku_d = sku_d.copy()
sku_d["ma30"] = sku_d["adet"].rolling(30, min_periods=1).mean()

# ─── Ana Zaman Serisi ─────────────────────────────────────────────────────────
st.subheader("📅 Günlük Talep + Tahmin")

horizon_sec = st.radio(
    "Tahmin Horizonu",
    options=[14, 30, 60],
    horizontal=True,
    format_func=lambda h: f"{h} Gün",
)
sku_fh = f[(f["barkod"] == secim) & (f["tahmin_horizon"] == horizon_sec)].sort_values("tarih")

fig = go.Figure()

# Gerçek talep
fig.add_trace(go.Bar(
    x=sku_d["tarih"], y=sku_d["adet"],
    name="Gerçek Talep",
    marker_color="#90CAF9",
    opacity=0.7,
))

# 30 günlük MA
fig.add_trace(go.Scatter(
    x=sku_d["tarih"], y=sku_d["ma30"],
    name="30 Gün MA",
    line=dict(color="#FF9800", width=2, dash="dot"),
))

# Tahmin
if not sku_fh.empty:
    model_adi = sku_fh["model"].iloc[0]
    fig.add_trace(go.Scatter(
        x=sku_fh["tarih"], y=sku_fh["tahmin_adet"],
        name=f"Tahmin ({model_adi})",
        line=dict(color=RENK_PALETI["vurgu"], width=2),
        mode="lines+markers",
    ))
    # Güven bandı
    fig.add_trace(go.Scatter(
        x=pd.concat([sku_fh["tarih"], sku_fh["tarih"][::-1]]),
        y=pd.concat([sku_fh["ust_band"], sku_fh["alt_band"][::-1]]),
        fill="toself",
        fillcolor="rgba(52,152,219,0.15)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Güven Bandı",
        showlegend=True,
    ))

fig.update_layout(
    height=400,
    xaxis_title="Tarih",
    yaxis_title="Adet",
    legend=dict(orientation="h", y=1.02, x=0),
    hovermode="x unified",
    margin=dict(t=30),
)
st.plotly_chart(fig, use_container_width=True)

# ─── Haftalık ve Aylık Özetler ────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("📆 Haftalık Toplam")
    haftalik = (
        sku_d.groupby(sku_d["tarih"].dt.to_period("W"))["adet"]
        .sum()
        .reset_index()
    )
    haftalik["tarih"] = haftalik["tarih"].dt.to_timestamp()
    fig_h = go.Figure(go.Bar(
        x=haftalik["tarih"], y=haftalik["adet"],
        marker_color=RENK_PALETI["vurgu"],
    ))
    fig_h.update_layout(height=280, margin=dict(t=10),
                        xaxis_title="Hafta", yaxis_title="Adet")
    st.plotly_chart(fig_h, use_container_width=True)

with col2:
    st.subheader("🗓 Aylık Toplam")
    aylik = (
        sku_d.groupby(sku_d["tarih"].dt.to_period("M"))["adet"]
        .sum()
        .reset_index()
    )
    aylik["tarih"] = aylik["tarih"].dt.to_timestamp()
    fig_a = go.Figure(go.Bar(
        x=aylik["tarih"], y=aylik["adet"],
        marker_color="#7E57C2",
    ))
    fig_a.update_layout(height=280, margin=dict(t=10),
                        xaxis_title="Ay", yaxis_title="Adet")
    st.plotly_chart(fig_a, use_container_width=True)

# ─── Hafta İçi / Sonu ────────────────────────────────────────────────────────
st.subheader("📊 Hafta İçi vs. Hafta Sonu Ortalama")
sku_d["gun_tipi"] = sku_d["hafta_ici_mi"].map({True: "Hafta İçi", False: "Hafta Sonu"})
gun_ozet = sku_d.groupby("gun_tipi")["adet"].mean().reset_index()
gun_ozet.columns = ["Gün Tipi", "Ort. Adet"]
fig_gun = go.Figure(go.Bar(
    x=gun_ozet["Gün Tipi"], y=gun_ozet["Ort. Adet"],
    marker_color=["#2ECC71", "#E74C3C"],
    text=gun_ozet["Ort. Adet"].round(2),
    textposition="outside",
))
fig_gun.update_layout(height=280, margin=dict(t=10), yaxis_title="Ort. Günlük Adet")
st.plotly_chart(fig_gun, use_container_width=True)

st.markdown("---")
if not sku_fh.empty:
    excel_indirme_butonu(sku_fh, f"tahmin_{secim}_{horizon_sec}gun.xlsx", "📥 Tahmin İndir")
