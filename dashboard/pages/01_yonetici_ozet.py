"""
01_yonetici_ozet.py — Stok Takip Tablosu (Ana Sayfa)

Acilis sayfasi. Kullaniciya dogrudan:
  - Her urun icin mevcut stok, kalan gun, durum
  - 1 / 2 / 3 aylik alim onerisi
  - 50 gunluk tahmini satis
  tablosu gosterir.
"""
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard._veri import ana_tablo, daily, excel_indirme_butonu, stock_history, alarms

# ─── Veri ─────────────────────────────────────────────────────────────────────

df_tam = ana_tablo()

# ─── Baslik ───────────────────────────────────────────────────────────────────

st.title("Stok Takip Tablosu")
st.caption(
    "Her urun icin mevcut stok, ne kadar surede biter ve ne kadar siparis verilmesi gerektigi gosterilir."
)

st.write("")
if st.button("Stoklari Guncelle (Entegra'dan)", type="primary"):
    with st.spinner("Stoklar guncelleniyor..."):
        try:
            from src.entegra_api import cek_entegra_urunleri_incremental
            from src.enrichment import zenginlestir
            from src.alarm import hesapla_alarmlar

            entegra_df = cek_entegra_urunleri_incremental()
            if entegra_df is not None and not entegra_df.empty:
                zenginlestir(entegra_df)
                hesapla_alarmlar()

                # Cache'leri temizle ki yeni veriler hemen gorunsun
                try:
                    ana_tablo.clear()
                    daily.clear()
                    stock_history.clear()
                    alarms.clear()
                except Exception:
                    pass

                st.success("Stoklar guncellendi. Tablo yenilendi.")
            else:
                st.warning("Entegra'dan stok verisi alinamadi.")
        except Exception as exc:
            st.error(f"Stok guncelleme sirasinda hata olustu: {exc}")
st.divider()

# ─── Ozet sayilar ─────────────────────────────────────────────────────────────

toplam = len(df_tam)
stok_yok = (df_tam["Durum"] == "Stok Yok").sum()
kritik = (df_tam["Durum"] == "Kritik").sum()
uyari = (df_tam["Durum"] == "Uyari").sum()
yeterli = (df_tam["Durum"] == "Yeterli").sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Toplam Urun", toplam)
k2.metric("Stok Yok", stok_yok)
k3.metric("Kritik (7 gun veya az kaldi)", kritik)
k4.metric("Uyari (8-30 gun kaldi)", uyari)
k5.metric("Yeterli (30 gunun uzeri)", yeterli)

st.divider()

# ─── Toplam siparis onerisi ozetleri ─────────────────────────────────────────

toplam_1ay = int(df_tam["1 Ay Alım Önerisi"].sum()) if "1 Ay Alım Önerisi" in df_tam.columns else 0
toplam_2ay = int(df_tam["2 Ay Alım Önerisi"].sum()) if "2 Ay Alım Önerisi" in df_tam.columns else 0
toplam_3ay = int(df_tam["3 Ay Alım Önerisi"].sum()) if "3 Ay Alım Önerisi" in df_tam.columns else 0

t1, t2, t3 = st.columns(3)
t1.metric("1 Ay Toplam Oneri", f"{toplam_1ay:,.0f}")
t2.metric("2 Ay Toplam Oneri", f"{toplam_2ay:,.0f}")
t3.metric("3 Ay Toplam Oneri", f"{toplam_3ay:,.0f}")

st.divider()

# ─── Filtreler (ustte, acilir kutu) ────────────────────────────────────────────

st.markdown("### Filtreler")

with st.expander("Filtreleri ac / kapa", expanded=False):
    f1, f2 = st.columns(2)

    with f1:
        abc_secim = st.multiselect(
            "ABC Sinifi",
            options=["A", "B", "C"],
            default=["A", "B", "C"],
            help="A = en cok satan urunler, C = en az satan urunler",
        )

    with f2:
        durum_secim = st.multiselect(
            "Durum",
            options=["Stok Yok", "Kritik", "Uyari", "Yeterli", "Pasif"],
            default=["Stok Yok", "Kritik", "Uyari", "Yeterli", "Pasif"],
        )

    arama = st.text_input("Urun Ara (urun adi veya barkod yaz)")

    hizli_filtre = st.radio(
        "Gorunumu secin (basit filtre)",
        options=["Hepsi", "Sadece stok yok + kritik", "Sadece A sinifi"],
        index=0,
    )

    negatif_stok_gizle = st.checkbox(
        "Mevcut stogu negatif olan urunleri gizle",
        value=True,
        help="Isaretliyken mevcut stogu 0'in altinda olan satirlar tabloda gosterilmez.",
    )

# ─── Filtre uygula ────────────────────────────────────────────────────────────

df = df_tam.copy()

if hizli_filtre == "Sadece stok yok + kritik":
    df = df[df["Durum"].isin(["Stok Yok", "Kritik"])]
elif hizli_filtre == "Sadece A sinifi":
    df = df[df["ABC"] == "A"]
else:
    if abc_secim:
        df = df[df["ABC"].isin(abc_secim)]
    if durum_secim:
        df = df[df["Durum"].isin(durum_secim)]

if arama:
    mask = (
        df["Ürün Adı"].str.contains(arama, case=False, na=False)
        | df["Barkod"].str.contains(arama, case=False, na=False)
    )
    df = df[mask]

if negatif_stok_gizle and "Mevcut Stok" in df.columns:
    df = df[df["Mevcut Stok"] >= 0]

# Tahmini bitis tarihi (bugun + kalan gun)
bugun = date.today()

def _tahmini_bitis(kalan: object) -> str:
    if kalan is None or (isinstance(kalan, float) and pd.isna(kalan)):
        return ""
    try:
        x = float(kalan)
    except (TypeError, ValueError):
        return ""
    if x <= 0:
        return ""
    gun = math.ceil(x)
    try:
        return (bugun + timedelta(days=gun)).strftime("%d.%m.%Y")
    except Exception:
        return ""

if "Kalan Gün" in df.columns:
    df["Tahmini Bitis Tarihi"] = df["Kalan Gün"].apply(_tahmini_bitis)

st.write(f"Gosterilen urun sayisi: **{len(df)}**")

# ─── Renklendirme ─────────────────────────────────────────────────────────────

RENK = {
    "Stok Yok": "background-color: #ff9999; color: #000000",
    "Kritik":   "background-color: #ffcc80; color: #000000",
    "Uyari":    "background-color: #fff176; color: #000000",
    "Yeterli":  "background-color: #ffffff; color: #000000",
    "Pasif":    "background-color: #d0d0d0; color: #555555",
}


def _satir_rengi(row: pd.Series) -> list[str]:
    durum = row["Durum"] if "Durum" in row.index else ""
    renk = RENK.get(durum, "background-color: #ffffff; color: #000000")
    return [renk] * len(row)


# ─── Tablo ────────────────────────────────────────────────────────────────────

# Gosterilecek kolonlar ve sirasi
goster_kolonlar = [
    "Barkod",
    "Ürün Adı",
    "ABC",
    "Mevcut Stok",
    "Kalan Gün",
    "Tahmini Bitis Tarihi",
    "Durum",
    "1 Ay Alım Önerisi",
    "2 Ay Alım Önerisi",
    "3 Ay Alım Önerisi",
    "50 Gün Tahmin Satış",
]
goster = [k for k in goster_kolonlar if k in df.columns]

# Kolon aciklamalari (hover/tooltip icin kullanilabilir)
# - Kalan Gun: mevcut stok bu hizda satilirsa kac gunde biter
# - 1/2/3 Ay Alim Onerisi: o ay icin yetecek kadar stogu saglamak icin siparis edilmesi gereken miktar
# - 50 Gun Tahmin Satis: tahmini satis adedi

if not df.empty:
    def _format_kalan_gun_deger(v: object) -> str:
        if v is None or (isinstance(v, float) and (pd.isna(v))):
            return ""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return str(v)
        if x <= 0:
            return "0 gun"
        if float(x).is_integer():
            return f"{int(x)} gun"
        gun = math.ceil(x)
        return f"{gun} gunden az"

    df_goster = df[goster].copy()
    if "Kalan Gün" in df_goster.columns:
        df_goster["Kalan Gün"] = df_goster["Kalan Gün"].apply(_format_kalan_gun_deger)

    styled = df_goster.style.apply(_satir_rengi, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.info("Secilen filtrelere uygun urun bulunamadi.")

# ─── Renk aciklamasi ──────────────────────────────────────────────────────────

st.divider()
st.markdown(
    "**Renk aciklamasi:** "
    "Kirmizi = Stok Yok (hemen siparis ver) &nbsp;|&nbsp; "
    "Turuncu = Kritik (7 gun veya az kaldi) &nbsp;|&nbsp; "
    "Sari = Uyari (8-30 gun kaldi) &nbsp;|&nbsp; "
    "Beyaz = Yeterli &nbsp;|&nbsp; "
    "Gri = Pasif (son 30 gunde satis yok)"
)

# ─── Sutun aciklamasi ─────────────────────────────────────────────────────────

with st.expander("Sutun aciklamalari nedir?"):
    st.markdown(
        """
| Sutun | Aciklama |
|-------|---------|
| Mevcut Stok | Depoda su an bulunan adet. (0 ise ya stok bitti ya da Entegra baglantisi yok.) |
| Kalan Gun | Bu hizda satilirsa stok kac gunde tukenir. |
| Durum | Stok durumunun ozeti: Stok Yok / Kritik / Uyari / Yeterli / Pasif. |
| 1 Ay Alim Onerisi | Onumuzdeki 30 gun icin yetecek stogu saglamak icin siparis edilmesi gereken adet. |
| 2 Ay Alim Onerisi | Onumuzdeki 60 gun icin gerekli siparis adedi. |
| 3 Ay Alim Onerisi | Onumuzdeki 90 gun icin gerekli siparis adedi. |
| 50 Gun Tahmin Satis | Onumuzdeki 50 gunde yaklasik kac adet satilmasi bekleniyor. |
        """
    )

st.divider()
excel_indirme_butonu(df[goster] if not df.empty else pd.DataFrame(columns=goster), "stok_takip.xlsx", "Tabloyu Excel Olarak Indir")

# ─── Urun Stok Degisim Grafigi ────────────────────────────────────────────────

st.divider()
st.subheader("Urun Bazli Stok Degisimi")
st.caption("Entegra'dan her veri cekiminde anlık stok seviyesi kaydedilir. Asagıdan bir urun secin.")

df_history = stock_history()

if df_history.empty:
    st.info(
        "Henuz stok gecmisi yok. "
        "baslat.bat calistirildikca her gun stok seviyesi buraya birikir."
    )
else:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df_daily = daily()

    # Urun secici: sadece gecmiste kaydi olan urunler
    barkodlar = sorted(df_history["barkod"].unique().tolist())

    # Urun adini barkoda esle (ana tablodan)
    barkod_ad = df_tam.set_index("Barkod")["Ürün Adı"].to_dict() if not df_tam.empty else {}
    secenekler = [f"{b}  —  {barkod_ad.get(b, '')}" for b in barkodlar]

    secim = st.selectbox(
        "Urun sec",
        options=secenekler,
        index=0,
    )
    secili_barkod = secim.split("  —  ")[0].strip()

    # Stok gecmisi
    df_s = df_history[df_history["barkod"] == secili_barkod].sort_values("tarih")

    # Gunluk satis
    df_d = df_daily[df_daily["barkod"] == secili_barkod].sort_values("tarih")

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.4],
        vertical_spacing=0.08,
        subplot_titles=("Mevcut Stok Seviyesi", "Gunluk Satis Adedi"),
    )

    # Stok cizgisi
    fig.add_trace(
        go.Scatter(
            x=df_s["tarih"],
            y=df_s["mevcut_stok"],
            mode="lines+markers",
            name="Mevcut Stok",
            line=dict(color="#2196F3", width=2),
            marker=dict(size=6),
        ),
        row=1, col=1,
    )

    # Gunluk satis cubukları
    if not df_d.empty:
        fig.add_trace(
            go.Bar(
                x=df_d["tarih"],
                y=df_d["adet"],
                name="Gunluk Satis",
                marker_color="#FF9800",
                opacity=0.8,
            ),
            row=2, col=1,
        )

    fig.update_layout(
        height=520,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=60, b=10),
    )
    fig.update_yaxes(title_text="Adet", row=1, col=1)
    fig.update_yaxes(title_text="Satis", row=2, col=1)
    fig.update_xaxes(title_text="Tarih", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)
