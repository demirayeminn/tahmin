# AGENTS.md — Stok Talep Tahmin Sistemi

> **ÖNEMLİ**: Bu dosyanın TAMAMINI okuma. Sadece PROGRESS.md'nin seni yönlendirdiği bölümleri oku.
> Üst kısım (═══ çizgisine kadar) her oturumda okunmalı. Geri kalan referanstır.

---

## KRİTİK KURALLAR (her oturumda oku)

**Proje**: E-ticaret stok talep tahmin + satın alma öneri + canlı izleme + alarm sistemi
**Veri kaynakları**:
- Sipariş geçmişi: `veri/siparisler.xlsx` — 114K satır, 5 kolon (Tarih, Sipariş Numarası, Ürün Fatura İsmi, Adet, Barkod)
- Canlı stok/ürün: Entegra API (`apiv2.entegrabilisim.com`) — stok, fiyat, kategori, marka
**Proje dizini**: `C:\Users\Emin\Desktop\Ev-tahmin`

**Ürün = Barkod.** Aynı barkod farklı isimle geçebilir. Kanonik ad = mode(isim). Tüm analizler barkod bazlı.
**Entegra eşleştirme**: Entegra API `barcode` alanı = sipariş verisindeki `barkod`. Join key bu.

**Eksik veri durumu (güncellendi)**:
- ~~Fiyat/ciro YOK~~ → Entegra'dan `buying_price` + marketplace fiyatları GELİYOR
- ~~Mevcut stok YOK~~ → Entegra'dan `quantity` GELİYOR
- ~~Kategori YOK~~ → Entegra'dan `group` + `brand` GELİYOR
- Lead time hâlâ YOK (7 gün varsay)
- Her varsayım kodda `# VARSAYIM:` ile işaretlenmeli

**Kod kuralları**:
- Magic number yasak → `src/config.py`'den al
- `veri/siparisler.xlsx` → SADECE OKU, değiştirme
- Intermediate → `data/processed/` (parquet)
- Excel çıktılar → `data/outputs/`
- Vectorized pandas, `iterrows()` yasak
- Type hint + docstring + logging
- Tüm çıktılar/etiketler Türkçe
- **API credential'ları kodda YAZMA** → `src/config.py` içinde environment variable'dan oku veya `.env` dosyasından

**Her oturum başında**: PROGRESS.md oku → orada hangi faz aktifse ona bak → orada hangi AGENTS.md bölümü yazıyorsa sadece onu oku.
**Her adım sonunda**: PROGRESS.md güncelle.

═══════════════════════════════════════════════════════════════════════════════
AŞAGISI REFERANS BÖLÜMLERİDİR — SADECE PROGRESS.MD YÖNLENDİRDİĞİNDE OKU
═══════════════════════════════════════════════════════════════════════════════

---

## REF-01: KLASÖR YAPISI

```
C:\Users\Emin\Desktop\Ev-tahmin\
├── AGENTS.md
├── PROGRESS.md
├── .env                         # API credential'ları (git'e EKLEME)
├── veri/
│   └── siparisler.xlsx          # Ham veri (read-only)
├── src/
│   ├── __init__.py
│   ├── config.py                # Sabitler, varsayımlar, parametreler, env okuma
│   ├── data_loader.py           # Excel okuma, temizlik, canonical name
│   ├── segmentation.py          # ABC, talep tipi, SKU sağlık
│   ├── feature_engine.py        # Lag/rolling/takvim
│   ├── forecasting.py           # Tahmin modelleri
│   ├── basket_analysis.py       # Birlikte satış
│   ├── reorder.py               # Satın alma önerisi
│   ├── anomaly.py               # Anomali algılama
│   ├── export.py                # Excel çıktı yazma
│   ├── entegra_api.py           # Entegra API client (token, ürün çekme)
│   ├── enrichment.py            # Entegra verisiyle mevcut tabloları zenginleştir
│   ├── alarm.py                 # Alarm motoru (eşik hesapla, tetikle)
│   ├── notifier.py              # Telegram + e-posta bildirim gönderici
│   ├── scheduler.py             # Günde 2-3 kez otomatik çalıştırma
│   └── utils.py
├── dashboard/
│   ├── app.py
│   ├── _veri.py
│   └── pages/
│       ├── 01_yonetici_ozet.py
│       ├── 02_talep_analizi.py
│       ├── 03_birlikte_satis.py
│       ├── 04_stok_planlama.py
│       ├── 05_anomali.py
│       └── 06_alarm.py          # YENİ: Canlı alarm sekmesi
├── data/
│   ├── processed/
│   └── outputs/
├── tests/
├── .env.example                 # Credential şablonu
├── requirements.txt
└── README.md
```

---

## REF-02: VERİ TEMİZLEME & CANONICAL NAME

Adımlar (data_loader.py):
1. Excel oku → DataFrame
2. Sütun adlarını standartlaştır: `tarih`, `siparis_no`, `urun_fatura_ismi`, `adet`, `barkod`
3. `pd.to_datetime()` ile tarih parse (naive, Türkiye yerel)
4. Barkod: strip + normalize
5. Adet kontrolü: 0 veya negatif → flag kolonu ekle
6. Kanonik ad: `df.groupby('barkod')['urun_fatura_ismi'].agg(lambda x: x.mode()[0])`
7. Alias tablosu: barkod → unique isim listesi (JSON array)
8. Çıktı: temiz DataFrame + ürün master seed

---

## REF-03: SEGMENTASYON

**ABC** (adet bazlı, ciro yok):
- A: kümülatif %80
- B: %80-95
- C: %95-100

**ABC v2** (Entegra zenginleştirme sonrası, ciro bazlı):
- `ciro = toplam_adet × buying_price` (veya marketplace fiyatı)
- Adet bazlı ABC korunur (`abc_adet`), ciro bazlı eklenir (`abc_ciro`)
- Dashboard'da her iki ABC gösterilir, filtre seçenekli

**Talep Tipi** (CV = Coefficient of Variation, ADI = Average Demand Interval):
| Tip | Kriter | Tahmin Yaklaşımı |
|---|---|---|
| Düzenli (smooth) | CV < 0.5, ADI < 1.32 | ETS / Prophet / ARIMA |
| Aralıklı (intermittent) | ADI ≥ 1.32, CV < 0.5 | Croston / TSB |
| Lumpy | ADI ≥ 1.32, CV ≥ 0.5 | Croston / TSB + min-max |
| Erratic | CV ≥ 0.5, ADI < 1.32 | Robust MA / kural |
| Yeni / Az veri | < 30 gün satış | Basit ortalama + geniş band |

**SKU Sağlık Skoru** (0-100): satış trendi, alias sayısı, anomali sıklığı, talep düzenliliği, son 30 gün aktivite.

---

## REF-04: TAHMİN MODELLERİ

| Katman | Model | Kullanım |
|---|---|---|
| Baseline | Naive, Simple MA, Weighted MA | Benchmark, her SKU |
| Orta | ETS, Holt-Winters | Düzenli/sezonluk |
| İleri | Prophet veya ARIMA | A sınıfı düzenli |
| Aralıklı | Croston / TSB | Intermittent/lumpy |
| Hibrit | Model + kural (min-max clamp) | Az veri / çok volatil |

Değerlendirme: backtesting (son 30 gün test), MAPE/WAPE/MAE/bias. Her SKU'ya en iyi modeli otomatik seç (WAPE bazlı).
Horizon: 14, 30, 60 gün (config'den).

---

## REF-05: BİRLİKTE SATIŞ ANALİZİ

- Sepet = Sipariş Numarası (aynı sipariş_no → bir sepet)
- Algoritma: Apriori veya FP-Growth (`mlxtend`)
- Min support: 0.005 (config'den)
- Çıktı: ürünA, ürünB, support, confidence, lift, sepet sayısı
- Aksiyon: bundle önerisi, cross-sell, "beraber stokla"

---

## REF-06: SATIN ALMA ÖNERİSİ

```
hedef_stok = günlük_ort_talep × hedef_gün + güvenlik_stoğu
güvenlik_stoğu = z_score × std_talep × sqrt(lead_time + review_period)
öneri = hedef_stok - mevcut_stok

Entegra sonrası: mevcut_stok = Entegra quantity (gerçek değer!)
Entegra öncesi fallback: mevcut_stok = 0

Config parametreleri:
  hedef_gün: 50 | lead_time: 7 | review_period: 7
  servis: A=%97 → z=1.88, B=%95 → z=1.65, C=%90 → z=1.28
```

Days of Supply: mevcut_stok / günlük_tahmin_talep

---

## REF-07: ANOMALİ ALGILAMA

| Yöntem | Ne Yakalar |
|---|---|
| Z-score (rolling) | Spike / düşüş |
| Zero-sales run | Beklenen satışın uzun süre gelmemesi |
| Change point | Trend kırılması |
| Rolling std band | Aralık dışı değerler |

Stok-out flag: aktif ürün + ani sıfır + beklenen aralıktan uzun sessizlik → "Olası stok-out" (kesinlik DÜŞÜK).
Kampanya proxy: z-score > 2 olan günler → "kampanya_benzeri" etiketi.

---

## REF-08: ÇIKTI TABLOLARI

**T1 — Ürün Master**: barkod, kanonik_ad, alias_listesi, alias_sayisi, ilk/son_satis_tarihi, toplam_adet, toplam_siparis, gunluk_ort_adet, abc_sinifi, talep_tipi, aktiflik, sku_saglik_skoru
→ Zenginleştirilmiş: + mevcut_stok, buying_price, kategori, marka, abc_ciro, kalan_gun

**T2 — Günlük Talep**: barkod, tarih, adet, kümülatif_adet, hafta_ici_mi, hafta_no, ay

**T3 — Tahmin**: barkod, tarih, tahmin_adet, alt_band, ust_band, model, tahmin_horizon

**T4 — Satın Alma Önerisi**: barkod, kanonik_ad, abc_sinifi, mevcut_stok, gunluk_ort, hedef_gun, onerilen_stok, guvenlik_stok, beklenen_tukenme_gun, risk_bandi

**T5 — Birlikte Satış**: urun_a_barkod, urun_b_barkod, urun_a_ad, urun_b_ad, support, confidence, lift, sepet_sayisi

**T6 — Anomali/Olay**: barkod, kanonik_ad, baslangic_tarih, bitis_tarih, olay_tipi, siddet, olasi_aciklama, guven_seviyesi

**T7 — Aykırı Günler Takvimi**: tarih, etkilenen_sku_sayisi, olay_tipi, toplam_anomali_adet

**T8 — Alarm Listesi** (YENİ): barkod, kanonik_ad, abc_sinifi, kategori, marka, mevcut_stok, gunluk_tahmin, kalan_gun, alarm_seviye (kritik/uyarı/izle), onerilen_siparis, son_guncelleme

---

## REF-09: DASHBOARD (Streamlit + Plotly)

**01 Yönetici Özet**: Top 20 ürün, ABC pasta, 6 ay trend, aktif/pasif SKU, sağlık dağılımı
**02 Talep Analizi**: Ürün seçici, günlük zaman serisi + tahmin + MA overlay, haftalık/aylık, hafta içi/sonu
**03 Birlikte Satış**: Ürün seçince top 10 eşleşme (lift sıralı), bundle öneri, "beraber stokla"
**04 Stok Planlama**: Hedef gün slider (30-90), öneri tablosu (filtre: ABC/aktiflik/talep tipi), "X stoksam kaç gün?" hesaplayıcı
**05 Anomali**: Olay listesi, drill-down zaman serisi, stok-out listesi, aykırı gün heatmap

**06 Alarm** (YENİ):
- Üst bant: 🔴 Kritik (≤7 gün) / 🟠 Uyarı (≤14 gün) / 🟡 İzle (≤21 gün) sayaçları
- Alarm tablosu: T8 verileri, renk kodlu, sıralı (kalan gün artan)
- Her satırda "Sipariş Ver" önerisi (hedef gün bazlı)
- Filtreler: ABC, kategori, marka, alarm seviyesi
- "Son güncelleme" zaman damgası (Entegra son çekim zamanı)
- Geçmiş alarm log'u (hangi ürün ne zaman alarma düştü, ne zaman çıktı)
- Excel indirme butonu

Ortak: sidebar (tarih/ABC/kategori/marka/arama filtresi), indirme butonları, Plotly hover, tutarlı renk paleti (config'den).

---

## REF-10: İŞ KARAR KURALLARI & EK VERİ

**Karar kuralları**: A→%97 servis+geniş güvenlik | B→%95 | C→%90+min stok | Yeni(<30gün)→geniş band+basit ort | Pasif(30gün 0)→öneri=0+uyarı | Stok-out→kırmızı flag

**Alarm eşikleri** (config'den):
- 🔴 Kritik: kalan_gun ≤ 7 → anında bildirim
- 🟠 Uyarı: kalan_gun ≤ 14 → günlük özet bildirim
- 🟡 İzle: kalan_gun ≤ 21 → dashboard'da göster, bildirim yok
- A sınıfı ürünlerde eşikler 1.5x genişletilir (ör: kritik ≤ 10 gün)

**Olmazsa olmaz ek veri**: ~~mevcut stok~~✅, ~~fiyat~~✅, lead time (hâlâ varsayım)
**Nice-to-have**: MOQ, paket içi adet, iade flag, kampanya takvimi, tedarikçi

---

## REF-11: EKSTRA ANALİZ ÖNERİLERİ

Ürün yaşam döngüsü (launch/growth/mature/decline) → `lifecycle_stage` | Churned SKU → son_satis>30gün | Stok-out erken uyarı → trend+hız | Sepet büyüten ürünler → basket+sepet boyutu | Hediye/aksesuar → tek yönlü confidence | Gün-özel pattern → weekday heatmap | Tatil etkisi → resmi tatil+anomali çakışması | Yeni ürün rampa → ilk 30 gün eğri

---

## REF-12: PYTHON PAKETLER

```
pandas>=2.0, numpy, openpyxl, xlsxwriter, scipy, statsmodels, scikit-learn,
mlxtend, streamlit, plotly, joblib,
requests, python-dotenv, schedule,
python-telegram-bot>=20.0, smtplib (stdlib)
# prophet → opsiyonel, ağır
```

---

## REF-13: ENTEGRA API ENTEGRASYonu

### API Bilgileri
- Base URL: `https://apiv2.entegrabilisim.com`
- Auth: JWT token (`/api/user/token/obtain/` POST → email + password)
- Ürün listesi: `/product/page={N}/` GET (paginated, JWT header)
- Credential'lar `.env` dosyasında:
  ```
  ENTEGRA_EMAIL=xxx@hotmail.com
  ENTEGRA_PASSWORD=xxx
  ```

### Entegra'dan Alınacak Alanlar (ihtiyaç olanlar)
| API Alanı | Bizde Karşılığı | Kullanım |
|---|---|---|
| barcode | barkod (JOIN KEY) | Sipariş verisiyle eşleştirme |
| quantity | mevcut_stok | Gerçek reorder, kalan gün hesabı |
| buying_price | alis_fiyati | Maliyet bazlı ABC, kârlılık |
| group | kategori | Filtreleme, raporlama |
| brand | marka | Filtreleme |
| name | entegra_urun_adi | Kanonik ad doğrulama/zenginleştirme |
| status | ilan_durumu | Aktif/pasif filtre |
| critical_stock | kritik_stok_miktari | Entegra'nın kendi eşiği (referans) |
| trendyol_listPrice | trendyol_fiyat | Ciro tahmini |
| hb_price | hb_fiyat | Ciro tahmini |

### API Client Kuralları (entegra_api.py)
- Token cache'le (expire'a kadar tekrar isteme)
- Pagination: tüm sayfaları çek, `time.sleep(0.5)` ile rate limit'e uy
- Barkod normalize: `_kod()` fonksiyonu (float→str, strip)
- Hata yönetimi: retry (3 deneme), loglama, partial failure → devam et
- Çıktı: `data/processed/entegra_products.parquet`

### Zenginleştirme Kuralları (enrichment.py)
- JOIN: `product_master.barkod == entegra.barcode`
- Eşleşmeyen sipariş barkodları → `entegra_eslesme=False` flag
- Eşleşmeyen Entegra ürünleri → "satışı olmayan stok" raporu
- Mevcut stok 0 olan aktif ürünler → otomatik "stok-out" flag
- `product_master.parquet` güncellenir (yeni kolonlar eklenir, eskiler korunur)
- Reorder tablosu yeniden hesaplanır (gerçek mevcut_stok ile)

---

## REF-14: ALARM SİSTEMİ

### Alarm Motoru (alarm.py)
```
kalan_gun = mevcut_stok / gunluk_tahmin_talep

IF gunluk_tahmin_talep == 0 → alarm yok (satış beklenmez)
IF mevcut_stok == 0 AND aktif → 🔴 "STOK BİTMİŞ"

Eşikler (config'den, ABC'ye göre ayarlı):
  A sınıfı: kritik ≤ 10, uyarı ≤ 18, izle ≤ 25
  B sınıfı: kritik ≤ 7, uyarı ≤ 14, izle ≤ 21
  C sınıfı: kritik ≤ 5, uyarı ≤ 10, izle ≤ 15

Çıktı: T8 alarm tablosu → data/processed/alarms.parquet
```

### Bildirim Sistemi (notifier.py)

**Telegram**:
- `python-telegram-bot` kütüphanesi (async)
- Bot oluşturma: BotFather → token al → `.env`'e ekle
- Chat ID: bot'a mesaj at → getUpdates ile chat_id bul → `.env`'e ekle
- Mesaj formatı:
  ```
  🔴 KRİTİK STOK ALARMI
  ━━━━━━━━━━━━━━━━━━
  📦 Ürün: [kanonik_ad]
  🏷️ Barkod: [barkod]
  📊 Mevcut: [stok] adet
  ⏳ Kalan: ~[X] gün
  🛒 Önerilen sipariş: [Y] adet
  ━━━━━━━━━━━━━━━━━━
  🕐 [tarih saat]
  ```
- 🔴 Kritik → anında tek tek bildirim
- 🟠 Uyarı → günde 1 özet mesaj (sabah 09:00)
- Flood koruması: aynı ürün için 12 saat içinde tekrar bildirim gönderme

**E-posta**:
- `smtplib` + `email.mime` (stdlib)
- SMTP ayarları `.env`'den
- Günlük özet rapor (sabah 09:00): tüm kritik + uyarılar, HTML tablo formatı
- Kritik alarm: ayrıca anlık e-posta

**.env credential'ları**:
```
ENTEGRA_EMAIL=xxx
ENTEGRA_PASSWORD=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=xxx@gmail.com
SMTP_PASSWORD=xxx (app password)
ALERT_EMAIL_TO=xxx@xxx.com
```

### Zamanlayıcı (scheduler.py)
- `schedule` kütüphanesi ile günde 2-3 kez çalıştır
- Varsayılan: 08:00, 14:00, 20:00 (config'den ayarlanabilir)
- Her çalışmada:
  1. Entegra API'den stok çek → entegra_products.parquet güncelle
  2. Zenginleştirme çalıştır → product_master güncelle
  3. Alarm hesapla → alarms.parquet güncelle
  4. Kritik alarmları bildir (Telegram + e-posta)
  5. Log yaz (çalışma zamanı, çekilen SKU sayısı, alarm sayısı)
- Çalıştırma: `python -m src.scheduler` (arka planda açık bırakılır)
- Alternatif: Windows Task Scheduler ile `python -m src.alarm --run-once`