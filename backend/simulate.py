"""Uçtan uca sistem simülasyonu (1002-A formundaki son mimariyle): gerçek seranın son 7 günü saat saat yeniden oynatılır.
    docker exec greenhouse_api python simulate.py --leaf /tmp/leaf.jpg      -> sim.json + zaman çizelgesi
    python simulate.py --plot sim.json                                     -> sim.png (matplotlib gereken bir ortamda)

Her saat: son 24 saat -> GBM ile 6 saat sonrası VPD -> histerezisli alarm (2 ardışık saat < 0,8 aç, > 0,9 kapat).
Model yalnız simülasyon haftasından önceki veriyle (30 saat boşlukla) eğitilir: geleceği görmez.
Senaryo: alarm ilk açıldıktan 1 saat sonra üretici bir yaprak fotoğrafı yükler; karar katmanı önceliği hesaplar.
"""
import argparse
import json
import os
from datetime import timedelta

import numpy as np


def simulate(leaf_path, days=7):
    from app import vision
    from app.ml.forecast import FEATS, GAP, HOR, OFF, THR, WIN, _gbm, alarm_series, load, make, tab

    df = load()
    X, y, idx, _ = make(df)
    times = df.index[idx]
    start = times[-1] - timedelta(days=days)
    te = np.where(times > start)[0]
    tr = np.arange(0, te[0] - GAP)
    m = _gbm().fit(tab(X[tr], times[tr]), y[tr])
    pred = m.predict(tab(X[te], times[te]))
    alarm = alarm_series(pred, times[te])
    vpd_now = X[te, -1, FEATS.index("vpd")]

    leaf, leaf_at = None, None
    on = np.where(alarm)[0]
    if leaf_path and len(on):
        leaf_at = on[0] + 1 if on[0] + 1 < len(te) else on[0]
        with open(leaf_path, "rb") as f:
            leaf = vision.diagnose_leaf_image(f.read())
    rec = {"time": None, "moist_prob": None}
    rows = []
    for k, i in enumerate(te):
        if leaf_at is not None and k == leaf_at and leaf.get("confident"):
            rec = {"time": times[i].to_pydatetime(), "moist_prob": leaf["moist_prob"]}
        pr = vision.alarm_priority(bool(alarm[k]), rec, times[i].to_pydatetime())
        fut = df["vpd"].iloc[idx[i] + 1: idx[i] + 1 + HOR].mean()
        rows.append({"time": times[i].isoformat(), "vpd": round(float(vpd_now[k]), 3), "pred_6h": round(float(pred[k]), 3),
                     "actual_6h": None if np.isnan(fut) else round(float(fut), 3), "alarm": bool(alarm[k]), "priority": pr})
    out = {"threshold": THR, "off": OFF, "window_h": WIN, "horizon_h": HOR, "train_until": times[tr[-1]].isoformat(), "rows": rows,
           "leaf": None if leaf is None else {k: leaf.get(k) for k in ("diagnosis", "confidence", "confident", "moist_prob")},
           "leaf_time": None if leaf_at is None else rows[leaf_at]["time"]}
    return out


def report(s):
    R = s["rows"]
    print(f"Model eğitimi: {s['train_until'][:16]}'e kadar | simülasyon: {R[0]['time'][:16]} -> {R[-1]['time'][:16]} ({len(R)} saat)")
    prev = "none"
    for r in R:
        if r["priority"] != prev:
            print(f"  {r['time'][:16]}  öncelik {prev} -> {r['priority']}  (ölçülen VPD {r['vpd']}, 6 sa tahmin {r['pred_6h']})")
            prev = r["priority"]
    if s["leaf_time"]:
        print(f"  {s['leaf_time'][:16]}  yaprak fotoğrafı: {s['leaf']}")
    a = np.array([r["alarm"] for r in R])
    ok = [r for r in R if r["actual_6h"] is not None]
    mae = np.mean([abs(r["pred_6h"] - r["actual_6h"]) for r in ok])
    al = [r for r in ok if r["alarm"]]
    hit = sum(r["actual_6h"] < s["threshold"] for r in al)
    print(f"Alarmlı saatlerin {hit}/{len(al)}'inde sonraki 6 saatin gerçek ortalama VPD'si de eşiğin altındaydı")
    print(f"Alarmlı saat: {a.sum()}/{len(R)} | yüksek öncelikli saat: {sum(r['priority'] == 'high' for r in R)} | bu haftanın 6 sa MAE: {mae:.3f} kPa")


def plot(s, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import pandas as pd
    R = pd.DataFrame(s["rows"])
    R["time"] = pd.to_datetime(R["time"]).dt.tz_convert("America/Denver")
    fig, ax = plt.subplots(figsize=(12, 4.5), dpi=150)
    for col, shade, lab in (("alarm", "#fde68a", "Alarm açık"), ("priority", "#fca5a5", "Yüksek öncelik (alarm + yaprak)")):
        on = (R[col] == "high") if col == "priority" else R[col]
        first = True
        for blk in (on != on.shift()).cumsum()[on].unique():
            t = R["time"][(on != on.shift()).cumsum() == blk]
            ax.axvspan(t.iloc[0], t.iloc[-1] + pd.Timedelta(hours=1), color=shade, alpha=0.6, lw=0, label=lab if first else None)
            first = False
    ax.plot(R["time"], R["vpd"], color="#2563eb", lw=1.4, label="Ölçülen VPD")
    ax.plot(R["time"], R["pred_6h"], color="#15803d", lw=1.4, ls="--", label="6 saat sonrası tahmin (GBM)")
    ax.axhline(s["threshold"], color="#b91c1c", lw=1, ls=":", label=f"Risk eşiği {s['threshold']} kPa")
    if s["leaf_time"]:
        lt = pd.Timestamp(s["leaf_time"]).tz_convert("America/Denver")
        ax.axvline(lt, color="black", lw=1)
        ax.annotate(f"Yaprak: {s['leaf']['diagnosis']}\n(neme bağlı olasılık {s['leaf']['moist_prob']:.2f})", (lt, ax.get_ylim()[0]),
                    xytext=(6, 8), textcoords="offset points", fontsize=8)
    ax.set_ylabel("VPD (kPa)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=R["time"].dt.tz))
    ax.set_title("Uçtan uca simülasyon: Verdify serası, son 7 gün (Denver saati)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=8, ncol=5, frameon=False)
    fig.tight_layout()
    fig.savefig(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--leaf", help="alarm açılınca yüklenecek yaprak fotoğrafı")
    ap.add_argument("--plot", help="sim.json'dan sim.png çiz")
    a = ap.parse_args()
    if a.plot:
        with open(a.plot, encoding="utf-8") as f:
            plot(json.load(f), os.path.splitext(a.plot)[0] + ".png")
    else:
        s = simulate(a.leaf)
        with open("sim.json", "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        report(s)
