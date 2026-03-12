# PROGRESS.md — Claude Code Pusulası

> **Her oturumda sadece bu dosyayı oku + AGENTS.md'nin üst kısmını (═══ çizgisine kadar).**
> Sonra aşağıdaki aktif faz ne diyorsa onu yap.

---

## AKTİF FAZ: Faz 7 — İleri Analizler (opsiyonel)

Okunacak: REF-11
Kapsam: ürün yaşam döngüsü, churned SKU, yeni ürün rampa, tatil etkisi, gün-özel pattern
Durum: uygulandı (kod tarafı tamamlandı, veri üretimi komut ile çalıştırılacak)

---

## TAMAMLANAN FAZLAR

### Faz 1 — Veri Hazırlık & Master Tablo ✅
Üretilen dosyalar:
- `src/config.py`, `src/__init__.py`, `src/data_loader.py`, `src/segmentation.py`, `src/export.py`
- `data/processed/clean_orders.parquet` (113.310 satır, 344 barkod)
- `data/processed/product_master.parquet` (344 SKU)
- `data/processed/daily_demand.parquet` (62.264 satır)
- `data/outputs/faz1_master_ve_talep.xlsx`
Tespitler: Tarih saat bileşeni düzeltildi. ABC: A=78, B=83, C=183. Talep tipi: toplu=161, yeni=125, düzensiz=57, düzgün=1. Ort SKU sağlık: 69.8

### Faz 2 — Tahmin & Değerlendirme ✅
Üretilen dosyalar:
- `src/forecasting.py`, `src/feature_engine.py`
- `data/processed/forecast_results.parquet`
- `data/outputs/faz2_tahmin.xlsx`

### Faz 3 — Satın Alma & Anomali ✅
Üretilen dosyalar:
- `src/reorder.py`, `src/anomaly.py`, `src/_faz3_excel.py`
- `data/processed/reorder.parquet` (344 SKU)
- `data/processed/anomaly_events.parquet` (7.353 olay)
- `data/processed/anomaly_calendar.parquet` (839 satır)
- `data/outputs/faz3_satin_alma_anomali.xlsx`
Tespitler: mevcut_stok=0 varsayım → 285 aktif SKU kırmızı risk. Anomali: kampanya_benzeri=3120, spike=1896, trend_düşüş=1099, trend_artış=803, olası_stok_out=435

### Faz 4 — Birlikte Satış ✅
Üretilen dosyalar:
- `src/basket_analysis.py`
- `data/processed/basket_rules.parquet`
- `data/outputs/faz4_birlikte_satis.xlsx`

### Faz 5 — Dashboard ✅
Üretilen dosyalar:
- `dashboard/app.py`, `dashboard/_veri.py`
- `dashboard/pages/01_yonetici_ozet.py` → `05_anomali.py`

### Faz 6 — Entegra Entegrasyonu, Zenginleştirme & Alarm Sistemi ✅
Üretilen dosyalar:
- `.env.example` (credential şablonu)
- `src/entegra_api.py` (JWT token, pagination, barkod normalize, retry)
- `src/enrichment.py` (master + reorder zenginleştirme, ABC v2 ciro bazlı)
- `src/alarm.py` (kalan gün hesabı, ABC'ye göre ayarlı eşikler, T8 tablosu)
- `src/notifier.py` (Telegram + e-posta, flood koruması)
- `src/scheduler.py` (schedule kütüphanesi, 08:00/14:00/20:00, --once modu)
- `dashboard/pages/06_alarm.py` (canlı alarm ekranı, sayaçlar, renk kodlu tablo)
- `config.py` güncellendi (alarm eşikleri, zamanlama, credential okuma, dotenv)
- `dashboard/_veri.py` güncellendi (alarms() + 4-değerli sidebar_filtreler)
- `dashboard/pages/01-05` güncellendi (kategori/marka filtresi eklendi)
- `requirements.txt` güncellendi + python-telegram-bot>=20.0, schedule, python-dotenv, requests kuruldu

Tespitler:
- Entegra API iki typo ('productList'/'porductList') handle ediliyor
- Alarm eşikleri: A=(10/18/25), B=(7/14/21), C=(5/10/15) gün
- Notifier flood koruması: 12 saat aynı barkod için tekrar bildirim yok
- Credential'lar için kullanıcı .env dosyasını doldurmalı (bkz. .env.example)

---

## BEKLEYEN (opsiyonel, ileride)

### Faz 7 — İleri Analizler (opsiyonel)
Okunacak: REF-11
Kapsam: ürün yaşam döngüsü, churned SKU, yeni ürün rampa, tatil etkisi, gün-özel pattern

### Faz 7 — İleri Analizler ✅
Üretilen dosyalar:
- `src/advanced_analytics.py`
- `dashboard/pages/07_ileri_analiz.py`
- `dashboard/_veri.py` güncellendi (lifecycle/weekday/holiday loader)
- `src/config.py` güncellendi (Faz 7 sabitleri + parquet yolları)

Beklenen çıktılar (çalıştırınca):
- `data/processed/lifecycle_analysis.parquet`
- `data/processed/weekday_pattern.parquet`
- `data/processed/holiday_impact.parquet`
