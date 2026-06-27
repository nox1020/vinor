#!/usr/bin/env python3
"""Generate all Vinor brand assets from a single logo PNG (site, PWA, APK)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "app" / "static" / "icons"
STATIC_DIR = ROOT / "app" / "static"
APK_RES = ROOT.parent / "apk" / "app" / "src" / "main" / "res"

SIZES = [48, 72, 96, 128, 144, 192, 256, 384, 512]
APK_DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
MONOCHROME_SIZES = [48, 72, 96, 128, 144, 192, 256, 512]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_source(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def resize_contain(img: Image.Image, target: int) -> Image.Image:
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    src_w, src_h = img.size
    scale = min(target / src_w, target / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    off_x = (target - new_w) // 2
    off_y = (target - new_h) // 2
    canvas.paste(resized, (off_x, off_y), resized)
    return canvas


def make_maskable(img: Image.Image, target: int, safe_ratio: float = 0.78) -> Image.Image:
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    safe = int(target * safe_ratio)
    src_w, src_h = img.size
    scale = min(safe / src_w, safe / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    off_x = (target - new_w) // 2
    off_y = (target - new_h) // 2
    canvas.paste(resized, (off_x, off_y), resized)
    return canvas


def make_monochrome(img: Image.Image, target: int) -> Image.Image:
    """White silhouette for notification badges."""
    base = resize_contain(img, target)
    out = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    px = base.load()
    opx = out.load()
    w, h = base.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 16:
                continue
            lum = (r * 299 + g * 587 + b * 114) / 1000
            if lum < 18:
                continue
            opx[x, y] = (255, 255, 255, min(255, a))
    return out


def strip_near_black_bg(img: Image.Image, threshold: int = 22) -> Image.Image:
    """Make outer black background transparent for Android launcher."""
    out = img.copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r < threshold and g < threshold and b < threshold:
                px[x, y] = (r, g, b, 0)
    return out


def write_web_icons(src: Image.Image) -> None:
    ensure_dir(ICONS_DIR)
    master = resize_contain(src, 1024)
    master.save(ICONS_DIR / "vinor-logo-source.png")

    for size in SIZES:
        icon = resize_contain(src, size)
        icon.save(ICONS_DIR / f"icon-{size}.png")
        make_maskable(src, size).save(ICONS_DIR / f"maskable-{size}.png")

    for size in MONOCHROME_SIZES:
        make_monochrome(src, size).save(ICONS_DIR / f"monochrome-{size}.png")

    fav32 = resize_contain(src, 32)
    fav32.save(STATIC_DIR / "favicon-32x32.png")

    ico_img = resize_contain(src, 256)
    ico_img.save(
        STATIC_DIR / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"Web icons -> {ICONS_DIR}")


def write_apk_icons(src: Image.Image) -> None:
    if not APK_RES.is_dir():
        print("APK res not found, skip Android icons")
        return

    master = strip_near_black_bg(resize_contain(src, 192))
    nodpi = APK_RES / "drawable-nodpi"
    ensure_dir(nodpi)
    master.save(nodpi / "ic_pwa_logo.png")

    for folder, size in APK_DENSITIES.items():
        icon_path = ICONS_DIR / f"icon-{size}.png"
        if icon_path.is_file():
            img = strip_near_black_bg(Image.open(icon_path).convert("RGBA"))
        else:
            img = strip_near_black_bg(resize_contain(src, size))
        out_dir = APK_RES / f"mipmap-{folder}"
        ensure_dir(out_dir)
        img.save(out_dir / "ic_launcher.png")
        img.save(out_dir / "ic_launcher_round.png")
        print(f"APK {folder}: {size}px")

    print(f"APK icons -> {APK_RES}")


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Vinor brand logo everywhere")
    p.add_argument(
        "--source",
        required=True,
        help="Path to master logo PNG (square, >=512px recommended)",
    )
    args = p.parse_args()
    source = Path(args.source).resolve()
    if not source.is_file():
        raise SystemExit(f"Source not found: {source}")

    src = load_source(source)
    write_web_icons(src)
    write_apk_icons(src)
    print("Done.")


if __name__ == "__main__":
    main()
