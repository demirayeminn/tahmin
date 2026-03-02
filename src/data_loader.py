"""
data_loader.py — Ham sipariş verisini okur, temizler ve canonical name atar.

REF-02 adımları:
  1. Excel oku → DataFrame
  2. Sütun adlarını standartlaştır
  3. Tarihleri parse et
  4. Barkodları normalize et
  5. Adet kontrolü (0/negatif → flag)
  6. Kanonik ad hesapla (barkod bazında mod)
  7. Alias tablosu oluştur
  8. Çıktı: clean_orders + product_master_seed → parquet
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Proje kökünü path'e ekle (script olarak çalıştırıldığında)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    CLEAN_ORDERS_PARQUET,
    DATA_PROCESSED_DIR,
    KOLON_MAP,
    LOG_FORMAT,
    LOG_LEVEL,
    SIPARIS_DOSYASI,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)


# ─── Yardımcı Fonksiyonlar ───────────────────────────────────────────────────

def _standartlastir_kolon_adi(ad: str) -> str:
    """Ham sütun adını küçük harf + strip ile normalize et."""
    return ad.strip().lower().replace("i̇", "i")


def _kolon_adlarini_esle(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame'deki sütunları KOLON_MAP'e göre standart isimlere çevir.
    Eşleşmeyen sütunları olduğu gibi bırakır.
    """
    yeni_isimler: dict[str, str] = {}
    for ham_ad in df.columns:
        normalize = _standartlastir_kolon_adi(str(ham_ad))
        if normalize in KOLON_MAP:
            yeni_isimler[ham_ad] = KOLON_MAP[normalize]
        else:
            yeni_isimler[ham_ad] = ham_ad
    df = df.rename(columns=yeni_isimler)
    log.debug("Sütun adları: %s", list(df.columns))
    return df


def _zorunlu_kolonlari_kontrol_et(df: pd.DataFrame) -> None:
    """Beklenen sütunların varlığını doğrula; eksikse ValueError fırlat."""
    beklenen = {"tarih", "siparis_no", "urun_fatura_ismi", "adet", "barkod"}
    eksik = beklenen - set(df.columns)
    if eksik:
        raise ValueError(f"Eksik sütunlar: {eksik}. Mevcut: {list(df.columns)}")


def _tarihleri_parse_et(df: pd.DataFrame) -> pd.DataFrame:
    """
    'tarih' sütununu pandas datetime'a çevir (yerel, naïve).
    Parse edilemeyen değerleri NaT yap ve logla.
    """
    onceki_tip = df["tarih"].dtype
    df["tarih"] = pd.to_datetime(df["tarih"], errors="coerce", dayfirst=True)
    nat_sayisi = df["tarih"].isna().sum()
    if nat_sayisi > 0:
        log.warning("Tarih parse edilemeyen satır sayısı: %d (NaT — düşürülecek)", nat_sayisi)
        df = df.dropna(subset=["tarih"])
    log.info("Tarih dönüşümü tamamlandı. Tip: %s → datetime64[ns]", onceki_tip)
    return df


def _barkodu_normalize_et(df: pd.DataFrame) -> pd.DataFrame:
    """
    Barkod sütununu string'e çevir, strip uygula, büyük harf yap.
    Boş/NaN barkodları çıkar.
    """
    df["barkod"] = (
        df["barkod"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": np.nan, "": np.nan, "NONE": np.nan})
    )
    bos_barkod = df["barkod"].isna().sum()
    if bos_barkod > 0:
        log.warning("Boş/geçersiz barkod sayısı: %d (düşürülecek)", bos_barkod)
        df = df.dropna(subset=["barkod"])
    return df


def _adet_kontrolu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adet sütununu numerik'e çevir.
    0 veya negatif değerlere 'anormal_adet' bayrağı ekle.
    """
    df["adet"] = pd.to_numeric(df["adet"], errors="coerce")
    sayisal_hata = df["adet"].isna().sum()
    if sayisal_hata > 0:
        log.warning("Adet parse edilemeyen satır: %d (düşürülecek)", sayisal_hata)
        df = df.dropna(subset=["adet"])

    df["anormal_adet"] = df["adet"] <= 0
    anormal_sayisi = df["anormal_adet"].sum()
    if anormal_sayisi > 0:
        log.warning("0 veya negatif adetli kayıt sayısı: %d (flag eklendi, silinmedi)", anormal_sayisi)
    return df


def _kanonik_ad_ve_alias(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Barkod bazında kanonik ad (mod) ve alias listesini hesapla.

    Returns:
        df: 'kanonik_ad' sütunu eklenmiş sipariş DataFrame'i
        alias_df: barkod → alias_listesi (JSON) tablosu
    """
    # Kanonik ad: her barkod için en çok görülen ürün ismi
    # mode() boş dönebilir (tüm değerler NaN) → güvenli fallback
    def _mod_al(x: pd.Series) -> str:
        temiz = x.dropna()
        if temiz.empty:
            return "BİLİNMİYOR"
        m = temiz.mode()
        return m.iloc[0] if len(m) > 0 else temiz.iloc[0]

    kanonik = (
        df.groupby("barkod")["urun_fatura_ismi"]
        .agg(_mod_al)
        .rename("kanonik_ad")
        .reset_index()
    )

    # Alias listesi: her barkod için benzersiz isim kümesi
    alias = (
        df.groupby("barkod")["urun_fatura_ismi"]
        .agg(lambda x: json.dumps(sorted(x.dropna().unique().tolist()), ensure_ascii=False))
        .rename("alias_listesi")
        .reset_index()
    )

    alias_df = kanonik.merge(alias, on="barkod")
    alias_df["alias_sayisi"] = alias_df["alias_listesi"].apply(
        lambda x: len(json.loads(x))
    )

    # Sipariş DataFrame'ine kanonik adı ekle
    df = df.merge(kanonik, on="barkod", how="left")

    log.info(
        "Kanonik ad hesaplandı. Benzersiz barkod: %d | Çoklu alias barkodar: %d",
        len(kanonik),
        (alias_df["alias_sayisi"] > 1).sum(),
    )
    return df, alias_df


def _urun_master_seed_olustur(df: pd.DataFrame, alias_df: pd.DataFrame) -> pd.DataFrame:
    """
    Sipariş verisinden T1 için temel istatistikleri hesapla (segmentasyon öncesi).
    Segmentasyon (ABC, talep tipi, sağlık skoru) segmentation.py'de eklenecek.
    """
    # Sadece normal (anormal_adet=False) kayıtlar üzerinden istatistik al
    normal = df[~df["anormal_adet"]].copy()

    agg = (
        normal.groupby("barkod")
        .agg(
            ilk_satis_tarihi=("tarih", "min"),
            son_satis_tarihi=("tarih", "max"),
            toplam_adet=("adet", "sum"),
            toplam_siparis=("siparis_no", "nunique"),
        )
        .reset_index()
    )

    # Gün sayısı ve günlük ortalama
    agg["satis_gun_sayisi"] = (
        (agg["son_satis_tarihi"] - agg["ilk_satis_tarihi"]).dt.days + 1
    )
    agg["gunluk_ort_adet"] = agg["toplam_adet"] / agg["satis_gun_sayisi"].clip(lower=1)

    # Alias bilgilerini ekle
    master = agg.merge(alias_df, on="barkod", how="left")

    # Aktiflik: son 30 günde satış var mı
    son_tarih = normal["tarih"].max()
    son30 = (
        normal[normal["tarih"] >= son_tarih - pd.Timedelta(days=30)]
        .groupby("barkod")["adet"]
        .sum()
        .gt(0)
        .rename("aktif")
        .reset_index()
    )
    master = master.merge(son30, on="barkod", how="left")
    master["aktif"] = master["aktif"].fillna(False)

    log.info("Ürün master seed oluşturuldu. SKU sayısı: %d", len(master))
    return master


# ─── Ana Fonksiyon ───────────────────────────────────────────────────────────

def yukle_ve_temizle(
    dosya: Path = SIPARIS_DOSYASI,
    kaydet: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Ham sipariş Excel'ini okur, temizler ve parquet olarak kaydeder.

    Args:
        dosya: Okunacak Excel dosyası (sadece oku, değiştirme!).
        kaydet: True ise parquet dosyalarını data/processed/ altına yazar.

    Returns:
        (clean_orders, product_master_seed): İki DataFrame tuple'ı.
    """
    log.info("Excel okunuyor: %s", dosya)
    ham_df = pd.read_excel(dosya, engine="openpyxl")
    log.info("Ham satır sayısı: %d | Sütunlar: %s", len(ham_df), list(ham_df.columns))

    # 1. Sütun adlarını standartlaştır
    df = _kolon_adlarini_esle(ham_df)
    _zorunlu_kolonlari_kontrol_et(df)

    # 2. Tarih parse
    df = _tarihleri_parse_et(df)

    # 3. Barkod normalize
    df = _barkodu_normalize_et(df)

    # 4. Adet kontrolü
    df = _adet_kontrolu(df)

    # 5-6. Kanonik ad + alias
    df, alias_df = _kanonik_ad_ve_alias(df)

    # 7. Ürün master seed
    master = _urun_master_seed_olustur(df, alias_df)

    log.info(
        "Temizlik tamamlandı. Kalan satır: %d | Benzersiz barkod: %d",
        len(df),
        df["barkod"].nunique(),
    )

    if kaydet:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(CLEAN_ORDERS_PARQUET, index=False)
        log.info("Kaydedildi: %s", CLEAN_ORDERS_PARQUET)

    return df, master


def gunluk_talep_olustur(
    df: pd.DataFrame,
    kaydet: bool = True,
) -> pd.DataFrame:
    """
    Temiz sipariş verisinden günlük talep tablosu (T2) üretir.
    Eksik günler 0 adet ile doldurulur.

    Args:
        df: clean_orders DataFrame'i (yukle_ve_temizle çıktısı).
        kaydet: True ise parquet kaydeder.

    Returns:
        Günlük talep DataFrame'i (T2 formatı).
    """
    from src.config import DAILY_DEMAND_PARQUET

    # Sadece normal kayıtlar
    normal = df[~df["anormal_adet"]].copy()

    # Tarihi gün başına normalize et (saat bileşenini sıfırla)
    normal = normal.copy()
    normal["tarih"] = normal["tarih"].dt.normalize()

    # Günlük adet topla (barkod × tarih)
    gunluk = (
        normal.groupby(["barkod", "tarih"])["adet"]
        .sum()
        .reset_index()
    )

    # Tarih aralığını kapsayan tam ızgara oluştur (eksik günler → 0)
    min_tarih = gunluk["ızgara_min"] if "ızgara_min" in gunluk else gunluk["tarih"].min()
    min_tarih = gunluk["tarih"].min()
    max_tarih = gunluk["tarih"].max()
    tum_tarihler = pd.date_range(min_tarih, max_tarih, freq="D")

    tum_barkodlar = gunluk["barkod"].unique()
    izgara = pd.MultiIndex.from_product(
        [tum_barkodlar, tum_tarihler], names=["barkod", "tarih"]
    )
    tam_df = gunluk.set_index(["barkod", "tarih"]).reindex(izgara, fill_value=0).reset_index()

    # T2 sütunları (REF-08)
    tam_df = tam_df.sort_values(["barkod", "tarih"])
    tam_df["kumulatif_adet"] = tam_df.groupby("barkod")["adet"].cumsum()
    tam_df["hafta_ici_mi"] = tam_df["tarih"].dt.dayofweek < 5   # Pzt-Cum
    tam_df["hafta_no"] = tam_df["tarih"].dt.isocalendar().week.astype(int)
    tam_df["ay"] = tam_df["tarih"].dt.month

    log.info(
        "Günlük talep tablosu oluşturuldu. Satır: %d | Barkod: %d | Tarih aralığı: %s – %s",
        len(tam_df),
        tam_df["barkod"].nunique(),
        min_tarih.date(),
        max_tarih.date(),
    )

    if kaydet:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        tam_df.to_parquet(DAILY_DEMAND_PARQUET, index=False)
        log.info("Kaydedildi: %s", DAILY_DEMAND_PARQUET)

    return tam_df


# ─── Script olarak çalıştırma ─────────────────────────────────────────────────
if __name__ == "__main__":
    clean_orders, product_master_seed = yukle_ve_temizle()
    daily_demand = gunluk_talep_olustur(clean_orders)
    print("\n=== Özet ===")
    print(f"Temiz sipariş satırı : {len(clean_orders):,}")
    print(f"Benzersiz barkod     : {clean_orders['barkod'].nunique():,}")
    print(f"Günlük talep satırı  : {len(daily_demand):,}")
    print(f"Tarih aralığı        : {daily_demand['tarih'].min().date()} → {daily_demand['tarih'].max().date()}")
