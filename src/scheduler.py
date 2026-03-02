"""
scheduler.py — Otomatik stok izleme zamanlayıcı.

REF-14 zamanlayıcı:
  Her çalışmada:
    1. Entegra API'den stok çek → entegra_products.parquet güncelle
    2. Zenginleştirme çalıştır → product_master güncelle
    3. Alarm hesapla → alarms.parquet güncelle
    4. Kritik alarmları bildir (Telegram + e-posta)
    5. Log yaz

Çalıştırma:
  python -m src.scheduler             → sürekli çalışır
  python -m src.scheduler --once      → tek seferlik çalışır (Task Scheduler için)
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import LOG_FORMAT, LOG_LEVEL, SCHEDULER_SAATLER

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)


def _calistir(ozet_mi: bool = False) -> None:
    """
    Tek bir döngü çalıştırır:
    Entegra çek → zenginleştir → alarm hesapla → bildir.

    Args:
        ozet_mi: True → sabah özet bildirimi (günlük özet modu).
    """
    baslangic = datetime.now()
    log.info("=== Scheduler döngüsü başlıyor: %s ===", baslangic.strftime("%d.%m.%Y %H:%M"))

    try:
        from src.entegra_api import cek_entegra_urunleri
        entegra_df = cek_entegra_urunleri()
        log.info("Entegra: %d ürün çekildi.", len(entegra_df))
    except Exception as exc:
        log.error("Entegra çekimi başarısız: %s", exc)
        entegra_df = None

    if entegra_df is not None and not entegra_df.empty:
        try:
            from src.enrichment import zenginlestir
            sonuc = zenginlestir(entegra_df)
            log.info(
                "Zenginleştirme tamamlandı. Eşleşen: %d, Satışsız stok: %d",
                sonuc.get("master", entegra_df).shape[0],
                len(sonuc.get("satissiz_stok", [])),
            )
        except Exception as exc:
            log.error("Zenginleştirme başarısız: %s", exc)
    else:
        log.warning("Entegra verisi yok. Zenginleştirme atlandı.")

    try:
        from src.alarm import hesapla_alarmlar
        alarmlar = hesapla_alarmlar()
        kritik_n = alarmlar["alarm_seviye"].isin(["kritik", "stok_bitmis"]).sum()
        uyari_n = (alarmlar["alarm_seviye"] == "uyarı").sum()
        log.info("Alarm: kritik=%d, uyarı=%d", kritik_n, uyari_n)
    except Exception as exc:
        log.error("Alarm hesaplama başarısız: %s", exc)
        alarmlar = None

    if alarmlar is not None and not alarmlar.empty:
        try:
            from src.notifier import bildir
            bildir(alarmlar, ozet_mi=ozet_mi)
        except Exception as exc:
            log.error("Bildirim başarısız: %s", exc)

    sure = (datetime.now() - baslangic).total_seconds()
    log.info("=== Döngü tamamlandı (%.1f sn) ===", sure)


def _calistir_once() -> None:
    """Tek seferlik çalıştırma (--once argümanı veya Task Scheduler için)."""
    _calistir(ozet_mi=False)


def _zamanlayici_baslat() -> None:
    """
    `schedule` kütüphanesiyle sürekli döngü.
    SCHEDULER_SAATLER config'den alınır (varsayılan: 08:00, 14:00, 20:00).
    Sabah ilk çalışma özet bildirimi yapar.
    """
    try:
        import schedule
    except ImportError:
        log.error("'schedule' paketi kurulu değil: pip install schedule")
        sys.exit(1)

    log.info("Zamanlayıcı başlatılıyor. Saatler: %s", SCHEDULER_SAATLER)

    ilk_saat = SCHEDULER_SAATLER[0] if SCHEDULER_SAATLER else "08:00"

    for i, saat in enumerate(SCHEDULER_SAATLER):
        ozet = saat == ilk_saat  # Sabah ilk çalışma → özet
        schedule.every().day.at(saat).do(_calistir, ozet_mi=ozet)
        log.info("Zamanlama eklendi: %s (ozet=%s)", saat, ozet)

    log.info("Zamanlayıcı aktif. Çıkmak için Ctrl+C.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        log.info("Zamanlayıcı durduruldu.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stok alarm zamanlayıcı")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Tek seferlik çalıştır ve çık (Windows Task Scheduler için)",
    )
    args = parser.parse_args()

    if args.once:
        _calistir_once()
    else:
        _zamanlayici_baslat()
