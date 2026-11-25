"""Marul yaprak hastalığı modeli: ConvNeXt-Tiny (ya da MobileNetV3) ince ayarı, fotoğraf grubu bazında 5 katlı çapraz doğrulama.
    python lettuce_data.py --data <klasör>      (manifest.csv üretir)
    python train_lettuce.py --data <klasör> --out ../app/ml

Protokol (sonuç görülmeden sabitlendi):
- Katlar fotoğraf grubuna göre (StratifiedGroupKFold): aynı fotoğrafın kopyası eğitim ve teste birlikte düşmez. Artırma yalnız eğitimde.
- Hiperparametreler sabit, test katında ayar/erken durdurma YOK. Dağıtılan model aynı ayarla tüm eğitim verisiyle kurulur.
- Birincil ölçüt: makro-F1, her gruptan TEK temsilci fotoğrafla; %95 aralık grup bootstrap (2000).
- Temel modeller: prototipteki renk eşik kuralı (yalnız sağlıklı/hastalıklı ayırır) ve renk oranlarıyla eğitilen sığ karar ağacı (5 sınıf).
- Dış test: rathorhome (hidroponik, Raspberry Pi kamera) eğitime girmez; sağlıklıdaki yanlış pozitif oranı kabin hedefinin (<%10) vekilidir.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import timm
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.tree import DecisionTreeClassifier

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.ml.lesion import lesion_mask, lesion_ratio  # noqa: E402
from app.vision import _color_rule  # noqa: E402
from lettuce_data import CLASSES  # noqa: E402

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
EPOCHS, BS, EPOCH_N, BOOT = 20, 32, 640, 2000
CROP = 0.7  # merkez kırpma: kenardaki filigran/açıklama yazıları modele ipucu olmasın (API'de de aynı kırpma)
BACKBONES = {"mobilenet": ("mobilenetv3_large_100.ra_in1k", 4e-4), "convnext": ("convnext_tiny.fb_in22k", 1e-4)}  # (ad, öğrenme hızı)
POOL = ThreadPoolExecutor(8)
DEV = "cuda" if torch.cuda.is_available() else "cpu"
AUG = T.Compose([T.RandomResizedCrop(224, scale=(0.4, 1), antialias=True), T.RandomHorizontalFlip(), T.RandomVerticalFlip(), T.RandomRotation(25),
                 T.ColorJitter(0.3, 0.3, 0.25, 0.03), T.RandomApply([T.GaussianBlur(5)], 0.2), T.ConvertImageDtype(torch.float), T.Normalize(MEAN, STD)])
PLAIN = T.Compose([T.Resize((224, 224), antialias=True), T.ConvertImageDtype(torch.float), T.Normalize(MEAN, STD)])


def center(im):
    w, h = im.size
    return im.crop((round(w * (1 - CROP) / 2), round(h * (1 - CROP) / 2), round(w * (1 + CROP) / 2), round(h * (1 + CROP) / 2)))


def load(root, paths):
    """Küçük set: kısa kenarı 320'ye indirip bellekte tutar (uint8)."""
    out = []
    for p in paths:
        im = center(Image.open(os.path.join(root, p)).convert("RGB"))
        s = 320 / min(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)))
        out.append(torch.from_numpy(np.asarray(im).copy()).permute(2, 0, 1))
    return out


def fit(X, y, g, seed, bb):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    name, LR = BACKBONES[bb]
    m = timm.create_model(name, pretrained=True, num_classes=len(CLASSES)).to(DEV)
    # sınıf dengeli, sınıf içinde grup dengeli örnekleme: kalabalık telefon serisi baskın olmasın
    s = pd.DataFrame({"y": y, "g": g})
    w = 1 / (s.groupby(["y", "g"]).y.transform("size") * s.groupby("y").g.transform("nunique"))
    w = (w / w.sum()).values
    steps = EPOCH_N // BS
    opt = torch.optim.AdamW(m.parameters(), LR, weight_decay=1e-3)
    sch = torch.optim.lr_scheduler.OneCycleLR(opt, LR, total_steps=EPOCHS * steps)
    for _ in range(EPOCHS):
        m.train()
        for _ in range(steps):
            ix = rng.choice(len(y), BS, p=w)
            x = torch.stack(list(POOL.map(AUG, [X[i] for i in ix]))).to(DEV)
            opt.zero_grad()
            with torch.autocast(DEV, dtype=torch.bfloat16):
                loss = nn.functional.cross_entropy(m(x), torch.tensor(y[ix]).to(DEV), label_smoothing=0.1)
            loss.backward()
            opt.step()
            sch.step()
    return m.eval()


def proba(m, X):
    with torch.no_grad():
        return np.concatenate([m(torch.stack([PLAIN(x) for x in X[i:i + 64]]).to(DEV)).softmax(1).cpu().numpy() for i in range(0, len(X), 64)])


def color_feats(X):
    f = []
    for x in X:
        a = x.numpy().astype(float).reshape(3, -1)
        c = (a / (a.sum(0) + 1e-6)).mean(1)
        f.append([c[0], c[1], c[2], 2 * c[1] - c[0] - c[2]])
    return np.array(f)


def boot_ci(y, p, fn):
    rng = np.random.default_rng(0)
    v = [fn(y[i], p[i]) for i in (rng.integers(0, len(y), len(y)) for _ in range(BOOT))]
    return [round(float(q), 3) for q in np.percentile(v, [2.5, 97.5])]


def summ(y, p, fn):
    return {"value": round(float(fn(y, p)), 3), "ci": boot_ci(y, p, fn)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backbone", choices=BACKBONES, default="convnext")
    a = ap.parse_args()
    man = pd.read_csv(os.path.join(a.data, "manifest.csv"))
    tr, ext = man[man.source != "rathorhome"].reset_index(drop=True), man[man.source == "rathorhome"].reset_index(drop=True)
    X, y, g = load(a.data, tr.path), tr.label.map(CLASSES.index).values, tr.group.values
    XE = load(a.data, ext.path)
    print(DEV, "eğitim", len(y), "fotoğraf,", len(set(g)), "grup | dış test", len(ext), flush=True)

    P, tree = np.zeros((len(y), len(CLASSES))), np.zeros(len(y), int)
    CF = color_feats(X)
    for k, (i_tr, i_te) in enumerate(StratifiedGroupKFold(5, shuffle=True, random_state=0).split(CF, y, g)):
        assert not set(g[i_tr]) & set(g[i_te])
        P[i_te] = proba(fit([X[i] for i in i_tr], y[i_tr], g[i_tr], k, a.backbone), [X[i] for i in i_te])
        tree[i_te] = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=0).fit(CF[i_tr], y[i_tr]).predict(CF[i_te])
        print(f"kat {k + 1}: makro-F1 {f1_score(y[i_te], P[i_te].argmax(1), average='macro'):.3f}", flush=True)

    def imgs(ps):
        return [center(Image.open(os.path.join(a.data, q)).convert("RGB")) for q in ps]

    def mf(t, q):
        return f1_score(t, q, average="macro", labels=range(len(CLASSES)), zero_division=0)

    def bf(t, q):
        return f1_score(t, q, average="macro", labels=[0, 1], zero_division=0)

    rep = tr.drop_duplicates("group").index.values  # her gruptan tek temsilci
    Y, pr = y[rep], P[rep].argmax(1)
    rule = np.array([_color_rule(im)["severity"] != "Optimal" for im in imgs(tr.path[rep])]).astype(int)
    B = (Y != 0).astype(int)
    M3 = np.array([0, 1, 1, 1, 2])  # formdaki "neme bağlı hastalık": mildiyö + mantar + bakteri
    p3 = np.stack([P[rep][:, M3 == c].sum(1) for c in range(3)], 1).argmax(1)
    pc, rc, f1, n = precision_recall_fscore_support(Y, pr, labels=range(len(CLASSES)), zero_division=0)
    res = {
        "crop": "Marul (Lactuca sativa)", "model": BACKBONES[a.backbone][0] + " (ince ayar)", "crop_ratio": CROP, "classes": CLASSES,
        "n_groups": int(len(rep)), "n_images": int(len(y)),
        "macro_f1": summ(Y, pr, mf), "macro_f1_color_tree": summ(Y, tree[rep], mf),
        "binary_macro_f1": summ(B, (pr != 0).astype(int), bf), "binary_macro_f1_color_rule": summ(B, rule, bf),
        "macro_f1_3class": summ(M3[Y], p3, lambda t, q: f1_score(t, q, average="macro", labels=[0, 1, 2], zero_division=0)),
        "per_class": {c: {"precision": round(float(pc[i]), 3), "recall": round(float(rc[i]), 3), "f1": round(float(f1[i]), 3), "n": int(n[i])}
                      for i, c in enumerate(CLASSES)},
        "confusion": confusion_matrix(Y, pr, labels=range(len(CLASSES))).tolist(),
        "healthy_false_positive_cv": round(float((pr[Y == 0] != 0).mean()), 3),
        "sources": ["ashishjstar/lettuce-diseases (Kaggle, Apache 2.0)", "santoshshaha/lettuce-plant-disease-dataset (Kaggle, CC0)",
                    "PlantSeg v3 (Zenodo 14935094, CC BY 4.0)", "rathorhome/lettuce-disease (Kaggle, CC0; yalnız dış test)"],
    }

    m = fit(X, y, g, 0, a.backbone)
    PE = proba(m, XE)
    er = ext.drop_duplicates("group").index.values
    lab = ext.label[er].values
    eh = er[lab == "healthy"]
    fp = (PE[eh].argmax(1) != 0).astype(int)
    res["external_healthy_fp"] = {"value": round(float(fp.mean()), 3), "n": int(len(eh)), "ci": boot_ci(fp, fp, lambda t, _: t.mean())}
    res["external_healthy_fp_color_rule"] = round(float(np.mean([_color_rule(im)["severity"] != "Optimal" for im in imgs(ext.path[eh])])), 3)
    res["external_flagged_not_healthy"] = {c: round(float((PE[er[lab == c]].argmax(1) != 0).mean()), 3) for c in ("ext_wilt", "ext_K", "ext_N")}

    # HSV/LAB lezyon analizi: PlantSeg maskeleriyle örtüşme ve sağlıklı/hastalıklı ayırma gücü
    ratios = [lesion_ratio(im) for im in imgs(tr.path[rep])]
    ok = np.array([r is not None for r in ratios])
    iou, base = [], []
    for q in tr.path[tr.source == "plantseg"]:
        q = q.replace("\\", "/")
        mp = os.path.splitext(q.replace("/images/", "/annotations/"))[0] + ".png"
        gt = np.asarray(Image.open(os.path.join(a.data, mp)).resize((256, 256), Image.NEAREST)) > 0
        gt = gt if gt.ndim == 2 else gt.any(2)
        les = lesion_mask(Image.open(os.path.join(a.data, q)))[0]
        iou.append((les & gt).sum() / max((les | gt).sum(), 1))
        base.append(gt.mean())
    res["lesion"] = {"auc_healthy_vs_diseased": round(float(roc_auc_score(B[ok], [r for r in ratios if r is not None])), 3),
                     "mask_iou_mean": round(float(np.mean(iou)), 3), "mask_iou_all_pixels_baseline": round(float(np.mean(base)), 3),
                     "n_masks": len(iou), "no_plant": int((~ok).sum())}
    np.savez(os.path.join(a.data, f"oof_{a.backbone}.npz"), P=P[rep], Y=Y, src=np.array(list(tr.source[rep])), path=np.array(list(tr.path[rep])), PE=PE[er], ext=np.array(list(lab)))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    m.cpu()
    torch.onnx.export(m, torch.zeros(1, 3, 224, 224), os.path.join(a.out, "lettuce_model.onnx"), input_names=["x"], output_names=["logits"],
                      dynamic_axes={"x": {0: "n"}, "logits": {0: "n"}}, opset_version=17, dynamo=False)
    with open(os.path.join(a.out, "lettuce_eval.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
