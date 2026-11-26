# Yol Haritası

Kapsam: donanım yok. Veri kaynağı Verdify'ın kamuya açık sera verisi (saatlik arşiv, iklim, dış hava, ekipman durumu). Görüntü tarafı arayüzden yüklenen yaprak fotoğraflarıyla devam eder.

Kapsam dışı: sensör/kamera donanımı, dil modelleri, Kafka, ekipmanı gerçekten çalıştıran kontrol.

Sıra: **1 → 2 → 3 → 6 → 4 → 9 → 10**. Zaman kısıtlıysa en az 1, 2, 6 ve 9 yapılmalı.

---

## Aşama 1: Bilimsel temel (öncelik: en yüksek)

Mevcut ölçülmüş zayıflıklar: kışın alarmların yalnız %16'sı doğru, medyan erken uyarı süresi 0 saat, VPD ile hastalık arasındaki bağ doğrudan kurulmamış.

### 1. Hastalık risk endeksi
- Verdify'ın saatlik iç sıcaklık ve nem verisinden: nemin %90 üstünde kaldığı ardışık saatler ve çiy noktası farkı (hava sıcaklığı − çiy noktası) küçük olan saatler.
- Bunlardan, literatürdeki mildiyö risk modellerine dayanan bir günlük enfeksiyon riski endeksi hesaplanır.
- Eşik değerleri kaynaktan doğrulanıp README'de kaynakça ile verilir.
- **Bitti sayılır:** endeks API'de ve Overview'da görünür; hesaplama birim testiyle doğrulanmış.

### 2. Kış kaymasının giderilmesi
- Modele Verdify'da bulunan ek girdiler eklenir: dış sıcaklık ve nem, güneş ışınımı, ısıtıcı çalışma süresi. Geçmiş verisi yeterince geriye gitmeyen girdi kullanılmaz.
- Son 2 hafta en başta **kilitli test** olarak ayrılır; tüm seçimler ondan önceki veriyle yapılır.
- **Bitti sayılır:** kilitli testte eski ve yeni model aynı tabloda; alarm doğruluğu ve haftalık yanlış alarm sayısı raporlanmış.

### 3. Olasılıklı alarm ve ödünleşim eğrisi
- Model "sonraki 6 saatte VPD 0,8 kPa altına düşer mi" olasılığını verir.
- Farklı uyarı eşiklerinde erken uyarı süresi ile haftalık yanlış alarm sayısı arasındaki ilişkiyi gösteren bir eğri çizilir. Kullanılan eşik doğrulama verisinde seçilir.
- **Bitti sayılır:** eğri Model Karşılaştırma sayfasında; seçilen nokta gerekçesiyle README'de.

## Aşama 2: Karar destek

### 4. Eylem önerisi
- Alarm açıkken ekipmanın o anki durumu Verdify'dan okunur (ısıtıcı, fan, sisleme, havalandırma) ve öneri buna göre verilir. Örnek: "sisleme çalışıyor, durdurulması önerilir"; "ısıtma kapalı, 1 °C artırılması VPD'yi yaklaşık 0,1 kPa yükseltir".
- VPD etkisi fiziksel formülle (doymuş buhar basıncı) hesaplanır.
- **Değerlendirme:** Verdify'ın gerçek iklim kontrolcüsünün aynı saatlerde yaptığıyla öneriler karşılaştırılır (örneğin önerinin kaçında kontrolcü de aynı yönde hareket etmiş).

### 5. Alarm geçmişi ve onay
- Alarm açılış/kapanış ve öncelik değişimleri veritabanına yazılır; kullanıcı panelden "gördüm" diye onaylar.
- **Bitti sayılır:** geçmiş alarmlar listelenir; erken uyarı ölçütü bu kayıtlardan da hesaplanabilir.

### 6. Bağlantı kopmasına dayanıklılık
- Veritabanı erişilemezken bridge ölçümleri yerel dosyada biriktirir, bağlantı gelince sırayla gönderir. Şu an bu aralıktaki veri kayboluyor.
- **Bitti sayılır:** veritabanı bağlantısı kesilip geri açıldığında arada eksik saat kalmadığı testle gösterilmiş.

### 7. Bildirim (isteğe bağlı)
- Yüksek öncelikli alarmda Telegram veya e-posta mesajı.

## Aşama 3: Görüntü modelinin güvenilirliği

### 8. Güven kalibrasyonu ve açıklanabilirlik
- Modelin "%90 eminim" dediği sonuçların gerçekten yaklaşık %90'ının doğru olup olmadığı ölçülür (güvenilirlik diyagramı, ECE). Gerekirse sıcaklık ölçeklemesiyle düzeltilir; "Emin değilim" eşiği (0,7) bu ölçüme göre gözden geçirilir.
- Kapatma (occlusion) haritası: fotoğrafın hangi bölgesinin karara etki ettiği arayüzde gösterilir. Bu yöntem ONNX modelle çalışır, ek kütüphane gerektirmez.

## Aşama 4: Sunum kalitesi

### 9. Demo modu
- Geçmişten seçilmiş gerçek bir yüksek risk olayı hızlandırılmış oynatılır: tahmin, alarm, öneri, yaprak teşhisi ve öncelik sırayla görünür. Böylece sunum günü canlı verinin sakin olması sorun olmaz.

### 10. Otomatik testler
- Mevcut testler (tahmin matematiği, publisher, alarm önceliği, lezyon) GitHub Actions ile her push'ta çalışır.

### 11. Belgeleme
- README'deki sonuç tabloları ve sınırlılıklar her aşamadan sonra güncellenir.

---

## Bilinen sınırlılıklar (bu planla değişmeyecekler)

- Tüm sonuçlar başka bir seranın (Colorado) verisine dayanır; Türkiye koşullarına ve marul kabinine genellenmesi doğrulanmamıştır.
- Verdify kameraları bitki yaprağı göstermez; görüntü modeli yalnız yüklenen fotoğraflarla çalışır.
- Görüntü verisi az ve karışık kaynaklıdır (309 fotoğraf grubu); bakteriyel ve diğer mantar sınıfları zayıftır.
