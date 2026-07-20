"""Generate the application icon (assets/icon.ico + icon.png).

Draws a rounded-square badge with the brand purple->pink gradient and a
download arrow, then exports a multi-resolution .ico plus a .png.

Run:  python tools/make_icon.py
Requires: pillow  (pip install pillow)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw


SIZE = 512
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets")


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def build() -> Image.Image:
    # diagonal gradient background (purple -> pink)
    c0, c1 = (168, 116, 255), (246, 95, 166)
    grad = Image.new("RGB", (SIZE, SIZE))
    px = grad.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * SIZE)
            px[x, y] = _lerp(c0, c1, t)

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    img.paste(grad, (0, 0), _rounded_mask(SIZE, radius=int(SIZE * 0.22)))

    # download arrow (white, centered)
    d = ImageDraw.Draw(img)
    cx = SIZE // 2
    stem_w = int(SIZE * 0.10)
    top = int(SIZE * 0.20)
    stem_bottom = int(SIZE * 0.56)
    d.rectangle([cx - stem_w // 2, top, cx + stem_w // 2, stem_bottom],
                fill=(255, 255, 255, 255))
    head = int(SIZE * 0.20)
    d.polygon([(cx - head, stem_bottom - int(SIZE * 0.04)),
               (cx + head, stem_bottom - int(SIZE * 0.04)),
               (cx, stem_bottom + int(SIZE * 0.18))],
              fill=(255, 255, 255, 255))
    # base tray
    tray_y = int(SIZE * 0.80)
    tw = int(SIZE * 0.30)
    bar = int(SIZE * 0.055)
    d.rounded_rectangle([cx - tw, tray_y, cx + tw, tray_y + bar],
                        radius=bar // 2, fill=(255, 255, 255, 255))
    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    img = build()
    png_path = os.path.join(ASSETS, "icon.png")
    ico_path = os.path.join(ASSETS, "icon.ico")
    img.save(png_path)
    img.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    print(f"wrote {png_path} and {ico_path}")


if __name__ == "__main__":
    main()
