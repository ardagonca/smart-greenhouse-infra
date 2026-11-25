"""Yaprak hastalığı modeli: PlantVillage (38 sınıf) üzerinde ImageNet ön eğitimli MobileNetV3-Large ince ayarı.
Ana makinede (GPU) çalışır, API konteynerinde değil:
    python train_leaf.py --data C:/Users/Arda/ml-vision/data --out ../app/ml
Çıktı: leaf_model.onnx (API'de onnxruntime ile çalışır), leaf_classes.json, leaf_eval.json

Bölme: eğitimin %10'u doğrulama (en iyi epoch seçimi), resmî test bölmesi yalnızca sonda bir kez değerlendirilir.
Uyarı: PlantVillage'da aynı yaprağın birden çok çekimi var; rastgele bölmede benzer kareler hem eğitimde hem testte olabilir,
bu yüzden test doğruluğu gerçek sera koşullarındaki doğruluğun üst sınırıdır.
"""
import argparse
import glob
import io
import json
import os

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision.models import MobileNet_V3_Large_Weights, mobilenet_v3_large

NAMES = ["Apple___Apple_scab", "Apple___Black_rot", "Apple___Cedar_apple_rust", "Apple___healthy", "Blueberry___healthy",
         "Cherry_(including_sour)___Powdery_mildew", "Cherry_(including_sour)___healthy", "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot",
         "Corn_(maize)___Common_rust_", "Corn_(maize)___Northern_Leaf_Blight", "Corn_(maize)___healthy", "Grape___Black_rot",
         "Grape___Esca_(Black_Measles)", "Grape___Leaf_blight_(Isariopsis_Leaf_Spot)", "Grape___healthy", "Orange___Haunglongbing_(Citrus_greening)",
         "Peach___Bacterial_spot", "Peach___healthy", "Pepper,_bell___Bacterial_spot", "Pepper,_bell___healthy", "Potato___Early_blight",
         "Potato___Late_blight", "Potato___healthy", "Raspberry___healthy", "Soybean___healthy", "Squash___Powdery_mildew",
         "Strawberry___Leaf_scorch", "Strawberry___healthy", "Tomato___Bacterial_spot", "Tomato___Early_blight", "Tomato___Late_blight",
         "Tomato___Leaf_Mold", "Tomato___Septoria_leaf_spot", "Tomato___Spider_mites Two-spotted_spider_mite", "Tomato___Target_Spot",
         "Tomato___Tomato_Yellow_Leaf_Curl_Virus", "Tomato___Tomato_mosaic_virus", "Tomato___healthy"]
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


class DS(Dataset):
    def __init__(self, df, tf):
        self.b, self.y, self.tf = df["image"].map(lambda d: d["bytes"]).values, df["label"].values, tf

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        return self.tf(Image.open(io.BytesIO(self.b[i])).convert("RGB")), int(self.y[i])


def evaluate(model, dl, dev):
    model.eval()
    P, Y = [], []
    with torch.no_grad(), torch.autocast(dev, enabled=dev == "cuda"):
        for x, y in dl:
            P.append(model(x.to(dev, non_blocking=True)).argmax(1).cpu())
            Y.append(y)
    return torch.cat(P).numpy(), torch.cat(Y).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("cihaz:", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "")

    rd = lambda pat: pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(a.data, pat)))], ignore_index=True)
    train, test = rd("train-*.parquet"), rd("test-*.parquet")
    perm = np.random.default_rng(0).permutation(len(train))
    nv = len(train) // 10
    val, train = train.iloc[perm[:nv]].reset_index(drop=True), train.iloc[perm[nv:]].reset_index(drop=True)
    print(f"eğitim {len(train)} | doğrulama {len(val)} | test {len(test)} | sınıf {len(NAMES)}")

    aug = T.Compose([T.RandomResizedCrop(224, scale=(0.6, 1)), T.RandomHorizontalFlip(), T.RandomVerticalFlip(), T.ColorJitter(0.3, 0.3, 0.3, 0.05),
                     T.ToTensor(), T.Normalize(MEAN, STD)])
    plain = T.Compose([T.Resize((224, 224)), T.ToTensor(), T.Normalize(MEAN, STD)])
    dl = lambda df, tf, sh: DataLoader(DS(df, tf), batch_size=128, shuffle=sh, num_workers=a.workers, persistent_workers=True, pin_memory=True)
    tr_dl, va_dl, te_dl = dl(train, aug, True), dl(val, plain, False), dl(test, plain, False)

    model = mobilenet_v3_large(weights=MobileNet_V3_Large_Weights.IMAGENET1K_V2)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(NAMES))
    model.to(dev)
    opt = torch.optim.AdamW(model.parameters(), 1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=a.epochs * len(tr_dl))
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    best, best_state = 0.0, None
    for ep in range(a.epochs):
        model.train()
        for x, y in tr_dl:
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            opt.zero_grad()
            with torch.autocast(dev, enabled=dev == "cuda"):
                loss = nn.functional.cross_entropy(model(x), y, label_smoothing=0.1)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
        p, y = evaluate(model, va_dl, dev)
        acc = float((p == y).mean())
        print(f"epoch {ep + 1}/{a.epochs}: kayıp {loss.item():.3f} | doğrulama doğruluğu {acc:.4f}", flush=True)
        if acc > best:
            best, best_state = acc, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    p, y = evaluate(model, te_dl, dev)
    per = {NAMES[c]: round(float((p[y == c] == c).mean()), 4) for c in range(len(NAMES))}
    healthy = np.array([n.endswith("healthy") for n in NAMES])
    res = {"test_accuracy": round(float((p == y).mean()), 4), "val_accuracy": round(best, 4), "test_n": int(len(y)),
           "healthy_vs_diseased_accuracy": round(float((healthy[p] == healthy[y]).mean()), 4),
           "worst_classes": dict(sorted(per.items(), key=lambda kv: kv[1])[:5]), "epochs": a.epochs,
           "dataset": "PlantVillage (BrandonFors mirror, CC0), 38 sınıf", "model": "MobileNetV3-Large (ImageNet önişleme, ince ayar)"}
    print(json.dumps(res, ensure_ascii=False, indent=1))

    model.eval().cpu()
    torch.onnx.export(model, torch.zeros(1, 3, 224, 224), os.path.join(a.out, "leaf_model.onnx"), input_names=["x"], output_names=["logits"],
                      dynamic_axes={"x": {0: "n"}, "logits": {0: "n"}}, opset_version=17, dynamo=False)
    json.dump(NAMES, open(os.path.join(a.out, "leaf_classes.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(res, open(os.path.join(a.out, "leaf_eval.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
