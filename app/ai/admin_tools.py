"""ابزارهای هستهٔ چت عملیات ادمین — propose_* + کارت تأیید."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .audience import AUDIENCE_ADMIN, VOICE_ADMIN

# --- tool names ---
TOOL_ADMIN_OPS_SUMMARY = "admin_ops_summary"
TOOL_ADMIN_SEARCH_LANDS = "admin_search_lands"
TOOL_ADMIN_PARTNER_STATUS = "admin_partner_status"
TOOL_PROPOSE_BROADCAST_SMS = "propose_broadcast_sms"
TOOL_PROPOSE_BROADCAST_PUSH = "propose_broadcast_push"
TOOL_PROPOSE_ADD_LISTING = "propose_add_express_listing"
TOOL_PROPOSE_UPDATE_LISTING = "propose_update_listing_status"
TOOL_PROPOSE_PARTNER_DECISION = "propose_partner_decision"
TOOL_PROPOSE_VISIT_ADMIN = "propose_visit_admin_action"
TOOL_PROPOSE_COMMISSION = "propose_commission_action"
TOOL_ANSWER_ESCALATION = "answer_escalation"

ADMIN_CONFIRM_TYPES = frozenset(
    {
        "confirm_broadcast_sms",
        "confirm_broadcast_push",
        "confirm_add_express_listing",
        "confirm_update_listing_status",
        "confirm_partner_decision",
        "confirm_visit_admin_action",
        "confirm_commission_action",
        "confirm_answer_escalation",
    }
)

CORE_ADMIN_TOOL_NAMES = frozenset(
    {
        TOOL_ADMIN_OPS_SUMMARY,
        TOOL_ADMIN_SEARCH_LANDS,
        TOOL_ADMIN_PARTNER_STATUS,
        TOOL_PROPOSE_BROADCAST_SMS,
        TOOL_PROPOSE_BROADCAST_PUSH,
        TOOL_PROPOSE_ADD_LISTING,
        TOOL_PROPOSE_UPDATE_LISTING,
        TOOL_PROPOSE_PARTNER_DECISION,
        TOOL_PROPOSE_VISIT_ADMIN,
        TOOL_PROPOSE_COMMISSION,
        TOOL_ANSWER_ESCALATION,
    }
)


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def _denied(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


def _store_pending(*, user_key: str, action_type: str, payload: dict[str, Any]) -> str:
    from .agent_tools import _store_pending_action

    return _store_pending_action(
        user_key=user_key,
        action_type=action_type,
        payload=payload,
    )


def _propose_card(
    *,
    user_key: str,
    action_type: str,
    payload: dict[str, Any],
    title: str,
    lines: list[str],
    confirm_label: str = "تأیید و اجرا",
    instruction: str = "کارت تأیید نشان داده می‌شود. تا تأیید نزده نگو انجام شد.",
) -> dict[str, Any]:
    token = _store_pending(
        user_key=user_key,
        action_type=action_type,
        payload=payload,
    )
    ui = {
        "type": action_type,
        "token": token,
        "title": title,
        "lines": [ln for ln in lines if str(ln).strip()],
        "status": "pending",
        "confirm_label": confirm_label,
        "cancel_label": "انصراف",
    }
    model = {
        "ok": True,
        "pending_confirm": True,
        "instruction": instruction,
    }
    return {"ok": True, "model_result": model, "ui_action": ui}


def tools_schema_admin() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": TOOL_ADMIN_OPS_SUMMARY,
                "description": "خلاصهٔ صف عملیات: درخواست همکار، بازدید، پورسانت، escalation.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_ADMIN_SEARCH_LANDS,
                "description": (
                    "جستجوی فایل/آگهی در سیستم برای ادمین. "
                    "پیش‌فرض فقط خلاصهٔ متنی؛ کارت ویژوال فقط اگر ادمین خواست "
                    "(show_cards=true وقتی گفت کارت نشان بده / پیشنهاد بده)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                        "show_cards": {
                            "type": "boolean",
                            "description": "فقط اگر ادمین صریحاً کارت/پیشنهاد ویژوال خواست",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_ADMIN_PARTNER_STATUS,
                "description": "وضعیت همکار یا درخواست همکاری با شماره موبایل.",
                "parameters": {
                    "type": "object",
                    "properties": {"phone": {"type": "string"}},
                    "required": ["phone"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_BROADCAST_SMS,
                "description": (
                    "پیشنهاد ارسال پیامک همگانی. متن را از پیام ادمین بگیر. "
                    "گروه: partners (همکاران) | all_users | club."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "متن پیامک"},
                        "recipient_group": {
                            "type": "string",
                            "description": "partners|all_users|club (پیش‌فرض partners)",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_BROADCAST_PUSH,
                "description": "پیشنهاد پوش نوتیفیکیشن به همکاران تأییدشده.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_ADD_LISTING,
                "description": (
                    "پیشنهاد افزودن فایل اکسپرس. فیلدها را یکی‌یکی جمع کن "
                    "(عنوان، شهر، موقعیت، متراژ، قیمت کل، درصد پورسانت)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "city": {"type": "string"},
                        "location": {"type": "string"},
                        "size": {"type": "integer"},
                        "price_total": {"type": "integer"},
                        "express_commission_pct": {"type": "number"},
                        "payment_method": {"type": "string"},
                        "description": {"type": "string"},
                        "category": {"type": "string"},
                        "vinor_contact": {"type": "string"},
                    },
                    "required": [
                        "title",
                        "city",
                        "location",
                        "size",
                        "price_total",
                        "express_commission_pct",
                    ],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_UPDATE_LISTING,
                "description": "پیشنهاد تغییر وضعیت فایل (approved|rejected|pending).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "land_code": {"type": "string"},
                        "status": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["land_code", "status"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_PARTNER_DECISION,
                "description": "پیشنهاد تأیید یا رد درخواست همکاری.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "decision": {"type": "string", "description": "approve|reject"},
                        "name": {"type": "string"},
                        "city": {"type": "string"},
                        "send_sms": {"type": "boolean"},
                    },
                    "required": ["phone", "decision"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_VISIT_ADMIN,
                "description": "پیشنهاد اقدام ادمین روی بازدید (مثلاً approved|cancelled|completed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "visit_id": {"type": "string"},
                        "status": {"type": "string"},
                        "admin_note": {"type": "string"},
                    },
                    "required": ["visit_id", "status"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_PROPOSE_COMMISSION,
                "description": (
                    "پیشنهاد اقدام مالی: approve_commission | reject_commission | "
                    "paid_withdrawal (برداشت پرداخت‌شده)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "commission_id": {"type": "integer"},
                        "withdrawal_id": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_ANSWER_ESCALATION,
                "description": "پاسخ به سوال ارجاع‌شدهٔ AI (escalation).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "escalation_id": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["escalation_id", "answer"],
                },
            },
        },
    ]


def run_admin_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    admin_key: str,
) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, dict) else {}
    n = (name or "").strip()
    me = (admin_key or "").strip()
    if not me:
        return _denied("شناسه ادمین نامعتبر است.")

    if n == TOOL_ADMIN_OPS_SUMMARY:
        return _tool_ops_summary()
    if n == TOOL_ADMIN_SEARCH_LANDS:
        return _tool_search_lands(args)
    if n == TOOL_ADMIN_PARTNER_STATUS:
        return _tool_partner_status(args)
    if n == TOOL_PROPOSE_BROADCAST_SMS:
        return _tool_propose_broadcast_sms(args, admin_key=me)
    if n == TOOL_PROPOSE_BROADCAST_PUSH:
        return _tool_propose_broadcast_push(args, admin_key=me)
    if n == TOOL_PROPOSE_ADD_LISTING:
        return _tool_propose_add_listing(args, admin_key=me)
    if n == TOOL_PROPOSE_UPDATE_LISTING:
        return _tool_propose_update_listing(args, admin_key=me)
    if n == TOOL_PROPOSE_PARTNER_DECISION:
        return _tool_propose_partner_decision(args, admin_key=me)
    if n == TOOL_PROPOSE_VISIT_ADMIN:
        return _tool_propose_visit_admin(args, admin_key=me)
    if n == TOOL_PROPOSE_COMMISSION:
        return _tool_propose_commission(args, admin_key=me)
    if n == TOOL_ANSWER_ESCALATION:
        return _tool_propose_answer_escalation(args, admin_key=me)
    return _denied(f"ابزار ناشناخته: {n}")


def confirm_admin_action(*, admin_key: str, token: str) -> dict[str, Any]:
    from .agent_tools import _consume_pending_action, _load_pending_action

    me = (admin_key or "").strip()
    pending = _load_pending_action(token)
    if not pending:
        return {"ok": False, "error": "این پیشنهاد منقضی یا نامعتبر است."}
    if str(pending.get("user_key") or "") != me:
        return {"ok": False, "error": "دسترسی به این پیشنهاد ندارید."}
    action_type = str(pending.get("action_type") or "")
    if action_type not in ADMIN_CONFIRM_TYPES:
        return {"ok": False, "error": "نوع اقدام ادمین نامعتبر است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}

    handlers = {
        "confirm_broadcast_sms": _exec_broadcast_sms,
        "confirm_broadcast_push": _exec_broadcast_push,
        "confirm_add_express_listing": _exec_add_listing,
        "confirm_update_listing_status": _exec_update_listing,
        "confirm_partner_decision": _exec_partner_decision,
        "confirm_visit_admin_action": _exec_visit_admin,
        "confirm_commission_action": _exec_commission,
        "confirm_answer_escalation": _exec_answer_escalation,
    }
    fn = handlers.get(action_type)
    if not fn:
        return {"ok": False, "error": "handler یافت نشد."}
    out = fn(payload)
    if out.get("ok"):
        _consume_pending_action(token)
    return out


# ----- read tools -----


def _tool_ops_summary() -> dict[str, Any]:
    try:
        from app.utils.storage import (
            load_express_commissions,
            load_express_partner_apps,
            load_express_visit_requests,
            load_partner_withdrawals,
        )
        from app.ai.escalations import list_pending_for_admin

        apps = load_express_partner_apps() or []
        visits = load_express_visit_requests() or []
        commissions = load_express_commissions() or []
        withdrawals = load_partner_withdrawals() or []
        pending_apps = sum(
            1
            for a in apps
            if isinstance(a, dict)
            and str(a.get("status") or "").lower() not in ("approved", "rejected")
        )
        pending_visits = sum(
            1
            for v in visits
            if isinstance(v, dict)
            and str(v.get("status") or "").lower() in ("pending", "done_pending")
        )
        pending_comm = sum(
            1
            for c in commissions
            if isinstance(c, dict) and str(c.get("status") or "") == "pending"
        )
        pending_wd = sum(
            1
            for w in withdrawals
            if isinstance(w, dict)
            and str(w.get("status") or "").lower() in ("pending", "approved", "processing")
        )
        esc = list_pending_for_admin() or []
        model = {
            "ok": True,
            "pending_partner_apps": pending_apps,
            "pending_visits": pending_visits,
            "pending_commissions": pending_comm,
            "open_withdrawals": pending_wd,
            "pending_escalations": len(esc),
            "instruction": "خلاصه را کوتاه بگو و یک اقدام پیشنهادی بده.",
        }
        return {"ok": True, "model_result": model}
    except Exception as exc:
        return _denied(f"خلاصه عملیات ممکن نشد: {exc}")


def _tool_search_lands(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    try:
        limit = max(1, min(int(args.get("limit") or 5), 8))
    except Exception:
        limit = 5
    show_cards = bool(args.get("show_cards"))
    if not query:
        return _denied("عبارت جستجو خالی است.")
    try:
        from admin.routes import _lands_path
        from app.utils.storage import load_json

        lands = load_json(_lands_path()) or []
        if not isinstance(lands, list):
            lands = []
        q = query.lower()
        hits = []
        for land in lands:
            if not isinstance(land, dict):
                continue
            blob = " ".join(
                str(land.get(k) or "")
                for k in ("code", "title", "location", "city", "status", "description")
            ).lower()
            if q in blob or any(tok and tok in blob for tok in q.split()):
                hits.append(
                    {
                        "code": land.get("code"),
                        "title": land.get("title"),
                        "city": land.get("city"),
                        "status": land.get("status") or land.get("express_status"),
                        "size": land.get("size"),
                        "price_total": land.get("price_total"),
                    }
                )
            if len(hits) >= limit:
                break
        codes = [str(h.get("code") or "").strip() for h in hits if h.get("code")]
        out: dict[str, Any] = {
            "ok": True,
            "model_result": {
                "ok": True,
                "count": len(hits),
                "lands": hits,
                "show_cards": show_cards,
                "instruction": (
                    "نتایج را کوتاه خلاصه کن؛ لینک صفحه نده. "
                    + (
                        "کارت فایل در UI نشان داده می‌شود؛ [[LAND:کد]] هم مجاز است."
                        if show_cards
                        else "کارت فایل نشان نده و [[LAND:]] ننویس — فقط متن."
                    )
                ),
            },
        }
        if show_cards and codes:
            out["land_codes"] = codes[:limit]
        return out
    except Exception as exc:
        return _denied(str(exc))


def _tool_partner_status(args: dict[str, Any]) -> dict[str, Any]:
    phone = _norm_phone(str(args.get("phone") or ""))
    if len(phone) != 11:
        return _denied("شماره موبایل معتبر نیست.")
    try:
        from app.utils.storage import load_express_partner_apps, load_express_partners

        partners = load_express_partners() or []
        apps = load_express_partner_apps() or []
        partner = next(
            (
                p
                for p in partners
                if isinstance(p, dict) and _norm_phone(str(p.get("phone") or "")) == phone
            ),
            None,
        )
        app = next(
            (
                a
                for a in apps
                if isinstance(a, dict) and _norm_phone(str(a.get("phone") or "")) == phone
            ),
            None,
        )
        return {
            "ok": True,
            "model_result": {
                "ok": True,
                "phone": phone,
                "partner": {
                    "name": (partner or {}).get("name"),
                    "status": (partner or {}).get("status"),
                    "city": (partner or {}).get("city"),
                }
                if partner
                else None,
                "application": {
                    "id": (app or {}).get("id"),
                    "name": (app or {}).get("name"),
                    "status": (app or {}).get("status"),
                    "city": (app or {}).get("city"),
                }
                if app
                else None,
            },
        }
    except Exception as exc:
        return _denied(str(exc))


# ----- propose tools -----


def _tool_propose_broadcast_sms(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "missing": "message",
                "instruction": "متن پیامک را از ادمین بپرس.",
            },
        }
    group = str(args.get("recipient_group") or "partners").strip() or "partners"
    try:
        from admin.sms_recipients import (
            count_sms_recipients,
            normalize_recipient_group,
            recipient_group_label,
        )

        group = normalize_recipient_group(group)
        count = count_sms_recipients(group)
        label = recipient_group_label(group)
    except Exception:
        count = 0
        label = group
    if count < 1:
        return _denied(f"گیرنده‌ای در گروه «{label}» یافت نشد.")
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_broadcast_sms",
        payload={"message": message, "recipient_group": group},
        title="تأیید ارسال پیامک همگانی",
        lines=[
            f"گروه: {label}",
            f"تعداد گیرنده: {count}",
            f"متن: {message[:280]}{'…' if len(message) > 280 else ''}",
        ],
        confirm_label="ارسال پیامک",
    )


def _tool_propose_broadcast_push(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    body = str(args.get("body") or "").strip()
    if not title or not body:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "missing": "title_or_body",
                "instruction": "عنوان و متن پوش را بپرس.",
            },
        }
    try:
        from admin.routes import _load_approved_express_partners

        partners = _load_approved_express_partners() or []
        count = len(partners)
    except Exception:
        count = 0
    if count < 1:
        return _denied("همکار تأییدشده‌ای برای پوش یافت نشد.")
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_broadcast_push",
        payload={"title": title, "body": body, "ntype": "admin_broadcast"},
        title="تأیید ارسال پوش همگانی",
        lines=[f"گیرندگان: {count} همکار", f"عنوان: {title}", f"متن: {body[:240]}"],
        confirm_label="ارسال پوش",
    )


def _tool_propose_add_listing(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    city = str(args.get("city") or "").strip()
    location = str(args.get("location") or "").strip()
    try:
        size = int(args.get("size") or 0)
        price_total = int(args.get("price_total") or 0)
        pct = float(args.get("express_commission_pct") or 0)
    except Exception:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "متراژ، قیمت و درصد پورسانت باید عدد باشند.",
            },
        }
    missing = []
    if not title or len(title) < 10:
        missing.append("title")
    if not city:
        missing.append("city")
    if not location:
        missing.append("location")
    if size <= 0:
        missing.append("size")
    if price_total <= 0:
        missing.append("price_total")
    if pct <= 0 or pct > 100:
        missing.append("express_commission_pct")
    if missing:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "missing": missing,
                "instruction": "فیلدهای ناقص را یکی‌یکی بپرس؛ لینک فرم نده.",
            },
        }
    payment_method = str(args.get("payment_method") or "نقدی").strip() or "نقدی"
    vinor_contact = re.sub(r"\D+", "", str(args.get("vinor_contact") or "09121471301"))
    payload = {
        "title": title,
        "city": city,
        "location": location,
        "size": size,
        "price_total": price_total,
        "express_commission_pct": pct,
        "payment_method": payment_method,
        "description": str(args.get("description") or "").strip(),
        "category": str(args.get("category") or "").strip(),
        "vinor_contact": vinor_contact or "09121471301",
    }
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_add_express_listing",
        payload=payload,
        title="تأیید افزودن فایل اکسپرس",
        lines=[
            f"عنوان: {title}",
            f"شهر/موقعیت: {city} — {location}",
            f"متراژ: {size}",
            f"قیمت: {price_total:,}",
            f"پورسانت: {pct}%",
            f"پرداخت: {payment_method}",
        ],
        confirm_label="ثبت فایل",
    )


def _tool_propose_update_listing(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    code = str(args.get("land_code") or "").strip()
    status = str(args.get("status") or "").strip().lower()
    reason = str(args.get("reason") or "").strip()
    if not code or status not in ("approved", "rejected", "pending"):
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "کد فایل و وضعیت (approved|rejected|pending) لازم است.",
            },
        }
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_update_listing_status",
        payload={"land_code": code, "status": status, "reason": reason},
        title="تأیید تغییر وضعیت فایل",
        lines=[f"کد: {code}", f"وضعیت جدید: {status}"]
        + ([f"دلیل: {reason}"] if reason else []),
    )


def _tool_propose_partner_decision(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    phone = _norm_phone(str(args.get("phone") or ""))
    decision = str(args.get("decision") or "").strip().lower()
    if len(phone) != 11 or decision not in ("approve", "reject"):
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "شماره ۱۱رقمی و decision=approve|reject لازم است.",
            },
        }
    send_sms = bool(args.get("send_sms", True))
    name = str(args.get("name") or "").strip()
    city = str(args.get("city") or "").strip()
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_partner_decision",
        payload={
            "phone": phone,
            "decision": decision,
            "name": name,
            "city": city,
            "send_sms": send_sms,
        },
        title="تأیید تصمیم همکار" if decision == "approve" else "تأیید رد همکار",
        lines=[
            f"شماره: {phone}",
            f"تصمیم: {'تأیید' if decision == 'approve' else 'رد'}",
        ]
        + ([f"نام: {name}"] if name else [])
        + ([f"شهر: {city}"] if city else []),
        confirm_label="تأیید همکار" if decision == "approve" else "رد درخواست",
    )


def _tool_propose_visit_admin(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    vid = str(args.get("visit_id") or "").strip()
    status = str(args.get("status") or "").strip().lower()
    note = str(args.get("admin_note") or "").strip()
    if not vid or not status:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "visit_id و status لازم است.",
            },
        }
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_visit_admin_action",
        payload={"visit_id": vid, "status": status, "admin_note": note},
        title="تأیید اقدام بازدید",
        lines=[f"بازدید: {vid}", f"وضعیت: {status}"]
        + ([f"یادداشت: {note}"] if note else []),
    )


def _tool_propose_commission(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if action not in ("approve_commission", "reject_commission", "paid_withdrawal"):
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "action یکی از approve_commission|reject_commission|paid_withdrawal.",
            },
        }
    payload = {
        "action": action,
        "commission_id": args.get("commission_id"),
        "withdrawal_id": str(args.get("withdrawal_id") or "").strip(),
        "note": str(args.get("note") or "").strip(),
    }
    lines = [f"اقدام: {action}"]
    if payload.get("commission_id") is not None:
        lines.append(f"پورسانت: {payload['commission_id']}")
    if payload.get("withdrawal_id"):
        lines.append(f"برداشت: {payload['withdrawal_id']}")
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_commission_action",
        payload=payload,
        title="تأیید اقدام مالی",
        lines=lines,
    )


def _tool_propose_answer_escalation(args: dict[str, Any], *, admin_key: str) -> dict[str, Any]:
    eid = str(args.get("escalation_id") or "").strip()
    answer = str(args.get("answer") or "").strip()
    if not eid or not answer:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "instruction": "escalation_id و متن پاسخ لازم است.",
            },
        }
    return _propose_card(
        user_key=admin_key,
        action_type="confirm_answer_escalation",
        payload={"escalation_id": eid, "answer": answer},
        title="تأیید پاسخ escalation",
        lines=[f"شناسه: {eid}", f"پاسخ: {answer[:300]}"],
        confirm_label="ارسال پاسخ",
    )


# ----- execute on confirm -----


def _exec_broadcast_sms(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    group = str(payload.get("recipient_group") or "partners").strip()
    if not message:
        return {"ok": False, "error": "متن پیامک خالی است."}
    try:
        from admin.sms_recipients import (
            count_sms_recipients,
            load_sms_recipients,
            normalize_recipient_group,
            recipient_group_label,
        )
        from admin.sms_scheduled import send_direct_to_recipients
        from app.services.sms_config import get_sms_line_number

        group = normalize_recipient_group(group)
        label = recipient_group_label(group)
        count = count_sms_recipients(group)
        if count < 1:
            return {"ok": False, "error": f"گیرنده‌ای در «{label}» نیست."}
        line = (get_sms_line_number() or "09981801922").strip()
        recipients = load_sms_recipients(group, limit=None, offset=0, validate=False)
        sent, failed, _details = send_direct_to_recipients(recipients, message, line)
        return {
            "ok": True,
            "message": f"پیامک به {sent} نفر از «{label}» ارسال شد"
            + (f" ({failed} خطا)." if failed else "."),
            "sent": sent,
            "failed": failed,
        }
    except Exception as exc:
        return {"ok": False, "error": f"ارسال پیامک ناموفق: {exc}"}


def _exec_broadcast_push(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    ntype = str(payload.get("ntype") or "admin_broadcast").strip()
    if not title or not body:
        return {"ok": False, "error": "عنوان/متن پوش ناقص است."}
    try:
        from admin.routes import (
            _load_approved_express_partners,
            _send_colleagues_notification_broadcast,
        )

        partners = _load_approved_express_partners() or []
        if not partners:
            return {"ok": False, "error": "همکار تأییدشده‌ای نیست."}
        result = _send_colleagues_notification_broadcast(
            title, body, ntype, partners, source="admin_ops_chat"
        )
        sent = int(result.get("sent") or 0)
        failed = int(result.get("failed") or 0)
        return {
            "ok": True,
            "message": f"پوش برای {sent} همکار ثبت شد"
            + (f" ({failed} خطا)." if failed else "."),
            "sent": sent,
            "failed": failed,
        }
    except Exception as exc:
        return {"ok": False, "error": f"ارسال پوش ناموفق: {exc}"}


def _exec_add_listing(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from admin.routes import _lands_path, _next_numeric_code
        from app.utils.storage import load_json, save_json

        title = str(payload.get("title") or "").strip()
        city = str(payload.get("city") or "").strip()
        location = str(payload.get("location") or "").strip()
        size = int(payload.get("size") or 0)
        price_total = int(payload.get("price_total") or 0)
        pct = float(payload.get("express_commission_pct") or 0)
        if not all([title, city, location]) or size <= 0 or price_total <= 0 or pct <= 0:
            return {"ok": False, "error": "اطلاعات فایل ناقص است."}
        lands = load_json(_lands_path()) or []
        if not isinstance(lands, list):
            lands = []
        code = _next_numeric_code(lands)
        ppm = int(round(price_total / size)) if size else 0
        amount = int(round(price_total * (pct / 100.0)))
        land = {
            "code": code,
            "title": title,
            "location": location,
            "city": city,
            "size": size,
            "price_total": price_total,
            "price_per_meter": ppm,
            "description": str(payload.get("description") or "").strip(),
            "images": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "owner": "vinor_support",
            "status": "approved",
            "ad_type": "express",
            "category": str(payload.get("category") or "").strip(),
            "payment_method": str(payload.get("payment_method") or "نقدی").strip(),
            "payment_terms": [],
            "is_express": True,
            "express_status": "approved",
            "expert_verified": False,
            "express_documents": [],
            "vinor_contact": str(payload.get("vinor_contact") or "09121471301"),
            "extras": {
                "express_commission_pct": pct,
                "express_commission_amount": amount,
            },
            "source": "admin_ops_chat",
        }
        lands.append(land)
        save_json(_lands_path(), lands)
        return {
            "ok": True,
            "message": f"فایل «{title}» با کد {code} ثبت شد.",
            "land_code": code,
        }
    except Exception as exc:
        return {"ok": False, "error": f"ثبت فایل ناموفق: {exc}"}


def _exec_update_listing(payload: dict[str, Any]) -> dict[str, Any]:
    code = str(payload.get("land_code") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    try:
        from admin.routes import _lands_path
        from app.utils.storage import load_json, save_json

        lands = load_json(_lands_path()) or []
        if not isinstance(lands, list):
            lands = []
        target = None
        for land in lands:
            if isinstance(land, dict) and str(land.get("code") or "") == code:
                target = land
                break
        if not target:
            return {"ok": False, "error": "فایل یافت نشد."}
        target["status"] = status
        if target.get("is_express") or target.get("ad_type") == "express":
            target["express_status"] = status
        if status == "rejected" and reason:
            target["reject_reason"] = reason
        save_json(_lands_path(), lands)
        return {"ok": True, "message": f"وضعیت فایل {code} → {status}."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _exec_partner_decision(payload: dict[str, Any]) -> dict[str, Any]:
    phone = _norm_phone(str(payload.get("phone") or ""))
    decision = str(payload.get("decision") or "").strip().lower()
    if len(phone) != 11:
        return {"ok": False, "error": "شماره نامعتبر است."}
    try:
        from app.utils.storage import (
            load_express_partner_apps,
            save_express_partner_apps,
        )

        apps = load_express_partner_apps() or []
        application = None
        for a in apps:
            if isinstance(a, dict) and _norm_phone(str(a.get("phone") or "")) == phone:
                application = a
                break

        if decision == "reject":
            if not application:
                return {"ok": False, "error": "درخواست همکاری یافت نشد."}
            application["status"] = "rejected"
            application["rejected_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            save_express_partner_apps(apps)
            try:
                from app.express_partner.referrals import mark_referral_rejected_for_application

                mark_referral_rejected_for_application(application)
            except Exception:
                pass
            return {"ok": True, "message": f"درخواست {phone} رد شد."}

        from admin.routes import _approve_express_partner
        from app.ai.chat_store import promote_public_chat_to_partner

        name = str(payload.get("name") or (application or {}).get("name") or "").strip()
        city = str(payload.get("city") or (application or {}).get("city") or "").strip()
        result = _approve_express_partner(
            phone=phone,
            name=name,
            city=city,
            national_id=str((application or {}).get("national_id") or ""),
            referred_by_phone=str((application or {}).get("referred_by_phone") or ""),
            application=application,
            remove_application=bool(application),
            send_sms=bool(payload.get("send_sms", True)),
            source="admin_ops_chat",
        )
        if not result.get("ok"):
            return {"ok": False, "error": str(result.get("error") or "تأیید ناموفق بود.")}
        try:
            promote_public_chat_to_partner(phone)
        except Exception:
            pass
        return {"ok": True, "message": f"همکار {phone} تأیید شد."}
    except Exception as exc:
        return {"ok": False, "error": f"تصمیم همکار ناموفق: {exc}"}


def _exec_visit_admin(payload: dict[str, Any]) -> dict[str, Any]:
    vid = str(payload.get("visit_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    note = str(payload.get("admin_note") or "").strip()
    try:
        from app.express_partner.visit_requests import (
            admin_can_transition_visit,
            admin_update_visit_request_status,
        )
        from app.utils.storage import load_express_visit_requests, save_express_visit_requests

        items = load_express_visit_requests() or []
        if not isinstance(items, list):
            items = []
        prev = ""
        for row in items:
            if isinstance(row, dict) and str(row.get("id") or "") == vid:
                prev = str(row.get("status") or "").strip()
                break
        if prev and status and not admin_can_transition_visit(prev, status):
            return {
                "ok": False,
                "error": f"تغییر وضعیت از {prev} به {status} مجاز نیست.",
            }
        rec, err = admin_update_visit_request_status(
            items, vid, status, admin_note=note
        )
        if err == "not_found":
            return {"ok": False, "error": "بازدید یافت نشد."}
        if err == "invalid_status":
            return {"ok": False, "error": "وضعیت نامعتبر است."}
        if err == "unchanged":
            return {"ok": True, "message": "تغییری لازم نبود.", "already": True}
        save_express_visit_requests(items)
        return {
            "ok": True,
            "message": f"بازدید {vid}: {prev or '?'} → {status}.",
            "visit_id": vid,
            "land_code": str((rec or {}).get("land_code") or ""),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _exec_commission(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    try:
        from app.utils.storage import (
            load_express_commissions,
            load_partner_withdrawals,
            save_express_commissions,
            save_partner_withdrawals,
        )

        if action in ("approve_commission", "reject_commission"):
            cid = int(payload.get("commission_id") or 0)
            if not cid:
                return {"ok": False, "error": "commission_id لازم است."}
            items = load_express_commissions() or []
            target = None
            for c in items:
                try:
                    if int(c.get("id") or 0) == cid:
                        target = c
                        break
                except Exception:
                    continue
            if not target:
                return {"ok": False, "error": "پورسانت یافت نشد."}
            if action == "approve_commission":
                if target.get("status") != "pending":
                    return {
                        "ok": True,
                        "message": "پورسانت قبلاً تأیید شده یا قابل تأیید نیست.",
                        "already": True,
                    }
                target["status"] = "approved"
                target["approved_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                save_express_commissions(items)
                return {"ok": True, "message": f"پورسانت {cid} تأیید شد."}
            if target.get("status") not in ("pending", "approved"):
                return {"ok": False, "error": "این پورسانت قابل رد نیست."}
            target["status"] = "rejected"
            save_express_commissions(items)
            return {"ok": True, "message": f"پورسانت {cid} رد شد."}

        if action == "paid_withdrawal":
            wid = str(payload.get("withdrawal_id") or "").strip()
            if not wid:
                return {"ok": False, "error": "withdrawal_id لازم است."}
            items = load_partner_withdrawals() or []
            row = next(
                (
                    w
                    for w in items
                    if isinstance(w, dict) and str(w.get("id") or "") == wid
                ),
                None,
            )
            if not row:
                return {"ok": False, "error": "برداشت یافت نشد."}
            old = str(row.get("status") or "").lower()
            if old == "paid":
                return {"ok": True, "message": "قبلاً پرداخت‌شده است.", "already": True}
            try:
                from app.express_partner.partner_withdrawals import admin_can_transition

                if not admin_can_transition(old, "paid"):
                    return {
                        "ok": False,
                        "error": f"تغییر از {old} به paid مجاز نیست.",
                    }
            except Exception:
                pass
            row["status"] = "paid"
            row["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            note = str(payload.get("note") or "").strip()
            if note:
                row["admin_note"] = note
            save_partner_withdrawals(items)
            return {"ok": True, "message": f"برداشت {wid} پرداخت‌شده شد."}

        return {"ok": False, "error": "اقدام مالی نامعتبر است."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _exec_answer_escalation(payload: dict[str, Any]) -> dict[str, Any]:
    eid = str(payload.get("escalation_id") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    if not eid or not answer:
        return {"ok": False, "error": "شناسه یا پاسخ خالی است."}
    try:
        from app.ai.escalations import answer_escalation

        result = answer_escalation(eid, answer)
        if not result.get("ok"):
            return {"ok": False, "error": str(result.get("error") or "ثبت پاسخ ناموفق.")}
        n = int(result.get("delivered_count") or 0)
        return {
            "ok": True,
            "message": f"پاسخ در {n} چت نمایش داده شد.",
            "delivered_count": n,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def is_admin_voice(voice: str | None) -> bool:
    return (voice or "").strip().lower() == VOICE_ADMIN


def is_admin_audience(audience: str | None) -> bool:
    return (audience or "").strip().lower() == AUDIENCE_ADMIN
