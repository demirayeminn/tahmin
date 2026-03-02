# tahmin

Stok Talep Tahmin & Alarm Sistemi

E-ticaret sipariş verisinden otomatik talep tahmini, satın alma önerisi, birlikte satış analizi, anomali tespiti ve **canlı stok alarm sistemi** yapan; Streamlit tabanlı interaktif dashboard ile görselleştirilen bir analiz sistemi.

Entegra API entegrasyonu sayesinde gerçek zamanlı stok seviyeleri, fiyatlar, kategori ve marka bilgileri çekilir; kritik stok uyarıları Telegram ve e-posta ile otomatik gönderilir.

---

## İçindekiler

- [Hızlı Başlangıç](#hızlı-başlangıç)
- [Gereksinimler](#gereksinimler)
- [Proje Yapısı](#proje-yapısı)
- [Veri Formatı](#veri-formatı)
- [Pipeline: Adım Adım Çalıştırma](#pipeline-adım-adım-çalıştırma)
- [Alarm & Bildirim Sistemi](#alarm--bildirim-sistemi)
- [Dashboard Kullanımı](#dashboard-kullanımı)
- [Çıktı Dosyaları](#çıktı-dosyaları)
- [Modüller](#modüller)
- [Varsayımlar & Kısıtlar](#varsayımlar--kısıtlar)
- [Sık Sorulan Sorular](#sık-sorulan-sorular)

---

## Hızlı Başlangıç

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. Credential şablonunu kopyala ve doldur
cp .env.example .env
# .env dosyasını düzenle: Entegra, Telegram, e-posta bilgilerini gir

# 3. Analiz pipeline'ını çalıştır (ilk kurulumda sırasıyla)
python -m src.data_loader
python -m src.segmentation
python -m src.forecasting
python -m src.reorder
python -m src.anomaly
python -m src.basket_analysis

# 4. Entegra API'den canlı stok çek + alarm oluştur
python -m src.scheduler --once

# 5. Dashboard'u aç
streamlit run dashboard/app.py
```

Tarayıcınızda `http://localhost:8501` adresi otomatik açılır.

---

## Gereksinimler

Python 3.10 veya üzeri gereklidir.

```bash
pip install -r requirements.txt
```

| Paket | Kullanım |
|-------|----------|
| pandas >= 2.0 | Veri işleme |
| numpy | Sayısal hesaplama |
| statsmodels >= 0.14 | ETS / Holt-Winters tahmini |
| mlxtend >= 0.24 | FP-Growth birlikte satış |
| streamlit >= 1.30 | Dashboard |
| plotly >= 5.0 | İnteraktif grafikler |
| openpyxl / xlsxwriter | Excel okuma/yazma |
| pyarrow | Parquet dosyaları |
| scipy | İstatistik |
| requests | Entegra API HTTP istekleri |
| python-dotenv | `.env` credential yönetimi |
| schedule | Otomatik zamanlama |
| python-telegram-bot >= 20.0 | Telegram bot bildirimleri |

---

## Proje Yapısı

```text
Ev-tahmin/
├── .env.example                 <- Credential şablonu (kopyala -> .env, git'e ekleme!)
├── .env                         <- Gerçek API şifreleri (git'e EKLEME)
├── veri/
│   └── siparisler.xlsx          <- Ham veri (SADECE OKUMA)
├── src/
│   ├── config.py                <- Tüm sabitler, parametreler, .env okuma
│   ├── data_loader.py           <- Veri okuma, temizleme, kanonik ad
│   ├── segmentation.py          <- ABC, talep tipi, SKU sağlık skoru
│   ├── feature_engine.py        <- Lag/rolling/takvim özellikleri
│   ├── forecasting.py           <- Tahmin modelleri + backtesting
│   ├── reorder.py               <- Satın alma önerisi
│   ├── anomaly.py               <- Anomali algılama
│   ├── basket_analysis.py       <- Birlikte satış analizi
│   ├── export.py                <- Excel çıktı yazıcı
│   ├── entegra_api.py           <- Entegra API client (token, pagination, barkod normalize)
│   ├── enrichment.py            <- Entegra verisiyle zenginleştirme (stok, fiyat, ABC v2)
│   ├── alarm.py                 <- Alarm motoru (kalan gün, eşik kontrolü, T8 tablosu)
│   ├── notifier.py              <- Telegram + e-posta bildirim gönderici
│   └── scheduler.py             <- Otomatik döngü (günde 3 kez)
├── dashboard/
│   ├── app.py
│   ├── _veri.py
│   └── pages/
│       ├── 01_yonetici_ozet.py
│       ├── 02_talep_analizi.py
│       ├── 03_birlikte_satis.py
│       ├── 04_stok_planlama.py
│       ├── 05_anomali.py
│       └── 06_alarm.py          <- Canlı Alarm Ekranı (YENİ)
├── data/
│   ├── processed/
│   └── outputs/
├── requirements.txt
└── README.md
```

---

## Veri Formatı

Ham veri dosyası: `veri/siparisler.xlsx`

| Sütun | Açıklama | Örnek |
|-------|----------|-------|
| Tarih | Sipariş tarihi (saat bileşeni olabilir) | 2025-09-01 14:32:00 |
| Sipariş Numarası | Sipariş ID (aynı ID = aynı sepet) | ORD-10045 |
| Ürün Fatura İsmi | Ürün adı (aynı barkod farklı isimle gelebilir) | Ürün A 500ml |
| Adet | Sipariş adedi (negatif = iade) | 3 |
| Barkod | Ürün kimliği — **tüm analizlerin temeli** | 8699956094113 |

> **Önemli:** Sistem barkod bazında çalışır; en sık görülen isim "kanonik ad" olarak kullanılır.

---

## Pipeline: Adım Adım Çalıştırma

Her adım bir öncekinin çıktısını kullanır.

### Adım 1 — Veri Temizleme

```bash
python -m src.data_loader
```

Tarih parse, barkod normalize, kanonik ad, günlük talep tablosu.  
**Çıktı:** `clean_orders.parquet`, `daily_demand.parquet`

### Adım 2 — Segmentasyon

```bash
python -m src.segmentation
```

ABC sınıfı (adet bazlı), talep tipi (Syntetos-Boylan), SKU Sağlık Skoru (0-100).  
**Çıktı:** `product_master.parquet`

### Adım 3 — Tahmin

```bash
python -m src.forecasting
```

Talep tipine göre model seçer (HoltWinters, Croston, TSB, Robust MA), backtesting (son 30 gün, WAPE), 14/30/60 günlük tahmin + güven bandı.  
**Çıktı:** `forecast_results.parquet`, `faz2_tahmin.xlsx`

### Adım 4 — Satın Alma Önerisi

```bash
python -m src.reorder
```

`hedef_stok = günlük_ort × hedef_gün + güvenlik_stoğu` (servis: A=%97, B=%95, C=%90).  
**Çıktı:** `reorder.parquet`, `faz3_satin_alma_anomali.xlsx`

### Adım 5 — Anomali Tespiti

```bash
python -m src.anomaly
```

Z-score (spike/düşüş), zero-sales run, EWM change point, kampanya proxy.  
**Çıktı:** `anomaly_events.parquet`, `anomaly_calendar.parquet`

### Adım 6 — Birlikte Satış

```bash
python -m src.basket_analysis
```

FP-Growth, support/confidence/lift, aksiyon önerisi.  
**Çıktı:** `basket_rules.parquet`, `faz4_birlikte_satis.xlsx`

---

## Alarm & Bildirim Sistemi

### 1. `.env` Dosyasını Doldur

```bash
cp .env.example .env
```

```env
ENTEGRA_EMAIL=kullanici@hotmail.com
ENTEGRA_PASSWORD=sifreniz

TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
TELEGRAM_CHAT_ID=123456789

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=kullanici@gmail.com
SMTP_PASSWORD=app_sifreniz
ALERT_EMAIL_TO=hedef@email.com
```

**Telegram:** @BotFather → `/newbot` → token → bota mesaj gönder → `getUpdates` ile chat_id.  
**Gmail:** Google Hesabı → Güvenlik → 2 Adımlı Doğrulama → Uygulama Şifreleri.

### 2. Tek Seferlik Çalıştırma

```bash
python -m src.scheduler --once
```

### 3. Otomatik Zamanlama

```bash
python -m src.scheduler   # 08:00 / 14:00 / 20:00 otomatik çalışır
```

### Alarm Eşikleri (ABC'ye göre)

| Sınıf | Kritik | Uyarı | İzle |
|-------|--------|-------|------|
| A | <= 10 gün | <= 18 gün | <= 25 gün |
| B | <= 7 gün  | <= 14 gün | <= 21 gün |
| C | <= 5 gün  | <= 10 gün | <= 15 gün |

- **Kritik / Stok Bitmiş** → Telegram anlık + e-posta
- **Uyarı** → Sabah günlük özet
- **İzle** → Yalnızca dashboard
- Flood koruması: Aynı barkod için 12 saat içinde tekrar bildirim yok

---

## Dashboard Kullanımı

```bash
streamlit run dashboard/app.py
```

Tüm sayfalarda sidebar'dan **ABC, kategori, marka** ve ürün arama filtreleri kullanılabilir.

| Sayfa | İçerik |
|-------|--------|
| 01 Yönetici Özet | KPI kartları, Top 20, ABC pasta, aylık trend, sağlık histogramı |
| 02 Talep Analizi | Ürün seçici, tahmin grafiği (14/30/60 gün), MA30, haftalık/aylık |
| 03 Birlikte Satış | Top 10 eşleşme, bundle önerisi, kural tablosu |
| 04 Stok Planlama | Hedef gün slider (30-90), risk bandı, anlık hesaplayıcı |
| 05 Anomali Takibi | Olay listesi, drill-down, stok-out listesi, ısı haritası |
| **06 Alarm** | Sayaçlar (kritik/uyarı/izle), renk kodlu tablo, kalan gün grafiği |

---

## Çıktı Dosyaları

| Dosya | İçerik |
|-------|--------|
| `data/outputs/faz1_master_ve_talep.xlsx` | T1 Ürün Master + T2 Günlük Talep |
| `data/outputs/faz2_tahmin.xlsx` | T3 Tahmin + Backtest Özeti + Model Dağılımı |
| `data/outputs/faz3_satin_alma_anomali.xlsx` | T4 Satın Alma + T6 Anomali + T7 Takvim |
| `data/outputs/faz4_birlikte_satis.xlsx` | T5 Birlikte Satış + Aksiyon Özeti |
| `data/outputs/faz6_alarm_raporu.xlsx` | T8 Alarm Listesi (kalan gün + önerilen sipariş) |
| `data/processed/entegra_products.parquet` | Entegra'dan çekilen canlı ürün verisi |
| `data/processed/alarms.parquet` | Güncel alarm tablosu (scheduler her çalışmada günceller) |

---

## Modüller

### `src/config.py` — Merkezi Parametre Dosyası

Tüm magic number'lar ve `.env` credential'ları buradan okunur.

```python
HEDEF_GUN = 50             # Satın alma önerisi hedef stok günü
LEAD_TIME_GUN = 7          # Tedarik süresi (gün) — VARSAYIM
REVIEW_PERIOD_GUN = 7      # Gözden geçirme periyodu
ABC_A_ESIK = 0.80          # Kümülatif %80 -> A sınıfı
BASKET_MIN_SUPPORT = 0.005 # FP-Growth minimum destek
SCHEDULER_SAATLER = ['08:00', '14:00', '20:00']
ALARM_ESIK = {
    'A': {'kritik': 10, 'uyari': 18, 'izle': 25},
    'B': {'kritik': 7,  'uyari': 14, 'izle': 21},
    'C': {'kritik': 5,  'uyari': 10, 'izle': 15},
}
```

---

## Varsayımlar & Kısıtlar

| Konu | Durum | Açıklama |
|------|-------|----------|
| Mevcut stok | Entegra'dan geliyor | Scheduler çalıştırılmadan: 0 varsayılır |
| Lead time | Bilinmiyor | 7 gün varsayıldı (`LEAD_TIME_GUN`) |
| Fiyat / ciro | Entegra'dan geliyor | `buying_price`; ABC v2 (ciro bazlı) hesaplanır |
| Kategori & marka | Entegra'dan geliyor | Dashboard filtresi olarak kullanılır |
| İade / negatif adet | Var | Bayraklandı, analizden hariç tutuldu |
| Kampanya takvimi | Yok | Proxy yöntemiyle tahmin edildi |

Tüm varsayımlar kod içinde `# VARSAYIM:` yorumuyla işaretlenmiştir.

---

## Sık Sorulan Sorular

**S: Yeni veri geldiğinde ne yapmalıyım?**  
`veri/siparisler.xlsx` dosyasını güncelleyin, pipeline adımlarını sırayla çalıştırın.

**S: Dashboard'da alarm sayfası boş?**  
`python -m src.scheduler --once` çalıştırın (`.env` doldurulmadan da stok=0 varsayımıyla alarm üretir).

**S: Telegram bildirimi gelmiyor?**  
`.env` dosyasındaki token ve chat_id'yi kontrol edin. Bota en az bir mesaj göndermiş olmanız gerekir.

**S: Satın alma önerisindeki hedef günü kalıcı değiştirmek istiyorum?**  
`src/config.py` → `HEDEF_GUN` değiştirin, ardından `python -m src.reorder` çalıştırın.

**S: Birlikte satış kuralı sayısı çok az / fazla?**  
`BASKET_MIN_SUPPORT` değerini ayarlayın (azaltmak: 0.002, artırmak: 0.01).

**S: Entegra API'ye bağlanamıyorum?**  
Sistem hata loglar ve mevcut `entegra_products.parquet` cache'ini kullanmaya devam eder. `python -m src.entegra_api` ile test edin.

