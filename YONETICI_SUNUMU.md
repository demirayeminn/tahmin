# Stok Takip Sistemi — Yönetici Sunumu

## Ne Yaptık, Neden?

Geçmişte hangi ürünün ne zaman biteceğini tahmin etmek zordu. Bu sistem, 6 aylık gerçek sipariş geçmişimizi analiz ederek her ürün için otomatik olarak şunu söylüyor:

- Mevcut stok kaç günde biter?
- Önümüzdeki 1–2–3 ay için ne kadar sipariş verilmeli?
- Hangi ürünler şu an kritik durumda?

---

## Hangi Veriyi Kullandık?

**Kaynak:** Entegra sistemindeki siparişlerimiz.
**Dönem:** Eylül 2025 – Şubat 2026 (6 ay, 181 gün).
**Hacim:** 113.310 sipariş satırı, 344 farklı ürün.

Sistemi kurarken elimizdeki en güvenilir veriyi kullandık: kendi gerçek satışlarımız. Hiçbir tahmin dışarıdan değil; tamamen kendi geçmişimizden üretildi.

---

## Ürünleri Nasıl Grupladık? (ABC Analizi)

Her ürün, toplam satış hacmindeki payına göre 3 gruba ayrıldı:

| Grup | Kriter | Ürün Sayısı | Ne Anlama Gelir? |
|------|--------|-------------|-----------------|
| **A** | Toplam ciromuzun ilk %80'ini oluşturan ürünler | 78 ürün | En kritik, en çok takip gereken |
| **B** | Sonraki %15'i oluşturan ürünler | 83 ürün | Orta önem |
| **C** | Kalan %5'i oluşturan ürünler | 183 ürün | Düşük hacim, düşük risk |

Bu gruplandırmayı neden yaptık? Çünkü A grubunda bir ürün stok bittiğinde kayıp çok büyük. C grubunda ise aynı hassasiyete gerek yok. Sistem her grubu farklı eşiklerle izliyor.

---

## Alım Önerisi Nasıl Hesaplandı?

### Temel Mantık

Her ürün için önce günlük ortalama satış hızı hesaplandı (son 90 günün ortalaması alındı).

Ardından iki şey toplandı:

1. **Hedef stok:** O ürünün 50 gün boyunca yetecek kadarı
2. **Güvenlik tamponu:** Satışın dalgalanmasına karşı ekstra stok

Sonra mevcut depo stoğu çıkarıldı. Fark = sipariş edilmesi gereken miktar.

```
Alım Önerisi = (Günlük Satış × Hedef Gün) + Güvenlik Tamponu − Mevcut Stok
```

Negatif çıkarsa sıfır alınır (zaten yeterli stok var demektir).

---

### Neden 50 Gün Hedef?

50 gün, iki temel süreden oluşuyor:

- **Tedarik süresi (lead time):** Sipariş verdikten ürünün gelmesine kadar geçen süre → 7 gün
- **Gözden geçirme periyodu:** Sistemi kontrol edip karar verme aralığı → 7 gün
- **Kalan tampon:** Beklenmedik satış artışlarına, gecikmelere karşı ek süre → ~36 gün

Toplamda 50 gün, operasyonumuzu rahatlatacak makul bir ufuk. Bu sayı istenirse değiştirilebilir.

---

### Güvenlik Tamponu Neden Farklı Gruplar İçin Farklı?

Satış dalgalanması ne kadar büyükse, o kadar fazla tampon gerekir. Ama A grubundaki ürünler daha değerli olduğundan daha yüksek güvence ile izleniyor:

| Grup | Güvence Düzeyi | Ne Anlama Gelir? |
|------|----------------|-----------------|
| **A** | %97 | 100 günden 97'sinde stok eksiği yaşanmaz |
| **B** | %95 | 100 günden 95'inde stok eksiği yaşanmaz |
| **C** | %90 | 100 günden 90'ında stok eksiği yaşanmaz |

Bu oranlar, tedarik zinciri yönetiminde standart kullanılan servis düzeyleri. Pazarda "A malı daha yüksek servis seviyesi ister" prensibi üzerine kurulu.

---

## Alarm Eşikleri Nasıl Belirlendi?

Mevcut stok, o ürünün günlük satış hızına bölünür → "kaç gün daha yeter?" sorusunu yanıtlar.

| Alarm | A Grubu | B Grubu | C Grubu |
|-------|---------|---------|---------|
| Stok Bitmis | Depo = 0 | Depo = 0 | Depo = 0 |
| Kritik (kırmızı) | 10 gün veya az kaldı | 7 gün veya az kaldı | 5 gün veya az kaldı |
| Uyarı (sarı) | 11–18 gün kaldı | 8–14 gün kaldı | 6–10 gün kaldı |
| İzle (yeşil) | 19–25 gün kaldı | 15–21 gün kaldı | 11–15 gün kaldı |
| Normal | 25 günün üzeri | 21 günün üzeri | 15 günün üzeri |

**Neden A grubu için daha uzun eşikler?**
Çünkü A grubu daha çok satılan ürünler. Tedarik gecikmesi olduğunda kaybı daha büyük. O yüzden daha erken uyarıyoruz.

---

## 50 Günlük Satış Tahmini Nereden Geliyor?

Bu sütun, her ürünün son 90 günlük günlük ortalama satış hızını 50 ile çarpmaktır.

Yani: "Bu ürün son 90 günde günde ortalama X adet sattı → 50 günde yaklaşık 50×X adet satarız."

Gerçek bir makine öğrenimi tahmini değil, iş kararları için sezgisel bir projeksiyon. Mevsimsellik veya kampanya varsa sapma olabilir.

---

## Pasif Ürün Nedir?

Son 30 gün içinde hiç satışı olmayan ürünler "Pasif" olarak işaretlendi. Bu ürünler için:
- Alım önerisi sıfırdır (satılmıyorsa sipariş vermek anlamsız)
- Alarm çalışmaz
- Tabloda gri renkte görünürler

---

## Entegra Bağlantısı Ne Yapıyor?

Her gün `baslat.bat` çalıştırıldığında sistem Entegra'ya bağlanarak depo stoğunu çekiyor. Bu sayede alım önerisi "teorik değil, gerçek" stok üzerinden hesaplanıyor.

Ek olarak, bu anlık stok değerleri tarihli olarak biriktiriliyor. Zamanla "bu ürünün stoğu nasıl değişti" grafiği oluşuyor.

---

## Özetle Sistemin Değeri

| Eskisi | Şimdisi |
|--------|---------|
| Stok ne zaman biter? El yordamıyla tahmin | Sistem her gün otomatik hesaplar |
| Sipariş miktarı? Deneyime dayalı | Formüle dayalı, ABC'ye göre ayarlı |
| Hangi ürün kritik? Fark edilene kadar geç kalınır | Alarm listesi günlük güncellenir |
| Stok geçmişi? Yoktu | Her gün birikimli kaydediliyor |

---

*Sistemdeki tüm eşikler (50 gün, servis seviyeleri, alarm günleri) gerektiğinde iş kararlarına göre değiştirilebilir. Formüller sabit, parametreler esnek.*
