#!/usr/bin/env python3
"""Generate Vinor brand assets from master logo PNG (site, PWA, APK)."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "app" / "static" / "icons"
STATIC_DIR = ROOT / "app" / "static"
APK_RES = ROOT.parent / "apk" / "app" / "src" / "main" / "res"
DEFAULT_SOURCE = ICONS_DIR / "vinor-logo-source.png"

SIZES = [48, 72, 96, 128, 144, 192, 256, 384, 512]
APK_DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
MONOCHROME_SIZES = [48, 72, 96, 128, 144, 192, 256, 512]

BLACK = (0, 0, 0, 255)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_source(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def resize_icon(img: Image.Image, target: int) -> Image.Image:
    return img.resize((target, target), Image.LANCZOS)


def make_maskable(img: Image.Image, target: int, safe_ratio: float = 0.82) -> Image.Image:
    canvas = Image.new("RGBA", (target, target), BLACK)
    safe = max(1, int(target * safe_ratio))
    resized = img.resize((safe, safe), Image.LANCZOS)
    off = (target - safe) // 2
    canvas.alpha_composite(resized, (off, off))
    return canvas


def make_monochrome(img: Image.Image, target: int) -> Image.Image:
    base = resize_icon(img, target)
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
            if lum > 180:
                opx[x, y] = (255, 255, 255, min(255, a))
    return out


def write_web_icons(src: Image.Image) -> None:
    ensure_dir(ICONS_DIR)
    resize_icon(src, 1024).save(ICONS_DIR / "vinor-logo-source.png")

    for size in SIZES:
        resize_icon(src, size).save(ICONS_DIR / f"icon-{size}.png")
        make_maskable(src, size).save(ICONS_DIR / f"maskable-{size}.png")

    for size in MONOCHROME_SIZES:
        make_monochrome(src, size).save(ICONS_DIR / f"monochrome-{size}.png")

    resize_icon(src, 32).save(STATIC_DIR / "favicon-32x32.png")
    resize_icon(src, 256).save(
        STATIC_DIR / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"Web icons -> {ICONS_DIR}")


def write_apk_icons(src: Image.Image) -> None:
    if not APK_RES.is_dir():
        print("APK res not found, skip Android icons")
        return

    nodpi = APK_RES / "drawable-nodpi"
    ensure_dir(nodpi)
    resize_icon(src, 192).save(nodpi / "ic_pwa_logo.png")

    splash_xml = APK_RES / "drawable" / "vinor_splash_mark.xml"
    if splash_xml.parent.is_dir():
        splash_xml.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<bitmap xmlns:android="http://schemas.android.com/apk/res/android"
    android:src="@drawable/ic_pwa_logo"
    android:gravity="center" />
""",
            encoding="utf-8",
        )

    for folder, size in APK_DENSITIES.items():
        img = resize_icon(src, size)
        out_dir = APK_RES / f"mipmap-{folder}"
        ensure_dir(out_dir)
        img.save(out_dir / "ic_launcher.png")
        img.save(out_dir / "ic_launcher_round.png")
        print(f"APK {folder}: {size}px")

    print(f"APK icons -> {APK_RES}")


def write_apk_launcher_bg() -> None:
    path = APK_RES / "values" / "colors.xml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "#00000000" in text:
        path.write_text(
            text.replace(
                '<color name="ic_launcher_background">#00000000</color>',
                '<color name="ic_launcher_background">#000000</color>',
            ),
            encoding="utf-8",
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Vinor brand logo everywhere")
    p.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="Master logo PNG (square, rounded black tile + white V)",
    )
    p.add_argument(
        "--apk-only",
        action="store_true",
        help="Regenerate Android launcher/splash assets only",
    )
    args = p.parse_args()
    source = Path(args.source).resolve()
    if not source.is_file():
        raise SystemExit(f"Source not found: {source}")

    src = load_source(source)
    if args.apk_only:
        write_apk_icons(src)
        write_apk_launcher_bg()
    else:
        write_web_icons(src)
        write_apk_icons(src)
        write_apk_launcher_bg()
    print("Done.")


if __name__ == "__main__":
    main()
