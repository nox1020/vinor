from __future__ import annotations

from flask import jsonify, redirect, request, session, url_for

from . import ai_bp
from .audience import AUDIENCE_PUBLIC
from .land_cards import partner_is_approved
from .http_errors import ai_chat_http_status
from .services import ai_config, generate_reply
from .user_key import ai_user_key


def _redirect_approved_partner() -> str | None:
    phone = (session.get("user_phone") or "").strip()
    if phone and partner_is_approved(phone):
        return url_for("express_partner.home", ai=1)
    return None


@ai_bp.get("/", endpoint="index")
def index():
    """چت AI عمومی — همکاران تأییدشده و کاربران پرتال به خانه هدایت می‌شوند."""
    partner_url = _redirect_approved_partner()
    if partner_url:
        return redirect(partner_url)

    # یکپارچه‌سازی با چت خانه (سطوح + همکاری برای مهمان/کاربر عادی)
    nxt = url_for("express_partner.home", ai=1)
    return redirect(nxt)


@ai_bp.get("/health", endpoint="health")
def health():
    cfg = ai_config()
    return jsonify({"ok": True, "service": "vinor-ai", **cfg})


@ai_bp.get("/sync", endpoint="sync")
def sync():
    """پیام‌های جدید گفتگوی فعال — برای نمایش فوری پاسخ ادمین."""
    from app.ai.chat_store import messages_since

    key = ai_user_key()
    thread_id = (request.args.get("thread_id") or "").strip() or None
    after = (request.args.get("after") or "").strip()
    after_count = request.args.get("count", type=int) or 0
    exclude_esc = [
        x.strip()
        for x in (request.args.get("exclude_esc") or "").split(",")
        if x.strip()
    ]
    msgs = messages_since(
        key,
        thread_id,
        after,
        audience=AUDIENCE_PUBLIC,
        after_count=max(0, after_count),
        exclude_escalation_ids=exclude_esc,
    )
    return jsonify({
        "ok": True,
        "messages": msgs,
        "thread_id": thread_id,
        "total": len(msgs),
        "audience": AUDIENCE_PUBLIC,
    })


@ai_bp.get("/history", endpoint="history")
def history():
    from app.ai.chat_store import messages_for_ui, threads_for_ui

    key = ai_user_key()
    thread_id = (request.args.get("thread_id") or "").strip() or None
    threads_only = request.args.get("threads_only", "").lower() in ("1", "true", "yes")
    payload = {
        "ok": True,
        "threads": threads_for_ui(key, audience=AUDIENCE_PUBLIC),
        "thread_id": thread_id,
        "audience": AUDIENCE_PUBLIC,
    }
    if not threads_only:
        payload["messages"] = messages_for_ui(key, thread_id, audience=AUDIENCE_PUBLIC)
    return jsonify(payload)


@ai_bp.post("/chat", endpoint="chat")
def chat():
    from app.ai.chat_store import (
        append_exchange,
        ensure_active_thread,
        history_for_api,
        threads_for_ui,
    )
    from app.ai.credits import (
        GUEST_FREE_ASSISTANT_REPLIES,
        check_guest_login_required,
        guest_replies_remaining,
        is_guest_user_key,
        record_guest_assistant_reply,
    )

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or request.form.get("message") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    chip_intent = (data.get("intent") or data.get("chip_intent") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "پیام خالی است."}), 400

    gate = check_guest_login_required(key)
    if gate:
        return jsonify(gate), ai_chat_http_status(gate)

    if not thread_id:
        thread_id = ensure_active_thread(key, audience=AUDIENCE_PUBLIC)

    history = history_for_api(key, thread_id, audience=AUDIENCE_PUBLIC)
    result = generate_reply(
        message,
        history=history,
        user_key=key,
        audience=AUDIENCE_PUBLIC,
        thread_id=thread_id,
        chip_intent=chip_intent,
    )
    if not result.get("ok"):
        return jsonify(result), ai_chat_http_status(result)

    land_codes = result.get("land_codes") or []
    agent_actions = result.get("agent_actions") or []
    msgs, tid = append_exchange(
        key,
        message,
        result.get("reply") or "",
        thread_id=thread_id,
        assistant_land_codes=land_codes,
        assistant_agent_actions=agent_actions,
        audience=AUDIENCE_PUBLIC,
    )
    used = record_guest_assistant_reply(key)
    remaining = guest_replies_remaining(key)
    if remaining is not None:
        result["guest_replies_remaining"] = remaining
        result["guest_replies_limit"] = GUEST_FREE_ASSISTANT_REPLIES
        result["guest_replies_used"] = used
    # اگر همین پاسخ سقف را پر کرد، فلگ برای UI
    if remaining == 0 and is_guest_user_key(key):
        result["guest_limit_reached"] = True
    result["messages"] = msgs
    result["thread_id"] = tid
    result["audience"] = AUDIENCE_PUBLIC
    result["threads"] = threads_for_ui(key, audience=AUDIENCE_PUBLIC)
    return jsonify(result)


@ai_bp.post("/clear", endpoint="clear")
def clear():
    from app.ai.chat_store import clear_chat
    from app.ai.http_errors import ai_chat_http_status

    key = ai_user_key()
    out = clear_chat(key, audience=AUDIENCE_PUBLIC)
    if not out.get("ok"):
        return jsonify(out), ai_chat_http_status(out)
    return jsonify({"ok": True, "thread_id": out.get("thread_id")})


@ai_bp.post("/agent/confirm", endpoint="agent_confirm")
def agent_confirm():
    """تأیید کارت اجنت برای مخاطب عمومی / کاربر عادی (مثلاً ثبت همکاری)."""
    from app.ai.agent_tools import confirm_action_from_token
    from app.ai.chat_store import append_exchange, ensure_active_thread

    phone = (session.get("user_phone") or "").strip()
    if not phone:
        return jsonify({
            "ok": False,
            "error": "برای ادامه وارد شوید.",
            "need_login": True,
            "login_url": "/express/partner/home?menu=1",
        }), 401

    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    if not token:
        return jsonify({"ok": False, "error": "توکن اقدام نامعتبر است."}), 400

    if not thread_id:
        thread_id = ensure_active_thread(ai_user_key(), audience=AUDIENCE_PUBLIC)

    out = confirm_action_from_token(phone=phone, token=token)
    if not out.get("ok"):
        return jsonify(out), 400

    note = str(out.get("message") or "انجام شد.")
    msgs, tid = append_exchange(
        ai_user_key(),
        "",
        note,
        thread_id=thread_id,
        audience=AUDIENCE_PUBLIC,
    )
    return jsonify({
        "ok": True,
        "message": note,
        "already": bool(out.get("already")),
        "thread_id": tid,
        "messages": msgs,
        "application_id": out.get("application_id") or "",
    })


@ai_bp.post("/agent/cancel", endpoint="agent_cancel")
def agent_cancel():
    from app.ai.agent_tools import cancel_pending_action

    phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "توکن نامعتبر است."}), 400
    if not phone:
        return jsonify({"ok": False, "error": "برای انصراف وارد شوید.", "need_login": True}), 401
    return jsonify(cancel_pending_action(phone=phone, token=token))


@ai_bp.post("/thread/switch", endpoint="switch_thread")
def switch_thread():
    from app.ai.chat_store import messages_for_ui, set_active_thread, threads_for_ui

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if not thread_id or not set_active_thread(key, thread_id, audience=AUDIENCE_PUBLIC):
        return jsonify({"ok": False, "error": "گفتگو یافت نشد."}), 404
    return jsonify({
        "ok": True,
        "thread_id": thread_id,
        "messages": messages_for_ui(key, thread_id, audience=AUDIENCE_PUBLIC),
        "threads": threads_for_ui(key, audience=AUDIENCE_PUBLIC),
    })


@ai_bp.post("/thread/delete", endpoint="delete_thread")
def delete_thread():
    from app.ai.chat_store import delete_thread, load_user_record, messages_for_ui, threads_for_ui

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if not thread_id or not delete_thread(key, thread_id, audience=AUDIENCE_PUBLIC):
        return jsonify({"ok": False, "error": "حذف ممکن نیست."}), 400
    record = load_user_record(key, audience=AUDIENCE_PUBLIC)
    active = record.get("active_id")
    return jsonify({
        "ok": True,
        "thread_id": active,
        "messages": messages_for_ui(key, active, audience=AUDIENCE_PUBLIC),
        "threads": threads_for_ui(key, audience=AUDIENCE_PUBLIC),
    })


@ai_bp.post("/api/chat", endpoint="legacy_chat")
def legacy_chat():
    """سازگاری با مسیر قدیمی — هدایت منطق به /ai/chat یا پرتال همکار."""
    partner_url = _redirect_approved_partner()
    if partner_url:
        return jsonify({
            "ok": False,
            "error": "لطفاً از پرتال همکار استفاده کنید.",
            "redirect": partner_url,
        }), 302

    return chat()
