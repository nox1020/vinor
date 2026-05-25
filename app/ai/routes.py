from __future__ import annotations

from flask import jsonify, redirect, render_template, request, session, url_for

from . import ai_bp
from .audience import AUDIENCE_PUBLIC
from .land_cards import partner_is_approved
from .http_errors import ai_chat_http_status
from .services import ai_config, generate_reply
from .user_key import ai_user_key


def _redirect_approved_partner() -> str | None:
    phone = (session.get("user_phone") or "").strip()
    if phone and partner_is_approved(phone):
        return url_for("express_partner.ai")
    return None


@ai_bp.get("/", endpoint="index")
def index():
    """چت AI برای کاربر عادی؛ همکار تأییدشده به پرتال همکار هدایت می‌شود."""
    partner_url = _redirect_approved_partner()
    if partner_url:
        return redirect(partner_url)

    from app.ai.chat_store import (
        ensure_active_thread,
        messages_for_ui,
        threads_for_ui,
    )

    key = ai_user_key()
    ensure_active_thread(key, audience=AUDIENCE_PUBLIC)
    threads = threads_for_ui(key, audience=AUDIENCE_PUBLIC)
    active_thread_id = next((t["id"] for t in threads if t.get("is_active")), "")
    return render_template(
        "ai/public_chat.html",
        chat_messages=messages_for_ui(key, audience=AUDIENCE_PUBLIC),
        chat_threads=threads,
        active_thread_id=active_thread_id,
        ai_audience="public",
        chat_api_url=url_for("ai.chat"),
        clear_api_url=url_for("ai.clear"),
        history_api_url=url_for("ai.history"),
        switch_thread_url=url_for("ai.switch_thread"),
        delete_thread_url=url_for("ai.delete_thread"),
        sync_api_url=url_for("ai.sync"),
    )


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

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or request.form.get("message") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    if not message:
        return jsonify({"ok": False, "error": "پیام خالی است."}), 400

    if not thread_id:
        thread_id = ensure_active_thread(key, audience=AUDIENCE_PUBLIC)

    history = history_for_api(key, thread_id, audience=AUDIENCE_PUBLIC)
    result = generate_reply(
        message,
        history=history,
        user_key=key,
        audience=AUDIENCE_PUBLIC,
        thread_id=thread_id,
    )
    if not result.get("ok"):
        return jsonify(result), ai_chat_http_status(result)

    land_codes = result.get("land_codes") or []
    msgs, tid = append_exchange(
        key,
        message,
        result.get("reply") or "",
        thread_id=thread_id,
        assistant_land_codes=land_codes,
        audience=AUDIENCE_PUBLIC,
    )
    result["messages"] = msgs
    result["thread_id"] = tid
    result["audience"] = AUDIENCE_PUBLIC
    result["threads"] = threads_for_ui(key, audience=AUDIENCE_PUBLIC)
    return jsonify(result)


@ai_bp.post("/clear", endpoint="clear")
def clear():
    from app.ai.chat_store import clear_chat

    key = ai_user_key()
    tid = clear_chat(key, audience=AUDIENCE_PUBLIC)
    return jsonify({"ok": True, "thread_id": tid})


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
