"""
05_anomali.py — Anomali & Stok-Out Ekranı.

İçerik (REF-09):
  - Olay listesi (filtre: olay tipi, tarih aralığı)
  - Drill-down: seçilen SKU'nun zaman serisi + anomali işaretleri
  - Stok-out riski listesi
  - Aykırı gün heatmap (tarih × olay tipi)
  - İndirme butonu
"""

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import (
    anomaly_calendar,
    anomaly_events,
    daily,
    excel_indirme_butonu,
    master,
    sidebar_filtreler,
)

st.set_page_config(page_title="Anomali", page_icon="⚠️", layout="wide")
st.title("⚠️ Anomali & Stok-Out Takibi")

# ─── Veri ─────────────────────────────────────────────────────────────────────
m = master()
ae = anomaly_events()
ac = anomaly_calendar()
d = daily()

abc_secim, kat_secim, marka_secim, arama = sidebar_filtreler(m)
m_filtre = m[m["abc_sinifi"].isin(abc_secim)]

# ─── KPI Kartları ─────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Toplam Olay", len(ae))
k2.metric("Olası Stok-Out", (ae["olay_tipi"] == "olasi_stok_out").sum())
k3.metric("Spike Sayısı", (ae["olay_tipi"] == "spike").sum())
k4.metric("Kampanya Benzeri", (ae["olay_tipi"] == "kampanya_benzeri").sum())

st.markdown("---")

# ─── Olay Tipi Filtresi ───────────────────────────────────────────────────────
col_f1, col_f2 = st.columns(2)
with col_f1:
    olay_tipleri = ae["olay_tipi"].unique().tolist()
    secili_tipler = st.multiselect(
        "Olay Tipi",
        options=olay_tipleri,
        default=olay_tipleri,
    )
with col_f2:
    min_t = ae["baslangic_tarih"].min().date()
    max_t = ae["baslangic_tarih"].max().date()
    tarih_araligi = st.date_input(
        "Tarih Aralığı",
        value=(min_t, max_t),
        min_value=min_t,
        max_value=max_t,
    )

ae_filtre = ae[
    ae["olay_tipi"].isin(secili_tipler)
    & (ae["baslangic_tarih"].dt.date >= tarih_araligi[0])
    & (ae["baslangic_tarih"].dt.date <= tarih_araligi[-1])
    & ae["barkod"].isin(m_filtre["barkod"])
]
if arama:
    ae_filtre = ae_filtre[
        ae_filtre["kanonik_ad"].str.contains(arama, case=False, na=False)
        | ae_filtre["barkod"].str.contains(arama, case=False, na=False)
    ]

# ─── Olay Listesi ─────────────────────────────────────────────────────────────
st.subheader("📋 Anomali Olay Listesi")
st.dataframe(
    ae_filtre[["barkod", "kanonik_ad", "baslangic_tarih", "bitis_tarih",
               "olay_tipi", "siddet", "olasi_aciklama", "guven_seviyesi"]]
    .rename(columns={
        "barkod": "Barkod", "kanonik_ad": "Ürün Adı",
        "baslangic_tarih": "Başlangıç", "bitis_tarih": "Bitiş",
        "olay_tipi": "Olay Tipi", "siddet": "Şiddet",
        "olasi_aciklama": "Açıklama", "guven_seviyesi": "Güven",
    })
    .sort_values("Başlangıç", ascending=False),
    use_container_width=True,
    height=280,
)

st.markdown("---")

# ─── Drill-Down: SKU Zaman Serisi + Anomali İşaretleri ───────────────────────
st.subheader("🔍 SKU Drill-Down — Zaman Serisi + Anomaliler")

skular_olayli = ae_filtre["barkod"].unique().tolist()
if skular_olayli:
    secim_b = st.selectbox(
        "Ürün Seçin (anomalisi olanlar)",
        options=skular_olayli,
        format_func=lambda b: ae_filtre[ae_filtre["barkod"] == b]["kanonik_ad"].iloc[0][:55]
        if not ae_filtre[ae_filtre["barkod"] == b].empty else b,
    )

    sku_d = d[d["barkod"] == secim_b].sort_values("tarih")
    sku_ae = ae_filtre[ae_filtre["barkod"] == secim_b]

    fig_dd = go.Figure()
    fig_dd.add_trace(go.Bar(
        x=sku_d["tarih"], y=sku_d["adet"],
        name="Günlük Adet", marker_color="#90CAF9", opacity=0.7,
    ))

    # Anomali günleri işaretle
    _RENK_OLAY = {
        "spike": "red",
        "dusus": "purple",
        "kampanya_benzeri": "orange",
        "olasi_stok_out": "black",
        "trend_artis": "green",
        "trend_dusus": "brown",
    }
    _SEMBOL = {
        "spike": "triangle-up",
        "dusus": "triangle-down",
        "kampanya_benzeri": "star",
        "olasi_stok_out": "x",
        "trend_artis": "arrow-up",
        "trend_dusus": "arrow-down",
    }
    for olay_tipi, grup in sku_ae.groupby("olay_tipi"):
        # Nokta: başlangıç tarihi üzerinde o günün adeti kadar yüksek
        olay_tarihler = grup["baslangic_tarih"]
        olay_adet = sku_d.set_index("tarih")["adet"].reindex(olay_tarihler).fillna(0)
        fig_dd.add_trace(go.Scatter(
            x=olay_tarihler,
            y=olay_adet.values + olay_adet.max() * 0.15,
            mode="markers",
            name=olay_tipi,
            marker=dict(
                symbol=_SEMBOL.get(olay_tipi, "circle"),
                size=12,
                color=_RENK_OLAY.get(olay_tipi, "grey"),
                line=dict(width=1, color="black"),
            ),
        ))

    fig_dd.update_layout(
        height=380,
        xaxis_title="Tarih", yaxis_title="Adet",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02),
        margin=dict(t=30),
    )
    st.plotly_chart(fig_dd, use_container_width=True)
else:
    st.info("Seçili filtre ile anomalili ürün bulunamadı.")

st.markdown("---")

# ─── Stok-Out Listesi ────────────────────────────────────────────────────────
st.subheader("🚨 Olası Stok-Out Listesi")
stok_out = ae_filtre[ae_filtre["olay_tipi"] == "olasi_stok_out"].copy()
if stok_out.empty:
    st.success("Seçili filtrede olası stok-out kaydı yok.")
else:
    stok_out_goster = stok_out[
        ["barkod", "kanonik_ad", "baslangic_tarih", "bitis_tarih", "siddet", "olasi_aciklama"]
    ].rename(columns={
        "barkod": "Barkod", "kanonik_ad": "Ürün Adı",
        "baslangic_tarih": "Başlangıç", "bitis_tarih": "Bitiş",
        "siddet": "Süre (gün)", "olasi_aciklama": "Açıklama",
    }).sort_values("Süre (gün)", ascending=False)
    st.error(f"⚠️ {len(stok_out_goster)} adet olası stok-out tespit edildi.")
    st.dataframe(stok_out_goster, use_container_width=True, height=200)

st.markdown("---")

# ─── Aykırı Gün Heatmap ──────────────────────────────────────────────────────
st.subheader("🗓 Aykırı Gün Takvimi")
if not ac.empty:
    ac_filtre = ac[ac["tarih"] >= ac["tarih"].max() - __import__("pandas").Timedelta(days=90)]
    pivot_data = ac_filtre.pivot_table(
        index=ac_filtre["tarih"].dt.strftime("%Y-%m-%d"),
        columns="olay_tipi",
        values="etkilenen_sku_sayisi",
        aggfunc="sum",
        fill_value=0,
    )
    fig_heat = px.imshow(
        pivot_data.T,
        color_continuous_scale="YlOrRd",
        aspect="auto",
        labels=dict(x="Tarih", y="Olay Tipi", color="Etkilenen SKU"),
        title="Son 90 Gün — Tarih × Olay Tipi (Etkilenen SKU Sayısı)",
    )
    fig_heat.update_layout(height=300, margin=dict(t=40))
    st.plotly_chart(fig_heat, use_container_width=True)

st.markdown("---")
excel_indirme_butonu(ae_filtre, "anomali_olaylar.xlsx", "📥 Olay Listesini İndir")
