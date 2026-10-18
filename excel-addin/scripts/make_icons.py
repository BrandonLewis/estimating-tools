"""Draw the generic Estimate Navigator icons (16-300 px PNG) with Pillow.

Run once and commit the output; rerun only when the generic mark changes:
    python excel-addin/scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "brand" / "assets"
ACCENT, WHITE = (0x24, 0x50, 0x7A, 255), (255, 255, 255, 255)
SIZES = (16, 32, 64, 80, 128, 300)


def icon(size: int) -> Image.Image:
    s = 8                                   # draw large, then downsample for clean edges
    big = size * s
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=ACCENT)
    c, r, w = big / 2, big * 0.31, max(int(big * 0.065), 1)
    d.ellipse((c - r, c - r, c + r, c + r), outline=WHITE, width=w)
    k = big / 64
    d.polygon([(41 * k, 23 * k), (35.5 * k, 36.5 * k), (22 * k, 42 * k), (27.5 * k, 28.5 * k)], fill=WHITE)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for n in SIZES:
        icon(n).save(OUT / f"icon-{n}.png")
        print("wrote", OUT / f"icon-{n}.png")
