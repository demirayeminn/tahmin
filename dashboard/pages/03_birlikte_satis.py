"""
03_birlikte_satis.py — Birlikte Satış Analizi.

İçerik (REF-09):
  - Ürün seçince top 10 eşleşme (lift sıralı, bar chart)
  - Kural tablosu (support, confidence, lift, aksiyon)
  - Bundle önerisi vurgusu
  - İndirme butonu
"""

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import (
    basket_rules,
    excel_indirme_butonu,
    master,
    sidebar_filtreler,
)
from src.basket_analysis import urun_icin_onerileri_getir

st.set_page_config(page_title="Birlikte Satış", page_icon="🛒", layout="wide")
st.title("🛒 Birlikte Satış Analizi")

# ─── Veri ─────────────────────────────────────────────────────────────────────
m = master()
rules = basket_rules()

abc_secim, kat_secim, marka_secim, _ = sidebar_filtreler(m)

# ─── Genel Kural Tablosu ──────────────────────────────────────────────────────
st.subheader("📋 Tüm Birliktelik Kuralları")

if rules.empty:
    st.warning("Henüz kural üretilmemiş. `src/basket_analysis.py` çalıştırın.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Toplam Kural", len(rules))
c2.metric("Bundle Önerisi", (rules["aksiyon"] == "bundle_onerisi").sum())
c3.metric("En Yüksek Lift", f"{rules['lift'].max():.1f}x")

# Aksiyon renk göstergesi
_RENK = {"bundle_onerisi": "🔴", "beraber_stokla": "🟡", "cross_sell": "🟢"}
rules_goster = rules.copy()
rules_goster["aksiyon"] = rules_goster["aksiyon"].map(
    lambda x: f"{_RENK.get(x, '')} {x}"
)
rules_goster = rules_goster.rename(columns={
    "urun_a_ad": "Ürün A",
    "urun_b_ad": "Ürün B",
    "support": "Destek",
    "confidence": "Güven",
    "lift": "Lift",
    "sepet_sayisi": "Sepet #",
    "aksiyon": "Aksiyon",
})
st.dataframe(
    rules_goster[["Ürün A", "Ürün B", "Destek", "Güven", "Lift", "Sepet #", "Aksiyon"]],
    use_container_width=True,
    height=300,
)

st.markdown("---")

# ─── Ürün Seçici: Top 10 Eşleşme ─────────────────────────────────────────────
st.subheader("🔎 Ürün Seçince Top 10 Eşleşme")

m_filtre = m[m["abc_sinifi"].isin(abc_secim)]
# Sadece kurallarda geçen barkodlar
kural_barkodlar = set(rules["urun_a_barkod"]) | set(rules["urun_b_barkod"])
m_kural = m_filtre[m_filtre["barkod"].isin(kural_barkodlar)]

if m_kural.empty:
    st.info("Seçilen ABC filtresiyle eşleşen ürün yok.")
else:
    secenekler = m_kural.set_index("barkod")["kanonik_ad"].to_dict()
    secim = st.selectbox(
        "Ürün Seçin",
        options=list(secenekler.keys()),
        format_func=lambda b: f"{b} — {secenekler[b][:45]}",
    )

    top10 = urun_icin_onerileri_getir(secim, rules, n=10)

    if top10.empty:
        st.info("Bu ürün için yeterli birlikte satış verisi yok.")
    else:
        col_g, col_t = st.columns([1, 1])

        with col_g:
            fig_lift = px.bar(
                top10,
                x="lift",
                y=top10["urun_b_ad"].str[:35],
                orientation="h",
                color="aksiyon",
                color_discrete_map={
                    "bundle_onerisi": "#E74C3C",
                    "beraber_stokla": "#F39C12",
                    "cross_sell": "#2ECC71",
                },
                labels={"lift": "Lift", "y": "Eşleşen Ürün", "aksiyon": "Aksiyon"},
                title=f"Top {len(top10)} Eşleşme — {secenekler[secim][:30]}",
            )
            fig_lift.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=380,
                margin=dict(l=0, t=40),
            )
            st.plotly_chart(fig_lift, use_container_width=True)

        with col_t:
            st.dataframe(
                top10[["urun_b_ad", "support", "confidence", "lift", "sepet_sayisi", "aksiyon"]]
                .rename(columns={
                    "urun_b_ad": "Eşleşen Ürün",
                    "support": "Destek",
                    "confidence": "Güven",
                    "lift": "Lift",
                    "sepet_sayisi": "Sepet #",
                    "aksiyon": "Aksiyon",
                }),
                use_container_width=True,
                height=380,
            )

        # Bundle önerileri kutusu
        bundle = top10[top10["aksiyon"] == "bundle_onerisi"]
        if not bundle.empty:
            st.success(
                "**🎁 Bundle Önerisi:**  \n"
                + "  \n".join(
                    f"- **{r['urun_b_ad'][:50]}** (lift={r['lift']:.1f}x, "
                    f"güven={r['confidence']*100:.0f}%)"
                    for _, r in bundle.iterrows()
                )
            )

        beraber = top10[top10["aksiyon"] == "beraber_stokla"]
        if not beraber.empty:
            st.info(
                "**📦 Beraber Stokla:**  \n"
                + "  \n".join(f"- {r['urun_b_ad'][:50]}" for _, r in beraber.iterrows())
            )

st.markdown("---")
excel_indirme_butonu(rules, "birlikte_satis_kurallari.xlsx", "📥 Kuralları İndir")
