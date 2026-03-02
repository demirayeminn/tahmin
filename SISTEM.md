# Stok Takip Sistemi — Sistem Tanıtımı

## Ne Yapar?

E-ticaret siparişlerinizden öğrenerek her ürün için:
- Stok ne zaman biter?
- Ne kadar sipariş verilmeli?
- Hangi ürünler kritik durumda?

sorularını otomatik olarak yanıtlar. Entegra'dan gerçek zamanlı stok seviyesi çeker, geçmiş sipariş verisini analiz eder ve bir web arayüzünde gösterir.

---

## Veri Kaynakları

| Kaynak | Ne Verir? | Nasıl Kullanılır? |
|--------|-----------|-------------------|
| `veri/siparisler.xlsx` | Eyl 2025 – Şub 2026 arası 113.310 sipariş satırı | Ham veri, sadece okunur |
| Entegra API | Her ürünün anlık depodaki adedi | `baslat.bat` her çalıştırıldığında çekilir |

---

## Ürün Seti

- **344 SKU** (benzersiz barkod)
- **ABC Sınıfı:** A = 78 ürün (en çok satanlar), B = 83 ürün, C = 183 ürün
- Veri aralığı: 181 gün

---

## Nasıl Çalışır? (Tek BAT Dosyası)

```
baslat.bat'a çift tıkla
       ↓
1. Entegra API → anlık stok çek (344 ürün)
       ↓
2. Stok geçmişine kaydet (stock_history.parquet — birikimli)
       ↓
3. Alarm hesapla → kim kritik, kim stok yok?
       ↓
4. Streamlit dashboard başlat → http://localhost:8501
```

Aynı Wi-Fi'daki başka cihazdan erişmek için `ip_goster.bat` çalıştırın.

---

## Dosya Yapısı

```
Ev-tahmin/
│
├── baslat.bat              ← Her şeyi başlatan tek dosya
├── ip_goster.bat           ← Ağ IP adresini gösterir
├── .env                    ← Entegra şifresi (gizli, Git'e gitmesin)
│
├── src/                    ← Hesaplama motoru
│   ├── config.py           ← Tüm ayarlar (eşikler, sabitler)
│   ├── data_loader.py      ← Ham Excel'i temizler
│   ├── segmentation.py     ← ABC sınıflandırması
│   ├── feature_engine.py   ← Günlük talep istatistikleri
│   ├── forecasting.py      ← Satış tahmini modelleri
│   ├── reorder.py          ← Alım önerisi hesabı
│   ├── anomaly.py          ← Anormal satış tespiti
│   ├── basket_analysis.py  ← Birlikte satış analizi
│   ├── entegra_api.py      ← Entegra'dan stok çekme
│   ├── enrichment.py       ← Entegra verisiyle ürün zenginleştirme
│   ├── alarm.py            ← Alarm motoru (kim kritik?)
│   ├── notifier.py         ← Telegram / e-posta bildirim
│   └── scheduler.py        ← Otomatik çalıştırıcı
│
├── dashboard/
│   ├── app.py              ← Streamlit giriş noktası
│   ├── _veri.py            ← Veri yükleyiciler (cache'li)
│   └── pages/
│       ├── 01_yonetici_ozet.py   ← Ana ekran: Stok Takip
│       └── 06_alarm.py           ← Alarm Listesi
│
├── data/
│   ├── processed/          ← Ara veriler (parquet)
│   └── outputs/            ← Excel raporları
│
└── veri/
    └── siparisler.xlsx     ← Ham veri (sadece okunur)
```

---

## Dashboard Ekranları

### Stok Takip (Ana Ekran)

Açılışta şu tablo görünür:

| Barkod | Ürün Adı | Mevcut Stok | Kalan Gün | Durum | 1 Ay Alım | 2 Ay Alım | 3 Ay Alım | 50 Gün Tahmin |
|--------|----------|-------------|-----------|-------|-----------|-----------|-----------|---------------|

**Satır renkleri:**
- Kırmızı → Stok Yok (hemen sipariş ver)
- Turuncu → Kritik (7 gün veya daha az kaldı)
- Sarı → Uyarı (8–30 gün kaldı)
- Beyaz → Yeterli
- Gri → Pasif (son 30 günde satış olmamış)

**Filtreler:** ABC sınıfı, stok durumu, ürün adı/barkod arama.

**Alım önerisi nasıl hesaplanır?**

```
1 Ay Alım = max(0,  günlük_ort × 30  + güvenlik_stoğu − mevcut_stok)
2 Ay Alım = max(0,  günlük_ort × 60  + güvenlik_stoğu − mevcut_stok)
3 Ay Alım = max(0,  günlük_ort × 90  + güvenlik_stoğu − mevcut_stok)
50 Gün Tahmin = günlük_ort × 50
```

Güvenlik stoğu ABC sınıfına göre değişir:
- A sınıfı: z = 1.88 (%97 servis düzeyi)
- B sınıfı: z = 1.65 (%95)
- C sınıfı: z = 1.28 (%90)

**Stok Değişim Grafiği (ekranın altında):**
Bir ürün seçince iki grafik yan yana açılır:
1. Stok seviyesi zaman içinde nasıl değişmiş (Entegra geçmişi)
2. Aynı dönemde günlük satış adetleri (sipariş verisi)

> Bu grafik `baslat.bat` ilk çalıştırıldıktan sonra dolmaya başlar. Her çalıştırma bir veri noktası ekler.

---

### Alarm Listesi

Kritik durumları listeler:

| Durum | Kalan Gün | ABC | Mevcut Stok | Günlük Talep | Önerilen Sipariş |
|-------|-----------|-----|-------------|--------------|------------------|

**Alarm seviyeleri (ABC'ye göre ayarlı eşikler):**

| Seviye | A sınıfı | B sınıfı | C sınıfı |
|--------|----------|----------|----------|
| Stok Bitmis | stok = 0 | stok = 0 | stok = 0 |
| Kritik | ≤ 10 gün | ≤ 7 gün | ≤ 5 gün |
| Uyarı | ≤ 18 gün | ≤ 14 gün | ≤ 10 gün |
| İzle | ≤ 25 gün | ≤ 21 gün | ≤ 15 gün |
| Normal | üstü | üstü | üstü |

Kalan gün grafiği (çubuk grafik) sayfanın altındadır.

---

## İşlenen Veriler (`data/processed/`)

| Dosya | Satır | Açıklama |
|-------|-------|----------|
| `clean_orders.parquet` | 113.310 | Temizlenmiş sipariş verisi |
| `product_master.parquet` | 344 | Her SKU için özet (ABC, talep tipi, stok) |
| `daily_demand.parquet` | 62.264 | Günlük satış adetleri (barkod × gün) |
| `forecast_results.parquet` | 35.776 | 14/30/60 günlük tahminler |
| `reorder.parquet` | 344 | Alım önerisi ve güvenlik stoğu |
| `alarms.parquet` | 344 | Güncel alarm durumu |
| `entegra_products.parquet` | 9.266 | Entegra'dan en son çekilen ürün verisi |
| `stock_history.parquet` | birikimli | Her Entegra çekiminde bir satır eklenir |
| `anomaly_events.parquet` | 7.353 | Tespit edilen anormal satış olayları |
| `basket_rules.parquet` | 26 | Birlikte satılan ürün çiftleri |

---

## Ayarlar (`.env`)

```
ENTEGRA_EMAIL=...
ENTEGRA_PASSWORD=...

# İsteğe bağlı — Telegram bildirimi için
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## Gereksinimler

```
python -m pip install -r requirements.txt
```

Python 3.11+ gereklidir. Kullanılan başlıca paketler: streamlit, pandas, plotly, scikit-learn, statsmodels, mlxtend, requests, python-dotenv.

---

## Günlük Kullanım

1. `baslat.bat` çift tıkla
2. Tarayıcıda `http://localhost:8501` aç
3. Başka cihazdan erişmek için `ip_goster.bat` çalıştır, o IP'yi kullan

Scheduler günde 3 kez otomatik çalışmak için de ayarlanabilir (`src/config.py` → `SCHEDULER_SAATLER`).
