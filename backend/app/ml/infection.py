"""Marul mildiyösü (Bremia lactucae) enfeksiyon koşulu: BREMCAST'ten uyarlanmış kural.

Kaynaklar: Kushalappa (2001), BREMCAST, Int. J. Pest Manag.; Wu ve ark. (2002), Phytopathology 92:631
(güneş doğuşundan sonra >= 3 saat ıslaklık; bu sürede ort. sıcaklık <= 20 °C, sonraki 4 saatte <= 22 °C).
Gün, seranın yerel saatine (Denver) göre alınır. Kullanım: python -m app.ml.infection (tüm geçmişin özeti)
"""
import math

import pandas as pd

# shortcut: yaprak ıslaklığı sensörü yok, nem >= %90 olan saat ıslak sayılır (vekil); sensör gelince doğrudan ölçüm kullanılmalı
WET_RH, WET_H, T_WET, POST_H, T_POST = 90.0, 3, 20.0, 4, 22.0
LAT, LON, TZ = 39.74, -104.99, "America/Denver"  # Colorado, yaklaşık (saatlik çözünürlükte yeterli)


def sunrise_hour(day):
    """Yerel güneş doğuş saati (ondalık), NOAA'nın basit formülü; birkaç dakikalık hata saatlik veride önemsiz."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(math.radians(LAT)) * math.cos(dec)) - math.tan(math.radians(LAT)) * math.tan(dec)))
    utc_min = 720 - 4 * (LON + ha) - eqt
    off = pd.Timestamp(day.strftime("%Y-%m-%d") + " 12:00", tz=TZ).utcoffset().total_seconds() / 3600
    return utc_min / 60 + off


def day_status(d):
    """d: tek bir yerel güne ait saatlik DataFrame (index yerel saat, sütunlar temp °C, hum %)."""
    d = d.dropna(subset=["temp", "hum"])
    out = {"date": d.index[0].strftime("%Y-%m-%d"), "wet_hours": int((d["hum"] >= WET_RH).sum()),
           "max_rh": round(float(d["hum"].max()), 1), "rh_gap": round(WET_RH - float(d["hum"].max()), 1),
           "morning_wet_h": 0, "favorable": False}
    sr = sunrise_hour(d.index[0])
    after = d[d.index.hour + d.index.minute / 60 >= math.floor(sr)]
    run = 0
    for i in range(len(after)):  # gün doğumundan itibaren kesintisiz ıslak saatler (saat atlanırsa seri biter)
        if after["hum"].iloc[i] < WET_RH or (i and after.index[i] - after.index[i - 1] != pd.Timedelta(hours=1)):
            break
        run += 1
    out["morning_wet_h"] = run
    if run >= WET_H:
        t_wet = after["temp"].iloc[:WET_H].mean()
        post = after["temp"].iloc[WET_H:WET_H + POST_H]
        out["favorable"] = bool(t_wet <= T_WET and len(post) == POST_H and post.mean() <= T_POST)
    return out


def daily(df):
    """df: saatlik, UTC index, temp (°C) ve hum (%) sütunları -> gün gün durum listesi."""
    loc = df.tz_convert(TZ) if df.index.tz is not None else df
    return [day_status(g) for _, g in loc.groupby(loc.index.date) if g[["temp", "hum"]].notna().any().all()]


def _selftest():
    idx = pd.date_range("2026-05-10 00:00", periods=24, freq="h", tz=TZ)
    base = pd.DataFrame({"temp": 18.0, "hum": 70.0}, index=idx)
    sr = math.floor(sunrise_hour(idx[0]))
    wet = base.copy()
    wet.loc[wet.index.hour.isin(range(sr - 2, sr + 3)), "hum"] = 95.0  # şafaktan önce başlayıp sonra 3 saat süren ıslaklık
    s = day_status(wet)
    assert s["morning_wet_h"] == 3 and s["favorable"], s
    hot = wet.copy()
    hot["temp"] = 25.0
    assert not day_status(hot)["favorable"], "sıcaklık eşiği aşılınca koşul oluşmamalı"
    short = base.copy()
    short.loc[short.index.hour.isin([sr, sr + 1]), "hum"] = 95.0
    assert not day_status(short)["favorable"], "2 saatlik ıslaklık yetmemeli"
    late = base.copy()
    late.loc[late.index.hour.isin(range(sr + 2, sr + 6)), "hum"] = 95.0
    assert day_status(late)["morning_wet_h"] == 0, "gün doğumunda kuru başlayan gün sayılmamalı"
    assert day_status(base)["rh_gap"] == 20.0
    assert 4.5 < sunrise_hour(pd.Timestamp("2026-06-21")) < 6.0 and 6.5 < sunrise_hour(pd.Timestamp("2026-12-21")) < 7.8
    print("infection self-test ok")


if __name__ == "__main__":
    _selftest()
    from app.ml.forecast import load
    days = daily(load())
    fav = [x["date"] for x in days if x["favorable"]]
    print(f"{len(days)} gün | koşulun oluştuğu gün: {len(fav)} {fav[:10]}")
    print(f"nemin >= %{WET_RH:.0f} olduğu gün: {sum(x['wet_hours'] > 0 for x in days)} | "
          f"günlük en yüksek nem, medyan: %{pd.Series([x['max_rh'] for x in days]).median():.1f}, en yüksek: %{max(x['max_rh'] for x in days):.1f}")
