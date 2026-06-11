"""Upload URL helpers for Vinor — بدون فشرده‌سازی یا واریانت."""
from __future__ import annotations

import imghdr
import os
from datetime import datetime
from typing import Any, Dict, Optional

from werkzeug.utils import secure_filename

ALLOWED_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp"})
_LEGACY_VARIANT_MARKERS = ("w=", "q=", "fmt=", "variant=")


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
    if s.startswith("/uploads/"):
        return s
    if s.startswith("uploads/"):
        return "/uploads/" + s[8:]
    if s.startswith("/static/"):
        return s
    if s.startswith("/"):
        return "/uploads" + s
    return "/uploads/" + s


def redirect_if_legacy_variant_request():
    """اگر کلاینت قدیمی ?w=&variant= فرستاد، به URL خام redirect کن."""
    from flask import redirect, request

    qs = request.query_string.decode("utf-8", errors="ignore") if request.query_string else ""
    if qs and any(m in qs for m in _LEGACY_VARIANT_MARKERS):
        return redirect(request.path, code=301)
    return None


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
    return normalize_upload_url(str(imgs[0])) if imgs else ""
