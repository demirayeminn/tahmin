"""
notifier.py — Telegram bot + e-posta bildirim gönderici.

REF-14:
  - Telegram: python-telegram-bot (async, asyncio.run ile çağrılır)
  - E-posta: smtplib + email.mime (stdlib), HTML tablo formatı
  - Flood koruması: aynı barkod için 12 saat içinde tekrar bildirim gönderilmez
  - 🔴 Kritik / stok_bitmis → anında tek tek bildirim
  - 🟠 Uyarı → günlük özet (sabah 09:00 scheduler tarafından tetiklenir)
"""

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    ALERT_EMAIL_TO,
    LOG_FORMAT,
    LOG_LEVEL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FLOOD_KORUMA_SAAT,
)

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger(__name__)

# Flood koruması: {barkod: son_bildirim_timestamp}
_son_bildirim: dict[str, datetime] = {}


def _flood_kontrolu(barkod: str) -> bool:
    """True → bildirim gönderilmeli. False → flood koruması aktif."""
    son = _son_bildirim.get(barkod)
    if son and datetime.now() - son < timedelta(hours=TELEGRAM_FLOOD_KORUMA_SAAT):
        return False
    _son_bildirim[barkod] = datetime.now()
    return True


# ─── Telegram ─────────────────────────────────────────────────────────────────

def _telegram_mesaj_olustur(row: pd.Series) -> str:
    """REF-14 mesaj formatı."""
    seviye = row.get("alarm_seviye", "")
    emoji = row.get("alarm_emoji", "🔴")
    baslik = "STOK BİTMİŞ" if seviye == "stok_bitmis" else "KRİTİK STOK ALARMI"
    kalan = row.get("kalan_gun")
    kalan_str = f"~{kalan} gün" if kalan is not None else "—"
    return (
        f"{emoji} {baslik}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 Ürün: {row.get('kanonik_ad', '')}\n"
        f"🏷️ Barkod: {row.get('barkod', '')}\n"
        f"📊 Mevcut: {row.get('mevcut_stok', 0)} adet\n"
        f"⏳ Kalan: {kalan_str}\n"
        f"🛒 Önerilen sipariş: {row.get('onerilen_siparis', 0)} adet\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )


async def _telegram_gonder_async(mesajlar: list[str]) -> None:
    """Asenkron Telegram gönderici."""
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        for mesaj in mesajlar:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mesaj)
            log.info("Telegram mesajı gönderildi.")
    except ImportError:
        log.error("python-telegram-bot kurulu değil: pip install python-telegram-bot>=20.0")
    except Exception as exc:
        log.error("Telegram gönderim hatası: %s", exc)


def telegram_gonder(alarms: pd.DataFrame) -> int:
    """
    Kritik + stok_bitmis alarmları için Telegram bildirimi gönderir.
    Flood koruması uygulanır.

    Returns:
        int: Gönderilen mesaj sayısı.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credential'ları eksik. .env dosyasını kontrol edin.")
        return 0

    kritik = alarms[alarms["alarm_seviye"].isin(["kritik", "stok_bitmis"])]
    mesajlar = []
    for _, row in kritik.iterrows():
        if _flood_kontrolu(row["barkod"]):
            mesajlar.append(_telegram_mesaj_olustur(row))

    if not mesajlar:
        log.info("Telegram: gönderilecek yeni kritik alarm yok (flood koruma veya alarm yok).")
        return 0

    asyncio.run(_telegram_gonder_async(mesajlar))
    return len(mesajlar)


def telegram_ozet_gonder(alarms: pd.DataFrame) -> None:
    """
    Günlük özet: kritik + uyarı sayısı, en kötü 5 ürün.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    kritik_sayi = alarms["alarm_seviye"].isin(["kritik", "stok_bitmis"]).sum()
    uyari_sayi = (alarms["alarm_seviye"] == "uyarı").sum()

    if kritik_sayi + uyari_sayi == 0:
        mesaj = "✅ Günlük Stok Özeti\nTüm ürünler yeterli stok seviyesinde."
    else:
        en_kotu = (
            alarms[alarms["alarm_seviye"].isin(["kritik", "stok_bitmis", "uyarı"])]
            .sort_values("kalan_gun")
            .head(5)
        )
        satirlar = "\n".join(
            f"  {r['alarm_emoji']} {r.get('kanonik_ad', r['barkod'])[:30]}: "
            f"{r.get('kalan_gun', '?')} gün"
            for _, r in en_kotu.iterrows()
        )
        mesaj = (
            f"📋 Günlük Stok Özeti — {datetime.now().strftime('%d.%m.%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔴 Kritik/Bitmiş: {kritik_sayi}\n"
            f"🟠 Uyarı: {uyari_sayi}\n\n"
            f"En kritik ürünler:\n{satirlar}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {datetime.now().strftime('%H:%M')}"
        )

    asyncio.run(_telegram_gonder_async([mesaj]))


# ─── E-posta ──────────────────────────────────────────────────────────────────

def _html_tablo(df: pd.DataFrame) -> str:
    """DataFrame'i HTML tablosuna çevirir."""
    style = (
        "border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px;"
    )
    th_style = "border:1px solid #ddd;padding:8px;background:#4472C4;color:white;text-align:left;"
    td_style = "border:1px solid #ddd;padding:6px;"
    tr_alt = "background:#f2f2f2;"

    html = f'<table style="{style}"><thead><tr>'
    for col in df.columns:
        html += f'<th style="{th_style}">{col}</th>'
    html += "</tr></thead><tbody>"
    for i, (_, row) in enumerate(df.iterrows()):
        row_style = tr_alt if i % 2 else ""
        html += f'<tr style="{row_style}">'
        for val in row:
            html += f'<td style="{td_style}">{val}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    return html


def eposta_gonder(alarms: pd.DataFrame, konu_ek: str = "") -> bool:
    """
    Günlük alarm raporunu HTML e-posta olarak gönderir.

    Args:
        alarms: T8 alarm tablosu.
        konu_ek: Konu satırına ek metin.

    Returns:
        bool: Gönderim başarılı mı.
    """
    if not all([SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO]):
        log.warning("E-posta credential'ları eksik. .env dosyasını kontrol edin.")
        return False

    kritik = alarms[alarms["alarm_seviye"].isin(["kritik", "stok_bitmis"])]
    uyari = alarms[alarms["alarm_seviye"] == "uyarı"]

    konu = f"📦 Stok Alarm Raporu — {datetime.now().strftime('%d.%m.%Y')} {konu_ek}"
    goruntule_cols = [
        c for c in ["kanonik_ad", "barkod", "abc_sinifi", "mevcut_stok",
                     "kalan_gun", "alarm_seviye", "onerilen_siparis"]
        if c in alarms.columns
    ]

    html_icerik = f"""
    <html><body>
    <h2>📦 Stok Alarm Raporu — {datetime.now().strftime('%d.%m.%Y %H:%M')}</h2>
    <p>🔴 Kritik/Bitmiş: <strong>{len(kritik)}</strong> &nbsp;|&nbsp;
       🟠 Uyarı: <strong>{len(uyari)}</strong></p>
    """

    if not kritik.empty:
        html_icerik += "<h3>🔴 Kritik Alarmlar</h3>"
        html_icerik += _html_tablo(kritik[goruntule_cols])

    if not uyari.empty:
        html_icerik += "<h3>🟠 Uyarılar</h3>"
        html_icerik += _html_tablo(uyari[goruntule_cols])

    html_icerik += "</body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = konu
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO
    msg.attach(MIMEText(html_icerik, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())
        log.info("E-posta gönderildi: %s → %s", SMTP_USER, ALERT_EMAIL_TO)
        return True
    except Exception as exc:
        log.error("E-posta gönderim hatası: %s", exc)
        return False


# ─── Ortak bildirim gönderici ─────────────────────────────────────────────────

def bildir(
    alarms: pd.DataFrame,
    ozet_mi: bool = False,
    yalnizca_son_guncellenen: bool = False,
) -> None:
    """
    Hem Telegram hem e-posta bildirimlerini gönderir.
    scheduler.py tarafından çağrılır.

    Args:
        alarms: T8 alarm tablosu.
        ozet_mi: True → özet mod (günlük sabah özeti).
    """
    df = alarms.copy()

    # Son güncellenenler filtresi (stok güncellemesi olan ürünler)
    if yalnizca_son_guncellenen and "son_guncelleme" in df.columns:
        try:
            ts = pd.to_datetime(df["son_guncelleme"], errors="coerce")
            if ts.notna().any():
                bugun = pd.Timestamp.now().normalize()
                df = df[ts.dt.normalize() == bugun]
                log.info(
                    "Bildirim: son güncellenenler filtresi aktif. Toplam=%d, bugun=%d",
                    len(alarms),
                    len(df),
                )
        except Exception as exc:
            log.warning("Son güncellenenler filtresi uygulanamadı: %s", exc)

    if df.empty:
        log.info("Bildirim: filtrelenmiş alarm tablosu boş, gönderim yok.")
        return

    if ozet_mi:
        # Günlük özet: tüm tabloyu kullan (yalnızca son güncellenenler değil)
        telegram_ozet_gonder(df)
        eposta_gonder(df, konu_ek="(Günlük Özet)")
    else:
        # Anlık kritik alarmlar: filtrelenmiş tablo üzerinden gönder
        n = telegram_gonder(df)
        if n > 0:
            eposta_gonder(df, konu_ek="(Anlık Kritik)")


if __name__ == "__main__":
    from src.alarm import hesapla_alarmlar
    alarmlar = hesapla_alarmlar()
    bildir(alarmlar)
