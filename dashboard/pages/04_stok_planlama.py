"""
04_stok_planlama.py — Stok Planlama & Satın Alma Önerisi.

İçerik (REF-09):
  - Hedef gün slider (30-90) → anlık yeniden hesap
  - Öneri tablosu (filtre: ABC / aktiflik / talep tipi)
  - Risk bandı dağılım grafiği
  - "X adet stoksam kaç gün?" hesaplayıcı
  - İndirme butonu
"""

import math
import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import (
    daily,
    excel_indirme_butonu,
    master,
    reorder,
    sidebar_filtreler,
)
from src.config import (
    HEDEF_GUN,
    LEAD_TIME_GUN,
    REVIEW_PERIOD_GUN,
    SERVIS_SEVIYE,
)

st.set_page_config(page_title="Stok Planlama", page_icon="📦", layout="wide")
st.title("📦 Stok Planlama & Satın Alma Önerisi")

# ─── Veri ─────────────────────────────────────────────────────────────────────
m = master()
r = reorder()
d = daily()

abc_secim, kat_secim, marka_secim, arama = sidebar_filtreler(m)

# ─── Canlı Hedef Gün Slider ───────────────────────────────────────────────────
st.subheader("⚙️ Parametreler")
hedef_gun = st.slider(
    "Hedef Gün (sipariş edilen stoğun kaç günü karşılaması gereksin?)",
    min_value=30, max_value=90, value=HEDEF_GUN, step=5,
)

st.caption(
    f"Varsayımlar: Lead time = {LEAD_TIME_GUN} gün | "
    f"Review period = {REVIEW_PERIOD_GUN} gün | Mevcut stok = 0 (bilinmiyor)"
)

# Hedef gün değişince yeniden hesapla
def _hesapla_oneri(row, h_gun: int) -> float:
    z = SERVIS_SEVIYE.get(row["abc_sinifi"], SERVIS_SEVIYE["C"])
    guvenlik = z * row["std_talep"] * math.sqrt(LEAD_TIME_GUN + REVIEW_PERIOD_GUN)
    hedef = row["gunluk_ort"] * h_gun + guvenlik
    return max(round(hedef, 2), 0.0)


r_hesap = r.copy()
r_hesap["onerilen_stok"] = r_hesap.apply(lambda row: _hesapla_oneri(row, hedef_gun), axis=1)

# ─── Filtreler ────────────────────────────────────────────────────────────────
filtre_abc = r_hesap["abc_sinifi"].isin(abc_secim)
filtre_aktif = st.sidebar.checkbox("Sadece Aktif SKU", value=True)
filtre_tip = st.sidebar.multiselect(
    "Talep Tipi",
    options=r_hesap["talep_tipi"].unique().tolist(),
    default=r_hesap["talep_tipi"].unique().tolist(),
)

r_filtre = r_hesap[
    filtre_abc
    & (r_hesap["talep_tipi"].isin(filtre_tip))
]
if filtre_aktif:
    r_filtre = r_filtre[r_filtre["risk_bandi"] != "Gri"]

if arama:
    r_filtre = r_filtre[
        r_filtre["kanonik_ad"].str.contains(arama, case=False, na=False)
        | r_filtre["barkod"].str.contains(arama, case=False, na=False)
    ]

# ─── KPI ──────────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric("Gösterilen SKU", len(r_filtre))
k2.metric("🔴 Kritik (Kırmızı)", (r_filtre["risk_bandi"] == "Kırmızı").sum())
k3.metric("Toplam Öneri Adet", f"{r_filtre['onerilen_stok'].sum():,.0f}")
k4.metric("Ort. Günlük Talep", f"{r_filtre['gunluk_ort'].mean():.2f}")

st.markdown("---")

# ─── Risk Bandı Dağılımı ──────────────────────────────────────────────────────
col1, col2 = st.columns([1, 2])
with col1:
    st.subheader("🎯 Risk Bandı Dağılımı")
    risk_say = r_filtre["risk_bandi"].value_counts().reset_index()
    risk_say.columns = ["Risk", "Adet"]
    renk_risk = {"Kırmızı": "#E74C3C", "Turuncu": "#F39C12", "Yeşil": "#2ECC71", "Gri": "#BDC3C7"}
    fig_risk = px.pie(
        risk_say, names="Risk", values="Adet",
        color="Risk", color_discrete_map=renk_risk,
        hole=0.45,
    )
    fig_risk.update_traces(textinfo="label+value")
    fig_risk.update_layout(height=280, margin=dict(t=10))
    st.plotly_chart(fig_risk, use_container_width=True)

with col2:
    st.subheader("📊 ABC × Önerilen Stok (Top 20)")
    top20r = r_filtre.nlargest(20, "onerilen_stok")
    fig_bar = px.bar(
        top20r,
        x="onerilen_stok",
        y=top20r["kanonik_ad"].str[:30],
        orientation="h",
        color="abc_sinifi",
        color_discrete_map={"A": "#E74C3C", "B": "#F39C12", "C": "#2ECC71"},
        labels={"onerilen_stok": "Önerilen Stok (Adet)", "y": "", "abc_sinifi": "ABC"},
    )
    fig_bar.update_layout(
        yaxis={"categoryorder": "total ascending"},
        height=280, margin=dict(l=0, t=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ─── Öneri Tablosu ────────────────────────────────────────────────────────────
st.subheader("📋 Satın Alma Önerisi Tablosu")
goster_kolonlar = ["barkod", "kanonik_ad", "abc_sinifi", "talep_tipi",
                   "gunluk_ort", "onerilen_stok", "risk_bandi", "uyari"]
st.dataframe(
    r_filtre[goster_kolonlar].rename(columns={
        "barkod": "Barkod", "kanonik_ad": "Ürün Adı", "abc_sinifi": "ABC",
        "talep_tipi": "Talep Tipi", "gunluk_ort": "Günlük Ort.",
        "onerilen_stok": "Öneri Adet", "risk_bandi": "Risk", "uyari": "Uyarı",
    }),
    use_container_width=True,
    height=350,
)

st.markdown("---")

# ─── "X Stoksam Kaç Gün?" Hesaplayıcı ────────────────────────────────────────
st.subheader("🧮 \"X Adet Stoksam Kaç Gün Yeter?\"")
hesap_col1, hesap_col2 = st.columns(2)

with hesap_col1:
    hesap_barkod_list = r_filtre[r_filtre["gunluk_ort"] > 0]["barkod"].tolist()
    if hesap_barkod_list:
        hesap_b = st.selectbox(
            "Ürün Seçin",
            options=hesap_barkod_list,
            format_func=lambda b: r_filtre.set_index("barkod").loc[b, "kanonik_ad"][:50]
            if b in r_filtre["barkod"].values else b,
        )
        mevcut_x = st.number_input("Mevcut Stok (Adet)", min_value=0, value=100, step=10)
        if hesap_b:
            gort = float(r_filtre.set_index("barkod").loc[hesap_b, "gunluk_ort"])
            if gort > 0:
                kac_gun = mevcut_x / gort
                st.success(f"**{mevcut_x:,}** adet stok ≈ **{kac_gun:.0f} gün** yeter  \n"
                           f"(günlük ort. talep: {gort:.2f} adet)")
            else:
                st.info("Bu ürün için günlük ortalama talep 0.")
    else:
        st.info("Aktif ürün bulunamadı.")

st.markdown("---")
excel_indirme_butonu(r_filtre, "satin_alma_onerisi.xlsx", "📥 Öneri Tablosunu İndir")
