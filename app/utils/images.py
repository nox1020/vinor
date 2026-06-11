"""
Image helper utilities for Vinor.

- Normalize upload URLs to absolute `/uploads/...` form
- Generate WebP variants (thumb/full) with cached files under `__variants__/`
- Compress originals on upload; serve compressed variants for display
"""
from __future__ import annotations

import imghdr
import os
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from werkzeug.utils import secure_filename

try:
    from PIL import Image, ImageOps  # type: ignore

    _PIL_OK = True
except Exception:  # pragma: no cover - fallback when Pillow is missing
    _PIL_OK = False

THUMB_WIDTH = 400
THUMB_QUALITY = 55
FULL_WIDTH = 1200
FULL_QUALITY = 75
ORIGINAL_MAX_SIDE = 2400
ORIGINAL_QUALITY = 90
AVATAR_DISPLAY_WIDTH = 256
AVATAR_DISPLAY_QUALITY = 72
DEFAULT_FMT = "WEBP"
ALLOWED_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp"})


def normalize_upload_url(value: Optional[str]) -> str:
    """
    Convert stored value to URL that can be requested from the client.
    - External URLs are returned as-is.
    - `uploads/...` or bare filenames are prefixed with `/uploads/`.
    """
    if not value:
        return ""
    s = str(value).strip()
    if "://" in s:
        return s
    if s.startswith("/uploads/"):
        return s
    if s.startswith("uploads/"):
        return "/uploads/" + s[8:]
    if s.startswith("/static/"):
        return s
    # date-based paths like 2025/08/...
    if s.startswith("/"):
        return "/uploads" + s
    return "/uploads/" + s


def build_variant_url(base_url: str, width: int, quality: int, fmt: str = "webp", variant: str = "") -> str:
    if not base_url:
        return ""
    params = f"w={width}&q={quality}&fmt={fmt}"
    if variant:
        params += f"&variant={variant}"
    joiner = "&" if "?" in base_url else "?"
    return f"{base_url}{joiner}{params}"


def _safe_open_image(src_path: str) -> Optional[Image.Image]:
    if not _PIL_OK:
        return None
    try:
        im = Image.open(src_path)
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        return im
    except Exception:
        return None


def _variant_paths(upload_root: str, rel_path: str, folder: str, fmt: str = "webp") -> Tuple[str, str]:
    rel_path = os.path.normpath(rel_path).replace("\\", "/")
    rel_no_ext, _ = os.path.splitext(rel_path)
    variant_rel = os.path.join("__variants__", folder, f"{rel_no_ext}.{fmt}").replace("\\", "/")
    variant_abs = os.path.join(upload_root, variant_rel)
    return variant_rel, variant_abs


def generate_variant(upload_root: str, rel_path: str, width: int, quality: int, folder: str, fmt: str = DEFAULT_FMT) -> Optional[str]:
    """
    Create (or return existing) variant file and return its *relative* path from upload root.
    """
    if not upload_root or not rel_path or not _PIL_OK or width <= 0:
        return None

    src_abs = os.path.join(upload_root, rel_path)
    if not os.path.isfile(src_abs):
        return None

    rel_variant, abs_variant = _variant_paths(upload_root, rel_path, folder, fmt.lower())
    os.makedirs(os.path.dirname(abs_variant), exist_ok=True)

    if os.path.isfile(abs_variant):
        return rel_variant

    im = _safe_open_image(src_abs)
    if im is None:
        return None

    try:
        im.thumbnail((width, width * 10_000), Image.LANCZOS)
        im.save(abs_variant, format=fmt.upper(), quality=quality, optimize=True)
        return rel_variant
    except Exception:
        try:
            # Clean up partial files on failure
            if os.path.isfile(abs_variant):
                os.remove(abs_variant)
        except Exception:
            pass
        return None


def generate_thumb_and_full(upload_root: str, rel_path: str) -> Dict[str, Optional[str]]:
    """
    Generate both thumb and full variants, returning their relative paths.
    Keys: thumb_rel, full_rel
    """
    return {
        "thumb_rel": generate_variant(upload_root, rel_path, THUMB_WIDTH, THUMB_QUALITY, "thumb", DEFAULT_FMT),
        "full_rel": generate_variant(upload_root, rel_path, FULL_WIDTH, FULL_QUALITY, "full", DEFAULT_FMT),
    }


def variant_headers_for_width(width: int) -> str:
    """
    Cache policy based on requested width.
    - thumb (<=450px): longer cache
    - full (>=1200px): medium cache
    - otherwise: default 1 day
    """
    if width <= 450:
        return "public, max-age=2592000, stale-while-revalidate=604800"  # 30d / 7d
    if width >= 1200:
        return "public, max-age=604800, stale-while-revalidate=604800"   # 7d / 7d
    return "public, max-age=86400, stale-while-revalidate=86400"


def prepare_variants_dict(url: str) -> Dict[str, str]:
    """
    Convenience helper to build thumb/full URLs with query parameters for a given base upload URL.
    """
    base = normalize_upload_url(url)
    return {
        "raw": base,
        "thumb": build_variant_url(base, THUMB_WIDTH, THUMB_QUALITY, "webp", "thumb") if base else "",
        "full": build_variant_url(base, FULL_WIDTH, FULL_QUALITY, "webp", "full") if base else "",
    }


def _guess_ext_from_bytes(raw: bytes) -> str:
    kind = imghdr.what(None, raw)
    if kind == "jpeg":
        return "jpg"
    return kind or "jpg"


def process_image_bytes(
    raw: bytes,
    ext_hint: str,
    *,
    max_side: int = ORIGINAL_MAX_SIDE,
    quality: int = ORIGINAL_QUALITY,
) -> Tuple[bytes, str]:
    """
    فشرده‌سازی تصویر اصلی برای ذخیره روی دیسک (کیفیت بالا برای دانلود همکار).
    GIF بدون تغییر باقی می‌ماند.
    """
    if (ext_hint or "").lower() == "gif" or not _PIL_OK:
        return raw, ext_hint

    try:
        with Image.open(BytesIO(raw)) as im:
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass

            if im.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")

            if max_side > 0:
                im.thumbnail((max_side, max_side), Image.LANCZOS)

            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            return buf.getvalue(), "jpg"
    except Exception:
        return raw, ext_hint


def generate_display_variants(upload_root: str, rel_path: str) -> Dict[str, Optional[str]]:
    """ساخت thumb/full وب‌پی برای نمایش — اصل فایل دست‌نخورده می‌ماند."""
    return generate_thumb_and_full(upload_root, rel_path)


def process_image_file_on_disk(upload_root: str, rel_path: str) -> Optional[str]:
    """
    فشرده‌سازی فایل موجود + ساخت واریانت‌های نمایش.
    rel_path نسبت به upload_root (مثلاً filename.jpg).
    مسیر ذخیره‌شده در JSON را برمی‌گرداند (uploads/...).
    """
    if not upload_root or not rel_path:
        return None

    abs_path = os.path.join(upload_root, rel_path)
    if not os.path.isfile(abs_path):
        return None

    try:
        with open(abs_path, "rb") as fh:
            raw = fh.read()
    except Exception:
        return None

    ext = os.path.splitext(rel_path)[1].lstrip(".") or _guess_ext_from_bytes(raw)
    processed, out_ext = process_image_bytes(raw, ext)

    base_name = os.path.splitext(os.path.basename(rel_path))[0]
    final_name = f"{base_name}.{out_ext.lower()}"
    final_abs = os.path.join(upload_root, final_name)

    try:
        with open(final_abs, "wb") as fh:
            fh.write(processed)
        if final_abs != abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                pass
    except Exception:
        return None

    try:
        generate_display_variants(upload_root, final_name)
    except Exception:
        pass

    return f"uploads/{final_name}"


def save_processed_form_image(file_storage, upload_folder: str) -> Optional[str]:
    """ذخیره تصویر فرم ادمین + فشرده‌سازی + واریانت نمایش."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    raw = file_storage.read()
    if not raw:
        return None

    ext = _guess_ext_from_bytes(raw)
    orig_ext = secure_filename(file_storage.filename).rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_IMAGE_EXTS and orig_ext in ALLOWED_IMAGE_EXTS:
        ext = orig_ext

    processed, out_ext = process_image_bytes(raw, ext)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    base = secure_filename(file_storage.filename)
    if base and "." in base:
        base = base.rsplit(".", 1)[0]
    if not base:
        base = "image"
    filename = f"{stamp}__{base}.{out_ext.lower()}"

    os.makedirs(upload_folder, exist_ok=True)
    abs_path = os.path.join(upload_folder, filename)
    try:
        with open(abs_path, "wb") as fh:
            fh.write(processed)
        generate_display_variants(upload_folder, filename)
    except Exception:
        return None

    return f"uploads/{filename}"


def display_thumb_url(url: Optional[str]) -> str:
    """WebP فشرده برای کارت‌ها و لیست — هرگز فایل اصلی."""
    base = normalize_upload_url(url)
    if not base:
        return ""
    return build_variant_url(base, THUMB_WIDTH, THUMB_QUALITY, "webp", "thumb")


def display_full_url(url: Optional[str]) -> str:
    """WebP با کیفیت متوسط برای گالری — نه فایل اصلی."""
    base = normalize_upload_url(url)
    if not base:
        return ""
    return build_variant_url(base, FULL_WIDTH, FULL_QUALITY, "webp", "full")


def display_avatar_url(url: Optional[str], version: Any = "") -> str:
    base = normalize_upload_url(url)
    if not base:
        return ""
    out = build_variant_url(base, AVATAR_DISPLAY_WIDTH, AVATAR_DISPLAY_QUALITY, "webp", "avatar")
    if version not in (None, ""):
        joiner = "&" if "?" in out else "?"
        out = f"{out}{joiner}v={version}"
    return out


def enrich_land_image_variants(land: Dict[str, Any]) -> Dict[str, Any]:
    """thumb/full برای نمایش — raw فقط برای دانلود."""
    if not isinstance(land, dict):
        return land
    imgs = land.get("images") or []
    if not imgs:
        return land

    item = land
    if not land.get("images_v2"):
        item = dict(land)
        item["images_v2"] = [prepare_variants_dict(str(i)) for i in imgs if i]

    first_raw = str(imgs[0]) if imgs else ""
    v2_list = item.get("images_v2") or []
    if v2_list and isinstance(v2_list[0], dict):
        cover = v2_list[0]
        item["image_thumb"] = cover.get("thumb") or display_thumb_url(first_raw)
        item["image_full"] = cover.get("full") or display_full_url(first_raw)
        item["image_raw"] = cover.get("raw") or normalize_upload_url(first_raw)
    else:
        item["image_thumb"] = display_thumb_url(first_raw)
        item["image_full"] = display_full_url(first_raw)
        item["image_raw"] = normalize_upload_url(first_raw)
    return item


def partner_card_image_url(land: Dict[str, Any]) -> str:
    """URL بهینه برای کارت همکار."""
    enriched = enrich_land_image_variants(land if isinstance(land, dict) else {})
    thumb = enriched.get("image_thumb") if isinstance(enriched, dict) else ""
    if thumb:
        return str(thumb)
    imgs = land.get("images") or [] if isinstance(land, dict) else []
    return display_thumb_url(str(imgs[0])) if imgs else ""

