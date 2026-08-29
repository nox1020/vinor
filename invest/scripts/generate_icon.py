"""Generate V+ app icon (black on white) for assets/app.ico and app.png."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
TEXT = "V+"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "segoeuib.ttf", "arial.ttf", "calibrib.ttf"):
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    font_size = max(7, int(size * 0.44))
    font = _load_font(font_size)
    bbox = draw.textbbox((0, 0), TEXT, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] - max(0, int(size * 0.03))
    draw.text((x, y), TEXT, fill=(0, 0, 0, 255), font=font)
    return img


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = render(256)
    master.save(
        ASSETS / "app.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    render(512).save(ASSETS / "app.png", format="PNG")
    print(f"Wrote {ASSETS / 'app.ico'} and {ASSETS / 'app.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
