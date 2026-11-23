"""python -m ingest.test_publisher (backend klasöründen)"""
from ingest.publisher import parse_rows, to_payload

CSV = """hour_start_local,timezone,hour_start_utc,temp_avg_f,vpd_avg_kpa
2026-10-13 11:00:00,America/Denver,2026-10-13 17:00:00+00,73.852,1.190
2026-10-13 10:00:00,America/Denver,2026-10-13 16:00:00+00,71.567,1.076
2026-10-13 12:00:00,America/Denver,2026-10-13 18:00:00+00,,1.2
2026-10-13 13:00:00,America/Denver,bozuk,70,1
"""


def test_parse_and_payload():
    rows = parse_rows(CSV)
    assert len(rows) == 2, "boş sıcaklık ve bozuk saat atlanmalı"
    assert rows[0][0] < rows[1][0], "zamana göre sıralı olmalı"
    p = to_payload(*rows[0])
    assert p["timestamp"] == "2026-10-13T16:00:00+00:00" and p["sensor_id"] == "GH_VERDIFY"
    assert 0 <= p["humidity"] <= 100 and p["temperature"] == 71.567


if __name__ == "__main__":
    test_parse_and_payload()
    print("OK")
