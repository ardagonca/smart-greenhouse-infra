"""python -m ingest.test_bridge (backend klasöründen): API kapalıyken ölçümler diske alınır, açılınca sırayla gönderilir."""
import json
import os
import tempfile

import requests

from ingest import bridge


class _Msg:
    def __init__(self, p):
        self.payload = json.dumps(p).encode()


def test_spool_and_flush():
    sent, up = [], {"v": False}

    def fake_post(url, json=None, timeout=None):
        if not up["v"]:
            raise requests.ConnectionError("API kapalı")
        sent.append(json["timestamp"])
        return type("R", (), {"raise_for_status": lambda self: None})()

    bridge.requests.post, bridge.time.sleep = fake_post, lambda s: None
    bridge.SPOOL = os.path.join(tempfile.mkdtemp(), "pending.jsonl")

    for t in ("10:00", "11:00", "12:00"):  # kesinti: üç ölçüm diske
        bridge.on_message(None, None, _Msg({"timestamp": t}))
    assert sent == [] and len(open(bridge.SPOOL).read().splitlines()) == 3

    up["v"] = True  # bağlantı geldi: yeni ölçüm + bekleyenler sırayla
    bridge.on_message(None, None, _Msg({"timestamp": "13:00"}))
    assert sent == ["13:00", "10:00", "11:00", "12:00"], sent
    assert open(bridge.SPOOL).read() == ""

    calls = {"n": 0}

    def flaky(url, json=None, timeout=None):  # ikinci bekleyende yine kopar: kalanlar silinmemeli
        calls["n"] += 1
        if calls["n"] == 2:
            raise requests.ConnectionError("tekrar koptu")
        return fake_post(url, json, timeout)

    for t in ("14:00", "15:00"):
        bridge.spool({"timestamp": t})
    bridge.requests.post = flaky
    assert bridge.flush() == 1 and open(bridge.SPOOL).read().splitlines() == ['{"timestamp": "15:00"}']
    print("bridge test ok")


if __name__ == "__main__":
    test_spool_and_flush()
