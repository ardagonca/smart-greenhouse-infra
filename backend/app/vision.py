import time
import requests
import numpy as np
from PIL import Image
import io
import re
import os
import json

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


# Yaprak olmayan görüntüyü eler: 0,5'te %24'ü geçiyordu, 0,75'te %6'sı (390 duvar kâğıdı/kamera kırpığı); gerçek yaprakların %98,7'si geçer (1500 test görüntüsü)
# shortcut: ayrı bir "yaprak mı" modeli yok, hatalı kabul sorun olursa yaprak olmayan sınıfla yeniden eğit
CONF_MIN = 0.75
_ML_DIR = os.path.join(os.path.dirname(__file__), "ml")
_model = {"sess": None, "classes": None, "acc": None}


def _load_model():
    """ONNX oturumunu ilk çağrıda bir kez yükler; dosya/kütüphane yoksa None döner."""
    if _model["sess"] is None:
        import onnxruntime as ort
        with open(os.path.join(_ML_DIR, "leaf_classes.json"), encoding="utf-8") as f:
            _model["classes"] = json.load(f)
        try:
            with open(os.path.join(_ML_DIR, "leaf_eval.json"), encoding="utf-8") as f:
                _model["acc"] = json.load(f).get("test_accuracy")
        except Exception:
            _model["acc"] = None
        _model["sess"] = ort.InferenceSession(os.path.join(_ML_DIR, "leaf_model.onnx"), providers=["CPUExecutionProvider"])
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


def _label(cls):
    return cls.replace("___", " — ").replace("_", " ")


def diagnose_leaf_image(image_bytes: bytes):
    """Yaprak fotoğrafını ONNX modeliyle sınıflandırır; model yoksa renk kuralına düşer."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        try:
            m = _load_model()
        except (ImportError, FileNotFoundError):
            return _color_rule(img)

        x = np.asarray(img.resize((224, 224)), dtype=np.float32) / 255.0
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).astype(np.float32)
        logits = m["sess"].run(None, {"x": x.transpose(2, 0, 1)[None]})[0][0]
        p = np.exp(logits - logits.max())
        p /= p.sum()
        idx = np.argsort(p)[::-1][:3]
        top3 = [{"class": m["classes"][i], "label": _label(m["classes"][i]), "prob": round(float(p[i]), 4)} for i in idx]
        conf = float(p[idx[0]])
        confident = conf >= CONF_MIN
        label = top3[0]["label"]
        healthy = top3[0]["class"].endswith("healthy")

        if not confident:
            diagnosis, severity, color = f"Emin değilim — en olası: {label}", "Uncertain", "#f59e0b"
            recommendation = "Sonuç güvenilir değil. Görüntü yaprak olmayabilir ya da modelin bilmediği bir bitkidir. Daha net, tek yapraklı ve düz arka planlı bir fotoğraf yükleyin."
        elif healthy:
            diagnosis, severity, color = label, "Optimal", "#10b981"
            recommendation = "Yaprak sağlıklı görünüyor. Mevcut bakım ve iklim rejimini koruyun."
        else:
            diagnosis, severity, color = label, "High Risk", "#ef4444"
            recommendation = "Hastalıklı yaprakları ayırın, nemi düşürün, havalandırmayı artırın; kesin tanı ve ilaç için uzmana veya zirai ilaç etiketine başvurun."

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
            "model_accuracy": m["acc"],
            "source": "onnx",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
