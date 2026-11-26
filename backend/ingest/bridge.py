"""Köprü: MQTT'deki telemetri mesajlarını API'nin /api/telemetry ucuna iletir (veritabanına yazma ve canlı yayın orada yapılır)."""
import json
import os
import time

import paho.mqtt.client as mqtt
import requests

HOST = os.getenv("MQTT_HOST", "mosquitto")
TOPIC = os.getenv("MQTT_TOPIC", "greenhouse/vallery/telemetry")
API = os.getenv("API_URL", "http://fastapi:8000/api/telemetry")
SPOOL = os.getenv("SPOOL_PATH", "/spool/pending.jsonl")  # iletilemeyen ölçümler (Docker biriminde, yeniden başlatmada kaybolmaz)


def forward(payload, tries=5):
    """API'ye en çok `tries` kez dener (API yeniden başlıyor olabilir). Başarısızsa False."""
    for attempt in range(tries):
        try:
            requests.post(API, json=payload, timeout=30).raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"API'ye iletilemedi ({attempt + 1}/{tries}): {e}", flush=True)
            if attempt + 1 < tries:
                time.sleep(2 ** attempt)
    return False


def spool(payload):
    """Veritabanı/API uzun süre yoksa ölçüm diske yazılır (publisher'ın 3 saatlik örtüşmesinden uzun kesintiler için)."""
    os.makedirs(os.path.dirname(SPOOL) or ".", exist_ok=True)
    with open(SPOOL, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def flush():
    """Bekleyen ölçümleri sırayla gönderir; ilk başarısızlıkta durur, kalanlar dosyada bekler. Gönderilen sayısını döner."""
    if not os.path.exists(SPOOL):
        return 0
    with open(SPOOL, encoding="utf-8") as f:
        rows = [ln for ln in f.read().splitlines() if ln.strip()]
    sent = 0
    for ln in rows:
        if not forward(json.loads(ln), tries=1):
            break
        sent += 1
    tmp = SPOOL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("".join(ln + "\n" for ln in rows[sent:]))
    os.replace(tmp, SPOOL)  # yarıda kesilirse dosya bozulmaz (en kötü ihtimalle bir ölçüm iki kez gider, sorgular saatlik ortalama alır)
    if sent:
        print(f"bekleyen {sent} ölçüm iletildi, kalan {len(rows) - sent}", flush=True)
    return sent


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
        flush()
    else:
        spool(payload)
        print(f"diske alındı, bağlantı gelince gönderilecek: {payload.get('timestamp')}", flush=True)


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gh-bridge", clean_session=False)  # kalıcı oturum: köprü kapalıyken gelenler kuyrukta bekler
    c.on_connect, c.on_message = on_connect, on_message
    c.connect_async(HOST, 1883, 60)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
