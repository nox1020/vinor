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
from app.utils import imgtype as imghdr
from datetime import datetime
from typing import Tuple
from flask import Blueprint, current_app, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from app.utils.storage import legacy_dir

uploads_bp = Blueprint("uploads", __name__)

ALLOWED_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_SIZE_MB = 12


def _ensure_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _guess_ext_from_bytes(b: bytes) -> str:
    kind = imghdr.what(None, b)
    if kind == "jpeg":
        return "jpg"
    return kind or "jpg"


def _validate_file(fieldname: str = "file") -> Tuple[bytes, str]:
    if fieldname not in request.files:
        raise ValueError("فایلی ارسال نشده است.")
    f = request.files[fieldname]
    if not f or f.filename == "":
        raise ValueError("نام فایل نامعتبر است.")

    raw = f.read()
    if not raw:
        raise ValueError("فایل خالی است.")

    if len(raw) > MAX_SIZE_MB * 1024 * 1024:
        raise ValueError(f"حجم بیش از {MAX_SIZE_MB} مگابایت است.")

    ext = _guess_ext_from_bytes(raw)
    if ext not in ALLOWED_EXTS:
        original_ext = secure_filename(f.filename).rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if original_ext in ALLOWED_EXTS:
            ext = original_ext
        else:
            raise ValueError("فقط تصاویر مجاز هستند.")

    return raw, ext


@uploads_bp.post("/api/uploads/images")
def upload_image():
    try:
        raw, ext = _validate_file("file")

        base_dir = current_app.config.get("UPLOAD_FOLDER")
        if not base_dir:
            return jsonify({"success": False, "error": "UPLOAD_FOLDER تنظیم نشده"}), 500

        today = datetime.utcnow()
        rel_dir = os.path.join(str(today.year), f"{today.month:02d}", f"{today.day:02d}")
        abs_dir = os.path.join(base_dir, rel_dir)
        _ensure_folder(abs_dir)

        uid = uuid.uuid4().hex
        filename = f"{uid}.{ext.lower()}"
        abs_path = os.path.join(abs_dir, filename)

        with open(abs_path, "wb") as out:
            out.write(raw)

        rel_path = os.path.join(rel_dir, filename).replace("\\", "/")
        url = f"/uploads/{rel_path}"

        return jsonify({
            "success": True,
            "ok": True,
            "id": rel_path,
            "url": url,
        })
    except Exception as e:
        current_app.logger.exception("Upload failed")
        return jsonify({"success": False, "ok": False, "error": str(e)}), 400


@uploads_bp.get("/uploads/<path:filename>")
def serve_uploads(filename: str):
    """سرو فایل‌های آپلود — با پشتیبانی resize اختیاری (?w=&q=)."""
    from app.utils.images import (
        make_resized_upload_response,
        parse_resize_request_args,
        redirect_if_legacy_variant_request,
    )

    legacy_redirect = redirect_if_legacy_variant_request()
    if legacy_redirect is not None:
        return legacy_redirect

    resize = parse_resize_request_args(request.args)
    cache_hdr = "public, max-age=86400, stale-while-revalidate=86400"
    base_dir = current_app.config.get("UPLOAD_FOLDER")
    safe_path = os.path.normpath(filename).replace("\\", "/")
    if safe_path.startswith("partner/avatars/"):
        cache_hdr = "public, max-age=31536000, immutable"

    abs_path = None
    if base_dir:
        candidate = os.path.join(base_dir, safe_path)
        if os.path.isfile(candidate):
            abs_path = candidate

    if abs_path is None:
        legacy_base = os.path.join(legacy_dir(current_app), "uploads")
        candidate = os.path.join(legacy_base, safe_path)
        if os.path.isfile(candidate):
            abs_path = candidate

    if resize and abs_path:
        max_w, quality = resize
        resized_resp = make_resized_upload_response(abs_path, max_w, quality)
        if resized_resp is not None:
            return resized_resp

    if base_dir:
        try:
            resp = send_from_directory(base_dir, safe_path)
            resp.headers["Cache-Control"] = cache_hdr
            return resp
        except Exception:
            pass

    legacy_base = os.path.join(legacy_dir(current_app), "uploads")
    resp = send_from_directory(legacy_base, safe_path)
    resp.headers["Cache-Control"] = cache_hdr
    return resp
