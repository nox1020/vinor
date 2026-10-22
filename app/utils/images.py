"""Upload URL helpers for Vinor — بدون فشرده‌سازی یا واریانت."""
from __future__ import annotations

from app.utils import imgtype as imghdr
import os
from datetime import datetime
from typing import Any, Dict, Optional

from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp"})
_LEGACY_VARIANT_MARKERS = ("fmt=", "variant=")
_GALLERY_DISPLAY_MAX_W = 1280
_GALLERY_DISPLAY_QUALITY = 82


def strip_legacy_variant_query(url: str) -> str:
    """حذف پارامترهای قدیمی فشرده‌سازی از URL تصویر."""
    if not url or "?" not in url:
        return url
    base, qs = url.split("?", 1)
    if any(m in qs for m in _LEGACY_VARIANT_MARKERS):
        return base
    return url


def normalize_upload_url(value: Optional[str]) -> str:
    """تبدیل مسیر ذخیره‌شده به URL قابل درخواست (`/uploads/...`)."""
    if not value:
        return ""
    s = strip_legacy_variant_query(str(value).strip())
    if "://" in s:
        return s
    if s.startswith("/static/"):
        return s

    rel = s
    if rel.startswith("/uploads/"):
        rel = rel[len("/uploads/") :]
    elif rel.startswith("uploads/"):
        rel = rel[len("uploads/") :]
    elif rel.startswith("/"):
        rel = rel.lstrip("/")

    while rel.startswith("uploads/"):
        rel = rel[len("uploads/") :]

    return f"/uploads/{rel}" if rel else ""


def redirect_if_legacy_variant_request():
    """سازگاری با پارامترهای variant= و fmt= قدیمی — به فایل خام redirect."""
    from flask import redirect, request

    qs = request.query_string.decode("utf-8", errors="ignore") if request.query_string else ""
    if qs and any(m in qs for m in _LEGACY_VARIANT_MARKERS):
        return redirect(request.path, code=301)
    return None


def gallery_display_url(value: Optional[str], max_width: int = _GALLERY_DISPLAY_MAX_W, quality: int = _GALLERY_DISPLAY_QUALITY) -> str:
    """URL سبک‌تر برای نمایش گالری/کارت — resize سمت سرور با ?w=&q=."""
    url = normalize_upload_url(value)
    if not url or "://" in url:
        return url
    return f"{url}?w={int(max_width)}&q={int(quality)}"


def parse_resize_request_args(args) -> Optional[tuple[int, int]]:
    """خواندن ?w=&q= از query string — None اگر resize لازم نیست."""
    try:
        w = int(args.get("w") or 0)
    except (TypeError, ValueError):
        return None
    if w < 1:
        return None
    w = min(w, 2400)
    try:
        q = int(args.get("q") or _GALLERY_DISPLAY_QUALITY)
    except (TypeError, ValueError):
        q = _GALLERY_DISPLAY_QUALITY
    q = max(50, min(q, 95))
    return w, q


def resize_image_file(abs_path: str, max_width: int, quality: int) -> Optional[bytes]:
    """کوچک‌سازی تصویر برای سرو سریع‌تر در موبایل."""
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(abs_path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            if im.width > max_width:
                ratio = max_width / float(im.width)
                new_h = max(1, int(im.height * ratio))
                im = im.resize((max_width, new_h), Image.Resampling.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue()
    except Exception:
        return None


def make_resized_upload_response(abs_path: str, max_width: int, quality: int):
    """پاسخ Flask برای تصویر resize‌شده — None اگر ناموفق."""
    resized = resize_image_file(abs_path, max_width, quality)
    if not resized:
        return None
    from flask import make_response

    resp = make_response(resized)
    resp.headers["Content-Type"] = "image/jpeg"
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Vary"] = "Accept"
    return resp


def sanitize_land_media(land: Dict[str, Any]) -> Dict[str, Any]:
    """پاک‌سازی images_v2 و URLهای قدیمی با query فشرده‌سازی."""
    if not isinstance(land, dict):
        return land
    out = dict(land)
    out.pop("images_v2", None)
    for key in ("image_thumb", "image_full", "image_raw"):
        out.pop(key, None)
    imgs = out.get("images")
    if isinstance(imgs, list):
        cleaned = []
        for img in imgs:
            if not img:
                continue
            raw = strip_legacy_variant_query(str(img).strip())
            cleaned.append(raw)
        out["images"] = cleaned
    video = out.get("video")
    if video:
        out["video"] = strip_legacy_variant_query(str(video).strip())
    return out


def _guess_ext_from_bytes(raw: bytes) -> str:
    kind = imghdr.what(None, raw)
    if kind == "jpeg":
        return "jpg"
    return kind or "jpg"


def save_upload_image(file_storage, upload_folder: str) -> Optional[str]:
    """ذخیره تصویر آپلودشده بدون تغییر — مسیر `uploads/...`."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    raw = file_storage.read()
    if not raw:
        return None

    ext = _guess_ext_from_bytes(raw)
    orig_ext = (
        secure_filename(file_storage.filename).rsplit(".", 1)[-1].lower()
        if "." in file_storage.filename
        else ""
    )
    if ext not in ALLOWED_IMAGE_EXTS and orig_ext in ALLOWED_IMAGE_EXTS:
        ext = orig_ext

    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    base = secure_filename(file_storage.filename)
    if base and "." in base:
        base = base.rsplit(".", 1)[0]
    if not base:
        base = "image"
    filename = f"{stamp}__{base}.{ext.lower()}"

    os.makedirs(upload_folder, exist_ok=True)
    abs_path = os.path.join(upload_folder, filename)
    try:
        with open(abs_path, "wb") as fh:
            fh.write(raw)
    except Exception:
        return None

    return f"uploads/{filename}"


def display_avatar_url(value: Optional[str], version: Any = "") -> str:
    url = normalize_upload_url(value)
    if url and version not in (None, ""):
        sep = "&" if "?" in url else "?"
        try:
            url = f"{url}{sep}v={int(version)}"
        except (TypeError, ValueError):
            pass
    return url


def partner_card_image_url(land: Dict[str, Any]) -> str:
    if not isinstance(land, dict):
        return ""
    imgs = land.get("images") or []
    return gallery_display_url(str(imgs[0])) if imgs else ""
