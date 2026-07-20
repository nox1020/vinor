# -*- coding: utf-8 -*-
"""چت عملیات ادمین — /admin/ops/* و خانهٔ /admin."""
from __future__ import annotations

from typing import Any

from flask import jsonify, render_template, request, session, url_for

from .blueprint import admin_bp
from .routes import ADMIN_LOGIN_OTP_PHONE, login_required


def _admin_ops_user_key() -> str:
    phone = (
        session.get("admin_phone")
        or session.get("username")
        or ADMIN_LOGIN_OTP_PHONE
        or "admin"
    )
    phone = str(phone).strip() or "admin"
    if phone.startswith("admin_"):
        return phone
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) >= 11:
        return f"admin_{digits[-11:]}"
    safe = "".join(c for c in phone if c.isalnum() or c in "_-")[:40]
    return f"admin_{safe or 'ops'}"


def _ops_chat_context() -> dict[str, Any]:
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import (
        ensure_active_thread,
        messages_for_ui,
        threads_for_ui,
    )
    from app.ai.welcome import ensure_vinor_opens_chat, opening_text

    user_key = _admin_ops_user_key()
    opening = opening_text(audience=AUDIENCE_ADMIN)
    try:
        ensure_active_thread(user_key, audience=AUDIENCE_ADMIN)
        ensure_vinor_opens_chat(
            user_key,
            audience=AUDIENCE_ADMIN,
            text=opening,
        )
        active_thread_id = ensure_active_thread(user_key, audience=AUDIENCE_ADMIN)
        chat_messages = messages_for_ui(
            user_key, active_thread_id, audience=AUDIENCE_ADMIN
        )
        chat_threads = threads_for_ui(user_key, audience=AUDIENCE_ADMIN)
    except Exception:
        active_thread_id = ""
        chat_messages = []
        chat_threads = []

    return {
        "ops_user_key": user_key,
        "chat_messages": chat_messages,
        "chat_threads": chat_threads,
        "active_thread_id": active_thread_id,
        "ai_chat_welcome": opening,
        "chat_mode": "home-inline",
        "chat_api_url": url_for("admin.ops_ai_chat"),
        "clear_api_url": url_for("admin.ops_ai_clear"),
        "history_api_url": url_for("admin.ops_ai_history"),
        "switch_thread_url": url_for("admin.ops_ai_switch_thread"),
        "delete_thread_url": url_for("admin.ops_ai_delete_thread"),
        "sync_api_url": "",
        "agent_confirm_url": url_for("admin.ops_ai_agent_confirm"),
        "agent_cancel_url": url_for("admin.ops_ai_agent_cancel"),
        "postchi_thread_id": "",
        "postchi_messages_url": "",
        "postchi_send_url": "",
        "postchi_open_url": "",
        "ai_quick_prompts": [
            {"label": "خلاصه صف عملیات", "prompt": "خلاصه صف عملیات را بگو"},
            {
                "label": "پیام همگانی SMS",
                "prompt": "می‌خواهم یک پیامک همگانی برای همکاران بفرستم",
            },
            {
                "label": "تأیید همکار",
                "prompt": "درخواست‌های همکاری معلق را بررسی کن",
            },
        ],
        "home_ai_enabled": True,
        "home_ai_open": True,
        "home_ai_open_thread": active_thread_id or "",
    }


@admin_bp.route("", endpoint="admin_root", strict_slashes=False)
@admin_bp.route("/", endpoint="dashboard", strict_slashes=False)
@login_required
def dashboard():
    """خانهٔ ادمین = چت عملیات."""
    ctx = _ops_chat_context()
    return render_template("admin/dashboard.html", **ctx)


@admin_bp.get("/ops/chat/history", endpoint="ops_ai_history")
@login_required
def ops_ai_history():
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import load_user_record, messages_for_ui, threads_for_ui

    user_key = _admin_ops_user_key()
    thread_id = (request.args.get("thread_id") or "").strip() or None
    threads_only = request.args.get("threads_only", "").lower() in ("1", "true", "yes")
    record = load_user_record(user_key, audience=AUDIENCE_ADMIN)
    active = thread_id or record.get("active_id")
    payload: dict[str, Any] = {
        "ok": True,
        "threads": threads_for_ui(user_key, audience=AUDIENCE_ADMIN),
        "thread_id": thread_id or active,
    }
    if not threads_only:
        payload["messages"] = messages_for_ui(
            user_key, thread_id or active, audience=AUDIENCE_ADMIN
        )
    return jsonify(payload)


@admin_bp.post("/ops/chat", endpoint="ops_ai_chat")
@login_required
def ops_ai_chat():
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import append_exchange, ensure_active_thread, history_for_api, threads_for_ui
    from app.ai.http_errors import ai_chat_http_status
    from app.ai.services import generate_reply

    user_key = _admin_ops_user_key()
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or request.form.get("message") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    chip_intent = (data.get("intent") or data.get("chip_intent") or "").strip()
    hide_user = bool(data.get("hide_user") or data.get("silent") or data.get("hide_ui"))
    if not message:
        return jsonify({"ok": False, "error": "پیام خالی است."}), 400

    if not thread_id:
        thread_id = ensure_active_thread(user_key, audience=AUDIENCE_ADMIN)

    history = history_for_api(user_key, thread_id, audience=AUDIENCE_ADMIN)
    result = generate_reply(
        message,
        history=history,
        user_key=user_key,
        audience=AUDIENCE_ADMIN,
        thread_id=thread_id,
        chip_intent=chip_intent,
    )
    if not result.get("ok"):
        return jsonify(result), ai_chat_http_status(result)

    msgs, tid = append_exchange(
        user_key,
        message,
        result.get("reply") or "",
        thread_id=thread_id,
        assistant_land_codes=result.get("land_codes") or [],
        assistant_agent_actions=result.get("agent_actions") or [],
        audience=AUDIENCE_ADMIN,
        hide_user=hide_user,
    )
    result["messages"] = msgs
    result["audience"] = AUDIENCE_ADMIN
    result["thread_id"] = tid
    result["threads"] = threads_for_ui(user_key, audience=AUDIENCE_ADMIN)
    return jsonify(result)


@admin_bp.post("/ops/chat/confirm", endpoint="ops_ai_agent_confirm")
@login_required
def ops_ai_agent_confirm():
    from app.ai.agent_tools import apply_confirm_result_to_chat, confirm_action_from_token
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import ensure_active_thread

    user_key = _admin_ops_user_key()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    if not token:
        return jsonify({"ok": False, "error": "توکن اقدام نامعتبر است."}), 400
    if not thread_id:
        thread_id = ensure_active_thread(user_key, audience=AUDIENCE_ADMIN)

    out = confirm_action_from_token(phone=user_key, token=token)
    if not out.get("ok"):
        return jsonify(out), 400

    chat = apply_confirm_result_to_chat(
        phone=user_key,
        token=token,
        thread_id=thread_id,
        audience=AUDIENCE_ADMIN,
        confirm_out=out,
    )
    return jsonify(
        {
            "ok": True,
            "message": chat.get("message") or out.get("message"),
            "already": bool(out.get("already")),
            "thread_id": chat.get("thread_id") or thread_id,
            "messages": chat.get("messages") or [],
            "card_updated": bool(chat.get("card_updated")),
        }
    )


@admin_bp.post("/ops/chat/cancel", endpoint="ops_ai_agent_cancel")
@login_required
def ops_ai_agent_cancel():
    from app.ai.agent_tools import cancel_pending_action
    from app.ai.audience import AUDIENCE_ADMIN

    user_key = _admin_ops_user_key()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    if not token:
        return jsonify({"ok": False, "error": "توکن نامعتبر است."}), 400
    return jsonify(
        cancel_pending_action(
            phone=user_key,
            token=token,
            thread_id=thread_id,
            audience=AUDIENCE_ADMIN,
        )
    )


@admin_bp.post("/ops/chat/clear", endpoint="ops_ai_clear")
@login_required
def ops_ai_clear():
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import clear_chat, messages_for_ui
    from app.ai.welcome import opening_text

    user_key = _admin_ops_user_key()
    opening = opening_text(audience=AUDIENCE_ADMIN)
    out = clear_chat(user_key, audience=AUDIENCE_ADMIN, opening_text=opening)
    tid = (out or {}).get("thread_id") or ""
    msgs = messages_for_ui(user_key, thread_id=tid, audience=AUDIENCE_ADMIN) if tid else []
    return jsonify({"ok": True, "thread_id": tid, "messages": msgs})


@admin_bp.post("/ops/chat/switch", endpoint="ops_ai_switch_thread")
@login_required
def ops_ai_switch_thread():
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import messages_for_ui, set_active_thread, threads_for_ui

    user_key = _admin_ops_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if not thread_id or not set_active_thread(
        user_key, thread_id, audience=AUDIENCE_ADMIN
    ):
        return jsonify({"ok": False, "error": "گفتگو یافت نشد."}), 404
    return jsonify(
        {
            "ok": True,
            "thread_id": thread_id,
            "messages": messages_for_ui(user_key, thread_id, audience=AUDIENCE_ADMIN),
            "threads": threads_for_ui(user_key, audience=AUDIENCE_ADMIN),
        }
    )


@admin_bp.post("/ops/chat/delete", endpoint="ops_ai_delete_thread")
@login_required
def ops_ai_delete_thread():
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.chat_store import (
        delete_thread,
        load_user_record,
        messages_for_ui,
        threads_for_ui,
    )

    user_key = _admin_ops_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if not thread_id or not delete_thread(
        user_key, thread_id, audience=AUDIENCE_ADMIN
    ):
        return jsonify({"ok": False, "error": "حذف ممکن نشد."}), 400
    record = load_user_record(user_key, audience=AUDIENCE_ADMIN)
    active = record.get("active_id") or ""
    return jsonify(
        {
            "ok": True,
            "thread_id": active,
            "messages": messages_for_ui(user_key, active, audience=AUDIENCE_ADMIN)
            if active
            else [],
            "threads": threads_for_ui(user_key, audience=AUDIENCE_ADMIN),
        }
    )
