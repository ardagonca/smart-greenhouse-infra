"""HSV + LAB renk uzayında lezyon ayrıştırma (destekleyici kontrol). Yalnız numpy ve Pillow kullanır."""
import numpy as np
from PIL import Image


def _lab(rgb):
    c = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]]) / [0.9505, 1.0, 1.089]
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return 116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])


def lesion_mask(img: Image.Image, size=256):
    """(lezyon, bitki) boolean maskeleri. Bitki: sarı-kahve-yeşil tonlu doygun piksel; lezyon: bitkinin yeşilliğini yitirmiş kısmı."""
    im = img.convert("RGB").resize((size, size))
    hsv = np.asarray(im.convert("HSV"), float)
    h, s, v = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    _, a, b = _lab(np.asarray(im, float) / 255)
    plant = (h >= 10) & (h <= 170) & (s >= 0.15) & (v >= 0.12) & (b > 0)
    return plant & ((h < 50) | (a > -4)), plant


def lesion_ratio(img: Image.Image):
    """Bitki alanının lezyonlu oranı (0-1); karede yeterli bitki yoksa None."""
    les, plant = lesion_mask(img)
    return float(les.sum() / plant.sum()) if plant.mean() >= 0.05 else None


if __name__ == "__main__":
    green, brown, grey = ((60, 150, 50), (140, 90, 40), (128, 128, 128))
    im = Image.new("RGB", (256, 256), green)
    im.paste(brown, (0, 0, 256, 64))
    assert abs(lesion_ratio(im) - 0.25) < 0.02
    assert lesion_ratio(Image.new("RGB", (64, 64), green)) == 0
    assert lesion_ratio(Image.new("RGB", (64, 64), grey)) is None
    print("OK")
