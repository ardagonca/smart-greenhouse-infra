"""Marul veri hazırlığı: açık lisanslı kaynakları birleştirir, aynı fotoğrafın kopyalarını tek grupta toplar -> manifest.csv
    python lettuce_data.py --data C:/Users/Arda/ml-vision/lettuce

Kaynaklar (zip'ler x_<ad> klasörlerine açılmış olmalı):
- ashishjstar/lettuce-diseases (Kaggle, Apache 2.0): hastalıklı orijinaller + tarlada telefonla çekilmiş sağlıklılar
- santoshshaha/lettuce-plant-disease-dataset (Kaggle, CC0): yalnız artırılmamış sağlıklı orijinaller (h#.jpg); hastalıklıları ashishjstar'ın artırılmış kopyası
- PlantSeg v3 (Zenodo 14935094, CC BY 4.0): marul mildiyösü, marul mozaik virüsü
- rathorhome/lettuce-disease (Kaggle, CC0): hidroponik, Raspberry Pi kamera; EĞİTİME GİRMEZ, dış test (kabin koşuluna en yakın kaynak)

Kopya eşleme: 8 yön (çevirme/döndürme) algısal özet VEYA ImageNet gömmesi çok yakın -> aynı grup. Bölme bu gruplarla yapılır.
"""
import argparse
import glob
import os
import re

import numpy as np
import pandas as pd
import torch
from PIL import Image
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

CLASSES = ["healthy", "downy_mildew", "other_fungal", "bacterial", "viral"]
ASHISH = {"Bacterial": "bacterial", "Downy_mildew_on_lettuce": "downy_mildew", "Powdery_mildew_on_lettuce": "other_fungal",
          "Septoria_blight_on_lettuce": "other_fungal", "Viral": "viral"}  # "Wilt" (6 dosya, etkeni belirsiz) ve yabani ot sınıfı alınmaz
HASH_BITS, COS = 8, 0.85
PHONE_STEP = 4  # telefon serisinde ardışık kareler neredeyse aynı: her 4.sü alınır


def collect(root):
    rows = []
    add = lambda f, label, src, g=None: rows.append({"path": os.path.relpath(f, root), "label": label, "source": src, "hint": g})
    for d, label in ASHISH.items():
        for f in glob.glob(f"{root}/x_ashishjstar/*/{d}/*"):
            add(f, label, "ashishjstar")
    for f in glob.glob(f"{root}/x_ashishjstar/*/Healthy/*"):
        n = int(re.search(r"\((\d+)\)", os.path.basename(f)).group(1))
        if n >= 1072:
            add(f, "healthy", "web_healthy")  # santoshshaha'nın h#.jpg dosyalarıyla aynı web görselleri
        elif n % PHONE_STEP == 0:
            add(f, "healthy", "phone_healthy", f"phone{n // 40}")  # ardışık 40 kare tek grup
    for f in glob.glob(f"{root}/x_santoshshaha/lettuce/*/healthy/*"):
        if re.fullmatch(r"h\d+\.jpe?g", os.path.basename(f)):
            add(f, "healthy", "web_healthy")
    for f in glob.glob(f"{root}/x_plantseg/*/images/*/lettuce_*"):
        add(f, "downy_mildew" if "downy" in f else "viral", "plantseg")
    ext = {"Healthy": "healthy", "Wilt fungal": "ext_wilt", "K Deficient": "ext_K", "N Deficient": "ext_N"}
    for d, label in ext.items():
        for f in glob.glob(f"{root}/x_rathorhome/*/{d}/*"):
            add(f, label, "rathorhome")
    return pd.DataFrame(rows).drop_duplicates("path").reset_index(drop=True)


def dct_hash(im):
    a = np.asarray(im.convert("L").resize((32, 32), Image.LANCZOS), float)
    k = np.arange(32)
    C = np.cos(np.pi * (2 * k[None] + 1) * k[:, None] / 64)
    d = (C @ a @ C.T)[:8, :8].ravel()[1:]
    return d > np.median(d)


def groups(df, root):
    """Birleşim-bul: hash (8 yön) ya da gömme yakınlığı ile aynı fotoğrafın kopyaları."""
    w = EfficientNet_B0_Weights.IMAGENET1K_V1
    net, tf = efficientnet_b0(weights=w), w.transforms()
    net.classifier = torch.nn.Identity()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net.eval().to(dev)
    H, E = [], []
    for p in df.path:
        im = Image.open(os.path.join(root, p)).convert("RGB")
        im.thumbnail((640, 640))
        views = [im.rotate(90 * r, expand=True) for r in range(4)]
        views += [v.transpose(Image.FLIP_LEFT_RIGHT) for v in views]
        H.append(np.stack([dct_hash(v) for v in views]))
        with torch.no_grad():
            e = net(torch.stack([tf(v) for v in (views[0], views[4])]).to(dev)).mean(0)
        E.append((e / e.norm()).cpu().numpy())
    H, E = np.stack(H), np.stack(E)
    n = len(df)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cos = E @ E.T
    pairs = []
    for i in range(n):
        dist = (H[i + 1:] != H[i, 0]).sum(2).min(1) if i + 1 < n else np.array([])
        for j in np.where((dist <= HASH_BITS) | (cos[i, i + 1:] >= COS))[0] + i + 1:
            pairs.append((i, j, int(dist[j - i - 1]), float(cos[i, j])))
            parent[find(j)] = find(i)
    for _, ix in df[df.hint.notna()].groupby("hint").groups.items():
        for j in ix[1:]:
            parent[find(j)] = find(ix[0])
    return [find(i) for i in range(n)], pairs, cos, H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    root = ap.parse_args().data
    df = collect(root)
    df["group"], pairs, cos, H = groups(df, root)
    # Bir grubun farklı etiketli kopyaları varsa etiket güvenilmez: tüm grup atılır
    tr = df[df.source != "rathorhome"]
    amb = tr.groupby("group").label.nunique()
    amb = set(amb[amb > 1].index)
    print("çelişkili etiketli grup:", len(amb), "| atılan dosya:", int(tr.group.isin(amb).sum()))
    ext_g = set(df[df.source == "rathorhome"].group)
    print("dış test ile eğitim arasında ortak grup:", len(ext_g & set(tr.group)))
    df = df[~(df.group.isin(amb) & (df.source != "rathorhome"))]
    df.drop(columns="hint").to_csv(os.path.join(root, "manifest.csv"), index=False)
    print(df.groupby(["label", "source"]).agg(dosya=("path", "size"), grup=("group", "nunique")))
    pd.DataFrame(pairs, columns=["i", "j", "hash", "cos"]).to_csv(os.path.join(root, "pairs.csv"), index=False)


if __name__ == "__main__":
    main()
