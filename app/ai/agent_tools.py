"""ابزارهای محدود Vinor AI به‌عنوان مشاور املاک — جستجو، کار بعدی، پیشنهاد بازدید."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app, url_for
from markupsafe import escape

from app.ai.audience import (
    AUDIENCE_PARTNER,
    AUDIENCE_PUBLIC,
    VOICE_PARTNER,
    VOICE_PUBLIC,
    VOICE_SPECIAL,
)
from app.ai.context import _land_matches_query, _land_summary, _select_lands_for_query
from app.ai.land_cards import accessible_lands_map, partner_is_approved
from app.ai.paths import ai_data_file

_PENDING_TTL_MIN = 30
_MAX_SEARCH = 5

TOOL_SEARCH = "search_lands"
TOOL_NEXT = "suggest_next_action"
TOOL_VISIT = "propose_visit_request"


def agent_system_hint(voice: str | None) -> str:
    v = (voice or "").strip().lower()
    if v == VOICE_PUBLIC:
        return (
            "ابزار: فقط search_lands برای یافتن ملک از داده سیستم. "
            "در پاسخ نهایی از [[LAND:کد]] برای پیشنهاد استفاده کن. "
            "ثبت بازدید همکار در دسترس این مخاطب نیست."
        )
    return (
        "ابزارها (اجباری وقتی لازم است): "
        "1) search_lands — جستجوی فایل/ملک؛ در پاسخ نهایی [[LAND:کد]] بگذار. "
        "2) suggest_next_action — کار بعدی واقعی داشبورد. "
        "3) propose_visit_request — فقط پیشنهاد ثبت بازدید؛ ثبت نهایی فقط با تأیید کاربر در کارت. "
        "هرگز ادعا نکن بازدید ثبت شد مگر ابزار تأیید کاربر را بگوید. "
        "اگر اطلاعات مشتری یا تاریخ ناقص است، اول بپرس؛ ابزار را با حدس پر نکن."
    )


def tools_schema_for_voice(voice: str | None) -> list[dict[str, Any]]:
    v = (voice or "").strip().lower()
    schemas: list[dict[str, Any]] = [_schema_search()]
    if v in (VOICE_PARTNER, VOICE_SPECIAL):
        schemas.append(_schema_next())
        schemas.append(_schema_visit())
    return schemas


def _schema_search() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH,
            "description": (
                "جستجوی فایل/ملک در لیست قابل‌دسترس کاربر بر اساس شهر، محله، کد، نوع یا کلمه کلیدی."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "عبارت جستجو مثل شهر، کد فایل، ویلا، باغ",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "حداکثر تعداد نتیجه (۱ تا ۵)",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _schema_next() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NEXT,
            "description": "پیشنهاد دقیق کار بعدی همکار بر اساس وضعیت زنده داشبورد (بازدید امروز، معامله، برداشت، پیگیری).",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _schema_visit() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_VISIT,
            "description": (
                "آماده‌سازی پیشنهاد ثبت بازدید برای فایل اختصاصی همکار. "
                "ثبت نهایی فقط پس از تأیید کاربر انجام می‌شود."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string", "description": "کد فایل"},
                    "visit_date": {
                        "type": "string",
                        "description": "تاریخ بازدید YYYY-MM-DD",
                    },
                    "customer_first_name": {"type": "string"},
                    "customer_last_name": {"type": "string"},
                    "customer_phone": {
                        "type": "string",
                        "description": "موبایل مشتری ایران",
                    },
                },
                "required": [
                    "land_code",
                    "visit_date",
                    "customer_first_name",
                    "customer_last_name",
                    "customer_phone",
                ],
            },
        },
    }


def run_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    phone: str,
    audience: str | None,
    voice: str | None,
) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    n = (name or "").strip()
    try:
        if n == TOOL_SEARCH:
            return _tool_search_lands(args, phone=phone, audience=audience)
        if n == TOOL_NEXT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("این ابزار برای مشتری عادی فعال نیست.")
            return _tool_suggest_next_action(phone=phone)
        if n == TOOL_VISIT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت بازدید فقط برای همکار اکسپرس است.")
            return _tool_propose_visit(args, phone=phone)
        return _denied(f"ابزار ناشناخته: {n}")
    except Exception as exc:
        try:
            current_app.logger.warning("AI tool failed | name=%s | err=%s", n, exc)
        except Exception:
            pass
        return {
            "ok": False,
            "error": "اجرای ابزار با خطا مواجه شد.",
            "model_result": {"ok": False, "error": "tool_failed"},
        }


def _denied(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg, "model_result": {"ok": False, "error": msg}}


def _tool_search_lands(
    args: dict[str, Any],
    *,
    phone: str,
    audience: str | None,
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    try:
        limit = int(args.get("limit") or _MAX_SEARCH)
    except Exception:
        limit = _MAX_SEARCH
    limit = max(1, min(limit, _MAX_SEARCH))

    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    lands_map = accessible_lands_map(phone, aud)
    lands = list(lands_map.values())
    if not lands:
        out = {"ok": True, "count": 0, "lands": [], "note": "فایلی در دسترس نیست."}
        return {"ok": True, "model_result": out, "land_codes": []}

    matched = _select_lands_for_query(
        lands, query, default_limit=limit, match_limit=limit
    )
    # اگر کوئری هست ولی match ضعیف بود، باز هم matched از default_limit می‌آید
    if query:
        tight = [l for l in lands if _land_matches_query(l, query)]
        if tight:
            matched = tight[:limit]

    items: list[dict[str, Any]] = []
    codes: list[str] = []
    for land in matched:
        code = str(land.get("code") or "").strip()
        if not code:
            continue
        codes.append(code)
        assigned = not bool(land.get("_is_public"))
        items.append(
            {
                "code": code,
                "summary": _land_summary(land, assigned=assigned, compact=True),
                "title": str(land.get("title") or "").strip(),
                "city": str(land.get("city") or "").strip(),
                "assigned": assigned,
            }
        )

    model = {
        "ok": True,
        "count": len(items),
        "lands": items,
        "instruction": "در پاسخ نهایی برای هر پیشنهاد از [[LAND:کد]] در خط جدا استفاده کن.",
    }
    return {"ok": True, "model_result": model, "land_codes": codes}


def _tool_suggest_next_action(*, phone: str) -> dict[str, Any]:
    ph = (phone or "").strip()
    if not ph:
        return _denied("کاربر شناسایی نشد.")

    from flask import g, has_request_context

    from app.express_partner.routes import (
        _build_partner_dashboard_lands,
        _commissions_for_phone,
        _home_follow_up_count,
        _home_urgent_actions,
        _is_partner_approved,
        _partner_commission_stats,
    )
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        DONE_PENDING_STATUS,
        PENDING_STATUS,
    )
    from app.utils.storage import load_express_visit_requests

    profile = None
    if has_request_context():
        profile = getattr(g, "express_partner_profile", None)
    is_approved = _is_partner_approved(profile)
    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []
    assigned, _ = _build_partner_dashboard_lands(ph, is_approved)
    my_comms = _commissions_for_phone(ph)
    stats = _partner_commission_stats(ph, my_comms)
    withdrawable = int(stats.get("withdrawable_balance") or 0)
    follow_up = _home_follow_up_count(ph, visit_rows)
    actions = _home_urgent_actions(
        ph,
        assigned_lands=assigned,
        visit_rows=visit_rows,
        withdrawable_balance=withdrawable,
        follow_up_count=follow_up,
    )

    mine = [
        r
        for r in visit_rows
        if isinstance(r, dict) and str(r.get("partner_phone") or "").strip() == ph
    ]
    stats_bit = {
        "pending_visits": sum(1 for r in mine if str(r.get("status") or "") == PENDING_STATUS),
        "approved_visits": sum(1 for r in mine if str(r.get("status") or "") == APPROVED_STATUS),
        "done_pending": sum(1 for r in mine if str(r.get("status") or "") == DONE_PENDING_STATUS),
        "withdrawable": withdrawable,
        "assigned_files": len(assigned or []),
    }

    if actions:
        a = actions[0]
        model = {
            "ok": True,
            "has_urgent": True,
            "action": {
                "key": a.get("key"),
                "title": a.get("title"),
                "subtitle": a.get("subtitle"),
                "cta": a.get("cta"),
                "url": a.get("url"),
            },
            "stats": stats_bit,
            "instruction": "همین کار بعدی را اولویت بده؛ لینک را اگر لازم است کوتاه بگو.",
        }
        ui = {
            "type": "next_action",
            "title": str(a.get("title") or "کار بعدی"),
            "subtitle": str(a.get("subtitle") or ""),
            "cta": str(a.get("cta") or "مشاهده"),
            "url": str(a.get("url") or ""),
            "status": "ready",
        }
        return {"ok": True, "model_result": model, "ui_action": ui}

    model = {
        "ok": True,
        "has_urgent": False,
        "action": None,
        "stats": stats_bit,
        "instruction": "کار فوری نیست؛ پیشنهاد کن فایل مناسب جستجو یا معرفی کند.",
    }
    return {"ok": True, "model_result": model}


def _validate_visit_proposal(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    """اعتبارسنجی پیشنهاد بازدید — بدون ذخیره توکن."""
    from app.express_partner.routes import (
        _express_land_partner_ctx,
        _partner_land_tx_payload,
    )
    from app.express_partner.visit_requests import (
        partner_can_request_new_visit,
        partner_visit_completed,
        _parse_visit_date,
        is_visit_weekday_allowed,
        visit_allowed_weekdays_summary,
    )
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
    from app.utils.storage import (
        load_ads_cached,
        load_express_partners,
        load_express_visit_requests,
    )

    me = (phone or "").strip()
    if not me:
        return {"ok": False, "error": "کاربر شناسایی نشد."}
    if not partner_is_approved(me):
        return {"ok": False, "error": "برای ثبت بازدید باید حساب همکاری تأیید شده باشد."}

    code = str(args.get("land_code") or "").strip()
    visit_date = str(args.get("visit_date") or "").strip()
    first = str(args.get("customer_first_name") or "").strip()
    last = str(args.get("customer_last_name") or "").strip()
    phone_raw = str(args.get("customer_phone") or "").strip()
    cust_phone = normalize_iran_mobile(phone_raw) or phone_raw

    missing = []
    if not code:
        missing.append("کد فایل")
    if not visit_date:
        missing.append("تاریخ بازدید")
    if not first:
        missing.append("نام مشتری")
    if not last:
        missing.append("نام خانوادگی مشتری")
    if not phone_raw:
        missing.append("شماره مشتری")
    if missing:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": missing,
            "instruction": "از کاربر همین فیلدها را بپرس؛ دوباره ابزار را صدا بزن.",
        }

    if not is_valid_iran_mobile(cust_phone):
        return {
            "ok": False,
            "error": "شماره تماس مشتری معتبر نیست.",
            "instruction": "شماره صحیح ۱۱ رقمی ایران بخواه.",
        }

    vd = _parse_visit_date(visit_date)
    if vd is None:
        return {"ok": False, "error": "تاریخ نامعتبر است. قالب YYYY-MM-DD."}
    if not is_visit_weekday_allowed(vd):
        return {
            "ok": False,
            "error": "روز انتخاب‌شده مجاز نیست.",
            "allowed": visit_allowed_weekdays_summary(),
        }

    ctx = _express_land_partner_ctx(code, me)
    if ctx is None:
        return {"ok": False, "error": "فایل پیدا نشد یا در اکسپرس نیست."}
    if not ctx.get("my_assignment"):
        return {
            "ok": False,
            "error": "برای این فایل انتساب فعالی ندارید؛ فقط فایل اختصاصی خودتان.",
        }

    current_status = ctx["global_status"]
    holder_phone = ctx.get("holder_phone")
    if current_status == "sold":
        return {"ok": False, "error": "فایل فروخته شده است."}
    if holder_phone and holder_phone != me:
        return {"ok": False, "error": "فایل در معامله همکار دیگر است."}
    if current_status == "in_transaction" or holder_phone == me:
        return {
            "ok": False,
            "error": "فایل در حال معامله است؛ ابتدا معامله را رفع کنید.",
        }

    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []
    if not partner_can_request_new_visit(current_status, visit_requests, me, str(code)):
        return {"ok": False, "error": "الان امکان ثبت بازدید جدید برای این فایل نیست."}
    if partner_visit_completed(visit_requests, me, str(code)):
        tx_revisit = _partner_land_tx_payload(
            code,
            me,
            is_partner_approved=True,
            global_assignment_status=current_status,
        )
        if not tx_revisit.get("can_revisit"):
            return {"ok": False, "error": "تا تأیید ادمین، بازدید مجدد ممکن نیست."}

    lands_all = load_ads_cached() or []
    land = next((l for l in lands_all if str(l.get("code")) == str(code)), None)
    land_title = (land.get("title") if land else None) or code

    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get("phone")) == me), None)
    partner_name = (partner_profile.get("name") if partner_profile else None) or me

    return {
        "ok": True,
        "payload": {
            "land_code": str(code),
            "land_title": str(land_title),
            "visit_date": vd.isoformat(),
            "customer_first_name": first,
            "customer_last_name": last,
            "customer_phone": cust_phone,
            "partner_name": partner_name,
        },
    }


def _tool_propose_visit(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    checked = _validate_visit_proposal(args, phone=phone)
    if not checked.get("ok"):
        model = {k: v for k, v in checked.items() if k != "payload"}
        return {"ok": False, "model_result": model}

    me = (phone or "").strip()
    payload = checked["payload"]
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_visit",
        payload=payload,
    )
    cust_phone = str(payload.get("customer_phone") or "")
    masked = cust_phone[:4] + "***" + cust_phone[-3:] if len(cust_phone) >= 7 else "***"
    lines = [
        f"فایل: {payload.get('land_title')} ({payload.get('land_code')})",
        f"تاریخ: {payload.get('visit_date')}",
        f"مشتری: {payload.get('customer_first_name')} {payload.get('customer_last_name')}",
        f"تماس: {masked}",
    ]
    ui = {
        "type": "confirm_visit",
        "token": token,
        "title": "تأیید ثبت بازدید",
        "lines": lines,
        "status": "pending",
        "land_code": str(payload.get("land_code") or ""),
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "land_code": payload.get("land_code"),
        "visit_date": payload.get("visit_date"),
        "instruction": (
            "کارت تأیید برای کاربر نمایش داده می‌شود. "
            "بگو جزئیات را چک کند و فقط اگر موافق است «تأیید و ثبت» را بزند. "
            "هنوز بازدید ثبت نشده است."
        ),
    }
    return {
        "ok": True,
        "model_result": model,
        "ui_action": ui,
        "land_codes": [str(payload.get("land_code") or "")],
    }


def confirm_visit_from_token(*, phone: str, token: str) -> dict[str, Any]:
    """اجرای قطعی ثبت بازدید پس از تأیید کاربر."""
    from app.express_partner.routes import _sync_visit_customer_to_club
    from app.express_partner.visit_requests import (
        create_visit_request as record_visit_request,
    )
    from app.utils.storage import (
        load_express_visit_requests,
        save_express_visit_requests,
    )

    me = (phone or "").strip()
    pending = _load_pending_action(token)
    if not pending:
        return {"ok": False, "error": "این پیشنهاد منقضی یا نامعتبر است."}
    if str(pending.get("user_key") or "") != me:
        return {"ok": False, "error": "دسترسی به این پیشنهاد ندارید."}
    if str(pending.get("action_type") or "") != "confirm_visit":
        return {"ok": False, "error": "نوع اقدام نامعتبر است."}

    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    code = str(payload.get("land_code") or "").strip()
    if not code:
        return {"ok": False, "error": "اطلاعات بازدید ناقص است."}

    recheck = _validate_visit_proposal(
        {
            "land_code": code,
            "visit_date": payload.get("visit_date"),
            "customer_first_name": payload.get("customer_first_name"),
            "customer_last_name": payload.get("customer_last_name"),
            "customer_phone": payload.get("customer_phone"),
        },
        phone=me,
    )
    if not recheck.get("ok"):
        return {"ok": False, "error": str(recheck.get("error") or "امکان ثبت وجود ندارد.")}

    fresh = recheck.get("payload") if isinstance(recheck.get("payload"), dict) else payload
    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    rec, err = record_visit_request(
        visit_requests,
        partner_phone=me,
        partner_name=str(fresh.get("partner_name") or me),
        land_code=code,
        land_title=str(fresh.get("land_title") or code),
        visit_date=str(fresh.get("visit_date") or ""),
        customer_first_name=str(fresh.get("customer_first_name") or ""),
        customer_last_name=str(fresh.get("customer_last_name") or ""),
        customer_phone=str(fresh.get("customer_phone") or ""),
    )
    if err == "already_pending":
        _consume_pending_action(token)
        return {
            "ok": True,
            "already": True,
            "message": "درخواست بازدید قبلاً ثبت شده است.",
            "requests_url": url_for("express_partner.requests", submitted=1),
        }
    if err or not rec:
        msg_map = {
            "customer_required": "نام و شماره مشتری الزامی است.",
            "past_date": "تاریخ نمی‌تواند در گذشته باشد.",
            "date_too_far": "تاریخ حداکثر تا ۹۰ روز آینده است.",
            "weekday_not_allowed": "روز انتخاب‌شده مجاز نیست.",
            "invalid_date": "تاریخ نامعتبر است.",
            "invalid": "اطلاعات نامعتبر است.",
        }
        return {"ok": False, "error": msg_map.get(str(err), "ثبت بازدید ممکن نشد.")}

    save_express_visit_requests(visit_requests)
    try:
        _sync_visit_customer_to_club(
            customer_phone=str(fresh.get("customer_phone") or ""),
            customer_first_name=str(fresh.get("customer_first_name") or ""),
            customer_last_name=str(fresh.get("customer_last_name") or ""),
        )
    except Exception:
        pass

    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "درخواست بازدید ثبت شد و منتظر تأیید تیم وینور است.",
        "visit_id": str(rec.get("id") or ""),
        "land_code": code,
        "requests_url": url_for("express_partner.requests", submitted=1),
    }


def cancel_pending_action(*, phone: str, token: str) -> dict[str, Any]:
    pending = _load_pending_action(token)
    if not pending:
        return {"ok": True, "cancelled": True}
    if str(pending.get("user_key") or "") != (phone or "").strip():
        return {"ok": False, "error": "دسترسی ندارید."}
    _consume_pending_action(token)
    return {"ok": True, "cancelled": True}


def render_agent_actions_html(actions: list[dict[str, Any]] | None) -> str:
    if not actions:
        return ""
    parts: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        atype = str(action.get("type") or "")
        if atype == "confirm_visit":
            parts.append(_render_confirm_visit_card(action))
        elif atype == "next_action":
            parts.append(_render_next_action_card(action))
    if not parts:
        return ""
    return (
        '<div class="ai-agent-actions mt-2.5 flex w-full max-w-full flex-col gap-2.5">'
        + "".join(parts)
        + "</div>"
    )


def _render_confirm_visit_card(action: dict[str, Any]) -> str:
    token = str(action.get("token") or "").strip()
    title = escape(str(action.get("title") or "تأیید ثبت بازدید"))
    status = str(action.get("status") or "pending")
    if status == "pending" and token and _load_pending_action(token) is None:
        status = "expired"
    lines = action.get("lines") if isinstance(action.get("lines"), list) else []
    body = "".join(
        f'<div class="ai-agent-line">{escape(str(line))}</div>' for line in lines if str(line).strip()
    )
    if status != "pending" or not token:
        if status == "confirmed":
            note = "بازدید ثبت شد."
        elif status == "cancelled":
            note = "انصراف داده شد."
        else:
            note = "این پیشنهاد منقضی یا دیگر فعال نیست."
        return (
            f'<div class="ai-agent-card ai-agent-card--done" data-agent-status="{escape(status)}">'
            f'<div class="ai-agent-card__title">{title}</div>'
            f'<div class="ai-agent-card__body">{body}</div>'
            f'<div class="ai-agent-card__note">{escape(note)}</div>'
            f"</div>"
        )
    return (
        f'<div class="ai-agent-card" data-agent-type="confirm_visit" data-token="{escape(token)}">'
        f'<div class="ai-agent-card__title">{title}</div>'
        f'<div class="ai-agent-card__body">{body}</div>'
        f'<div class="ai-agent-card__actions">'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--confirm" data-agent-confirm>تأیید و ثبت</button>'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--cancel" data-agent-cancel>انصراف</button>'
        f"</div>"
        f'<div class="ai-agent-card__note hidden" data-agent-note></div>'
        f"</div>"
    )


def _render_next_action_card(action: dict[str, Any]) -> str:
    title = escape(str(action.get("title") or "کار بعدی"))
    subtitle = escape(str(action.get("subtitle") or ""))
    cta = escape(str(action.get("cta") or "مشاهده"))
    url = str(action.get("url") or "").strip()
    link = ""
    if url:
        link = (
            f'<a class="ai-agent-btn ai-agent-btn--confirm" href="{escape(url)}">{cta}</a>'
        )
    sub_html = f'<div class="ai-agent-line">{subtitle}</div>' if subtitle else ""
    return (
        f'<div class="ai-agent-card ai-agent-card--hint" data-agent-type="next_action">'
        f'<div class="ai-agent-card__title">{title}</div>'
        f'<div class="ai-agent-card__body">{sub_html}</div>'
        f'<div class="ai-agent-card__actions">{link}</div>'
        f"</div>"
    )


def _pending_path() -> str:
    path = ai_data_file("ai_pending_actions.json")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
    return path


def _read_pending_store() -> dict[str, Any]:
    path = _pending_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_pending_store(data: dict[str, Any]) -> None:
    path = _pending_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _store_pending_action(
    *,
    user_key: str,
    action_type: str,
    payload: dict[str, Any],
) -> str:
    store = _read_pending_store()
    _prune_pending(store)
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    store[token] = {
        "user_key": user_key,
        "action_type": action_type,
        "payload": payload,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(minutes=_PENDING_TTL_MIN)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    _write_pending_store(store)
    return token


def _load_pending_action(token: str) -> dict[str, Any] | None:
    tok = (token or "").strip()
    if not tok:
        return None
    store = _read_pending_store()
    _prune_pending(store)
    item = store.get(tok)
    if not isinstance(item, dict):
        return None
    exp = str(item.get("expires_at") or "")
    try:
        exp_dt = datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            store.pop(tok, None)
            _write_pending_store(store)
            return None
    except Exception:
        pass
    return item


def _consume_pending_action(token: str) -> None:
    tok = (token or "").strip()
    if not tok:
        return
    store = _read_pending_store()
    if tok in store:
        store.pop(tok, None)
        _write_pending_store(store)


def _prune_pending(store: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    dead: list[str] = []
    for tok, item in list(store.items()):
        if not isinstance(item, dict):
            dead.append(tok)
            continue
        exp = str(item.get("expires_at") or "")
        try:
            exp_dt = datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if exp_dt < now:
                dead.append(tok)
        except Exception:
            dead.append(tok)
    for tok in dead:
        store.pop(tok, None)


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
