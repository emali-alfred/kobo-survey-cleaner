"""Draw the Survey Cleaner logo and export every size the project needs.

A clipboard checklist (two answers checked, one flagged) with a sparkle:
survey data, checked and cleaned.

Run:  pip install pillow && python assets/make_logo.py
Outputs (in assets/ unless noted):
  icon-512-playstore.png     512x512 full-bleed square (Google Play app icon spec)
  icon-1024.png              1024x1024 rounded, for the README / websites
  icon.ico                   Windows icon, 16-256 px (desktop shortcut)
  feature-graphic-1024x500.png   Google Play feature graphic
  ../surveyclean/assets/icon.png and icon.ico   used by the desktop window
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
PKG = HERE.parent / "surveyclean" / "assets"

SS = 4  # supersampling factor for smooth edges
TEAL_LIGHT = (24, 170, 128)
TEAL_DARK = (10, 82, 104)
INK = (12, 74, 92)
CHECK = (20, 150, 112)
FLAG = (245, 160, 36)
BAR = (208, 228, 226)
SPARK = (255, 209, 102)
WHITE = (255, 255, 255)


def gradient(size: int | tuple[int, int]) -> Image.Image:
    w, h = (size, size) if isinstance(size, int) else size
    # diagonal gradient, top-left light to bottom-right dark
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TEAL_LIGHT, TEAL_DARK))
    return small.resize((w, h), Image.BICUBIC)


def star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for i in range(8):
        ang = -math.pi / 2 + i * math.pi / 4
        rad = r if i % 2 == 0 else r * 0.3
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def draw_mark(size: int, rounded: bool, background: bool = True) -> Image.Image:
    """The icon at `size` px. Geometry is designed on a 1024 grid.
    background=False draws only the clipboard and sparkles (transparent around them)."""
    S = size * SS
    u = S / 1024  # one design unit

    def b(*v):  # scale a box / point
        return [x * u for x in v]

    img = gradient(S).convert("RGBA") if background else Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # soft shadow under the clipboard
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(b(282, 262, 762, 862), radius=64 * u, fill=(0, 30, 40, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28 * u)))

    d = ImageDraw.Draw(img)
    # clipboard board
    d.rounded_rectangle(b(262, 232, 742, 842), radius=64 * u, fill=WHITE)
    # clip
    d.rounded_rectangle(b(392, 186, 612, 292), radius=34 * u, fill=INK)
    d.ellipse(b(482, 206, 522, 246), fill=TEAL_LIGHT)

    # checklist rows: checked, checked, flagged
    rows = [410, 548, 686]
    for i, y in enumerate(rows):
        cx, r = 362, 44
        color = FLAG if i == 2 else CHECK
        d.ellipse(b(cx - r, y - r, cx + r, y + r), fill=color)
        if i < 2:
            d.line(b(cx - 22, y + 1, cx - 5, y + 19, cx + 24, y - 16), fill=WHITE,
                   width=round(15 * u), joint="curve")
        else:  # exclamation mark: flagged for checking
            d.rounded_rectangle(b(cx - 7, y - 27, cx + 7, y + 7), radius=7 * u, fill=WHITE)
            d.ellipse(b(cx - 8, y + 14, cx + 8, y + 30), fill=WHITE)
        width = [270, 220, 250][i]
        d.rounded_rectangle(b(436, y - 18, 436 + width, y + 18), radius=18 * u, fill=BAR)

    # sparkle: the data is clean
    star(d, 772 * u, 262 * u, 118 * u, SPARK)
    star(d, 862 * u, 392 * u, 50 * u, SPARK)
    star(d, 668 * u, 150 * u, 34 * u, (255, 232, 170))

    if rounded:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.22, fill=255)
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    for p in [Path("C:/Windows/Fonts") / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def feature_graphic() -> Image.Image:
    W, H = 1024, 500
    img = gradient((W, H)).convert("RGBA")
    icon = draw_mark(300, rounded=True)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([78, 112, 378, 412], radius=66, fill=(0, 20, 30, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    img.alpha_composite(icon, (70, 100))
    d = ImageDraw.Draw(img)
    d.text((420, 150), "Survey Cleaner", font=font(76, bold=True), fill=WHITE)
    d.text((424, 252), "Clean KoboToolbox & ODK data", font=font(36), fill=(225, 245, 238))
    d.text((424, 300), "and get a data quality report", font=font(36), fill=(225, 245, 238))
    return img.convert("RGB")


def main() -> None:
    PKG.mkdir(parents=True, exist_ok=True)
    draw_mark(512, rounded=False).convert("RGB").save(HERE / "icon-512-playstore.png", optimize=True)
    big = draw_mark(1024, rounded=True)
    big.save(HERE / "icon-1024.png", optimize=True)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(HERE / "icon.ico", sizes=[(s, s) for s in ico_sizes])
    big.save(PKG / "icon.ico", sizes=[(s, s) for s in ico_sizes])
    draw_mark(256, rounded=True).save(PKG / "icon.png", optimize=True)
    feature_graphic().save(HERE / "feature-graphic-1024x500.png", optimize=True)

    # Web app / Android icons
    web = HERE.parent / "web" / "icons"
    web.mkdir(parents=True, exist_ok=True)
    draw_mark(192, rounded=True).save(web / "icon-192.png", optimize=True)
    draw_mark(512, rounded=True).save(web / "icon-512.png", optimize=True)
    # Maskable: Android crops icons to circles/squircles, so keep the mark in the
    # central safe zone (80%) on a full-bleed background.
    maskable = gradient(512).convert("RGBA")
    maskable.alpha_composite(draw_mark(410, rounded=False, background=False), (51, 51))
    maskable.convert("RGB").save(web / "maskable-512.png", optimize=True)
    print("Logo files written to", HERE, PKG, "and", web)


if __name__ == "__main__":
    main()
