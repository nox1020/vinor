#!/usr/bin/env python3
"""Generate Vinor brand assets — professional black/white V icon (site, PWA, APK)."""
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

# iOS-style squircle corner radius (~22.37% of edge)
TILE_RADIUS_RATIO = 0.2237
# Letter sits in optical center (slightly above geometric center)
V_LIFT_RATIO = 0.018


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _v_arm_polygons(size: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Bold geometric V — legs meet at a single apex."""
    s = float(size)
    pad_x = s * 0.205
    top = s * 0.255 - s * V_LIFT_RATIO
    apex_y = s * 0.755 - s * V_LIFT_RATIO
    mid = s * 0.5
    sw = s * 0.108

    left = [
        (pad_x, top),
        (pad_x + sw * 1.92, top),
        (mid, apex_y),
        (mid - sw, apex_y),
    ]
    right = [
        (s - pad_x, top),
        (s - pad_x - sw * 1.92, top),
        (mid, apex_y),
        (mid + sw, apex_y),
    ]
    return left, right


def _draw_tile(draw: ImageDraw.ImageDraw, size: int, inset: float = 0.0, fill: tuple[int, ...] = BLACK) -> None:
    margin = int(size * inset)
    radius = max(1, int((size - margin * 2) * TILE_RADIUS_RATIO))
    draw.rounded_rectangle(
        (margin, margin, size - 1 - margin, size - 1 - margin),
        radius=radius,
        fill=fill,
    )


def render_glyph(size: int, color: tuple[int, ...] = WHITE) -> Image.Image:
    """White V on transparent canvas."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    left, right = _v_arm_polygons(size)
    draw.polygon(left, fill=color)
    draw.polygon(right, fill=color)
    return img


def render_brand_icon(size: int, tile_inset: float = 0.0) -> Image.Image:
    """Squircle tile + white V."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    _draw_tile(draw, size, inset=tile_inset, fill=BLACK)
    glyph = render_glyph(size)
    img.alpha_composite(glyph)
    return img


def render_maskable(size: int, safe_ratio: float = 0.80) -> Image.Image:
    inset = (1.0 - safe_ratio) * 0.5
    return render_brand_icon(size, tile_inset=inset)


def render_monochrome(size: int) -> Image.Image:
    return render_glyph(size, WHITE)


def load_source(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def resize_icon(img: Image.Image, target: int) -> Image.Image:
    return img.resize((target, target), Image.Resampling.LANCZOS)


def write_web_icons(src: Image.Image) -> None:
    ensure_dir(ICONS_DIR)
    resize_icon(src, 1024).save(ICONS_DIR / "vinor-logo-source.png")

    for size in SIZES:
        resize_icon(src, size).save(ICONS_DIR / f"icon-{size}.png")
        render_maskable(size).save(ICONS_DIR / f"maskable-{size}.png")

    for size in MONOCHROME_SIZES:
        render_monochrome(size).save(ICONS_DIR / f"monochrome-{size}.png")

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
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="120dp"
    android:height="120dp"
    android:viewportWidth="120"
    android:viewportHeight="120">
    <path
        android:fillColor="#000000"
        android:pathData="M8,26 C8,14 14,8 26,8 H94 C106,8 112,14 112,26 V94 C112,106 106,112 94,112 H26 C14,112 8,106 8,94 Z" />
    <path
        android:fillColor="#FFFFFF"
        android:pathData="M30,34 L44,34 L60,88 L76,34 L90,34 L68,90 L52,90 Z" />
</vector>
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


def build_master(size: int = 1024) -> Image.Image:
    return render_brand_icon(size)


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Vinor brand logo everywhere")
    p.add_argument(
        "--source",
        help="Optional raster override (default: programmatic redesign)",
    )
    p.add_argument(
        "--apk-only",
        action="store_true",
        help="Regenerate Android launcher/splash assets only",
    )
    args = p.parse_args()

    if args.source:
        source = Path(args.source).resolve()
        if not source.is_file():
            raise SystemExit(f"Source not found: {source}")
        src = load_source(source)
    else:
        src = build_master(1024)

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
