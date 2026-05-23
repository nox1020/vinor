from __future__ import annotations

from flask import jsonify, render_template, request, url_for

from . import ai_bp
from .services import ai_config, generate_reply


@ai_bp.get("/", endpoint="index")
def index():
    return render_template(
        "index.html",
        ai_cfg=ai_config(),
        chat_api_url=url_for("ai.chat"),
    )


@ai_bp.get("/health", endpoint="health")
def health():
    cfg = ai_config()
    return jsonify({"ok": True, "service": "vinor-ai", **cfg})


@ai_bp.post("/api/chat", endpoint="chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or request.form.get("message") or "").strip()
    history = data.get("history") if isinstance(data.get("history"), list) else None
    result = generate_reply(message, history=history)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)
