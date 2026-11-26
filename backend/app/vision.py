import time
import requests
import numpy as np
from PIL import Image
import io
import re
import os
import json
from datetime import datetime, timedelta, timezone

from app.ml.lesion import lesion_ratio

# In-memory cache for Verdify API
_cache = {
    "crop_health": None,
    "last_fetched": 0
}


def get_verdify_vision_data():
    """
    Fetches real-time visual crop health observations from Verdify API.
    Uses in-memory cache to prevent excessive external requests.
    """
    now = time.time()
    if _cache["crop_health"] and (now - _cache["last_fetched"] < 60):
        return _cache["crop_health"]

    crop_info = {}

    try:
        # Fetch crop details
        r_crop = requests.get('https://api.verdify.ai/api/v1/crops/5', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r_crop.status_code == 200:
            c_data = r_crop.json()
            crop_info = {
                "name": c_data.get("name"),
                "variety": c_data.get("variety"),
                "stage": c_data.get("stage"),
                "zone": (c_data.get("zone") or "").capitalize() or None,
            }
    except Exception as e:
        print(f"Error fetching crop details: {e}")

    events = []
    try:
        # Fetch visual health log
        r_health = requests.get('https://api.verdify.ai/api/v1/crops/5/health', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r_health.status_code == 200:
            records = r_health.json()
            for rec in records:
                score = rec.get("health_score") or 0
                notes = rec.get("notes", "")
                ts = rec.get("ts", "")
                source = rec.get("source", "gemini-vision")

                # Categorize based on notes
                lower_notes = notes.lower()
                if "yellow" in lower_notes or "stress" in lower_notes or "dry" in lower_notes:
                    status = "warning"
                    badge = "Stress / Yellowing Warning"
                elif "bloom" in lower_notes or "flower" in lower_notes:
                    status = "flowering"
                    badge = "Flowering Active"
                elif re.search(r"\bir\b", lower_notes):  # tam kelime: "air", "their" eşleşmesin
                    status = "night_ir"
                    badge = "Night IR Vision"
                else:
                    status = "healthy"
                    badge = "Optimal Vigour"

                events.append({
                    "timestamp": ts,
                    "health_score": round(score * 100, 1),
                    "notes": notes,
                    "source": source,
                    "status": status,
                    "badge": badge
                })
    except Exception as e:
        print(f"Error fetching vision health: {e}")

    latest_score = events[0]["health_score"] if events else None

    result = {
        "crop": crop_info,
        "latest_health_score": latest_score,
        "vision_model": "Verdify (Gemini) gözlemleri · yükleme: renk tabanlı ExG kuralı",
        "total_observations": len(events),
        "events": events[:25] # Return top 25 recent events
    }

    _cache["crop_health"] = result
    _cache["last_fetched"] = now
    return result


# Eşik altında "emin değilim": 5 katlı çapraz doğrulamada 0,7 ile fotoğrafların %79'u yanıtlanır, yanıtlananların %87'si doğru
CONF_MIN = 0.7
# sınıf -> (Türkçe ad, öneri); sıra lettuce_eval.json "classes" ile aynı olmak zorunda değil, ada göre bakılır
LETTUCE = {
    "healthy": ("Belirgin hastalık belirtisi yok", "Belirti görülmedi; bu, yaprağın kesin sağlıklı olduğu anlamına gelmez (solgunluk ve besin eksikliği tanınmaz). İzlemeye devam edin."),
    "downy_mildew": ("Mildiyö (Bremia lactucae)", "Nemi düşürün, havalandırmayı artırın, yaprakları ıslatmadan sulayın; hastalıklı yaprakları uzaklaştırın. Kesin tanı için uzmana danışın."),
    "other_fungal": ("Diğer mantar (külleme / Septoria)", "Hastalıklı yaprakları ayırın ve havalandırmayı artırın. Bu sınıfta model zayıftır, uzman doğrulaması gerekir."),
    "bacterial": ("Bakteriyel yaprak lekesi", "Hastalıklı yaprakları ayırın, üstten sulamadan ve ıslak bitkiye dokunmaktan kaçının. Uzman doğrulaması gerekir."),
    "viral": ("Viral hastalık (marul mozaiği)", "Bitkiyi ayırın, yaprak biti ve diğer taşıyıcıları kontrol edin. Uzman doğrulaması gerekir."),
}
MOIST = ("downy_mildew", "other_fungal", "bacterial")  # neme bağlı hastalık sınıfları
LEAF_TTL_H, LEAF_MOIST_MIN = 24, 0.5


def alarm_priority(alarm, leaf, now):
    """Karar düzeyinde birleştirme (form, 11. bölüm): iklim alarmı açıkken son 24 saatteki güvenilir yaprak sonucu
    neme bağlı hastalığı >= 0,5 olasılıkla gösteriyorsa öncelik yükselir. Alarm kararı her zaman iklim kuralındadır."""
    if not alarm:
        return "none"
    fresh = leaf["time"] is not None and (now - leaf["time"]).total_seconds() <= LEAF_TTL_H * 3600
    return "high" if fresh and leaf["moist_prob"] >= LEAF_MOIST_MIN else "normal"


_ML_DIR = os.path.join(os.path.dirname(__file__), "ml")
_model = {"sess": None, "classes": None, "f1": None}


def _load_model():
    """ONNX oturumunu ilk çağrıda bir kez yükler; dosya/kütüphane yoksa None döner."""
    if _model["sess"] is None:
        import onnxruntime as ort
        with open(os.path.join(_ML_DIR, "lettuce_eval.json"), encoding="utf-8") as f:
            ev = json.load(f)
        _model["classes"], _model["f1"], _model["crop"] = ev["classes"], ev["macro_f1"], ev["crop_ratio"]
        _model["sess"] = ort.InferenceSession(os.path.join(_ML_DIR, "lettuce_model.onnx"), providers=["CPUExecutionProvider"])
    return _model


def _color_rule(img):
    """Eski renk tabanlı (ExG) kural; model yoksa yedek olarak kullanılır."""
    arr = np.array(img.resize((400, 400)), dtype=np.float32)
    R, G, B = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    total = R + G + B + 1e-6
    green_ratio = float(np.mean(G / total))
    red_ratio = float(np.mean(R / total))

    if red_ratio > 0.38 and green_ratio < 0.34:
        diagnosis = "Early Blight / Brown Spot (Erken Yanıklık / Leke)"
        severity = "High Risk"
        color = "#ef4444"
        recommendation = "Nem seviyesini %65 altına düşürün, havalandırma fanlarını çalıştırın ve fungisit kontrolü yapın."
    elif green_ratio > 0.33 and red_ratio > 0.34:
        diagnosis = "Nitrogen / Iron Chlorosis (Kloroz - Yaprak Sararması)"
        severity = "Medium Risk"
        color = "#f59e0b"
        recommendation = "Kök bölgesi gübre çözeltisinin EC ve pH değerlerini kontrol edin. Şelatlar takviye edilebilir."
    else:
        diagnosis = "Healthy Vegetative Leaf (Sağlıklı Doku)"
        severity = "Optimal"
        color = "#10b981"
        recommendation = "Bitki fotosentez aktivitesi yüksek ve doku yapısı homojen. Mevcut iklim rejimini koruyun."

    return {
        "status": "success",
        "diagnosis": diagnosis,
        "severity": severity,
        "color": color,
        "chlorophyll_index": round(green_ratio * 100, 1),
        "recommendation": recommendation,
        "source": "color-rule",
        "note": "Model dosyası bulunamadı, renk kuralı kullanıldı",
    }


def diagnose_leaf_image(image_bytes: bytes):
    """Marul yaprağı fotoğrafını ONNX modeliyle sınıflandırır; model yoksa renk kuralına düşer."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        try:
            m = _load_model()
        except (ImportError, FileNotFoundError):
            return _color_rule(img)

        w, h = img.size
        mx, my = round(w * (1 - m["crop"]) / 2), round(h * (1 - m["crop"]) / 2)
        img = img.crop((mx, my, w - mx, h - my))  # eğitimdeki merkez kırpmayla aynı
        x = np.asarray(img.resize((224, 224)), dtype=np.float32) / 255.0
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).astype(np.float32)
        logits = m["sess"].run(None, {"x": x.transpose(2, 0, 1)[None]})[0][0]
        p = np.exp(logits - logits.max())
        p /= p.sum()
        idx = np.argsort(p)[::-1][:3]
        top3 = [{"class": m["classes"][i], "label": LETTUCE[m["classes"][i]][0], "prob": round(float(p[i]), 4)} for i in idx]
        conf = float(p[idx[0]])
        confident = conf >= CONF_MIN
        moist = float(sum(p[m["classes"].index(c)] for c in MOIST))
        label = top3[0]["label"]
        healthy = top3[0]["class"] == "healthy"

        if not confident:
            diagnosis, severity, color = f"Emin değilim — en olası: {label}", "Uncertain", "#f59e0b"
            recommendation = "Sonuç güvenilir değil. Görüntü marul yaprağı olmayabilir ya da belirti modelin tanımadığı türdendir. Daha net, tek yapraklı ve düz arka planlı bir fotoğraf yükleyin."
        elif healthy:
            diagnosis, severity, color = label, "Optimal", "#10b981"
            recommendation = LETTUCE["healthy"][1]
        else:
            diagnosis, severity, color = label, "High Risk", "#ef4444"
            recommendation = LETTUCE[top3[0]["class"]][1]

        arr = np.asarray(img.resize((400, 400)), dtype=np.float32)
        green_ratio = float(np.mean(arr[:, :, 1] / (arr.sum(axis=2) + 1e-6)))
        return {
            "status": "success",
            "diagnosis": diagnosis,
            "severity": severity,
            "color": color,
            "recommendation": recommendation,
            "chlorophyll_index": round(green_ratio * 100, 1),
            "top3": top3,
            "confidence": round(conf, 4),
            "confident": confident,
            "macro_f1": m["f1"],
            "lesion_ratio": lesion_ratio(img),
            "source": "onnx",
            "moist_prob": round(moist, 4),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


if __name__ == "__main__":
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    leaf = {"time": t, "moist_prob": 0.8}
    assert alarm_priority(False, leaf, t) == "none"
    assert alarm_priority(True, leaf, t + timedelta(hours=23)) == "high"
    assert alarm_priority(True, leaf, t + timedelta(hours=25)) == "normal"  # bayat yaprak sonucu
    assert alarm_priority(True, {"time": t, "moist_prob": 0.3}, t) == "normal"
    assert alarm_priority(True, {"time": None, "moist_prob": None}, t) == "normal"
    print("OK")
