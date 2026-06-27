#!/usr/bin/env python3
"""Generate Vinor brand assets (X-style bold V) for site, PWA, and APK."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "app" / "static" / "icons"
STATIC_DIR = ROOT / "app" / "static"
APK_RES = ROOT.parent / "apk" / "app" / "src" / "main" / "res"

SIZES = [48, 72, 96, 128, 144, 192, 256, 384, 512]
APK_DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
MONOCHROME_SIZES = [48, 72, 96, 128, 144, 192, 256, 512]

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _v_polygons(size: int, inset: float = 0.20, gap: float = 0.055) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Geometric bold V (two strokes) sized like the X app icon."""
    s = float(size)
    pad = s * inset
    gap_half = s * gap * 0.5
    mid = s * 0.5
    bottom = s - pad
    top = pad
    stroke = s * 0.145

    left = [
        (pad, top),
        (pad + stroke, top),
        (mid - gap_half, bottom),
        (mid - gap_half - stroke, bottom),
    ]
    right = [
        (s - pad, top),
        (s - pad - stroke, top),
        (mid + gap_half, bottom),
        (mid + gap_half + stroke, bottom),
    ]
    return left, right


def render_x_glyph(size: int, color: tuple[int, int, int, int] = WHITE) -> Image.Image:
    """White V on transparent canvas (adaptive-icon foreground / splash mark)."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    left, right = _v_polygons(size)
    draw.polygon(left, fill=color)
    draw.polygon(right, fill=color)
    return img


def render_x_icon(size: int) -> Image.Image:
    """Black square + white V (launcher / PWA icon like X)."""
    img = Image.new("RGBA", (size, size), BLACK)
    glyph = render_x_glyph(size)
    img.alpha_composite(glyph)
    return img


def render_x_maskable(size: int, safe_ratio: float = 0.78) -> Image.Image:
    safe = max(1, int(size * safe_ratio))
    glyph = render_x_glyph(safe)
    canvas = Image.new("RGBA", (size, size), BLACK)
    off = (size - safe) // 2
    canvas.alpha_composite(glyph, (off, off))
    return canvas


def render_monochrome(size: int) -> Image.Image:
    return render_x_glyph(size, WHITE)


def write_web_icons() -> None:
    ensure_dir(ICONS_DIR)
    render_x_icon(1024).save(ICONS_DIR / "vinor-logo-source.png")

    for size in SIZES:
        render_x_icon(size).save(ICONS_DIR / f"icon-{size}.png")
        render_x_maskable(size).save(ICONS_DIR / f"maskable-{size}.png")

    for size in MONOCHROME_SIZES:
        render_monochrome(size).save(ICONS_DIR / f"monochrome-{size}.png")

    render_x_icon(32).save(STATIC_DIR / "favicon-32x32.png")
    render_x_icon(256).save(
        STATIC_DIR / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"Web icons -> {ICONS_DIR}")


def write_apk_icons() -> None:
    if not APK_RES.is_dir():
        print("APK res not found, skip Android icons")
        return

    nodpi = APK_RES / "drawable-nodpi"
    ensure_dir(nodpi)
    render_x_glyph(192).save(nodpi / "ic_pwa_logo.png")

    for folder, size in APK_DENSITIES.items():
        img = render_x_icon(size)
        out_dir = APK_RES / f"mipmap-{folder}"
        ensure_dir(out_dir)
        img.save(out_dir / "ic_launcher.png")
        img.save(out_dir / "ic_launcher_round.png")
        print(f"APK {folder}: {size}px")

    print(f"APK icons -> {APK_RES}")


def write_apk_splash_vector() -> None:
    path = APK_RES / "drawable" / "vinor_splash_mark.xml"
    if not path.parent.is_dir():
        return
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="120dp"
    android:height="120dp"
    android:viewportWidth="120"
    android:viewportHeight="120">
    <path
        android:fillColor="#FFFFFF"
        android:pathData="M24,28 L42,28 L60,88 L78,28 L96,28 L72,100 L48,100 Z" />
</vector>
""",
        encoding="utf-8",
    )
    print(f"APK splash vector -> {path}")


def write_apk_launcher_bg() -> None:
    path = APK_RES / "values" / "colors.xml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    updated = text.replace(
        '<color name="ic_launcher_background">#00000000</color>',
        '<color name="ic_launcher_background">#000000</color>',
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        print(f"APK launcher bg -> {path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Vinor X-style V logo everywhere")
    p.add_argument(
        "--apk-only",
        action="store_true",
        help="Regenerate Android launcher/splash assets only",
    )
    args = p.parse_args()

    if args.apk_only:
        write_apk_icons()
        write_apk_splash_vector()
        write_apk_launcher_bg()
    else:
        write_web_icons()
        write_apk_icons()
        write_apk_splash_vector()
        write_apk_launcher_bg()
    print("Done.")


if __name__ == "__main__":
    main()
