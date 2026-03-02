"""
06_alarm.py — Stok Alarm Listesi.

Icerik:
  - Ust bant: Stok Bitmis / Kritik / Uyari / Izle sayaclari
  - Alarm tablosu: T8 verileri, renk kodlu, kalan gun artan sirali
  - Filtreler: ABC, kategori, marka, alarm seviyesi
  - Son guncelleme zaman damgasi
  - Excel indirme butonu
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import alarms, excel_indirme_butonu

# ─── Veri yukle ───────────────────────────────────────────────────────────────

df_alarm = alarms()

if df_alarm.empty:
    st.warning(
        "Alarm verisi bulunamadi. "
        "Once 'python -m src.alarm' veya 'python -m src.scheduler' calistirin."
    )
    st.stop()

# ─── Filtreler (ustte, acilir kutu) ────────────────────────────────────────────

st.markdown("### Filtreler")

with st.expander("Filtreleri ac / kapa", expanded=False):
    col1, col2 = st.columns(2)

    with col1:
        abc_secenek = (
            sorted(df_alarm["abc_sinifi"].dropna().unique().tolist())
            if "abc_sinifi" in df_alarm.columns
            else ["A", "B", "C"]
        )
        abc_secim = st.multiselect(
            "ABC Sinifi",
            options=abc_secenek,
            default=abc_secenek,
        )

        if "kategori" in df_alarm.columns and df_alarm["kategori"].notna().any():
            kat_secenek = sorted(df_alarm["kategori"].dropna().unique().tolist())
            kat_secim = st.multiselect("Kategori", options=kat_secenek, default=kat_secenek)
        else:
            kat_secim = None

    with col2:
        seviye_etiket = {
            "stok_bitmis": "Stok Bitmis",
            "kritik": "Kritik",
            "uyarı": "Uyari",
            "izle": "Izle",
            "normal": "Normal",
            "pasif": "Pasif",
        }
        seviye_secenek = ["stok_bitmis", "kritik", "uyarı", "izle", "normal", "pasif"]
        seviye_mevcut = [s for s in seviye_secenek if s in df_alarm["alarm_seviye"].unique()]
        seviye_secim = st.multiselect(
            "Alarm Seviyesi",
            options=seviye_mevcut,
            default=seviye_mevcut,
            format_func=lambda x: seviye_etiket.get(x, x),
        )

        if "marka" in df_alarm.columns and df_alarm["marka"].notna().any():
            marka_secenek = sorted(df_alarm["marka"].dropna().unique().tolist())
            marka_secim = st.multiselect("Marka", options=marka_secenek, default=marka_secenek)
        else:
            marka_secim = None

    arama = st.text_input("Urun Ara (ad veya barkod)")

    negatif_stok_gizle = st.checkbox(
        "Mevcut stogu negatif olan urunleri gizle",
        value=True,
    )

    yalnizca_a = st.checkbox(
        "Sadece A sinifi (en onemli urunler)",
        value=False,
    )

    bugun_guncellenen = st.checkbox(
        "Sadece bugun guncellenen urunler",
        value=False,
    )

# ─── Filtre uygula ────────────────────────────────────────────────────────────

df = df_alarm.copy()

if abc_secim:
    df = df[df["abc_sinifi"].isin(abc_secim)]
if seviye_secim:
    df = df[df["alarm_seviye"].isin(seviye_secim)]
if kat_secim is not None:
    df = df[df["kategori"].isin(kat_secim)]
if marka_secim is not None:
    df = df[df["marka"].isin(marka_secim)]
if arama:
    mask = (
        df["kanonik_ad"].str.contains(arama, case=False, na=False)
        | df["barkod"].str.contains(arama, case=False, na=False)
    )
    df = df[mask]

if negatif_stok_gizle and "mevcut_stok" in df.columns:
    df = df[df["mevcut_stok"] >= 0]

if yalnizca_a and "abc_sinifi" in df.columns:
    df = df[df["abc_sinifi"] == "A"]

if bugun_guncellenen and "son_guncelleme" in df.columns:
    bugun = pd.Timestamp.now().normalize()
    df = df[pd.to_datetime(df["son_guncelleme"]).dt.normalize() == bugun]

# ─── Baslik ───────────────────────────────────────────────────────────────────

st.title("Stok Alarm Listesi")

if "son_guncelleme" in df_alarm.columns and df_alarm["son_guncelleme"].notna().any():
    son_gun = df_alarm["son_guncelleme"].dropna().max()
    st.caption(f"Son guncelleme: {pd.Timestamp(son_gun).strftime('%d.%m.%Y %H:%M')}")

st.divider()

# ─── Ust bant: sayaclar ───────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns(5)
ozet = df_alarm["alarm_seviye"].value_counts()

c1.metric("Stok Bitmis",  int(ozet.get("stok_bitmis", 0)))
c2.metric("Kritik",       int(ozet.get("kritik", 0)))
c3.metric("Uyari",        int(ozet.get("uyarı", 0)))
c4.metric("Izle",         int(ozet.get("izle", 0)))
c5.metric("Normal",       int(ozet.get("normal", 0)))

st.divider()

# A sinifi ozet sayaclari
if "abc_sinifi" in df_alarm.columns:
    a_df = df_alarm[df_alarm["abc_sinifi"] == "A"]
    if not a_df.empty:
        a_ozet = a_df["alarm_seviye"].value_counts()
        a1, a2, a3 = st.columns(3)
        a1.metric("A sinifi stok bitmis", int(a_ozet.get("stok_bitmis", 0)))
        a2.metric("A sinifi kritik",      int(a_ozet.get("kritik", 0)))
        a3.metric("A sinifi uyari",       int(a_ozet.get("uyarı", 0)))
        st.divider()

# ─── Alarm tablosu ────────────────────────────────────────────────────────────

goruntule_cols = [
    c for c in [
        "kanonik_ad", "barkod", "abc_sinifi",
        "kategori", "marka",
        "mevcut_stok", "gunluk_tahmin", "kalan_gun",
        "alarm_seviye", "onerilen_siparis",
    ] if c in df.columns
]

st.write(f"Gosterilen urun sayisi: **{len(df)}**")


ALARM_RENK = {
    "stok_bitmis": "background-color: #ff9999; color: #000000",
    "kritik":      "background-color: #ffcc80; color: #000000",
    "uyarı":       "background-color: #fff176; color: #000000",
    "izle":        "background-color: #e8f5e9; color: #000000",
    "normal":      "background-color: #ffffff; color: #000000",
    "pasif":       "background-color: #d0d0d0; color: #555555",
}


def _renk_satir(row: pd.Series) -> list[str]:
    seviye = row["alarm_seviye"] if "alarm_seviye" in row.index else ""
    renk = ALARM_RENK.get(seviye, "background-color: #ffffff; color: #000000")
    return [renk] * len(row)


KOLON_ISIM = {
    "kanonik_ad":      "Urun Adi",
    "barkod":          "Barkod",
    "abc_sinifi":      "ABC",
    "kategori":        "Kategori",
    "marka":           "Marka",
    "mevcut_stok":     "Mevcut Stok",
    "gunluk_tahmin":   "Gunluk Talep",
    "kalan_gun":       "Kalan Gun",
    "alarm_seviye":    "Alarm",
    "onerilen_siparis":"Onerilen Siparis",
}

if not df.empty:
    def _format_kalan_gun(v: object) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return str(v)
        if x <= 0:
            return "0 gun"
        if float(x).is_integer():
            return f"{int(x)} gun"
        import math

        gun = math.ceil(x)
        return f"{gun} gunden az"

    goruntule = df[goruntule_cols].copy()
    if "kalan_gun" in goruntule.columns:
        goruntule["kalan_gun"] = goruntule["kalan_gun"].apply(_format_kalan_gun)
    # Renklendirme ÖNCE uygulanır (alarm_seviye sütunu henüz var),
    # ardından başlıklar Türkçe olarak relabel edilir.
    yeni_isimler = [KOLON_ISIM.get(c, c) for c in goruntule.columns]
    styled = goruntule.style.apply(_renk_satir, axis=1)
    styled = styled.relabel_index(yeni_isimler, axis="columns")
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.info("Secilen filtrelerle eslesen alarm bulunamadi.")

# ─── Renk aciklamasi ──────────────────────────────────────────────────────────

st.divider()
st.markdown(
    "**Renk aciklamasi:** "
    "Kirmizi = Stok Bitmis &nbsp;|&nbsp; "
    "Turuncu = Kritik &nbsp;|&nbsp; "
    "Sari = Uyari &nbsp;|&nbsp; "
    "Yesil = Izle &nbsp;|&nbsp; "
    "Beyaz = Normal &nbsp;|&nbsp; "
    "Gri = Pasif"
)

# ─── Indirme ──────────────────────────────────────────────────────────────────

st.divider()
_excel_df = df[goruntule_cols].rename(columns=KOLON_ISIM) if not df.empty else df
excel_indirme_butonu(_excel_df, "alarm_raporu.xlsx", "Alarm Raporunu Indir")

# ─── Kalan gun dagilimi grafigi ───────────────────────────────────────────────

st.divider()
st.subheader("Kalan Gun Dagilimi (Alarmlar)")

if "kalan_gun" in df.columns:
    import plotly.express as px

    df_plot = df[df["alarm_seviye"].isin(["stok_bitmis", "kritik", "uyarı", "izle"])].copy()
    df_plot = df_plot[df_plot["kalan_gun"].notna()]

    renk_map_px = {
        "stok_bitmis": "#cc0000",
        "kritik":      "#E74C3C",
        "uyarı":       "#F39C12",
        "izle":        "#F1C40F",
    }

    if not df_plot.empty:
        ad_kol = "kanonik_ad" if "kanonik_ad" in df_plot.columns else "barkod"
        fig = px.bar(
            df_plot.sort_values("kalan_gun"),
            x=ad_kol,
            y="kalan_gun",
            color="alarm_seviye",
            color_discrete_map=renk_map_px,
            labels={
                ad_kol:        "Urun",
                "kalan_gun":   "Kalan Gun",
                "alarm_seviye":"Alarm Seviyesi",
            },
            title="Kritik / Uyari Urunler — Kalan Gun",
        )
        fig.update_layout(xaxis_tickangle=-45, height=450)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Gosterilecek alarm yok.")
