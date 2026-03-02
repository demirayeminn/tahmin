"""
config.py — Proje genelinde kullanılan sabitler, varsayımlar ve parametreler.

KURAL: Kod içinde magic number kullanılmaz; tüm sabitler buradan alınır.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # .env dosyasını yükle (yoksa sessizce devam eder)

# ─── Dizinler ───────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
VERI_DIR = ROOT_DIR / "veri"
DATA_PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DATA_OUTPUTS_DIR = ROOT_DIR / "data" / "outputs"
SRC_DIR = ROOT_DIR / "src"

# Ham veri dosyası (SADECE OKU)
SIPARIS_DOSYASI = VERI_DIR / "siparisler.xlsx"

# Ara/çıktı dosyaları
CLEAN_ORDERS_PARQUET = DATA_PROCESSED_DIR / "clean_orders.parquet"
PRODUCT_MASTER_PARQUET = DATA_PROCESSED_DIR / "product_master.parquet"
DAILY_DEMAND_PARQUET = DATA_PROCESSED_DIR / "daily_demand.parquet"
FAZ1_EXCEL = DATA_OUTPUTS_DIR / "faz1_master_ve_talep.xlsx"

# ─── Veri sütun adları ───────────────────────────────────────────────────────
# Ham Excel sütunları → standart isimler eşlemesi (küçük-büyük harf bağımsız)
KOLON_MAP: dict[str, str] = {
    "tarih": "tarih",
    "sipariş numarası": "siparis_no",
    "siparis numarasi": "siparis_no",
    "sipariş no": "siparis_no",
    "siparis no": "siparis_no",
    "ürün fatura i̇smi": "urun_fatura_ismi",
    "ürün fatura ismi": "urun_fatura_ismi",
    "urun fatura ismi": "urun_fatura_ismi",
    "adet": "adet",
    "barkod": "barkod",
}

# ─── ABC segmentasyon eşikleri ───────────────────────────────────────────────
ABC_A_ESIK: float = 0.80   # Kümülatif %80 → A sınıfı
ABC_B_ESIK: float = 0.95   # Kümülatif %95 → B sınıfı (üstü C)

# ─── Talep tipi eşikleri (Syntetos-Boylan) ───────────────────────────────────
ADI_ESIK: float = 1.32     # Average Demand Interval eşiği
CV_ESIK: float = 0.50      # Coefficient of Variation eşiği
MIN_SATIS_GUN: int = 30    # Bu günden az satışı olan SKU → "yeni/az veri"

# ─── SKU Sağlık Skoru ağırlıkları ────────────────────────────────────────────
SAGLIK_AGIRLIK: dict[str, float] = {
    "satis_trendi": 0.30,       # Son 30 / önceki 30 gün adet oranı (normalize)
    "alias_sayisi": 0.10,       # Az alias → iyi veri kalitesi
    "duzensizlik": 0.25,        # Düşük CV → düzenli talep
    "son30_aktiflik": 0.25,     # Son 30 günde satış var mı
    "negatif_adet": 0.10,       # Az negatif/sıfır kayıt → temiz veri
}

# ─── Satın alma & servis seviyeleri (Faz 3 için hazır) ───────────────────────
# VARSAYIM: Mevcut stok bilinmiyor → 0 kabul edilir
MEVCUT_STOK_VARSAYIM: int = 0

# VARSAYIM: Lead time bilinmiyor → 7 gün kabul edilir
LEAD_TIME_GUN: int = 7

REVIEW_PERIOD_GUN: int = 7
HEDEF_GUN: int = 50

SERVIS_SEVIYE: dict[str, float] = {
    "A": 1.88,   # %97 servis düzeyi z-skoru
    "B": 1.65,   # %95
    "C": 1.28,   # %90
}

# ─── Tahmin ufukları (Faz 2 için hazır) ──────────────────────────────────────
TAHMIN_HORIZONLAR: list[int] = [14, 30, 60]   # gün

# ─── Birlikte satış parametreleri (Faz 4 için hazır) ─────────────────────────
BASKET_MIN_SUPPORT: float = 0.005
BASKET_MIN_CONFIDENCE: float = 0.10
BASKET_MIN_LIFT: float = 1.0

# ─── Dashboard renk paleti ────────────────────────────────────────────────────
RENK_PALETI: dict[str, str] = {
    "A": "#E74C3C",    # kırmızı
    "B": "#F39C12",    # turuncu
    "C": "#2ECC71",    # yeşil
    "vurgu": "#3498DB",
    "arka_plan": "#F8F9FA",
}

# ─── Ara/çıktı dosyaları (Faz 6) ─────────────────────────────────────────────
ENTEGRA_PRODUCTS_PARQUET = DATA_PROCESSED_DIR / "entegra_products.parquet"
ALARMS_PARQUET = DATA_PROCESSED_DIR / "alarms.parquet"
FAZ6_EXCEL = DATA_OUTPUTS_DIR / "faz6_alarm_raporu.xlsx"
STOCK_HISTORY_PARQUET = DATA_PROCESSED_DIR / "stock_history.parquet"

# ─── Entegra API ──────────────────────────────────────────────────────────────
ENTEGRA_BASE_URL: str = "https://apiv2.entegrabilisim.com"
ENTEGRA_TOKEN_URL: str = f"{ENTEGRA_BASE_URL}/api/user/token/obtain/"
ENTEGRA_PRODUCT_URL: str = f"{ENTEGRA_BASE_URL}/product/page={{page}}/"
ENTEGRA_EMAIL: str = os.getenv("ENTEGRA_EMAIL", "")
ENTEGRA_PASSWORD: str = os.getenv("ENTEGRA_PASSWORD", "")
ENTEGRA_RATE_LIMIT_SANIYE: float = 0.5   # sayfa başı bekleme
ENTEGRA_MAX_RETRY: int = 3

# ─── Alarm eşikleri (REF-10, REF-14) ─────────────────────────────────────────
# A sınıfı için genişletilmiş eşikler
ALARM_ESIK: dict[str, dict[str, int]] = {
    "A": {"kritik": 10, "uyari": 18, "izle": 25},
    "B": {"kritik": 7,  "uyari": 14, "izle": 21},
    "C": {"kritik": 5,  "uyari": 10, "izle": 15},
}

# ─── Zamanlayıcı (scheduler) ──────────────────────────────────────────────────
SCHEDULER_SAATLER: list[str] = ["08:00", "14:00", "20:00"]

# ─── Telegram bildirim ────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_FLOOD_KORUMA_SAAT: int = 12   # aynı ürün için tekrar bildirim aralığı

# ─── E-posta bildirim ─────────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")

# ─── Loglama ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
