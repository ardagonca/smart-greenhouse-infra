"""Marul sınıflandırması için donmuş omurga + lojistik regresyon karşılaştırması (train_lettuce.py ile aynı manifest ve aynı katlar).
    python compare_backbones.py --data <klasör>

Seçim yanlılığı: "nested" satırında omurga ve C her dış katta yalnız eğitim kısmındaki iç katlarla seçilir; dürüst başarım odur.
Her omurga için C de iç katlarla seçilir. Birincil ölçüt: grup temsilcileriyle makro-F1. 5 tekrar x 5 kat.
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
import timm
import torch
import torchvision.transforms.functional as F
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from lettuce_data import CLASSES

BACKBONES = {
    "mobilenetv3_large": ("mobilenetv3_large_100.ra_in1k", 224),
    "convnext_tiny_in22k": ("convnext_tiny.fb_in22k", 224),
    "dinov2_s": ("vit_small_patch14_dinov2.lvd142m", 224),
    "dinov2_b": ("vit_base_patch14_dinov2.lvd142m", 224),
    "dinov2_b_392": ("vit_base_patch14_dinov2.lvd142m", 392),
    "siglip_b": ("vit_base_patch16_siglip_224.webli", 224),
}
CS, REPEATS = (0.0003, 0.003, 0.03, 0.3), 5
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def center(im, crop):
    """Kenarları atar: filigran ve açıklama yazıları (ör. "Disease: Bacterial blight") modele ipucu olmasın."""
    w, h = im.size
    return im.crop((round(w * (1 - crop) / 2), round(h * (1 - crop) / 2), round(w * (1 + crop) / 2), round(h * (1 + crop) / 2)))


def feats(name, size, root, paths, crop):
    m = timm.create_model(name, pretrained=True, num_classes=0, **({"img_size": size} if "dinov2" in name else {})).eval().to(DEV)
    cfg = timm.data.resolve_model_data_config(m)
    out = []
    with torch.no_grad(), torch.autocast(DEV):
        for p in paths:
            t = F.to_tensor(center(Image.open(os.path.join(root, p)).convert("RGB"), crop).resize((size, size), Image.BICUBIC))
            x = torch.stack([t, F.hflip(t), F.vflip(t), F.rotate(t, 180)])
            x = F.normalize(x, cfg["mean"], cfg["std"]).to(DEV)
            out.append(m(x).float().mean(0).cpu().numpy())
    return np.stack(out)


def clf(C):
    return make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight="balanced", max_iter=3000))


def weights(g):
    """Her grup toplamda eşit ağırlık alsın (telefon serisi baskın olmasın)."""
    return 1 / pd.Series(g).map(pd.Series(g).value_counts()).values


def fit_pred(Xa, ya, ga, Xb, C):
    m = clf(C).fit(Xa, ya, logisticregression__sample_weight=weights(ga))
    P = np.zeros((len(Xb), len(CLASSES)))
    P[:, m[-1].classes_] = m.predict_proba(Xb)
    return P


def mf1(y, p):
    return f1_score(y, p, average="macro", labels=range(len(CLASSES)), zero_division=0)


def rep_score(y, P, g):
    i = pd.Series(g).drop_duplicates().index.values
    return mf1(y[i], P[i].argmax(1))


def inner(X, y, g, seed):
    """Her C için iç kat dışı skor."""
    s = {}
    for C in CS:
        P = np.zeros((len(y), len(CLASSES)))
        for a, b in StratifiedGroupKFold(4, shuffle=True, random_state=seed).split(X, y, g):
            P[b] = fit_pred(X[a], y[a], g[a], X[b], C)
        s[C] = rep_score(y, P, g)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--crop", type=float, default=1.0, help="merkez kırpma oranı (0.7: yazısız denetim)")
    ap.add_argument("--only", nargs="*", default=list(BACKBONES))
    a = ap.parse_args()
    root, sfx = a.data, "" if a.crop == 1 else f"_c{a.crop}"
    man = pd.read_csv(os.path.join(root, "manifest.csv"))
    tr, ext = man[man.source != "rathorhome"].reset_index(drop=True), man[man.source == "rathorhome"].reset_index(drop=True)
    y, g = tr.label.map(CLASSES.index).values, tr.group.values
    paths = [p.replace("\\", "/") for p in list(tr.path) + list(ext.path)]
    X = {}
    for k, (name, size) in ((k, BACKBONES[k]) for k in a.only):
        fp = os.path.join(root, f"feat_{k}{sfx}.npy")
        if not os.path.exists(fp):
            np.save(fp, feats(name, size, root, paths, a.crop))
        X[k] = np.load(fp)
        print(k, X[k].shape, flush=True)
    XT = {k: v[:len(tr)] for k, v in X.items()}
    XE = {k: v[len(tr):] for k, v in X.items()}
    rep = tr.drop_duplicates("group").index.values
    names = list(X) + ["nested"]
    OOF = {k: np.zeros((REPEATS, len(y), len(CLASSES))) for k in names}
    picks = []
    for r in range(REPEATS):
        for i_tr, i_te in StratifiedGroupKFold(5, shuffle=True, random_state=r).split(y, y, g):
            best = {}
            for k in X:
                s = inner(XT[k][i_tr], y[i_tr], g[i_tr], r)
                C = max(s, key=s.get)
                best[k] = (s[C], C)
                OOF[k][r, i_te] = fit_pred(XT[k][i_tr], y[i_tr], g[i_tr], XT[k][i_te], C)
            w = max(best, key=lambda k: best[k][0])
            picks.append(w)
            OOF["nested"][r, i_te] = OOF[w][r, i_te]
        print("tekrar", r + 1, {k: round(mf1(y[rep], OOF[k][r, rep].argmax(1)), 3) for k in names}, flush=True)

    Y, rng, res = y[rep], np.random.default_rng(0), {}
    BI = [rng.integers(0, len(rep), len(rep)) for _ in range(1000)]
    # 3 sınıflı görünüm (formdaki "neme bağlı hastalık"): sağlıklı / mildiyö+mantar+bakteri / viral; olasılıklar toplanır
    M3 = np.array([0, 1, 1, 1, 2])
    for k in names:
        P = OOF[k][:, rep]
        sc = [mf1(Y, p.argmax(1)) for p in P]
        pm = P.mean(0).argmax(1)  # yalnız sınıf bazlı döküm için
        ci = np.percentile([np.mean([mf1(Y[i], p[i].argmax(1)) for p in P]) for i in BI[:300]], [2.5, 97.5])
        P3 = np.stack([np.stack([p[:, M3 == c].sum(1) for c in range(3)], 1) for p in P])
        f3 = np.mean([f1_score(M3[Y], p.argmax(1), average="macro") for p in P3])
        b2 = np.mean([f1_score(Y > 0, p.argmax(1) > 0, average="macro") for p in P])
        res[k] = {"macro_f1": round(float(np.mean(sc)), 3), "rep_std": round(float(np.std(sc)), 3), "ci": [round(float(v), 3) for v in ci],
                  "macro_f1_3": round(float(f3), 3), "binary_f1": round(float(b2), 3),
                  "per_class": dict(zip(CLASSES, [round(float(v), 2) for v in f1_score(Y, pm, average=None, labels=range(5), zero_division=0)]))}
    er = ext.drop_duplicates("group").index.values
    lab = np.array(list(ext.label[er]))
    for k in X:
        s = inner(XT[k], y, g, 0)
        C = max(s, key=s.get)
        p = fit_pred(XT[k], y, g, XE[k][er], C).argmax(1)
        res[k].update(C=C, ext={c: f"{int((p[lab == c] > 0).sum())}/{int((lab == c).sum())}" for c in sorted(set(lab))})
    res["nested"]["picks"] = pd.Series(picks).value_counts().to_dict()
    for k in names:
        print(k, json.dumps(res[k], ensure_ascii=False))
    with open(os.path.join(root, f"backbones{sfx}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
