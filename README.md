# Akıllı Sera: Hastalık Riski için Erken Uyarı ve Teşhis Sistemi

Örtü altı marul yetiştiriciliğinde yüksek nem kaynaklı hastalık riskini **belirtiler ortaya çıkmadan** öngörmeyi ve yaprak fotoğrafındaki bulguyla birleştirmeyi amaçlayan bir prototip (TÜBİTAK 1002-A önerisinin yazılım altyapısı).

Kabin ve sensör düğümleri kurulana kadar sistem, ABD Colorado'daki gerçek bir seranın ([Verdify](https://lab.verdify.ai)) kamuya açık saatlik verisiyle çalışır.

## Mimari

```
Verdify saatlik arşiv ─► publisher ─► MQTT (Mosquitto) ─► bridge ─► FastAPI ─► Supabase (PostgreSQL)
(ileride: ESP32 sensör düğümleri)                                     │
                                                                      ├─ VPD tahmini (GBM) + histerezisli alarm
Yaprak fotoğrafı (arayüzden) ─────────────────────────────────────────├─ Görüntü modeli (ConvNeXt-Tiny, ONNX)
                                                                      ├─ Karar düzeyinde birleştirme (öncelik)
                                                                      └─ REST + WebSocket ─► React/Electron arayüz
```

| Servis (Docker) | Görev |
|---|---|
| `greenhouse_mosquitto` | MQTT aracı (yalnız Docker ağı içinde) |
| `greenhouse_publisher` | Verdify arşivini 10 dakikada bir MQTT'ye yayınlar (gerçek sensör yerine geçer) |
| `greenhouse_bridge` | MQTT mesajlarını `POST /api/telemetry` ile API'ye iletir; veritabanı yoksa API 503 döner, köprü yeniden dener |
| `greenhouse_api` | FastAPI: veri, tahmin, alarm, görüntü teşhisi, birleştirme; tahmin modeli 7 günde bir kendini yeniden eğitir |

## Karar mantığı

1. **Tahmin:** Son 24 saatin sıcaklık, nem ve VPD'sinden sonraki 6 saatin ortalama VPD'si tahmin edilir (gradyan artırmalı ağaçlar, GBM).
2. **Alarm (kural tabanlı):** Tahmin **2 ardışık saat** 0,8 kPa'nın altındaysa alarm açılır; tahmin 0,9 kPa'yı geçince kapanır (histerezis, kısa dalgalanmalarda alarm üretmez).
3. **Görüntü:** Yüklenen marul yaprağı fotoğrafı 5 sınıfa ayrılır (sağlıklı, mildiyö, diğer mantar, bakteriyel, viral). Güven 0,7'nin altındaysa "Emin değilim" denir. Sonuç veritabanına yazılır (`leaf_diagnosis`).
4. **Birleştirme:** Alarm açıkken son 24 saatteki güvenilir yaprak sonucunda neme bağlı hastalık olasılığı ≥ 0,5 ise öncelik **yüksek** olur. Alarm kararını görüntü vermez, yalnız önceliği değiştirir.

## Çalıştırma

```bash
cp .env.example .env            # Supabase bağlantı adresini girin
docker compose up -d            # API http://localhost:8000
cd frontend && npm install && npm run dev   # Electron penceresi açılır (Docker servislerini de başlatır)
```

Değerlendirme ve simülasyon (API konteyneri içinde):

```bash
docker exec greenhouse_api python eval_models.py          # zamana dayalı model değerlendirmesi -> app/ml/eval_results.json
docker exec greenhouse_api python simulate.py --leaf <foto>  # son 7 günün uçtan uca simülasyonu -> sim.json
python backend/simulate.py --plot backend/sim.json         # grafik (matplotlib gerekir)
```

Görüntü modeli GPU'lu bir ortamda eğitilir: `backend/ml_vision/lettuce_data.py` (veri hazırlığı, kopya gruplama) → `train_lettuce.py` (eğitim + değerlendirme) → `compare_backbones.py` (omurga karşılaştırması).

## Sonuçlar

### VPD tahmini ve alarm (Temmuz–Kasım 2026, 3394 test saati, 5 ardışık blok)

Eğitim her blokta testten önceki veriyle (30 saat boşlukla) yapılır; güven aralıkları 7 günlük blok bootstrap ile.

| Model | MAE (kPa) | PR-AUC | MCC |
|---|---|---|---|
| Persistence (taban) | 0,198 | 0,676 | 0,465 |
| Saatlik klimatoloji (taban) | 0,170 | 0,554 | 0,440 |
| **GBM (canlı sistem)** | 0,122 | 0,897 | 0,748 |
| CNN-LSTM | 0,103 | 0,900 | 0,743 |

- GBM ve CNN-LSTM, iki taban modeli PR-AUC ve MCC'de güven aralıkları örtüşmeden geçer.
- CNN-LSTM'in MAE avantajı eşli bootstrap ile anlamlıdır; PR-AUC ve MCC farkı anlamlı değildir.
- Histerezisli alarm haftalık yanlış alarmı ham kurala göre azaltır (1,25 → 0,35).

### Görüntü modeli (309 özgün fotoğraf grubu, 5 katlı grup bazlı çapraz doğrulama)

| Ölçüt | CNN (ConvNeXt-Tiny) | Renk tabanlı yöntem |
|---|---|---|
| Makro-F1, 5 sınıf | 0,61 [0,54–0,67] | 0,29 [0,24–0,34] |
| Makro-F1, sağlıklı / neme bağlı / viral | 0,83 [0,78–0,88] | – |
| Makro-F1, sağlıklı / hastalıklı | 0,92 [0,89–0,95] | 0,58 [0,53–0,64] |
| Dış test, sağlıklı yaprakta yanlış alarm | 0/30 | 30/30 |

Aynı fotoğrafın kopyaları (döndürme, kırpma, gürültü) tek grupta tutulur, eğitim ve teste birlikte düşmez. Kenarlardaki filigran ve açıklama yazıları modele ipucu olmasın diye görüntülerin ortadaki %70'i kullanılır.

## Sınırlılıklar

- **Mevsimsel kayma:** Kasım simülasyonunda (son 7 gün) alarm her gece açıldı; alarmlı saatlerin yalnız %16'sında sonraki 6 saat gerçekten eşiğin altındaydı. Gece ısıtması VPD'yi eşiğin hemen üstünde tuttuğu için yaz-sonbahar verisiyle eğitilen model kışın fazla alarm üretir.
- **Erken uyarı süresi kısa:** Ölçülen VPD'nin eşiğin altına indiği 155 olayda histerezisli alarmın medyan erkenliği 0 saattir; olayların %37'sinde en az 1 saat önce uyarır. Histerezis yanlış alarmı azaltırken erkenliği de azaltır.
- **Görüntü verisi az ve karışık kaynaklı:** Bakteriyel (16 grup) ve diğer mantar (27 grup) sınıfları zayıftır (F1 0,49 ve 0,16). Sağlıklı ve hastalıklı fotoğraflar farklı kaynaklardan geldiği için model kısmen çekim tarzını öğrenmiş olabilir. Solgunluk ve besin eksikliği eğitimde yoktur.
- **Gerçek kabin verisi henüz yok:** Tüm sonuçlar başka bir seranın verisi ve açık fotoğraf setleriyle elde edildi; kabin kurulduğunda yeniden ölçülmelidir.

## Veri kaynakları ve lisanslar

| Kaynak | Kullanım | Lisans |
|---|---|---|
| Verdify (lab.verdify.ai, graphs.verdify.ai) | Sera iklim verisi, kameralar | Kamuya açık |
| ashishjstar/lettuce-diseases (Kaggle) | Hastalıklı ve sağlıklı marul | Apache 2.0 |
| santoshshaha/lettuce-plant-disease-dataset (Kaggle) | Sağlıklı marul (yalnız özgün görüntüler) | CC0 |
| PlantSeg v3 (Zenodo 14935094) | Marul mildiyösü, mozaik virüsü | CC BY 4.0 |
| rathorhome/lettuce-disease (Kaggle) | Yalnız dış test (hidroponik) | CC0 |

Ham fotoğraflar depoda tutulmaz; indirme ve işleme betikleri `backend/ml_vision/` altındadır.

## Klasör yapısı

```
backend/
  app/            FastAPI (main.py), veritabanı (db.py), Verdify erişimi (public_data.py, scada.py), görüntü (vision.py)
  app/ml/         tahmin modeli (forecast.py), lezyon analizi (lesion.py), eğitilmiş modeller ve sonuç dosyaları
  ingest/         MQTT publisher ve bridge
  ml_vision/      görüntü veri hazırlığı, eğitim ve karşılaştırma betikleri
  eval_models.py  zamana dayalı tahmin değerlendirmesi
  simulate.py     uçtan uca simülasyon
frontend/src/components/
  pages/          Overview, Weather, Analytics, Monitoring, System Health
  overview/ monitoring/ layout/   sayfa bileşenleri
```
