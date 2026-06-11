# -*- coding: utf-8 -*-
"""
Uploads API for Vinor (vinor.ir)
- Endpoint: POST /api/uploads/images  → برمی‌گرداند: {"success": true, "id": "...", "url": "..."}
- Static serve: GET  /uploads/<path:filename>
- هماهنگ با CONFIG: app.config["UPLOAD_FOLDER"]
"""
from __future__ import annotations
import os
import uuid
import imghdr
from datetime import datetime
from typing import Tuple
from flask import Blueprint, current_app, request, jsonify, send_from_directory
from app.utils.storage import legacy_dir
from app.utils.images import (
    generate_thumb_and_full,
    process_image_bytes,
    THUMB_WIDTH,
    THUMB_QUALITY,
    FULL_WIDTH,
    FULL_QUALITY,
    variant_headers_for_width,
)

uploads_bp = Blueprint("uploads", __name__)

# محدودیت‌ها
ALLOWED_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_SIZE_MB = 12  # با فرانت هماهنگ

def _ensure_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _guess_ext_from_bytes(b: bytes) -> str:
    kind = imghdr.what(None, b)
    if kind == "jpeg":
        return "jpg"
    return kind or "jpg"

def _validate_file(fieldname: str = "file") -> Tuple[bytes, str]:
    """
    برمی‌گرداند: (file_bytes, ext) — در صورت خطا raise Exception
    """
    if fieldname not in request.files:
        raise ValueError("فایلی ارسال نشده است.")
    f = request.files[fieldname]
    if not f or f.filename == "":
        raise ValueError("نام فایل نامعتبر است.")

    raw = f.read()
    if not raw:
        raise ValueError("فایل خالی است.")

    # محدودیت حجم
    if len(raw) > MAX_SIZE_MB * 1024 * 1024:
        raise ValueError(f"حجم بیش از {MAX_SIZE_MB} مگابایت است.")

    ext = _guess_ext_from_bytes(raw)
    if ext not in ALLOWED_EXTS:
        # اگر حدس اشتباه بود، از پسوند امن‌شده استفاده کنیم
        original_ext = secure_filename(f.filename).rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if original_ext in ALLOWED_EXTS:
            ext = original_ext
        else:
            raise ValueError("فقط تصاویر مجاز هستند.")

    return raw, ext


@uploads_bp.post("/api/uploads/images")
def upload_image():
    """
    ذخیرهٔ تصویر و برگرداندن شناسه
    پاسخ استاندارد:
    {
      "success": true,
      "id": "2025/08/31/4d2f...e7.jpg",
      "url": "/uploads/2025/08/31/4d2f...e7.jpg"
    }
    """
    try:
        raw, ext = _validate_file("file")
        raw, out_ext = process_image_bytes(raw, ext)

        base_dir = current_app.config.get("UPLOAD_FOLDER")
        if not base_dir:
            return jsonify({"success": False, "error": "UPLOAD_FOLDER تنظیم نشده"}), 500

        # ساخت مسیر تاریخ‌محور: /YYYY/MM/DD/
        today = datetime.utcnow()
        rel_dir = os.path.join(str(today.year), f"{today.month:02d}", f"{today.day:02d}")
        abs_dir = os.path.join(base_dir, rel_dir)
        _ensure_folder(abs_dir)

        # نام یکتا
        uid = uuid.uuid4().hex
        filename = f"{uid}.{(out_ext or ext).lower()}"
        abs_path = os.path.join(abs_dir, filename)

        # نوشتن فایل
        with open(abs_path, "wb") as out:
            out.write(raw)

        rel_path = os.path.join(rel_dir, filename).replace("\\", "/")
        url = f"/uploads/{rel_path}"

        # Pre-generate thumb/full variants for faster first paint
        try:
            variants = generate_thumb_and_full(base_dir, rel_path)
            url_thumb = f"/uploads/{variants['thumb_rel']}" if variants.get("thumb_rel") else ""
            url_full = f"/uploads/{variants['full_rel']}" if variants.get("full_rel") else ""
        except Exception:
            url_thumb = ""
            url_full = ""

        return jsonify({
            "success": True,
            "ok": True,
            "id": rel_path,
            "url": url,
            "url_thumb": url_thumb,
            "url_full": url_full,
            "meta": {
                "thumb": {"width": THUMB_WIDTH, "quality": THUMB_QUALITY, "format": "webp"},
                "full": {"width": FULL_WIDTH, "quality": FULL_QUALITY, "format": "webp"},
            },
        })
    except Exception as e:
        current_app.logger.exception("Upload failed")
        return jsonify({"success": False, "ok": False, "error": str(e)}), 400

@uploads_bp.get("/uploads/<path:filename>")
def serve_uploads(filename: str):
    """
    سرو فایل‌های آپلود شده از UPLOAD_FOLDER.
    پشتیبانی از پارامترهای واریانت:
      - w: عرض هدف
      - q: کیفیت
      - fmt: فرمت خروجی (webp)
      - variant: thumb|full (صرفاً برای دیباگ)
    """
    def _try_variant(root: str, safe_name: str):
        from app.utils.images import generate_variant, resolve_variant_generation

        try:
            width = int(request.args.get("w", 0) or 0)
            quality = int(request.args.get("q", 0) or 0) or 80
            fmt = (request.args.get("fmt") or "webp").lower()
            variant_kind = (request.args.get("variant") or "").strip()
        except Exception:
            width = 0
            quality = 80
            fmt = "webp"
            variant_kind = ""

        gen_w, gen_q, folder = resolve_variant_generation(width, quality, variant_kind)
        if gen_w <= 0 or not folder:
            return None

        variant_abs = None
        try:
            variant_abs = generate_variant_path(root, safe_name, gen_w, gen_q, folder, fmt)
        except Exception:
            variant_abs = None

        if not variant_abs:
            return None

        variant_dir, variant_file = os.path.split(variant_abs)
        resp = send_from_directory(variant_dir, variant_file)
        resp.headers["Cache-Control"] = variant_headers_for_width(gen_w)
        resp.headers["Content-Type"] = "image/webp"
        return resp

    def generate_variant_path(root: str, safe_name: str, width: int, quality: int, folder: str, fmt: str):
        from app.utils.images import generate_variant

        variant_rel = generate_variant(root, safe_name, width, quality, folder, fmt.upper())
        if not variant_rel:
            return None
        abs_path = os.path.join(root, variant_rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        return abs_path

    base_dir = current_app.config.get("UPLOAD_FOLDER")
    if base_dir:
        safe_path = os.path.normpath(filename).replace("\\", "/")
        try:
            # در صورت درخواست واریانت (w/q) سعی کن از کش بسازی/بخوانی
            variant_resp = _try_variant(base_dir, safe_path)
            if variant_resp:
                return variant_resp
        except Exception:
            current_app.logger.debug("Variant generation skipped", exc_info=True)
        try:
            resp = send_from_directory(base_dir, safe_path)
            resp.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=86400"
            return resp
        except Exception:
            pass

    # فالبک به مسیر قدیمی کنار کد
    legacy_base = os.path.join(legacy_dir(current_app), "uploads")
    safe_path = os.path.normpath(filename).replace("\\", "/")
    return send_from_directory(legacy_base, safe_path)
