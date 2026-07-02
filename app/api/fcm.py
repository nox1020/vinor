# -*- coding: utf-8 -*-
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session

from app.services.firebase_config import get_firebase_status, get_mobile_config_public
from app.services.fcm_tokens import register_token, unregister_token
from app.utils.apk_version import is_vinor_apk_request

api_fcm_bp = Blueprint("api_fcm", __name__, url_prefix="/api/fcm")


def _session_phone() -> str:
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(session.get("user_phone") or "")


@api_fcm_bp.get("/mobile-config")
def fcm_mobile_config():
    """پیکربندی Firebase برای APK — خودکار از google-services.json سرور."""
    mobile = get_mobile_config_public()
    if not mobile:
        status = get_firebase_status()
        return jsonify({
            "ok": False,
            "configured": False,
            "mobile_ready": bool(status.get("mobile_ready")),
            "send_ready": bool(status.get("send_ready")),
            "hint": "google-services.json را در apk/app/ یا instance/secrets/ سرور قرار دهید",
        }), 404
    return jsonify({
        "ok": True,
        "configured": True,
        "mobile": mobile,
    })


@api_fcm_bp.post("/register")
def fcm_register():
    """ثبت FCM token دستگاه — نیاز به سشن همکار."""
    if not is_vinor_apk_request(request):
        ua = (request.headers.get("User-Agent") or "")
        if "VinorApp/" not in ua:
            return jsonify({"ok": False, "error": "APK_ONLY"}), 403

    phone = _session_phone()
    if not phone or len(phone) != 11:
        return jsonify({"ok": False, "error": "LOGIN_REQUIRED"}), 401

    data = request.get_json(silent=True) or {}
    token = (data.get("token") or request.form.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "MISSING_TOKEN"}), 400

    platform = (data.get("platform") or "android").strip()
    app_version = (data.get("app_version") or request.headers.get("X-Vinor-App-Version") or "").strip()

    ok = register_token(phone, token, platform=platform, app_version=app_version)
    return jsonify({"ok": ok, "phone": phone})


@api_fcm_bp.post("/unregister")
def fcm_unregister():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "MISSING_TOKEN"}), 400
    unregister_token(token)
    return jsonify({"ok": True})


@api_fcm_bp.get("/status")
def fcm_status():
    status = get_firebase_status()
    phone = _session_phone()
    tagged = 0
    if phone:
        from app.services.fcm_tokens import tokens_for_phone
        tagged = len(tokens_for_phone(phone))
    return jsonify({
        "ok": True,
        "configured": bool(status.get("send_ready")),
        "mobile_ready": bool(status.get("mobile_ready")),
        "project_id": status.get("project_id"),
        "logged_in": bool(phone),
        "device_tokens": tagged,
    })
