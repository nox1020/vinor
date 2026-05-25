from __future__ import annotations

from flask import jsonify, redirect, request, url_for

from . import ai_bp
from .services import ai_config, generate_reply


@ai_bp.get("/", endpoint="index")
def index():
    """مسیر قدیمی — هدایت به صفحه داخلی پرتال همکار."""
    return redirect(url_for("express_partner.ai"))


@ai_bp.get("/health", endpoint="health")
def health():
    cfg = ai_config()
    return jsonify({"ok": True, "service": "vinor-ai", **cfg})


@ai_bp.post("/api/chat", endpoint="chat")
def chat():
    """سازگاری با مسیر قدیمی — در صورت لاگین، همان منطق پرتال همکار."""
    from flask import session

    phone = (session.get("user_phone") or "").strip()
    if phone:
        from app.ai.chat_store import append_exchange, history_for_api

        data = request.get_json(silent=True) or {}
        message = (data.get("message") or request.form.get("message") or "").strip()
        history = history_for_api(phone)
        result = generate_reply(message, history=history, phone=phone)
        if result.get("ok"):
            append_exchange(
                phone,
                message,
                result.get("reply") or "",
                assistant_land_codes=result.get("land_codes"),
            )
        if not result.get("ok"):
            return jsonify(result), 400
        return jsonify(result)

    return jsonify({"ok": False, "error": "لطفاً از طریق پرتال همکار وارد شوید."}), 401
