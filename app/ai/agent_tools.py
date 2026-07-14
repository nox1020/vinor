"""ابزارهای محدود Vinor AI به‌عنوان مشاور املاک — جستجو، کار بعدی، پیشنهاد بازدید."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app
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
TOOL_COMPLETE_VISIT = "propose_complete_visit"
TOOL_DEAL = "propose_deal"
TOOL_RELEASE = "propose_release_deal"
TOOL_LISTING = "draft_listing_copy"
TOOL_COOP_INFO = "get_cooperation_info"
TOOL_APP_STATUS = "get_application_status"
TOOL_PROPOSE_APPLY = "propose_partner_application"


def _active_mission_land_code(phone: str) -> str:
    """کد فایل مأموریت فعال همکار — اگر نباشد خالی."""
    ph = (phone or "").strip()
    if not ph:
        return ""
    try:
        from app.express_partner.partner_missions import (
            get_active_mission,
            refresh_mission_if_land_closed,
        )

        mission = refresh_mission_if_land_closed(ph) or get_active_mission(ph)
        if not mission:
            return ""
        return str(mission.get("land_code") or "").strip()
    except Exception:
        return ""


def _resolve_tool_land_code(phone: str, args: dict[str, Any] | None = None) -> str:
    """کد فایل از آرگومان ابزار، وگرنه از مأموریت فعال."""
    raw = ""
    if isinstance(args, dict):
        raw = str(args.get("land_code") or "").strip()
    if raw:
        return raw
    return _active_mission_land_code(phone)


def agent_system_hint(voice: str | None) -> str:
    """یادآوری کوتاه مسیریابی ابزار — جزئیات در system prompt است."""
    v = (voice or "").strip().lower()
    if v == VOICE_PUBLIC:
        return (
            "ابزار: search→ملک | coop_info→همکاری | app_status→وضعیت | propose_apply→کارت ثبت "
            "(نام/کدملی/شهر یکی‌یکی؛ need_login=منوی راست). فروش همکار نزن."
        )
    return (
        "ابزار وقتی لازم: search→[[LAND]] | next→کار بعدی | listing→کارت کپی "
        "| propose_visit/complete/deal/release→کارت تأیید. "
        "بازدید: نام→نام‌خانوادگی→شماره→propose بدون تاریخ→لیست ۱…۵→فقط visit_date. مأموریت: land_code خالی."
    )


def tools_schema_for_voice(voice: str | None) -> list[dict[str, Any]]:
    v = (voice or "").strip().lower()
    schemas: list[dict[str, Any]] = [_schema_search()]
    if v == VOICE_PUBLIC:
        schemas.append(_schema_coop_info())
        schemas.append(_schema_app_status())
        schemas.append(_schema_propose_apply())
        return schemas
    if v in (VOICE_PARTNER, VOICE_SPECIAL):
        schemas.append(_schema_next())
        schemas.append(_schema_listing())
        schemas.append(_schema_visit())
        schemas.append(_schema_complete_visit())
        schemas.append(_schema_deal())
        schemas.append(_schema_release())
    return schemas


def _schema_search() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH,
            "description": "جستجوی ملک در لیست قابل‌دسترس (شهر/کد/نوع/کلیدواژه).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "عبارت جستجو"},
                    "limit": {"type": "integer", "description": "۱ تا ۵"},
                },
                "required": ["query"],
            },
        },
    }


def _schema_coop_info() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_COOP_INFO,
            "description": "سطوح/شرایط/مسیر همکاری (بدون لینک). قبل از توضیح همکاری بزن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "levels|terms|how|all"},
                },
                "required": [],
            },
        },
    }


def _schema_app_status() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_APP_STATUS,
            "description": "وضعیت درخواست همکاری کاربر لاگین‌شده.",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _schema_propose_apply() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_PROPOSE_APPLY,
            "description": "کارت تأیید ثبت همکاری؛ فقط با نام+کدملی+شهر. مهمان→need_login.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "national_id": {"type": "string"},
                    "city": {"type": "string"},
                    "experience": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name", "national_id", "city"],
            },
        },
    }


def _schema_next() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NEXT,
            "description": "کار بعدی واقعی همکار از داشبورد.",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _schema_listing() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_LISTING,
            "description": "متن دیوار/اینستا برای فایل (مأموریت فعال→land_code لازم نیست).",
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "channel": {"type": "string", "description": "divar|instagram|both"},
                },
                "required": [],
            },
        },
    }


def _schema_visit() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_VISIT,
            "description": (
                "کارت ثبت بازدید. فیلدها را یکی‌یکی جمع کن: "
                "customer_first_name → customer_last_name → customer_phone → "
                "بدون visit_date صدا بزن تا لیست ۱…۵ تاریخ بیاید → فقط شمارهٔ تاریخ را در visit_date بفرست. "
                "مأموریت فعال→land_code اختیاری. ثبت فقط بعد از تأیید کارت."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "customer_first_name": {
                        "type": "string",
                        "description": "فقط نام کوچک مشتری",
                    },
                    "customer_last_name": {
                        "type": "string",
                        "description": "فقط نام خانوادگی مشتری",
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "اختیاری/قدیمی؛ ترجیح first+last جدا",
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "موبایل ۱۱ رقمی ایران",
                    },
                    "visit_date": {
                        "type": "string",
                        "description": "شماره ۱ تا ۵ از لیست، یا YYYY-MM-DD؛ خالی=لیست تاریخ",
                    },
                },
            },
        },
    }


def _schema_complete_visit() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_COMPLETE_VISIT,
            "description": "کارت «بازدید انجام شد»؛ مأموریت فعال→land_code اختیاری.",
            "parameters": {
                "type": "object",
                "properties": {"land_code": {"type": "string"}},
                "required": [],
            },
        },
    }


def _schema_deal() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_DEAL,
            "description": "کارت ثبت معامله/فروش نهایی (بازدید تکمیل‌شده). land_code اختیاری اگر مأموریت فعال.",
            "parameters": {
                "type": "object",
                "properties": {"land_code": {"type": "string"}},
                "required": [],
            },
        },
    }


def _schema_release() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_RELEASE,
            "description": "کارت انصراف از معاملهٔ در انتظار تأیید. land_code اختیاری اگر مأموریت فعال.",
            "parameters": {
                "type": "object",
                "properties": {"land_code": {"type": "string"}},
                "required": [],
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
        if n == TOOL_COOP_INFO:
            return _tool_coop_info(args)
        if n == TOOL_APP_STATUS:
            return _tool_application_status(phone=phone)
        if n == TOOL_PROPOSE_APPLY:
            return _tool_propose_partner_application(args, phone=phone)
        if n == TOOL_NEXT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("این ابزار برای مشتری عادی فعال نیست.")
            return _tool_suggest_next_action(phone=phone)
        if n == TOOL_LISTING:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("متن آگهی فروش برای مشتری عادی فعال نیست.")
            return _tool_draft_listing(args, phone=phone, audience=audience)
        if n == TOOL_VISIT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت بازدید فقط برای همکار اکسپرس است.")
            return _tool_propose_visit(args, phone=phone)
        if n == TOOL_COMPLETE_VISIT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت انجام بازدید فقط برای همکار است.")
            return _tool_propose_simple_tx(args, phone=phone, action_type="confirm_complete_visit")
        if n == TOOL_DEAL:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت معامله فقط برای همکار است.")
            return _tool_propose_simple_tx(args, phone=phone, action_type="confirm_deal")
        if n == TOOL_RELEASE:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("بستن معامله فقط برای همکار است.")
            return _tool_propose_simple_tx(args, phone=phone, action_type="confirm_release")
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


def _session_phone() -> str:
    try:
        from flask import session

        return str(session.get("user_phone") or "").strip()
    except Exception:
        return ""


def _tool_coop_info(args: dict[str, Any]) -> dict[str, Any]:
    topic = str(args.get("topic") or "all").strip().lower() or "all"
    cities: list[str] = []
    try:
        from app.utils.storage import load_active_cities

        cities = [str(c) for c in (load_active_cities() or []) if str(c).strip()][:12]
    except Exception:
        cities = []
    city_bit = f"شهرهای فعال: {', '.join(cities)}." if cities else ""

    blocks: dict[str, str] = {
        "levels": (
            "سطوح: ۱) کاربر عادی — چت و درخواست همکاری. "
            "۲) همکار — بعد از تأیید، فایل آماده می‌گیرد، می‌فروشد، پورسانت می‌گیرد؛ کار اصلی از چت. "
            "۳) همکار ویژه — مالک/فروشنده با آگهی و بازدیدهای خودش."
        ),
        "terms": (
            "شرایط: فایل‌های تأییدشده با قیمت و پورسانت مشخص؛ فروش؛ بعد از تأیید معامله پورسانت به کیف پول. "
            "وینور پرونده را بررسی می‌کند. " + city_bit
        ),
        "how": (
            "شروع از همین چت: بگو می‌خواهم همکار شوم → اگر وارد نیستی منوی راست ورود → "
            "نام، کد ملی، شهر → کارت تأیید → بررسی تیم. لینک صفحه نده."
        ),
    }
    if topic in blocks:
        chosen = {topic: blocks[topic]}
    else:
        chosen = blocks
    model = {
        "ok": True,
        "topic": topic if topic in blocks else "all",
        "facts": chosen,
        "instruction": (
            "همین facts را کوتاه و خودمونی بگو. URL/مسیر صفحه نده. "
            "اگر خواست ثبت کند، فیلدها را یکی‌یکی بپرس و propose_partner_application بزن."
        ),
    }
    return {"ok": True, "model_result": model}


def _tool_application_status(*, phone: str) -> dict[str, Any]:
    me = _session_phone() or (
        phone if phone and not str(phone).startswith("guest_") else ""
    )
    if not me:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "need_login": True,
                "instruction": "وارد نشده؛ از منوی راست بخواهد وارد شود. لینک نده.",
            },
            "ui_action": {
                "type": "need_login",
                "title": "ورود برای دیدن وضعیت",
                "subtitle": "با شماره موبایل وارد شو تا وضعیت درخواست را بگویم.",
                "cta": "ورود",
            },
        }
    try:
        from app.express_partner.routes import (
            _get_my_last_application,
            _is_partner_approved,
            _partner_profile_for_phone,
        )

        if _is_partner_approved(_partner_profile_for_phone(me)):
            model = {
                "ok": True,
                "status": "approved",
                "label": "همکار تأییدشده",
                "instruction": "کوتاه بگو الان همکار است و از چت خانه کار فروش را جلو ببرد.",
            }
            return {"ok": True, "model_result": model}

        last = _get_my_last_application(me)
        if not last:
            model = {
                "ok": True,
                "status": "none",
                "label": "بدون درخواست",
                "instruction": "بگو هنوز درخواست نداده؛ اگر خواست از همین چت ثبت کنیم.",
            }
            return {"ok": True, "model_result": model}

        st = str(last.get("status") or "").strip().lower() or "new"
        label_map = {
            "new": "ثبت‌شده؛ در صف بررسی",
            "pending": "در انتظار بررسی",
            "under_review": "در حال بررسی",
            "approved": "تأیید شده",
            "rejected": "رد شده",
            "cancelled": "لغو شده",
        }
        model = {
            "ok": True,
            "status": st,
            "label": label_map.get(st, st),
            "name": str(last.get("name") or "").strip(),
            "city": str(last.get("city") or "").strip(),
            "instruction": "وضعیت را کوتاه بگو؛ لینک صفحه تشکر/درخواست نده.",
        }
        return {"ok": True, "model_result": model}
    except Exception as exc:
        return _denied(f"خواندن وضعیت ممکن نشد: {exc}")


def _tool_propose_partner_application(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    me = _session_phone() or (
        phone if phone and not str(phone).startswith("guest_") else ""
    )
    if not me:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "need_login": True,
                "missing": ["login"],
                "instruction": (
                    "کاربر مهمان است. بگو از منوی راست وارد شود تا درخواست را از همین چت ثبت کنیم. "
                    "URL نده. بعد از ورود دوباره همین ابزار را با همان فیلدها بزن."
                ),
            },
            "ui_action": {
                "type": "need_login",
                "title": "ورود برای ثبت همکاری",
                "subtitle": "با موبایل وارد شو؛ بعد از ورود درخواست را از همین چت تمام می‌کنیم.",
                "cta": "ورود",
            },
        }

    name = str(args.get("name") or "").strip()
    national_id = str(args.get("national_id") or "").strip()
    city = str(args.get("city") or "").strip()
    experience = str(args.get("experience") or "").strip()
    note = str(args.get("note") or "").strip()
    missing = [k for k, v in (("name", name), ("national_id", national_id), ("city", city)) if not v]
    if missing:
        return {
            "ok": True,
            "model_result": {
                "ok": False,
                "missing": missing,
                "instruction": "فقط فیلدهای missing را یکی‌یکی بپرس؛ لینک نده.",
            },
        }

    try:
        from app.express_partner.routes import (
            _active_cities_cached,
            _clip_apply_fields,
            _get_my_last_application,
            _has_active_application,
            _is_partner_approved,
            _parse_apply_national_id,
            _partner_profile_for_phone,
        )
        from app.utils.iran_ids import is_valid_iran_national_id

        if _is_partner_approved(_partner_profile_for_phone(me)):
            return {
                "ok": True,
                "model_result": {
                    "ok": False,
                    "already_partner": True,
                    "instruction": "هم‌اکنون همکار تأییدشده است؛ درخواست جدید لازم نیست.",
                },
            }
        if _has_active_application(me):
            last = _get_my_last_application(me) or {}
            return {
                "ok": True,
                "model_result": {
                    "ok": False,
                    "already_pending": True,
                    "status": str(last.get("status") or "pending"),
                    "instruction": "درخواست فعال دارد؛ بگو منتظر بررسی بماند.",
                },
            }

        name, city, experience, note = _clip_apply_fields(name, city, experience, note)
        national_id = _parse_apply_national_id(national_id)
        if not is_valid_iran_national_id(national_id):
            return {
                "ok": True,
                "model_result": {
                    "ok": False,
                    "invalid": "national_id",
                    "instruction": "کد ملی نامعتبر است؛ دوباره بپرس.",
                },
            }
        cities = _active_cities_cached() or []
        if cities and city not in cities:
            return {
                "ok": True,
                "model_result": {
                    "ok": False,
                    "invalid": "city",
                    "allowed_cities": list(cities)[:20],
                    "instruction": "شهر باید از allowed_cities باشد؛ دوباره بپرس.",
                },
            }
    except Exception as exc:
        return _denied(str(exc))

    payload = {
        "name": name,
        "national_id": national_id,
        "city": city,
        "experience": experience,
        "note": note,
        "source": "ai_chat",
    }
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_partner_application",
        payload=payload,
    )
    lines = [f"نام: {name}", f"کد ملی: {national_id}", f"شهر: {city}"]
    if experience:
        lines.append(f"سابقه: {experience}")
    if note:
        lines.append(f"توضیح: {note}")
    ui = {
        "type": "confirm_partner_application",
        "token": token,
        "title": "تأیید ثبت درخواست همکاری",
        "lines": lines,
        "status": "pending",
        "confirm_label": "ثبت درخواست",
        "cancel_label": "انصراف",
    }
    model = {
        "ok": True,
        "pending_confirm": True,
        "fields": {"name": name, "city": city, "national_id": national_id},
        "instruction": (
            "کارت تأیید نشان داده می‌شود. بگو روی تأیید بزند. "
            "تا تأیید نزده نگو ثبت شد. لینک صفحه نده."
        ),
    }
    return {"ok": True, "model_result": model, "ui_action": ui}


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

    coach_tip = ""
    coach_land_code = ""
    try:
        from app.express_partner.sales_coach import (
            coach_tip_for_stage,
            resolve_stuck_nudge_for_partner,
        )

        stuck = resolve_stuck_nudge_for_partner(
            ph, assigned_lands=assigned or [], visit_rows=visit_rows
        )
        if stuck:
            coach_tip = str(stuck.get("tip") or "")
            coach_land_code = str(stuck.get("code") or "")
        elif assigned:
            land0 = assigned[0]
            from app.express_partner.routes import _home_funnel_for_land

            funnel = _home_funnel_for_land(ph, land0, visit_rows=visit_rows)
            st0 = str(land0.get("_assignment_status") or "").strip().lower()
            coach_tip = coach_tip_for_stage(
                stage_label=str(funnel.get("stage_label") or ""),
                in_transaction=st0 == "in_transaction",
                sold=st0 == "sold",
                commission_amount=int(land0.get("_commission_amount") or 0),
            )
            coach_land_code = str(land0.get("code") or "")
    except Exception:
        pass

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
            "coach_tip": coach_tip,
            "coach_land_code": coach_land_code,
            "stats": stats_bit,
            "instruction": (
                "همین کار بعدی را اولویت بده و از چت مأموریت جلو ببر. "
                "اگر coach_tip هست یک جمله تشویقی اضافه کن. "
                "برای ثبت بازدید/انجام بازدید/معامله از ابزارهای propose_* استفاده کن. "
                "برای آگهی دیوار/اینستا از draft_listing_copy استفاده کن."
            ),
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
        "coach_tip": coach_tip
        or "فایل اختصاصی را در دیوار و اینستا آگهی کن؛ بعد تماس‌ها را به بازدید تبدیل کن.",
        "coach_land_code": coach_land_code,
        "stats": stats_bit,
        "instruction": (
            "کار فوری سیستمی نیست؛ مربی فروش باش: "
            "اگر فایل اختصاصی دارد بگو دیوار/اینستا آگهی کند و در صورت نیاز draft_listing_copy بزن. "
            "اگر فایل ندارد جستجو پیشنهاد بده."
        ),
    }
    return {"ok": True, "model_result": model}


def _tool_draft_listing(
    args: dict[str, Any],
    *,
    phone: str,
    audience: str | None,
) -> dict[str, Any]:
    code = _resolve_tool_land_code(phone, args)
    channel = str(args.get("channel") or "both").strip().lower() or "both"
    if not code:
        return _denied(
            "کد فایل مشخص نیست. اگر مأموریت فعال نیست، کد فایل را بپرس یا جستجو کن."
        )

    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    lands_map = accessible_lands_map(phone, aud)
    land = lands_map.get(code)
    if not land:
        for k, v in lands_map.items():
            if str(k).strip().lower() == code.lower():
                land = v
                break
    if not land:
        return _denied("این فایل در دسترس شما نیست یا پیدا نشد.")

    from app.express_partner.sales_coach import draft_listing_copy

    copies = draft_listing_copy(land, channel=channel)
    blocks: list[dict[str, str]] = []
    divar = str(copies.get("divar") or "").strip()
    insta = str(copies.get("instagram") or "").strip()
    if divar:
        blocks.append({"id": "divar", "label": "متن دیوار", "text": divar})
    if insta:
        blocks.append({"id": "instagram", "label": "کپشن اینستا", "text": insta})

    model = {
        "ok": True,
        "land_code": str(land.get("code") or code),
        "title": str(land.get("title") or "").strip(),
        "copies": {"divar": bool(divar), "instagram": bool(insta)},
        "copy_blocks_count": len(blocks),
        "instruction": "کارت کپی نشان داده شد؛ ۱–۲ جمله بگو و متن کامل را در پیام تکرار نکن.",
    }
    out: dict[str, Any] = {
        "ok": True,
        "model_result": model,
        "land_codes": [],
    }
    if blocks:
        out["ui_action"] = {
            "type": "copy_blocks",
            "title": "متن‌های آماده",
            "blocks": blocks,
        }
    return out


def _visit_draft_key(user_key: str) -> str:
    return f"visit_draft:{(user_key or '').strip()}"


def _save_visit_draft(user_key: str, draft: dict[str, Any]) -> None:
    """پیش‌نویس نام/شماره/فایل بین مرحلهٔ انتخاب تاریخ."""
    uk = (user_key or "").strip()
    if not uk or not isinstance(draft, dict):
        return
    store = _read_pending_store()
    _prune_pending(store)
    now = datetime.now(timezone.utc)
    store[_visit_draft_key(uk)] = {
        "user_key": uk,
        "action_type": "visit_draft",
        "payload": {
            "land_code": str(draft.get("land_code") or "").strip(),
            "customer_name": str(draft.get("customer_name") or "").strip(),
            "customer_first_name": str(draft.get("customer_first_name") or "").strip(),
            "customer_last_name": str(draft.get("customer_last_name") or "").strip(),
            "customer_phone": str(draft.get("customer_phone") or "").strip(),
        },
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(minutes=_PENDING_TTL_MIN)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    _write_pending_store(store)


def _load_visit_draft(user_key: str) -> dict[str, Any]:
    uk = (user_key or "").strip()
    if not uk:
        return {}
    store = _read_pending_store()
    _prune_pending(store)
    item = store.get(_visit_draft_key(uk))
    if not isinstance(item, dict):
        return {}
    exp = str(item.get("expires_at") or "")
    try:
        exp_dt = datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            store.pop(_visit_draft_key(uk), None)
            _write_pending_store(store)
            return {}
    except Exception:
        pass
    payload = item.get("payload")
    return payload if isinstance(payload, dict) else {}


def _clear_visit_draft(user_key: str) -> None:
    uk = (user_key or "").strip()
    if not uk:
        return
    store = _read_pending_store()
    if store.pop(_visit_draft_key(uk), None) is not None:
        _write_pending_store(store)


def _validate_visit_proposal(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    """اعتبارسنجی پیشنهاد بازدید — بدون ذخیره توکن."""
    from app.express_partner.routes import (
        _express_land_partner_ctx,
        _partner_land_tx_payload,
    )
    from app.express_partner.visit_requests import (
        list_upcoming_visit_dates,
        partner_can_request_new_visit,
        partner_open_visit,
        partner_visit_completed,
        resolve_visit_date_choice,
        split_customer_full_name,
        is_visit_weekday_allowed,
        visit_allowed_weekdays_summary,
        _today,
    )
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
    from app.utils.dates import format_display_jalali_date, format_iso_date_jalali
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

    draft = _load_visit_draft(me)
    merged = dict(args or {})
    # فیلدهای خالی را از پیش‌نویس مرحلهٔ قبل پر کن (نام/شماره بین انتخاب تاریخ)
    for key in (
        "land_code",
        "customer_name",
        "customer_first_name",
        "customer_last_name",
        "customer_phone",
    ):
        if not str(merged.get(key) or "").strip() and draft.get(key):
            merged[key] = draft.get(key)

    code = _resolve_tool_land_code(phone, merged)
    visit_date_raw = str(merged.get("visit_date") or "").strip()
    full_name = str(merged.get("customer_name") or "").strip()
    first = str(merged.get("customer_first_name") or "").strip()
    last = str(merged.get("customer_last_name") or "").strip()
    if full_name and (not first or not last):
        parts = [p for p in full_name.split() if p]
        if len(parts) >= 2:
            first, last = split_customer_full_name(full_name)
        elif parts and not first:
            first = parts[0]
    if first and last:
        full_name = f"{first} {last}".strip()
    phone_raw = str(merged.get("customer_phone") or "").strip()
    cust_phone = normalize_iran_mobile(phone_raw) or phone_raw

    available = list_upcoming_visit_dates(limit=5)
    available_labels = [str(x.get("label") or "") for x in available]

    # پیش‌نویس جزئی را نگه دار تا مراحل یکی‌یکی ادامه پیدا کند
    if code or first or last or phone_raw:
        _save_visit_draft(
            me,
            {
                "land_code": code,
                "customer_name": full_name or f"{first} {last}".strip(),
                "customer_first_name": first,
                "customer_last_name": last,
                "customer_phone": cust_phone if is_valid_iran_mobile(cust_phone) else phone_raw,
            },
        )

    # فقط همان قدم بعدی را برگردان تا مدل یکی‌یکی بپرسد
    if not code:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["land_code"],
            "mission_land_code": _active_mission_land_code(me),
            "instruction": (
                "کد فایل را بپرس یا جستجو کن. اگر مأموریت فعال است land_code خالی بگذار و دوباره بزن. "
                "هنوز نام/شماره/تاریخ نپرس."
            ),
        }
    if not first:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["customer_first_name"],
            "land_code": code,
            "instruction": "فقط نام کوچک مشتری را بپرس (نه نام خانوادگی، نه شماره، نه تاریخ).",
        }
    if not last:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["customer_last_name"],
            "land_code": code,
            "customer_first_name": first,
            "instruction": "فقط نام خانوادگی مشتری را بپرس (نه شماره، نه تاریخ).",
        }
    if not phone_raw:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["customer_phone"],
            "land_code": code,
            "customer_first_name": first,
            "customer_last_name": last,
            "instruction": "فقط شماره موبایل مشتری را بپرس (نه تاریخ).",
        }

    if not is_valid_iran_mobile(cust_phone):
        return {
            "ok": False,
            "error": "شماره تماس مشتری معتبر نیست.",
            "missing": ["customer_phone"],
            "instruction": "شماره صحیح ۱۱ رقمی ایران بخواه.",
        }

    # پیش‌نویس کامل نام/شماره برای مرحلهٔ تاریخ
    _save_visit_draft(
        me,
        {
            "land_code": code,
            "customer_name": full_name or f"{first} {last}".strip(),
            "customer_first_name": first,
            "customer_last_name": last,
            "customer_phone": cust_phone,
        },
    )

    if not visit_date_raw:
        if not available:
            return {
                "ok": False,
                "error": "الان روز مجازی برای بازدید تعریف نشده است.",
                "allowed_weekdays": visit_allowed_weekdays_summary(),
                "instruction": "به کاربر بگو با پشتیبانی هماهنگ کند.",
            }
        return {
            "ok": True,
            "status": "needs_date_choice",
            "land_code": code,
            "customer_name": full_name or f"{first} {last}".strip(),
            "available_date_labels": available_labels,
            "allowed_weekdays": visit_allowed_weekdays_summary(),
            "instruction": (
                f"فایل {code}: لیست تاریخ را عیناً با شماره ۱ تا ۵ نشان بده "
                "(همه شمسی هستند؛ میلادی نگو و تاریخ خودت نساز). "
                "بگو فقط همان عدد را بفرستد (مثلاً ۲). "
                "بعد فقط visit_date=همان عدد را بفرست (نام/شماره ذخیره است)."
            ),
        }

    vd = resolve_visit_date_choice(visit_date_raw, options=available)
    if vd is None:
        return {
            "ok": True,
            "status": "needs_date_choice",
            "error": "انتخاب تاریخ نامعتبر است.",
            "land_code": code,
            "available_date_labels": available_labels,
            "instruction": (
                "لیست را دوباره عیناً نشان بده؛ فقط عدد ۱ تا ۵ بخواهد. سپس فقط visit_date بفرست."
            ),
        }
    if vd < _today():
        return {"ok": False, "error": "تاریخ بازدید نمی‌تواند در گذشته باشد."}
    if vd > _today() + timedelta(days=90):
        return {"ok": False, "error": "تاریخ بازدید حداکثر تا ۹۰ روز آینده قابل انتخاب است."}
    if not is_visit_weekday_allowed(vd):
        return {
            "ok": True,
            "status": "needs_date_choice",
            "error": "روز انتخاب‌شده مجاز نیست.",
            "allowed": visit_allowed_weekdays_summary(),
            "available_date_labels": available_labels,
            "land_code": code,
            "instruction": "از لیست تاریخ‌های مجاز فقط یک شماره بخواهد.",
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
    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    open_rec = partner_open_visit(visit_requests, me, str(code))
    if open_rec:
        return {
            "ok": False,
            "error": "برای این فایل درخواست بازدید باز دارید؛ بعد از بازدید از همین چت بگو «بازدید انجام شد».",
            "existing_visit_id": str(open_rec.get("id") or ""),
        }

    if current_status == "sold":
        return {"ok": False, "error": "فایل فروخته شده است."}
    if holder_phone and holder_phone != me:
        return {"ok": False, "error": "فایل در معامله همکار دیگر است."}
    if current_status == "in_transaction" or holder_phone == me:
        return {
            "ok": False,
            "error": "فایل در حال معامله است؛ ابتدا معامله را رفع کنید.",
        }

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
    me_norm = normalize_iran_mobile(me) or me
    partner_profile = next(
        (
            p
            for p in partners
            if (normalize_iran_mobile(str(p.get("phone") or "")) or str(p.get("phone") or "").strip())
            == me_norm
        ),
        None,
    )
    partner_name = (partner_profile.get("name") if partner_profile else None) or me

    visit_iso = vd.isoformat()
    visit_jalali = format_display_jalali_date(visit_iso) or format_iso_date_jalali(visit_iso)
    visit_jalali_wd = format_display_jalali_date(visit_iso, with_weekday=True) or visit_jalali

    return {
        "ok": True,
        "payload": {
            "land_code": str(code),
            "land_title": str(land_title),
            "visit_date": visit_iso,  # ذخیره داخلی میلادی
            "visit_date_jalali": visit_jalali,
            "visit_date_display": visit_jalali_wd,
            "customer_first_name": first,
            "customer_last_name": last,
            "customer_name": full_name or f"{first} {last}".strip(),
            "customer_phone": cust_phone,
            "partner_name": partner_name,
        },
    }


def _tool_propose_visit(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    from app.utils.dates import format_display_jalali_date

    checked = _validate_visit_proposal(args, phone=phone)
    # مرحلهٔ انتخاب تاریخ — موفقیت‌آمیز برای مدل، بدون کارت تأیید
    if checked.get("status") == "needs_date_choice":
        model = {k: v for k, v in checked.items() if k != "payload"}
        return {"ok": True, "model_result": model}

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
    _clear_visit_draft(me)
    cust_phone = str(payload.get("customer_phone") or "")
    masked = cust_phone[:4] + "***" + cust_phone[-3:] if len(cust_phone) >= 7 else "***"
    date_show = (
        str(payload.get("visit_date_display") or "").strip()
        or str(payload.get("visit_date_jalali") or "").strip()
        or format_display_jalali_date(str(payload.get("visit_date") or ""))
    )
    cust_show = (
        str(payload.get("customer_name") or "").strip()
        or f"{payload.get('customer_first_name') or ''} {payload.get('customer_last_name') or ''}".strip()
    )
    lines = [
        f"فایل: {payload.get('land_title')} ({payload.get('land_code')})",
        f"تاریخ شمسی: {date_show}",
        f"مشتری: {cust_show}",
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
        "visit_date_jalali": date_show,
        "instruction": (
            "کارت تأیید نشان داده شد؛ تاریخ را فقط شمسی بگو. بگو چک کند و تأیید بزند. هنوز ثبت نشده."
        ),
    }
    return {
        "ok": True,
        "model_result": model,
        "ui_action": ui,
        "land_codes": [],
    }


_SIMPLE_TX_META = {
    "confirm_complete_visit": {
        "title": "تأیید: بازدید انجام شد",
        "need_mode": ("visit_done",),
        "tool_ok_modes": ("visit_done",),
        "instruction": "کارت تأیید؛ هنوز ثبت نشده.",
    },
    "confirm_deal": {
        "title": "تأیید معامله",
        "need_mode": ("deal",),
        "tool_ok_modes": ("deal",),
        "instruction": "کارت معامله؛ هنوز ثبت نشده — بعد از تأیید ادمین فایل بسته می‌شود.",
    },
    "confirm_release": {
        "title": "تأیید بستن معامله",
        "need_mode": ("deal_pending", "release"),
        "tool_ok_modes": ("deal_pending", "release"),
        "instruction": "کارت بستن معامله؛ هنوز لغو نشده.",
    },
}


def _partner_tx_snapshot(phone: str, code: str) -> dict[str, Any]:
    from app.express_partner.routes import _is_partner_approved
    from app.express_partner.visit_requests import resolve_partner_land_tx_state
    from app.utils.storage import (
        load_express_assignments,
        load_express_commissions,
        load_express_partners,
        load_express_visit_requests,
        load_ads_cached,
    )

    me = (phone or "").strip()
    code_s = str(code or "").strip()
    if not me or not code_s:
        return {"ok": False, "error": "کد فایل یا کاربر نامعتبر است."}

    partners = load_express_partners() or []
    profile = next((p for p in partners if str(p.get("phone")) == me), None)
    if not _is_partner_approved(profile):
        return {"ok": False, "error": "حساب همکاری هنوز تأیید نشده است."}

    ctx = None
    try:
        from app.express_partner import routes as ep_routes
        ctx = ep_routes._express_land_partner_ctx(code_s, me)
    except Exception:
        ctx = None
    assignments = load_express_assignments() or []
    if ctx is None:
        mine = [
            a for a in assignments
            if isinstance(a, dict)
            and str(a.get("partner_phone") or "").strip() == me
            and str(a.get("land_code") or "").strip() == code_s
        ]
        if not mine:
            return {"ok": False, "error": "این فایل در مأموریت/اختصاص شما نیست."}
        gs = str(mine[0].get("status") or "active").strip().lower()
    else:
        gs = str(ctx.get("global_status") or "active").strip().lower()

    visits = load_express_visit_requests() or []
    commissions = load_express_commissions() or []
    visit_commission_required = False
    try:
        from app.express_partner.routes import _visit_commission_required_for
        visit_commission_required = bool(
            _visit_commission_required_for(commissions, me, code_s)
        )
    except Exception:
        pass

    tx = resolve_partner_land_tx_state(
        me_phone=me,
        land_code=code_s,
        assignments=assignments,
        visit_requests=visits if isinstance(visits, list) else [],
        is_partner_approved=True,
        global_assignment_status=gs,
        commissions=commissions if isinstance(commissions, list) else [],
        visit_commission_required=visit_commission_required,
    )
    lands = load_ads_cached() or []
    land = next((l for l in lands if str(l.get("code")) == code_s), None)
    title = (land.get("title") if land else None) or code_s
    from app.utils.dates import format_display_jalali_date

    v_iso = str(tx.get("visit_date") or "")
    return {
        "ok": True,
        "tx_mode": str(tx.get("tx_mode") or ""),
        "land_title": str(title),
        "land_code": code_s,
        "visit_date": v_iso,
        "visit_date_jalali": str(tx.get("visit_date_jalali") or "")
        or format_display_jalali_date(v_iso),
        "global_status": gs,
        "has_assignment": bool(tx.get("has_assignment")),
        "deal_finalized": bool(tx.get("deal_finalized")),
    }


def _tool_propose_simple_tx(
    args: dict[str, Any], *, phone: str, action_type: str
) -> dict[str, Any]:
    from app.utils.dates import format_display_jalali_date

    meta = _SIMPLE_TX_META.get(action_type)
    if not meta:
        return _denied("نوع اقدام نامعتبر است.")
    code = _resolve_tool_land_code(phone, args)
    if not code:
        return {
            "ok": False,
            "model_result": {
                "ok": False,
                "error": "کد فایل مشخص نیست.",
                "instruction": "اگر مأموریت فعال نیست کد فایل را بپرس؛ وگرنه دوباره بدون land_code صدا بزن.",
            },
        }
    snap = _partner_tx_snapshot(phone, code)
    if not snap.get("ok"):
        return {"ok": False, "model_result": {"ok": False, "error": snap.get("error")}}

    mode = str(snap.get("tx_mode") or "")
    ok_modes = meta.get("tool_ok_modes") or ()
    if action_type == "confirm_deal" and not snap.get("has_assignment"):
        return {
            "ok": False,
            "model_result": {
                "ok": False,
                "error": (
                    "این فایل در اختصاص شما نیست؛ ثبت معامله فقط روی فایل اختصاص‌یافته ممکن است. "
                    "فایل مأموریت/اختصاص فعال را بگو یا از خانه ادامه بده."
                ),
                "tx_mode": mode,
                "land_code": code,
            },
        }
    if mode not in ok_modes:
        hints = {
            "confirm_complete_visit": "الان نمی‌شود «بازدید انجام شد» زد؛ باید بازدید تأییدشده در جریان باشد.",
            "confirm_deal": {
                "visit_commission_pending": (
                    "هنوز پورسانت بازدید تأیید نشده؛ بعد از تأیید ادمین می‌توانی معامله ثبت کنی. "
                    "به کاربر وضعیت را بگو و کارت معامله نساز."
                ),
                "deal_pending": (
                    "فروش قبلاً ثبت شده و منتظر تأیید ادمین است. "
                    "به کاربر بگو صبر کند؛ اگر انصراف می‌خواهد propose_release_deal بزن."
                ),
                "release": (
                    "فایل در معامله است بدون پورسانت در صف؛ اگر باید ببندد propose_release_deal، "
                    "وگرنه وضعیت را بگو."
                ),
                "visit_done": "اول «بازدید انجام شد» را ثبت و تکمیل کن؛ بعد معامله.",
                "visit_done_pending": "انجام بازدید منتظر تأیید ادمین است؛ هنوز معامله نزن.",
                "visit_pending": "اول درخواست بازدید باید نهایی شود؛ هنوز معامله نزن.",
                "hidden": (
                    "الان ثبت معامله برای این فایل ممکن نیست "
                    "(اختصاص نیست یا قبلاً پورسانت معامله تأیید شده). وضعیت را کوتاه بگو."
                ),
                "_": "الان معامله فعال نیست؛ اول بازدید را کامل کن یا منتظر تأیید باش.",
            },
            "confirm_release": "معاملهٔ بازی برای بستن نیست.",
        }
        if action_type == "confirm_deal":
            deal_hints = hints["confirm_deal"]
            err = deal_hints.get(mode) or deal_hints["_"]
        else:
            err = hints.get(action_type, "این اقدام الان ممکن نیست.")
        return {
            "ok": False,
            "model_result": {
                "ok": False,
                "error": err,
                "tx_mode": mode,
            },
        }

    me = (phone or "").strip()
    payload = {
        "land_code": code,
        "land_title": snap.get("land_title"),
        "visit_date": snap.get("visit_date"),
        "visit_date_jalali": snap.get("visit_date_jalali")
        or format_display_jalali_date(str(snap.get("visit_date") or "")),
    }
    token = _store_pending_action(user_key=me, action_type=action_type, payload=payload)
    lines = [
        f"فایل: {payload.get('land_title')} ({code})",
    ]
    vdisp = (
        str(payload.get("visit_date_jalali") or "").strip()
        or format_display_jalali_date(str(payload.get("visit_date") or ""))
    )
    if vdisp:
        lines.append(f"بازدید (شمسی): {vdisp}")
    ui = {
        "type": action_type,
        "token": token,
        "title": meta["title"],
        "lines": lines,
        "status": "pending",
        "land_code": code,
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "land_code": code,
        "tx_mode": mode,
        "instruction": meta["instruction"],
    }
    return {
        "ok": True,
        "model_result": model,
        "ui_action": ui,
        "land_codes": [],
    }


def confirm_visit_from_token(*, phone: str, token: str) -> dict[str, Any]:
    """اجرای قطعی ثبت بازدید پس از تأیید کاربر — بلافاصله نهایی می‌شود."""
    from app.express_partner.routes import (
        _send_visit_admin_sms,
        _sync_visit_customer_to_club,
    )
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
    action_type = str(pending.get("action_type") or "")
    if action_type != "confirm_visit":
        return confirm_action_from_token(phone=phone, token=token)

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

    partner_name = str(fresh.get("partner_name") or me)
    land_title = str(fresh.get("land_title") or code)
    visit_date = str(fresh.get("visit_date") or "")

    rec, err = record_visit_request(
        visit_requests,
        partner_phone=me,
        partner_name=partner_name,
        land_code=code,
        land_title=land_title,
        visit_date=visit_date,
        customer_first_name=str(fresh.get("customer_first_name") or ""),
        customer_last_name=str(fresh.get("customer_last_name") or ""),
        customer_phone=str(fresh.get("customer_phone") or ""),
    )
    if err == "already_pending":
        _consume_pending_action(token)
        return {
            "ok": True,
            "already": True,
            "message": (
                "این بازدید از قبل ثبت شده. قدم بعدی: با مشتری هماهنگ کن؛ "
                "بعد از بازدید از همین چت بگو «بازدید انجام شد»."
            ),
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

    try:
        _send_visit_admin_sms(
            partner_phone=me,
            partner_name=partner_name,
            land_code=code,
            land_title=land_title,
            visit_date=str(rec.get("visit_date") or visit_date),
        )
    except Exception:
        pass
    try:
        from app.express_partner.visit_sms import notify_partner_land_tx_sms

        notify_partner_land_tx_sms(
            partner_phone=me,
            event="visit_submitted",
            land_code=code,
            land_title=land_title,
            visit_date=str(rec.get("visit_date") or visit_date),
            reference_id=str(rec.get("id") or ""),
        )
    except Exception:
        pass

    _consume_pending_action(token)
    from app.utils.dates import format_display_jalali_date

    vdate_iso = str(rec.get("visit_date") or visit_date or "").strip()
    vdate_j = format_display_jalali_date(
        str(fresh.get("visit_date_jalali") or "") or vdate_iso,
        with_weekday=True,
    ) or format_display_jalali_date(vdate_iso)
    date_bit = f" برای {vdate_j}" if vdate_j else ""
    return {
        "ok": True,
        "message": (
            f"بازدید{date_bit} ثبت شد. "
            "قدم بعدی: با مشتری هماهنگ کن؛ بعد از بازدید از همین چت بگو «بازدید انجام شد» "
            "تا کارت تأیید بیاید — لازم نیست به صفحه دیگری بروی."
        ),
        "visit_id": str(rec.get("id") or ""),
        "land_code": code,
        "visit_date_jalali": vdate_j,
    }


def confirm_action_from_token(*, phone: str, token: str) -> dict[str, Any]:
    """تأیید عمومی اکشن‌های چت (بازدید انجام شد / معامله / بستن / درخواست همکاری)."""
    me = (phone or "").strip()
    pending = _load_pending_action(token)
    if not pending:
        return {"ok": False, "error": "این پیشنهاد منقضی یا نامعتبر است."}
    if str(pending.get("user_key") or "") != me:
        return {"ok": False, "error": "دسترسی به این پیشنهاد ندارید."}
    action_type = str(pending.get("action_type") or "")
    if action_type == "confirm_visit":
        return confirm_visit_from_token(phone=phone, token=token)
    if action_type == "confirm_partner_application":
        return _confirm_partner_application(phone=me, token=token, pending=pending)
    if action_type not in _SIMPLE_TX_META:
        return {"ok": False, "error": "نوع اقدام نامعتبر است."}

    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    code = str(payload.get("land_code") or "").strip()
    snap = _partner_tx_snapshot(me, code)
    if not snap.get("ok"):
        return {"ok": False, "error": str(snap.get("error") or "امکان اجرا نیست.")}
    mode = str(snap.get("tx_mode") or "")
    ok_modes = _SIMPLE_TX_META[action_type].get("tool_ok_modes") or ()
    if action_type == "confirm_deal" and not snap.get("has_assignment"):
        return {
            "ok": False,
            "error": (
                "این فایل در اختصاص شما نیست؛ ثبت معامله فقط روی فایل اختصاص‌یافته ممکن است."
            ),
        }
    if mode not in ok_modes:
        return {"ok": False, "error": "وضعیت فایل عوض شده؛ این اقدام دیگر ممکن نیست."}

    if action_type == "confirm_complete_visit":
        out = _execute_complete_visit(me, code)
    elif action_type == "confirm_deal":
        out = _execute_start_deal(me, code)
    else:
        out = _execute_release_deal(me, code)

    if out.get("ok"):
        _consume_pending_action(token)
    return out


def _confirm_partner_application(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    try:
        from app.express_partner.routes import create_partner_application_core

        out = create_partner_application_core(phone, dict(payload))
    except Exception as exc:
        return {"ok": False, "error": f"ثبت درخواست ممکن نشد: {exc}"}
    if out.get("ok"):
        _consume_pending_action(token)
        return {
            "ok": True,
            "message": str(out.get("message") or "درخواست همکاری ثبت شد."),
            "application_id": out.get("application_id"),
        }
    return {"ok": False, "error": str(out.get("error") or "ثبت درخواست ناموفق بود.")}


def _execute_complete_visit(phone: str, code: str) -> dict[str, Any]:
    from app.express_partner.visit_requests import request_visit_done_confirmation
    from app.utils.storage import load_express_visit_requests, save_express_visit_requests

    visits = load_express_visit_requests() or []
    if not isinstance(visits, list):
        visits = []
    rec, err = request_visit_done_confirmation(visits, phone, code)
    if err == "not_approved":
        return {"ok": False, "error": "اول باید درخواست بازدید ثبت شده باشد."}
    if not rec:
        return {"ok": False, "error": "ثبت انجام بازدید ممکن نشد."}
    save_express_visit_requests(visits)
    need_visit_commission = False
    try:
        from flask import current_app
        from app.utils.storage import load_settings

        need_visit_commission = max(
            0,
            int((load_settings(current_app) or {}).get("visit_commission_amount_toman") or 0),
        ) > 0
    except Exception:
        need_visit_commission = False
    if need_visit_commission:
        msg = (
            "بازدید انجام شد ثبت شد و منتظر تأیید ادمین است. "
            "قدم بعدی: بعد از تأیید انجام بازدید، پورسانت بازدید باید تأیید شود؛ "
            "سپس می‌توانی معامله را ثبت کنی."
        )
        if err == "already_pending":
            msg = (
                "قبلاً ثبت شده و منتظر تأیید ادمین است. "
                "بعد از تأیید انجام و تأیید پورسانت بازدید، معامله را ثبت کن."
            )
    else:
        msg = (
            "بازدید انجام شد ثبت شد و منتظر تأیید ادمین است. "
            "قدم بعدی: بعد از تأیید، از همین چت بگو «ثبت معامله»."
        )
        if err == "already_pending":
            msg = (
                "قبلاً ثبت شده و منتظر تأیید ادمین است. "
                "قدم بعدی: صبر کن تا تأیید شود؛ بعد از همین چت معامله را ثبت کن."
            )
    return {"ok": True, "message": msg, "land_code": code}


def _execute_start_deal(phone: str, code: str) -> dict[str, Any]:
    """شروع معامله از چت — همان منطق mark_in_transaction با درخواست AJAX."""
    from flask import session

    from app.express_partner.routes import mark_in_transaction

    me = (phone or "").strip()
    code_s = str(code or "").strip()
    with current_app.test_request_context(
        f"/express/partner/mark-in-transaction/{code_s}",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ):
        session["user_phone"] = me
        try:
            resp = mark_in_transaction(code_s)
        except Exception as exc:
            current_app.logger.exception("chat deal execute failed: %s", exc)
            return {"ok": False, "error": "ثبت معامله ممکن نشد."}
    data = {}
    try:
        data = resp.get_json(silent=True) or {}
    except Exception:
        try:
            status = getattr(resp, "status_code", 500)
            if status and int(status) >= 400:
                return {"ok": False, "error": "ثبت معامله ممکن نشد."}
        except Exception:
            pass
        return {
            "ok": True,
            "message": "معامله ثبت شد. پس از تأیید ادمین فایل بسته و پورسانت به کیف پول می‌رود.",
            "land_code": code_s,
        }
    if not data.get("success"):
        return {"ok": False, "error": str(data.get("message") or "ثبت معامله ممکن نشد.")}
    return {
        "ok": True,
        "message": str(
            data.get("message")
            or "معامله ثبت شد. پس از تأیید ادمین، فایل بسته و پورسانت به کیف پول اضافه می‌شود."
        ),
        "land_code": code_s,
        "tx_mode": data.get("tx_mode"),
    }


def _execute_release_deal(phone: str, code: str) -> dict[str, Any]:
    from flask import session

    from app.express_partner.routes import mark_in_transaction

    me = (phone or "").strip()
    code_s = str(code or "").strip()
    with current_app.test_request_context(
        f"/express/partner/mark-in-transaction/{code_s}",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ):
        session["user_phone"] = me
        try:
            resp = mark_in_transaction(code_s)
        except Exception as exc:
            current_app.logger.exception("chat release execute failed: %s", exc)
            return {"ok": False, "error": "بستن معامله ممکن نشد."}
    data = {}
    try:
        data = resp.get_json(silent=True) or {}
    except Exception:
        return {"ok": True, "message": "معامله بسته شد.", "land_code": code_s}
    if not data.get("success"):
        return {"ok": False, "error": str(data.get("message") or "بستن معامله ممکن نشد.")}
    return {
        "ok": True,
        "message": str(data.get("message") or "معامله بسته شد."),
        "land_code": code_s,
        "tx_mode": data.get("tx_mode"),
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
        if atype in (
            "confirm_visit",
            "confirm_complete_visit",
            "confirm_deal",
            "confirm_release",
            "confirm_partner_application",
        ):
            parts.append(_render_confirm_action_card(action))
        elif atype == "need_login":
            parts.append(_render_need_login_card(action))
        elif atype == "next_action":
            parts.append(_render_next_action_card(action))
        elif atype == "copy_blocks":
            parts.append(_render_copy_blocks_card(action))
    if not parts:
        return ""
    return (
        '<div class="ai-agent-actions mt-2.5 flex w-full max-w-full flex-col gap-2.5">'
        + "".join(parts)
        + "</div>"
    )


def _render_need_login_card(action: dict[str, Any]) -> str:
    title = escape(str(action.get("title") or "ورود لازم است").strip() or "ورود لازم است")
    subtitle = escape(str(action.get("subtitle") or "").strip())
    cta = escape(str(action.get("cta") or "ورود").strip() or "ورود")
    sub_html = f'<div class="ai-agent-card__body"><div class="ai-agent-line">{subtitle}</div></div>' if subtitle else ""
    return (
        f'<div class="ai-agent-card" data-agent-type="need_login">'
        f'<div class="ai-agent-card__title">{title}</div>'
        f"{sub_html}"
        f'<div class="ai-agent-card__actions">'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--confirm" data-agent-login>{cta}</button>'
        f"</div>"
        f"</div>"
    )


def _render_copy_blocks_card(action: dict[str, Any]) -> str:
    """کارت‌های کپی GPT-style — هر متن (دیوار / اینستا) جدا."""
    blocks = action.get("blocks") if isinstance(action.get("blocks"), list) else []
    icon_copy = (
        '<svg class="ai-copy-block__icon-copy" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.85" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<rect x="9" y="9" width="13" height="13" rx="2"></rect>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>'
        "</svg>"
    )
    icon_check = (
        '<svg class="ai-copy-block__icon-check" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.1" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<path d="M20 6L9 17l-5-5"></path>'
        "</svg>"
    )
    chunks: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        label = escape(str(block.get("label") or "متن").strip() or "متن")
        chunks.append(
            '<div class="ai-copy-block" data-ai-copy-block>'
            '<div class="ai-copy-block__bar">'
            f'<span class="ai-copy-block__label">{label}</span>'
            '<button type="button" class="ai-copy-block__btn" data-ai-copy '
            'aria-label="کپی متن">'
            f"{icon_copy}{icon_check}"
            "</button>"
            "</div>"
            f'<pre class="ai-copy-block__pre" data-ai-copy-text>{escape(text)}</pre>'
            "</div>"
        )
    if not chunks:
        return ""
    return '<div class="ai-copy-blocks">' + "".join(chunks) + "</div>"


def _render_confirm_action_card(action: dict[str, Any]) -> str:
    atype = str(action.get("type") or "confirm_visit")
    token = str(action.get("token") or "").strip()
    defaults = {
        "confirm_visit": "تأیید ثبت بازدید",
        "confirm_complete_visit": "تأیید: بازدید انجام شد",
        "confirm_deal": "تأیید معامله",
        "confirm_release": "تأیید بستن معامله",
        "confirm_partner_application": "تأیید ثبت درخواست همکاری",
    }
    title = escape(str(action.get("title") or defaults.get(atype) or "تأیید اقدام"))
    confirm_label = escape(str(action.get("confirm_label") or "تأیید و ثبت").strip() or "تأیید و ثبت")
    cancel_label = escape(str(action.get("cancel_label") or "انصراف").strip() or "انصراف")
    status = str(action.get("status") or "pending")
    if status == "pending" and token and _load_pending_action(token) is None:
        status = "expired"
    lines = action.get("lines") if isinstance(action.get("lines"), list) else []
    body = "".join(
        f'<div class="ai-agent-line">{escape(str(line))}</div>' for line in lines if str(line).strip()
    )
    if status != "pending" or not token:
        if status == "confirmed":
            note = "انجام شد."
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
        f'<div class="ai-agent-card" data-agent-type="{escape(atype)}" data-token="{escape(token)}">'
        f'<div class="ai-agent-card__title">{title}</div>'
        f'<div class="ai-agent-card__body">{body}</div>'
        f'<div class="ai-agent-card__actions">'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--confirm" data-agent-confirm>{confirm_label}</button>'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--cancel" data-agent-cancel>{cancel_label}</button>'
        f"</div>"
        f'<div class="ai-agent-card__note hidden" data-agent-note></div>'
        f"</div>"
    )


def _render_confirm_visit_card(action: dict[str, Any]) -> str:
    return _render_confirm_action_card(action)


def _render_next_action_card(action: dict[str, Any]) -> str:
    title = escape(str(action.get("title") or "کار بعدی"))
    subtitle = escape(str(action.get("subtitle") or ""))
    cta = escape(str(action.get("cta") or "مشاهده"))
    url = str(action.get("url") or "").strip()
    link = ""
    if url:
        link = (
            f'<a class="ai-agent-btn ai-agent-btn--confirm" href="{escape(url)}" '
            f'data-vinor-express-nav>{cta}</a>'
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
