"""Köprü: MQTT'deki telemetri mesajlarını API'nin /api/telemetry ucuna iletir (veritabanına yazma ve canlı yayın orada yapılır)."""
import json
import os
import time

import paho.mqtt.client as mqtt
import requests

HOST = os.getenv("MQTT_HOST", "mosquitto")
TOPIC = os.getenv("MQTT_TOPIC", "greenhouse/vallery/telemetry")
API = os.getenv("API_URL", "http://fastapi:8000/api/telemetry")


def forward(payload):
    """API'ye en çok 5 kez dener (API yeniden başlıyor olabilir). Başarısızsa False; yayıncının örtüşmesi sonraki turda tekrar yollar."""
    for attempt in range(5):
        try:
            requests.post(API, json=payload, timeout=30).raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"API'ye iletilemedi ({attempt + 1}/5): {e}", flush=True)
            time.sleep(2 ** attempt)
    return False


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(TOPIC, qos=1)  # her (yeniden) bağlanışta abone ol
    print(f"MQTT bağlandı, abone: {TOPIC}", flush=True)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
    except ValueError:
        print("bozuk mesaj atlandı", flush=True)
        return
    if forward(payload):
        print(f"iletildi: {payload.get('timestamp')}", flush=True)


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gh-bridge", clean_session=False)  # kalıcı oturum: köprü kapalıyken gelenler kuyrukta bekler
    c.on_connect, c.on_message = on_connect, on_message
    c.connect_async(HOST, 1883, 60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
