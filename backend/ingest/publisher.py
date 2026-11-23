"""Yayıncı: Verdify'ın saatlik arşivini (herkese açık CSV) MQTT'ye telemetri mesajı olarak yayınlar.

Gerçek sera sensörü yerine geçer: tezdeki akış  sensör -> MQTT -> köprü -> API -> Supabase  aynı kalır.
Yeni saatler yayınlanır; son yayından 3 saat geriye örtüşme olur (köprü bir mesajı kaçırırsa kendini onarır, API tekrarı yok sayar).
"""
import csv
import io
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import requests

LAB = "https://lab.verdify.ai"
H = {"User-Agent": "Mozilla/5.0"}
HOST = os.getenv("MQTT_HOST", "mosquitto")
TOPIC = os.getenv("MQTT_TOPIC", "greenhouse/vallery/telemetry")
INTERVAL = int(os.getenv("PUBLISH_INTERVAL_S", "600"))
CATCHUP_H = int(os.getenv("PUBLISH_CATCHUP_HOURS", "336"))  # ilk açılışta geriye doğru kaç saat yayınlansın
OVERLAP_H = 3


def rh_from(temp_c, vpd):
    """API'deki (public_data.rh_from) ile aynı Tetens formülü, 0-100'e kırpılır."""
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return max(0.0, min(100.0, (1 - vpd / es) * 100))


def parse_rows(text):
    """CSV metni -> [(utc_zaman, sıcaklık_F, vpd_kPa)] sıralı. Boş/bozuk satırlar atlanır."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            ts = r["hour_start_utc"].strip()
            if ts.endswith("+00"):
                ts += ":00"  # "2026-10-13 16:00:00+00" -> fromisoformat okuyabilsin
            t = datetime.fromisoformat(ts).astimezone(timezone.utc)
            f, v = float(r["temp_avg_f"]), float(r["vpd_avg_kpa"])
        except (KeyError, ValueError):
            continue
        if math.isnan(f) or math.isnan(v):
            continue
        out.append((t, f, v))
    return sorted(out)


def to_payload(t, f, v):
    return {"sensor_id": "GH_VERDIFY", "timestamp": t.isoformat(), "temperature": f,  # °F, mevcut satırlarla aynı birim
            "humidity": rh_from((f - 32) * 5 / 9, v), "vpd": v}


def fetch_text():
    m = requests.get(f"{LAB}/static/data/hourly-performance/manifest.json", headers=H, timeout=30).json()
    return requests.get(LAB + m["latest"]["url"], headers=H, timeout=60).text


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gh-publisher")
    while True:
        try:
            c.connect(HOST, 1883, 60)
            break
        except OSError as e:
            print(f"MQTT bağlantısı bekleniyor: {e}", flush=True)
            time.sleep(3)
    c.loop_start()
    last = None
    while True:
        try:
            cut = (last - timedelta(hours=OVERLAP_H)) if last else datetime.now(timezone.utc) - timedelta(hours=CATCHUP_H)
            new = [r for r in parse_rows(fetch_text()) if r[0] > cut]
            for t, f, v in new:
                c.publish(TOPIC, json.dumps(to_payload(t, f, v)), qos=1)
            if new:
                last = new[-1][0]
            print(f"{len(new)} saat yayınlandı, son: {last}", flush=True)
        except Exception as e:  # ağ/arşiv hatası: döngü ölmesin, sonraki turda tekrar dener
            print(f"yayın hatası: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
