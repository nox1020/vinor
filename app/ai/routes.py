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


def _session_phone() -> str:
    return (session.get("user_phone") or "").strip()


def _lawyer_login_required_response():
    return jsonify({
        "ok": False,
        "error": "برای مشاوره با وکیل ملکی وارد شوید.",
        "need_login": True,
        "login_url": url_for("express_partner.home", menu=1),
    }), 401


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
    from app.ai.chat_store import include_land_cards_from_request

    msgs = messages_since(
        key,
        thread_id,
        after,
        audience=AUDIENCE_PUBLIC,
        after_count=max(0, after_count),
        exclude_escalation_ids=exclude_esc,
        include_land_cards=include_land_cards_from_request(request),
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
    from app.ai.chat_store import threads_for_ui
    from app.lawyer.service import is_lawyer_thread, threads_with_lawyer

    key = ai_user_key()
    thread_id = (request.args.get("thread_id") or "").strip() or None
    threads_only = request.args.get("threads_only", "").lower() in ("1", "true", "yes")
    logged_in = bool(_session_phone())
    if is_lawyer_thread(thread_id) and not logged_in:
        return _lawyer_login_required_response()
    threads = (
        threads_with_lawyer(key, audience=AUDIENCE_PUBLIC, active_thread_id=thread_id)
        if logged_in
        else (threads_for_ui(key, audience=AUDIENCE_PUBLIC) or [])
    )
    payload = {
        "ok": True,
        "threads": threads,
        "thread_id": thread_id,
        "audience": AUDIENCE_PUBLIC,
    }
    if not threads_only:
        from app.ai.chat_store import coerce_history_page, history_messages_payload

        raw_limit = request.args.get("limit")
        if raw_limit is None:
            raw_limit = request.args.get("page_size")
        from app.ai.chat_store import include_land_cards_from_request

        page_size, before_id = coerce_history_page(raw_limit, request.args.get("before_id"))
        payload.update(
            history_messages_payload(
                key,
                thread_id,
                AUDIENCE_PUBLIC,
                limit=page_size,
                before_id=before_id,
                include_land_cards=include_land_cards_from_request(request),
            )
        )
        payload["mode"] = (
            "lawyer" if logged_in and is_lawyer_thread(thread_id) else "chat"
        )
    return jsonify(payload)


@ai_bp.get("/land-cards", endpoint="land_cards")
def land_cards():
    """Batch land-card HTML for codes this viewer may see. Max 10."""
    from app.ai.land_cards import (
        LAND_CARDS_BATCH_MAX,
        land_cards_batch,
        parse_land_code_list,
    )

    codes = parse_land_code_list(request.args.get("codes") or "")
    if len(codes) > LAND_CARDS_BATCH_MAX:
        return jsonify({
            "ok": False,
            "error": "too_many_codes",
            "max": LAND_CARDS_BATCH_MAX,
        }), 400
    return jsonify(land_cards_batch(ai_user_key(), codes, audience=AUDIENCE_PUBLIC))


@ai_bp.post("/chat", endpoint="chat")
def chat():
    from app.ai.audience import VOICE_LAWYER
    from app.ai.chat_store import (
        append_exchange,
        ensure_active_thread,
        history_for_api,
    )
    from app.ai.credits import (
        check_guest_login_required,
        guest_free_assistant_replies,
        guest_replies_remaining,
        is_guest_user_key,
        record_guest_assistant_reply,
    )
    from app.lawyer.config import lawyer_enabled
    from app.lawyer.service import (
        ensure_lawyer_thread,
        is_lawyer_thread,
        threads_with_lawyer,
    )
    from app.ai.chat_store import threads_for_ui

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or request.form.get("message") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    chip_intent = (data.get("intent") or data.get("chip_intent") or "").strip()
    hide_user = bool(data.get("hide_user") or data.get("silent") or data.get("hide_ui"))
    mode = (data.get("mode") or "").strip().lower()
    if not message:
        return jsonify({"ok": False, "error": "پیام خالی است."}), 400

    gate = check_guest_login_required(key)
    if gate:
        return jsonify(gate), ai_chat_http_status(gate)

    voice = None
    if mode in ("lawyer", "vakil") or is_lawyer_thread(thread_id):
        if not _session_phone():
            return _lawyer_login_required_response()
        if not lawyer_enabled():
            return jsonify({"ok": False, "error": "وکیل ملکی فعلاً غیرفعال است."}), 403
        thread_id = ensure_lawyer_thread(key, audience=AUDIENCE_PUBLIC)
        voice = VOICE_LAWYER
        chip_intent = ""

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
        voice=voice,
    )
    if not result.get("ok"):
        return jsonify(result), ai_chat_http_status(result)

    from app.ai.chat_store import include_land_cards_from_request

    land_codes = [] if voice == VOICE_LAWYER else (result.get("land_codes") or [])
    agent_actions = [] if voice == VOICE_LAWYER else (result.get("agent_actions") or [])
    include_cards = include_land_cards_from_request(request)
    msgs, tid = append_exchange(
        key,
        message,
        result.get("reply") or "",
        thread_id=thread_id,
        assistant_land_codes=land_codes,
        assistant_agent_actions=agent_actions,
        audience=AUDIENCE_PUBLIC,
        hide_user=hide_user,
        include_land_cards=include_cards,
    )
    used = record_guest_assistant_reply(key)
    remaining = guest_replies_remaining(key)
    guest_limit = guest_free_assistant_replies()
    if remaining is not None:
        result["guest_replies_remaining"] = remaining
        result["guest_replies_limit"] = guest_limit
        result["guest_replies_used"] = used
    # اگر همین پاسخ سقف را پر کرد، فلگ برای UI
    if remaining == 0 and is_guest_user_key(key):
        result["guest_limit_reached"] = True
    if not include_cards and not agent_actions:
        result.pop("cards_html", None)
        result.pop("land_cards", None)
    result["messages"] = msgs
    result["thread_id"] = tid
    result["audience"] = AUDIENCE_PUBLIC
    result["mode"] = "lawyer" if is_lawyer_thread(tid) else "chat"
    if _session_phone():
        result["threads"] = threads_with_lawyer(
            key,
            audience=AUDIENCE_PUBLIC,
            active_thread_id=tid,
        )
    else:
        result["threads"] = threads_for_ui(key, audience=AUDIENCE_PUBLIC) or []
    return jsonify(result)


@ai_bp.post("/clear", endpoint="clear")
def clear():
    from app.ai.chat_store import clear_chat, messages_for_ui
    from app.ai.http_errors import ai_chat_http_status
    from app.ai.welcome import opening_text

    key = ai_user_key()
    opening = opening_text()
    out = clear_chat(key, audience=AUDIENCE_PUBLIC, opening_text=opening)
    if not out.get("ok"):
        return jsonify(out), ai_chat_http_status(out)
    tid = out.get("thread_id")
    msgs = out.get("messages")
    if msgs is None:
        from app.ai.chat_store import include_land_cards_from_request

        msgs = messages_for_ui(
            key,
            thread_id=tid,
            audience=AUDIENCE_PUBLIC,
            include_land_cards=include_land_cards_from_request(request),
        )
    return jsonify({"ok": True, "thread_id": tid, "messages": msgs})


@ai_bp.post("/agent/confirm", endpoint="agent_confirm")
def agent_confirm():
    """تأیید کارت اجنت برای مخاطب عمومی / کاربر عادی (مثلاً ثبت همکاری)."""
    from app.ai.chat_store import ensure_active_thread
    from app.ai.confirmation import apply_confirm_to_chat, confirm_action

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

    out = confirm_action(phone=phone, token=token)
    if not out.get("ok"):
        return jsonify(out), 400

    chat = apply_confirm_to_chat(
        phone=phone,
        token=token,
        thread_id=thread_id,
        audience=AUDIENCE_PUBLIC,
        confirm_out=out,
    )
    note = str(chat.get("message") or out.get("message") or "انجام شد.")
    return jsonify({
        "ok": True,
        "message": note,
        "already": bool(out.get("already")),
        "thread_id": chat.get("thread_id") or thread_id,
        "messages": chat.get("messages") or [],
        "card_updated": bool(chat.get("card_updated")),
        "application_id": out.get("application_id") or "",
    })


@ai_bp.post("/agent/cancel", endpoint="agent_cancel")
def agent_cancel():
    from app.ai.confirmation import cancel_action

    phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    thread_id = (data.get("thread_id") or "").strip() or None
    if not token:
        return jsonify({"ok": False, "error": "توکن نامعتبر است."}), 400
    if not phone:
        return jsonify({"ok": False, "error": "برای انصراف وارد شوید.", "need_login": True}), 401
    return jsonify(
        cancel_action(
            phone=phone,
            token=token,
            thread_id=thread_id,
            audience=AUDIENCE_PUBLIC,
        )
    )


@ai_bp.post("/thread/switch", endpoint="switch_thread")
def switch_thread():
    from app.ai.chat_store import ensure_active_thread, threads_for_ui
    from app.lawyer.config import lawyer_enabled
    from app.lawyer.service import (
        ensure_lawyer_thread,
        is_lawyer_thread,
        threads_with_lawyer,
    )

    from app.ai.chat_store import coerce_history_page, history_messages_payload

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if not thread_id:
        return jsonify({"ok": False, "error": "گفتگو یافت نشد."}), 404
    logged_in = bool(_session_phone())
    raw_limit = data.get("limit")
    if raw_limit is None and "page_size" in data:
        raw_limit = data.get("page_size")
    page_size, before_id = coerce_history_page(raw_limit, data.get("before_id"))

    def _threads(active_id: str | None):
        if logged_in:
            return threads_with_lawyer(
                key,
                audience=AUDIENCE_PUBLIC,
                active_thread_id=active_id,
            )
        return threads_for_ui(key, audience=AUDIENCE_PUBLIC) or []

    if is_lawyer_thread(thread_id) or thread_id in ("lawyer", "vakil"):
        if not logged_in:
            return _lawyer_login_required_response()
        if not lawyer_enabled():
            return jsonify({"ok": False, "error": "وکیل ملکی فعلاً غیرفعال است."}), 403
        tid = ensure_lawyer_thread(key, audience=AUDIENCE_PUBLIC)
        body = {
            "ok": True,
            "thread_id": tid,
            "mode": "lawyer",
            "threads": _threads(tid),
        }
        from app.ai.chat_store import include_land_cards_from_request

        body.update(
            history_messages_payload(
                key,
                tid,
                AUDIENCE_PUBLIC,
                limit=page_size,
                before_id=before_id,
                include_land_cards=include_land_cards_from_request(request),
            )
        )
        return jsonify(body)
    thread_id = ensure_active_thread(key, audience=AUDIENCE_PUBLIC)
    body = {
        "ok": True,
        "thread_id": thread_id,
        "mode": "chat",
        "threads": _threads(thread_id),
    }
    from app.ai.chat_store import include_land_cards_from_request

    body.update(
        history_messages_payload(
            key,
            thread_id,
            AUDIENCE_PUBLIC,
            limit=page_size,
            before_id=before_id,
            include_land_cards=include_land_cards_from_request(request),
        )
    )
    return jsonify(body)


@ai_bp.post("/thread/delete", endpoint="delete_thread")
def delete_thread():
    from app.ai.chat_store import delete_thread, load_user_record, threads_for_ui
    from app.ai.credits import is_guest_user_key
    from app.lawyer.service import is_lawyer_thread, threads_with_lawyer

    key = ai_user_key()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get("thread_id") or "").strip()
    if is_lawyer_thread(thread_id):
        return jsonify({"ok": False, "error": "این گفتگو قابل حذف نیست."}), 400
    if is_guest_user_key(key) and not _session_phone():
        return jsonify({
            "ok": False,
            "error": "برای حذف گفتگو وارد شوید.",
            "need_login": True,
            "login_url": url_for("express_partner.home", menu=1),
        }), ai_chat_http_status({"need_login": True})
    if not thread_id or not delete_thread(key, thread_id, audience=AUDIENCE_PUBLIC):
        return jsonify({"ok": False, "error": "حذف ممکن نیست."}), 400
    record = load_user_record(key, audience=AUDIENCE_PUBLIC)
    active = record.get("active_id")
    logged_in = bool(_session_phone())
    threads = (
        threads_with_lawyer(key, audience=AUDIENCE_PUBLIC, active_thread_id=active)
        if logged_in
        else (threads_for_ui(key, audience=AUDIENCE_PUBLIC) or [])
    )
    from app.ai.chat_store import coerce_history_page, history_messages_payload

    raw_limit = data.get("limit")
    if raw_limit is None and "page_size" in data:
        raw_limit = data.get("page_size")
    page_size, before_id = coerce_history_page(raw_limit, data.get("before_id"))
    body = {
        "ok": True,
        "thread_id": active,
        "threads": threads,
    }
    from app.ai.chat_store import include_land_cards_from_request

    body.update(
        history_messages_payload(
            key,
            active,
            AUDIENCE_PUBLIC,
            limit=page_size,
            before_id=before_id,
            include_land_cards=include_land_cards_from_request(request),
        )
    )
    return jsonify(body)


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
