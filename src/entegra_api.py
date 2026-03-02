"""
entegra_api.py — Entegra API client.

İşlevler:
  - JWT token alma + cache
  - Ürün listesini tüm sayfalarda çekme (pagination)
  - Barkod normalizasyonu
  - Hata yönetimi (retry, partial failure)

Çıktı: data/processed/entegra_products.parquet
"""

import logging
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests

from src.config import (
    DATA_PROCESSED_DIR,
    ENTEGRA_EMAIL,
    ENTEGRA_MAX_RETRY,
    ENTEGRA_PASSWORD,
    ENTEGRA_PRODUCT_URL,
    ENTEGRA_PRODUCTS_PARQUET,
    ENTEGRA_RATE_LIMIT_SANIYE,
    ENTEGRA_TOKEN_URL,
    LOG_FORMAT,
    LOG_LEVEL,
    STOCK_HISTORY_PARQUET,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

# ─── Barkod normalizasyonu ────────────────────────────────────────────────────

def _kod(val: Any) -> str:
    """Float veya string barkodu normalize eder. Örn: 8690536804368.0 → '8690536804368'."""
    if val is None:
        return ""
    s = str(val).strip()
    # Float gönderilmiş olabilir: "123456.0" → "123456"
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ─── Token yönetimi ────────────────────────────────────────────────────────────

_token_cache: dict[str, Any] = {"token": None}


def _get_token() -> str:
    """
    JWT token döndürür. Cache'de varsa yeniden istemez.
    Returns:
        str: Bearer token.
    Raises:
        RuntimeError: Credential eksik veya API yanıt vermezse.
    """
    if _token_cache["token"]:
        return _token_cache["token"]

    if not ENTEGRA_EMAIL or not ENTEGRA_PASSWORD:
        raise RuntimeError(
            "Entegra credential'ları eksik. .env dosyasına "
            "ENTEGRA_EMAIL ve ENTEGRA_PASSWORD ekleyin."
        )

    payload = {"email": ENTEGRA_EMAIL, "password": ENTEGRA_PASSWORD}
    for attempt in range(1, ENTEGRA_MAX_RETRY + 1):
        try:
            resp = requests.post(ENTEGRA_TOKEN_URL, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access") or data.get("token") or data.get("access_token")
            if not token:
                raise ValueError(f"Token alanı bulunamadı. Yanıt: {data}")
            _token_cache["token"] = token
            log.info("Entegra token alındı.")
            return token
        except Exception as exc:
            log.warning("Token alma denemesi %d/%d başarısız: %s", attempt, ENTEGRA_MAX_RETRY, exc)
            if attempt < ENTEGRA_MAX_RETRY:
                time.sleep(2)

    raise RuntimeError("Entegra API token alınamadı. Loglara bakın.")


def _token_sifirla() -> None:
    """Token cache'ini temizler (401 alındığında çağrılır)."""
    _token_cache["token"] = None


# ─── Sayfa çekme ──────────────────────────────────────────────────────────────

def _sayfa_cek(page: int, token: str) -> list[dict]:
    """
    Belirtilen sayfayı çeker.
    API typo handle: 'productList' veya 'porductList' (Entegra bug).
    """
    url = ENTEGRA_PRODUCT_URL.format(page=page)
    headers = {"Authorization": f"JWT {token}"}

    for attempt in range(1, ENTEGRA_MAX_RETRY + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 401:
                log.warning("401 alındı, token yenileniyor... URL: %s | Yanıt: %s", url, resp.text[:200])
                _token_sifirla()
                token = _get_token()
                headers["Authorization"] = f"Bearer {token}"
                continue
            resp.raise_for_status()
            data = resp.json()
            # Entegra typo: porductList veya productList
            urunler = (
                data.get("productList")
                or data.get("porductList")
                or data.get("results")
                or []
            )
            return urunler
        except Exception as exc:
            log.warning("Sayfa %d, deneme %d/%d başarısız: %s", page, attempt, ENTEGRA_MAX_RETRY, exc)
            if attempt < ENTEGRA_MAX_RETRY:
                time.sleep(2)

    log.error("Sayfa %d çekilemedi, atlanıyor.", page)
    return []


# ─── Ana çekme fonksiyonu ─────────────────────────────────────────────────────

def _stok_gecmisine_ekle(df: pd.DataFrame) -> None:
    """
    Her çekimde barkod + mevcut_stok + tarih üçlüsünü birikimli olarak kaydeder.
    Dashboard'daki stok değişim grafiği bu dosyayı kullanır.
    """
    if "barkod" not in df.columns or "mevcut_stok" not in df.columns:
        return

    snapshot = df[["barkod", "mevcut_stok"]].copy()
    snapshot["tarih"] = pd.Timestamp.now().floor("min")

    if STOCK_HISTORY_PARQUET.exists():
        gecmis = pd.read_parquet(STOCK_HISTORY_PARQUET)
        gecmis = pd.concat([gecmis, snapshot], ignore_index=True)
    else:
        gecmis = snapshot

    gecmis.to_parquet(STOCK_HISTORY_PARQUET, index=False)
    log.info("Stok geçmişi güncellendi: %d toplam kayıt", len(gecmis))


def cek_entegra_urunleri() -> pd.DataFrame:
    """
    Entegra API'den tüm ürünleri çeker, parquet'e kaydeder.

    Returns:
        pd.DataFrame: Entegra ürün tablosu.
    """
    log.info("Entegra ürün çekme başlıyor...")
    token = _get_token()

    tum_urunler: list[dict] = []
    page = 1

    while True:
        log.info("Sayfa %d çekiliyor...", page)
        urunler = _sayfa_cek(page, token)
        if not urunler:
            log.info("Sayfa %d boş döndü. Çekim tamamlandı.", page)
            break
        tum_urunler.extend(urunler)
        log.info("Sayfa %d: %d ürün alındı (toplam: %d)", page, len(urunler), len(tum_urunler))
        page += 1
        time.sleep(ENTEGRA_RATE_LIMIT_SANIYE)

    if not tum_urunler:
        log.warning("Entegra'dan hiç ürün çekilemedi.")
        return pd.DataFrame()

    df = pd.DataFrame(tum_urunler)
    df = _temizle(df)

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ENTEGRA_PRODUCTS_PARQUET, index=False)
    log.info("Entegra ürünleri kaydedildi: %s (%d satır)", ENTEGRA_PRODUCTS_PARQUET, len(df))

    _stok_gecmisine_ekle(df)
    return df


def cek_entegra_urunleri_incremental() -> pd.DataFrame:
    """
    Son senkron tarihten itibaren sadece degisen urunleri ceker (product/list/v2).
    Ilk calismada veya cache yoksa otomatik olarak tam cekime (cek_entegra_urunleri)
    geri doner.
    """
    # Daha once cache var mi, son guncelleme ne zaman?
    if ENTEGRA_PRODUCTS_PARQUET.exists():
        try:
            cache_df = pd.read_parquet(ENTEGRA_PRODUCTS_PARQUET)
            if "entegra_son_guncelleme" in cache_df.columns and not cache_df.empty:
                last_sync = pd.to_datetime(cache_df["entegra_son_guncelleme"]).max()
            else:
                last_sync = None
        except Exception:
            last_sync = None
    else:
        last_sync = None

    # Ilk calisma veya tarih bulunamazsa tam cekim yap
    if last_sync is None:
        log.info("Entegra incremental icin once tam cekim yapiliyor (cache yok veya tarih bulunamadi).")
        return cek_entegra_urunleri()

    now = datetime.now()
    log.info("Entegra incremental cekim: %s - %s", last_sync, now)

    token = _get_token()
    url = "https://apiv2.entegrabilisim.com/product/list/v2/"
    headers = {
        "Authorization": f"JWT {token}",
        "Content-Type": "application/json",
    }

    tum_urunler: list[dict] = []
    page = 1

    while True:
        time_period = [
            {
                "start_date": last_sync.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date_change": 1,
            }
        ]

        payload = {
            "product": [
                {
                    "page": page,
                    "parameters": [
                        {
                            "date_change": 1,
                            "time_period": time_period,
                        }
                    ],
                    "additional_categories": True,
                    "compatible_fields": True,
                    "variants": [
                        {
                            "id": True,
                            "productCode": True,
                            "barcode": True,
                            "quantities": True,
                            "prices": True,
                        }
                    ],
                    "others": [
                        {
                            "id": True,
                            "productCode": True,
                            "barcode": True,
                            "name": True,
                            "brand": True,
                            "quantity": True,
                            "date_change": True,
                            "date_add": True,
                            "critical_stock": True,
                            "critical_stock_enable": True,
                        }
                    ],
                }
            ]
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Yanitta urun listesini bulmaya calis
            urunler = (
                data.get("productList")
                if isinstance(data, dict)
                else None
            )
            if urunler is None and isinstance(data, dict):
                urunler = (
                    data.get("porductList")
                    or data.get("results")
                    or data.get("data")
                    or data.get("products")
                )
            if urunler is None and isinstance(data, list):
                urunler = data

            if not urunler:
                log.info("Incremental sayfa %d bos dondu, durduruluyor.", page)
                break

            tum_urunler.extend(urunler)
            log.info("Incremental sayfa %d: %d urun alindi (toplam: %d)", page, len(urunler), len(tum_urunler))
            page += 1
            time.sleep(ENTEGRA_RATE_LIMIT_SANIYE)
        except Exception as exc:
            log.error("Incremental sayfa %d cekilemedi: %s", page, exc)
            break

    if not tum_urunler:
        log.warning("Entegra incremental: degisen urun bulunamadi, cache aynen kullaniliyor.")
        return yukle_entegra_urunleri()

    df_yeni = pd.DataFrame(tum_urunler)
    df_yeni = _temizle(df_yeni)

    # Mevcut cache ile birlestir (upsert)
    if ENTEGRA_PRODUCTS_PARQUET.exists():
        eski = pd.read_parquet(ENTEGRA_PRODUCTS_PARQUET)
        if "barkod" in eski.columns and "barkod" in df_yeni.columns:
            eski = eski[~eski["barkod"].isin(df_yeni["barkod"])]
            birlesik = pd.concat([eski, df_yeni], ignore_index=True)
        else:
            birlesik = df_yeni
    else:
        birlesik = df_yeni

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    birlesik.to_parquet(ENTEGRA_PRODUCTS_PARQUET, index=False)
    log.info(
        "Entegra incremental cache guncellendi: %s (tam=%d, degisen=%d)",
        ENTEGRA_PRODUCTS_PARQUET,
        len(birlesik),
        len(df_yeni),
    )

    _stok_gecmisine_ekle(df_yeni)
    return birlesik


def _temizle(df: pd.DataFrame) -> pd.DataFrame:
    """Ham API verisini normalize eder."""
    # Barkod normalizasyonu
    if "barcode" in df.columns:
        df["barcode"] = df["barcode"].apply(_kod)
    else:
        log.warning("'barcode' sütunu bulunamadı.")
        df["barcode"] = ""

    # Sayısal alanlar
    for col in ["quantity", "buying_price", "trendyol_listPrice", "hb_price", "critical_stock"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Metin alanlar
    for col in ["name", "group", "brand", "status"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Yeni kolon isimleri (Türkçe takma adlar)
    yeniden_adlandir = {
        "barcode": "barkod",
        "quantity": "mevcut_stok",
        "buying_price": "alis_fiyati",
        "group": "kategori",
        "brand": "marka",
        "name": "entegra_urun_adi",
        "status": "ilan_durumu",
        "critical_stock": "kritik_stok_miktari",
        "trendyol_listPrice": "trendyol_fiyat",
        "hb_price": "hb_fiyat",
    }
    df = df.rename(columns={k: v for k, v in yeniden_adlandir.items() if k in df.columns})

    # Zaman damgası
    df["entegra_son_guncelleme"] = pd.Timestamp.now().floor("s")

    log.info("Entegra verisi temizlendi: %d satır, kolonlar=%s", len(df), list(df.columns))
    return df


# ─── Mevcut cache'i yükle ─────────────────────────────────────────────────────

def yukle_entegra_urunleri() -> pd.DataFrame:
    """
    Kaydedilmiş parquet'ten Entegra verisini yükler.
    Dosya yoksa boş DataFrame döner.
    """
    if ENTEGRA_PRODUCTS_PARQUET.exists():
        df = pd.read_parquet(ENTEGRA_PRODUCTS_PARQUET)
        log.info("Entegra cache yüklendi: %d satır", len(df))
        return df
    log.warning("Entegra parquet bulunamadı. Önce cek_entegra_urunleri() çağırın.")
    return pd.DataFrame()


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = cek_entegra_urunleri()
    if not df.empty:
        print(df[["barkod", "entegra_urun_adi", "mevcut_stok", "alis_fiyati", "kategori", "marka"]].head(10))
        print(f"\nToplam: {len(df)} ürün")
