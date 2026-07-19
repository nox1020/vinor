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
TOOL_LOG_CALL = "propose_log_call"
TOOL_FOLLOWUP = "propose_followup"
TOOL_VISIT_RESULT = "propose_visit_result"
TOOL_NO_SHOW = "propose_no_show"
TOOL_OFFER = "propose_offer"
TOOL_COUNTER_OFFER = "propose_counter_offer"
TOOL_RESERVATION = "propose_reservation"
TOOL_CONTRACT = "propose_contract"
TOOL_PAYMENT_MILESTONE = "propose_payment_milestone"
TOOL_SETTLEMENT = "propose_settlement"
TOOL_LEAD = "propose_lead"
TOOL_TASK = "propose_task"


def _norm_partner_phone(phone: str) -> str:
    ph = str(phone or "").strip()
    if not ph:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(ph) or ph
    except Exception:
        return ph


def _tool_thread_meta() -> tuple[str | None, str]:
    try:
        from flask import g

        tid = getattr(g, "ai_tool_thread_id", None)
        aud = getattr(g, "ai_tool_audience", None)
    except Exception:
        return None, AUDIENCE_PARTNER
    tid_s = str(tid or "").strip() or None
    aud_s = aud if aud in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    return tid_s, aud_s


def _active_mission_land_code(phone: str, thread_id: str | None = None) -> str:
    """بازنشسته: مأموریت خودکار حذف شد — همیشه خالی."""
    return ""


def _active_assignment_land_codes(phone: str) -> list[str]:
    """کد فایل‌های اختصاص شخصی (active / in_transaction) — معاملهٔ باز اول."""
    ph = _norm_partner_phone(phone)
    if not ph:
        return []
    try:
        from app.utils.storage import load_express_assignments

        rows = []
        for a in load_express_assignments() or []:
            if not isinstance(a, dict):
                continue
            aph = _norm_partner_phone(str(a.get("partner_phone") or ""))
            if aph != ph:
                continue
            st = str(a.get("status") or "active").strip().lower()
            if st not in ("", "active", "in_transaction"):
                continue
            if not str(a.get("land_code") or "").strip():
                continue
            rows.append(a)
        rows.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
        in_tx: list[str] = []
        active: list[str] = []
        seen: set[str] = set()
        for a in rows:
            code = str(a.get("land_code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            st = str(a.get("status") or "active").strip().lower()
            if st == "in_transaction":
                in_tx.append(code)
            else:
                active.append(code)
        return in_tx + active
    except Exception:
        return []


def _thread_focus_land_code(phone: str, thread_id: str | None = None) -> str:
    """آخرین کد فایلی که روی همین گفتگو (کارت/اکشن/پرونده) آمده."""
    ph = _norm_partner_phone(phone) or str(phone or "").strip()
    if not ph:
        return ""
    tid, aud = _tool_thread_meta()
    if thread_id:
        tid = str(thread_id).strip() or tid
    # Case پرونده
    if tid:
        try:
            from app.ai.case_store import get_case_for_thread

            case = get_case_for_thread(ph, tid, aud)
            if case:
                c = str(case.get("land_code") or "").strip()
                if c:
                    return c
        except Exception:
            pass
    # پیام‌ها / کارت‌های thread
    try:
        from app.ai.chat_store import recent_thread_land_codes

        codes = recent_thread_land_codes(ph, tid, audience=aud, limit=5)
        if codes:
            return str(codes[0] or "").strip()
    except Exception:
        pass
    # عنوان thread مثل «ماموریت 123…»
    if tid:
        try:
            import re
            from app.ai.chat_store import load_user_record

            record = load_user_record(ph, aud)
            for th in record.get("threads") or []:
                if str(th.get("id") or "") != tid:
                    continue
                title = str(th.get("title") or "")
                m = re.search(r"(?:ماموریت|ماموريت|فایل|کد)\s*([0-9]{6,20})", title)
                if m:
                    return str(m.group(1) or "").strip()
                break
        except Exception:
            pass
    return ""


def _land_code_from_user_message() -> str:
    """اگر در آخرین پیام کاربر «فایل ۱۲۳…» آمده، همان کد."""
    try:
        from flask import g
        import re

        text = str(getattr(g, "ai_last_user_message", "") or "")
        if not text:
            return ""
        m = re.search(
            r"(?:فایل|کد\s*فایل|کد\s*ملک|ماموریت)\s*[#:：]?\s*(\d{6,20})",
            text,
        )
        if m:
            return str(m.group(1) or "").strip()
        # کد خام طولانی در پیام
        m2 = re.search(r"\b(\d{10,20})\b", text)
        if m2:
            return str(m2.group(1) or "").strip()
    except Exception:
        pass
    return ""


def resolve_conversation_land_code(
    phone: str,
    args: dict[str, Any] | None = None,
    *,
    thread_id: str | None = None,
) -> str:
    """کد فایل موضوع گفتگو — هرگز از کاربر نپرس؛ از زمینه بگیر.

    اولویت:
    آرگومان → cache → فوکوس thread/case → پیام کاربر → مأموریت همان thread
    → پیش‌نویس → اختصاص‌ها
    """
    tid, _aud = _tool_thread_meta()
    if thread_id:
        tid = str(thread_id).strip() or tid

    raw = ""
    if isinstance(args, dict):
        raw = str(args.get("land_code") or "").strip()
    if raw:
        return raw

    # cache روی g برای یک دور ابزار
    try:
        from flask import g

        cached = str(getattr(g, "ai_focus_land_code", "") or "").strip()
        if cached:
            return cached
    except Exception:
        pass

    thread_code = _thread_focus_land_code(phone, tid)
    if thread_code:
        return thread_code

    msg_code = _land_code_from_user_message()
    if msg_code:
        return msg_code

    mission = _active_mission_land_code(phone, tid)
    if mission:
        return mission

    try:
        draft_code = str(_load_visit_draft(phone).get("land_code") or "").strip()
        if draft_code:
            return draft_code
    except Exception:
        pass

    assigned = _active_assignment_land_codes(phone)
    if len(assigned) == 1:
        return assigned[0]
    if assigned:
        # چند فایل: جدیدترین/معامله‌باز — باز هم از کاربر نپرس
        return assigned[0]
    return ""


def _resolve_tool_land_code(phone: str, args: dict[str, Any] | None = None) -> str:
    return resolve_conversation_land_code(phone, args)


def _never_ask_land_instruction(phone: str = "") -> str:
    focus = ""
    try:
        focus = resolve_conversation_land_code(phone) if phone else ""
    except Exception:
        focus = ""
    if focus:
        return (
            f"کد فایل موضوع: {focus}. به کاربر کد فایل را نپرس و نام نبر مگر لازم باشد. "
            f"propose_* / draft_listing_copy را با land_code خالی یا «{focus}» بزن."
        )
    return (
        "اگر فایل موضوع گفتگو معلوم نیست: معیار مشتری یا نوع فایل را بپرس، "
        "بعد search_lands بزن و با [[LAND:کد]] پیشنهاد بده. "
        "روی فایل توافق‌شده propose_* را با land_code خالی صدا بزن."
    )


def agent_system_hint(voice: str | None) -> str:
    """یادآوری کوتاه مسیریابی ابزار — جزئیات در system prompt است."""
    v = (voice or "").strip().lower()
    if v == VOICE_PUBLIC:
        return (
            "بازاریاب فروش برای مهمان/کاربر عادی: جواب را به فروش فایل ببر. "
            "خرید/جستجو→search_lands→[[LAND]] | فروش/بازاریاب شدن→coop_info سپس propose_apply "
            "(نام/کدملی/شهر یکی‌یکی؛ need_login=منوی راست). propose_visit/deal نزن."
        )
    return (
        "بازاریاب فروش: مشتری→معیار→search_lands→[[LAND]] | یا نوع فایل→search→معرفی. "
        "listing→کارت کپی | propose_visit/complete/deal/release→کارت تأیید. "
        "بازدید یکی‌یکی: propose با land_code موضوع گفتگو → «نام مشتری را بگو» → شماره → تاریخ. "
        "مأموریت اجباری نداریم."
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
        # Phase 1 CRM tools — only when VINOR_CRM_AI_TOOLS_ENABLED (default ON)
        try:
            from app.crm.config import crm_ai_tools_enabled
            if crm_ai_tools_enabled():
                schemas.append(_schema_log_call())
                schemas.append(_schema_followup())
        except Exception:
            pass
        # Phase 2 Visit Result tools — only when VINOR_VISIT_RESULT_AI_TOOLS_ENABLED
        try:
            from app.visit_result.config import visit_result_ai_tools_enabled
            if visit_result_ai_tools_enabled():
                schemas.append(_schema_visit_result())
                schemas.append(_schema_no_show())
        except Exception:
            pass
        # Phase 3 Commercial tools
        try:
            from app.commercial.config import commercial_ai_tools_enabled
            if commercial_ai_tools_enabled():
                schemas.append(_schema_offer())
                schemas.append(_schema_counter_offer())
                schemas.append(_schema_reservation())
        except Exception:
            pass
        # Phase 4 Closing tools
        try:
            from app.closing.config import closing_ai_tools_enabled
            if closing_ai_tools_enabled():
                schemas.append(_schema_contract())
                schemas.append(_schema_payment_milestone())
                schemas.append(_schema_settlement())
        except Exception:
            pass
        # Phase 6 Integration tools
        try:
            from app.integration.config import integration_ai_tools_enabled
            if integration_ai_tools_enabled():
                schemas.append(_schema_lead())
                schemas.append(_schema_task())
        except Exception:
            pass
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
                "کارت ثبت بازدید یا بازدید مجدد. فیلدها یکی‌یکی؛ چندتایی نفرست. "
                "فوری با land_code خالی بزن (کد را از کاربر نپرس؛ سیستم از مأموریت/گفتگو/اختصاص می‌گیرد) سپس: "
                "customer_name → customer_phone → "
                "بدون visit_date صدا بزن تا لیست ۱…۵ تاریخ بیاید → فقط شمارهٔ تاریخ را در visit_date بفرست. "
                "ثبت فقط بعد از تأیید کارت."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "customer_name": {
                        "type": "string",
                        "description": "نام مشتری (یکجا؛ نام کوچک و خانوادگی جدا نپرس)",
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
            "description": "کارت «بازدید انجام شد»؛ land_code را خالی بگذار مگر چند فایل بدون زمینه.",
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
            "description": "کارت ثبت معامله/فروش نهایی (بازدید تکمیل‌شده). معمولاً land_code خالی.",
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
            "description": "کارت انصراف از معاملهٔ در انتظار تأیید. معمولاً land_code خالی.",
            "parameters": {
                "type": "object",
                "properties": {"land_code": {"type": "string"}},
                "required": [],
            },
        },
    }


def _schema_log_call() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_LOG_CALL,
            "description": (
                "کارت تأیید ثبت تماس CRM با مشتری. "
                "customer_phone الزامی؛ outcome و notes اختیاری. "
                "پیش‌فرض شماره مقصد هماهنگی بازدید 09121471301."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string", "description": "موبایل مشتری"},
                    "customer_name": {"type": "string", "description": "نام مشتری (اختیاری)"},
                    "outcome": {
                        "type": "string",
                        "description": "answered|no_answer|busy|visit_scheduled|other",
                    },
                    "notes": {"type": "string"},
                    "to_number": {
                        "type": "string",
                        "description": "شماره مقصد تماس؛ خالی=09121471301",
                    },
                },
                "required": ["customer_phone"],
            },
        },
    }


def _schema_followup() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_FOLLOWUP,
            "description": (
                "کارت تأیید ثبت پیگیری CRM. customer_phone الزامی؛ due_at تاریخ YYYY-MM-DD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "due_at": {"type": "string", "description": "YYYY-MM-DD"},
                    "notes": {"type": "string"},
                },
                "required": ["customer_phone"],
            },
        },
    }


def _schema_visit_result() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_VISIT_RESULT,
            "description": (
                "کارت تأیید ثبت نتیجه بازدید. outcome: interested|not_interested|follow_up. "
                "land_code را خالی بگذار مگر چند فایل."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "outcome": {
                        "type": "string",
                        "description": "interested|not_interested|follow_up",
                    },
                    "notes": {"type": "string"},
                },
                "required": ["outcome"],
            },
        },
    }


def _schema_no_show() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NO_SHOW,
            "description": (
                "کارت تأیید عدم حضور مشتری (no-show). پورسانت ساخته نمی‌شود. "
                "land_code را خالی بگذار مگر چند فایل."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [],
            },
        },
    }


def _schema_offer() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_OFFER,
            "description": "کارت تأیید پیشنهاد قیمت. amount الزامی؛ land_code و buyer_phone اختیاری.",
            "parameters": {
                "type": "object",
                "properties": {
                    "land_code": {"type": "string"},
                    "amount": {"type": "integer"},
                    "buyer_phone": {"type": "string"},
                    "terms": {"type": "string"},
                },
                "required": ["amount"],
            },
        },
    }


def _schema_counter_offer() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_COUNTER_OFFER,
            "description": "کارت تأیید پیشنهاد متقابل. offer_id و amount الزامی.",
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string"},
                    "amount": {"type": "integer"},
                    "terms": {"type": "string"},
                },
                "required": ["offer_id", "amount"],
            },
        },
    }


def _schema_reservation() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_RESERVATION,
            "description": "کارت تأیید رزرو نرم از پیشنهاد پذیرفته‌شده. assignment را قفل نمی‌کند.",
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string"},
                    "hold_note": {"type": "string"},
                },
                "required": ["offer_id"],
            },
        },
    }


def _schema_contract() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_CONTRACT,
            "description": "کارت تأیید ثبت قرارداد روی Deal. deal_id یا land_code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "land_code": {"type": "string"},
                    "title": {"type": "string"},
                    "document_ref": {"type": "string"},
                },
                "required": [],
            },
        },
    }


def _schema_payment_milestone() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_PAYMENT_MILESTONE,
            "description": "کارت تأیید قسط/milestone پرداخت روی Deal. amount الزامی.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "land_code": {"type": "string"},
                    "amount": {"type": "integer"},
                    "milestone_label": {"type": "string"},
                    "due_at": {"type": "string"},
                },
                "required": ["amount"],
            },
        },
    }


def _schema_settlement() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_SETTLEMENT,
            "description": "کارت تأیید باز کردن Settlement روی Deal. می‌تواند withdrawal_id لینک کند.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "land_code": {"type": "string"},
                    "partner_amount": {"type": "integer"},
                    "withdrawal_id": {"type": "string"},
                },
                "required": [],
            },
        },
    }


def _schema_lead() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_LEAD,
            "description": "کارت تأیید ثبت Lead/Contact در CRM. customer_phone یا display_name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                    "display_name": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [],
            },
        },
    }


def _schema_task() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_TASK,
            "description": "کارت تأیید ثبت Task در CRM. title الزامی.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "customer_phone": {"type": "string"},
                    "due_at": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title"],
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
    thread_id: str | None = None,
) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, dict) else {}
    n = (name or "").strip()
    try:
        from flask import g

        g.ai_tool_thread_id = (thread_id or "").strip() or None
        g.ai_tool_audience = audience
        focus = resolve_conversation_land_code(phone, args, thread_id=thread_id)
        if focus:
            g.ai_focus_land_code = focus
            # تزریق خودکار — مدل نباید کد را از کاربر بگیرد
            if not str(args.get("land_code") or "").strip():
                args["land_code"] = focus
    except Exception:
        pass
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
        if n == TOOL_LOG_CALL:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت تماس فقط برای همکار است.")
            return _tool_propose_log_call(args, phone=phone)
        if n == TOOL_FOLLOWUP:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت پیگیری فقط برای همکار است.")
            return _tool_propose_followup(args, phone=phone)
        if n == TOOL_VISIT_RESULT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت نتیجه بازدید فقط برای همکار است.")
            return _tool_propose_visit_result(args, phone=phone)
        if n == TOOL_NO_SHOW:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت عدم حضور فقط برای همکار است.")
            return _tool_propose_no_show(args, phone=phone)
        if n == TOOL_OFFER:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت پیشنهاد فقط برای همکار است.")
            return _tool_propose_offer(args, phone=phone)
        if n == TOOL_COUNTER_OFFER:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("پیشنهاد متقابل فقط برای همکار است.")
            return _tool_propose_counter_offer(args, phone=phone)
        if n == TOOL_RESERVATION:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("رزرو نرم فقط برای همکار است.")
            return _tool_propose_reservation(args, phone=phone)
        if n == TOOL_CONTRACT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت قرارداد فقط برای همکار است.")
            return _tool_propose_contract(args, phone=phone)
        if n == TOOL_PAYMENT_MILESTONE:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت قسط فقط برای همکار است.")
            return _tool_propose_payment_milestone(args, phone=phone)
        if n == TOOL_SETTLEMENT:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت تسویه فقط برای همکار است.")
            return _tool_propose_settlement(args, phone=phone)
        if n == TOOL_LEAD:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت لید فقط برای همکار است.")
            return _tool_propose_lead(args, phone=phone)
        if n == TOOL_TASK:
            if (voice or "").strip().lower() == VOICE_PUBLIC:
                return _denied("ثبت وظیفه فقط برای همکار است.")
            return _tool_propose_task(args, phone=phone)
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
    try:
        from app.utils.iran_cities import FOCUS_SERVICE_CITY, focus_location_label

        city_bit = (
            f"محدوده سرویس: {focus_location_label()}. "
            f"شهر همکاری فقط «{FOCUS_SERVICE_CITY}»."
        )
    except Exception:
        city_bit = "محدوده سرویس: استان تهران · شهرستان دماوند · روستای گرمابسرد."

    blocks: dict[str, str] = {
        "levels": (
            "سطوح: ۱) کاربر عادی — چت و درخواست بازاریاب شدن. "
            "۲) بازاریاب فروش — بعد از تأیید از چت مشتری یا نوع فایل می‌فرستد، فایل می‌گیرد، می‌فروشد، پورسانت می‌گیرد. "
            "۳) بازاریاب ویژه — مالک/فروشنده با آگهی و بازدیدهای خودش."
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
                "label": "بازاریاب فروش",
                "instruction": "کوتاه بگو الان بازاریاب فروش است؛ از چت مشتری یا نوع فایل بفرستد تا فایل معرفی شود.",
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
        try:
            from app.utils.iran_cities import FOCUS_SERVICE_CITY, normalize_to_focus_city

            city = normalize_to_focus_city(city) or city
            if city and city != FOCUS_SERVICE_CITY and FOCUS_SERVICE_CITY in (normalize_to_focus_city(city) or ""):
                city = FOCUS_SERVICE_CITY
            if city and "گرمابسرد" in city:
                city = FOCUS_SERVICE_CITY
        except Exception:
            pass
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
            # نام‌های معادل گرمابسرد را بپذیر
            try:
                from app.utils.iran_cities import FOCUS_SERVICE_CITY, normalize_to_focus_city

                if normalize_to_focus_city(city) == FOCUS_SERVICE_CITY and FOCUS_SERVICE_CITY in cities:
                    city = FOCUS_SERVICE_CITY
                else:
                    return {
                        "ok": True,
                        "model_result": {
                            "ok": False,
                            "invalid": "city",
                            "allowed_cities": list(cities)[:20],
                            "instruction": "شهر باید گرمابسرد باشد؛ دوباره بپرس.",
                        },
                    }
            except Exception:
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
    try:
        from app.utils.iran_cities import (
            SERVICE_VILLAGE,
            focus_location_label,
            land_in_service_focus,
        )

        focus_lands = [l for l in lands if land_in_service_focus(l)]
        lands = focus_lands if focus_lands else []
        loc_label = focus_location_label()
        village = SERVICE_VILLAGE
    except Exception:
        loc_label = "روستای گرمابسرد"
        village = "گرمابسرد"

    if not lands:
        out = {
            "ok": True,
            "count": 0,
            "lands": [],
            "note": f"فعلاً فایلی در {village} در دسترس نیست.",
            "service_area": loc_label,
            "instruction": (
                f"بگو فعلا سرویس فقط {loc_label} است و فایل آماده‌ای نیست؛ "
                "جای دیگر پیشنهاد نده."
            ),
        }
        return {"ok": True, "model_result": out, "land_codes": []}

    matched = _select_lands_for_query(
        lands, query, default_limit=limit, match_limit=limit
    )
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
                "city": str(land.get("city") or "").strip() or village,
                "assigned": assigned,
            }
        )

    model = {
        "ok": True,
        "count": len(items),
        "lands": items,
        "service_area": loc_label,
        "instruction": (
            f"فقط فایل‌های {village} را پیشنهاد بده؛ برای هر کدام [[LAND:کد]] در خط جدا. "
            f"اگر کاربر جای دیگری خواست، بگو فعلا فقط {loc_label}."
        ),
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
        chat_prompt = str(a.get("chat_prompt") or "").strip()
        model = {
            "ok": True,
            "has_urgent": True,
            "action": {
                "key": a.get("key"),
                "title": a.get("title"),
                "subtitle": a.get("subtitle"),
                "cta": a.get("cta"),
                "url": a.get("url"),
                "chat_prompt": chat_prompt,
                "chat_intent": a.get("chat_intent") or "",
            },
            "coach_tip": coach_tip,
            "coach_land_code": coach_land_code,
            "stats": stats_bit,
            "instruction": (
                "همین کار بعدی را اولویت بده و از چت مأموریت جلو ببر. "
                "اگر coach_tip هست یک جمله تشویقی اضافه کن. "
                "اگر action.chat_prompt هست همان مسیر را با ابزار propose_* ادامه بده؛ لینک صفحه نده. "
                "برای آگهی دیوار/اینستا از draft_listing_copy استفاده کن."
            ),
        }
        ui = {
            "type": "next_action",
            "title": str(a.get("title") or "کار بعدی"),
            "subtitle": str(a.get("subtitle") or ""),
            "cta": str(a.get("cta") or "ادامه در چت"),
            "url": "" if chat_prompt else str(a.get("url") or ""),
            "chat_prompt": chat_prompt,
            "chat_intent": str(a.get("chat_intent") or ""),
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
        return _denied(_never_ask_land_instruction(phone))

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


def clear_visit_draft(user_key: str) -> None:
    """شروع مجدد فرم بازدید / بازدید مجدد — پیش‌نویس مراحل قبلی پاک می‌شود."""
    _clear_visit_draft(user_key)


def reset_visit_draft_keep_land(
    user_key: str,
    *,
    thread_id: str | None = None,
) -> str:
    """پاک کردن نام/شماره پیش‌نویس بازدید؛ نگه داشتن کد فایل موضوع گفتگو."""
    focus = resolve_conversation_land_code(user_key, thread_id=thread_id)
    _clear_visit_draft(user_key)
    if focus:
        _save_visit_draft(user_key, {"land_code": focus})
    return focus


VISIT_ASK_NAME = "نام مشتری را بگو"
VISIT_ASK_PHONE = "شماره موبایل مشتری را بگو"


def _visit_draft_has_name(draft: dict[str, Any]) -> bool:
    if str(draft.get("customer_name") or "").strip():
        return True
    first = str(draft.get("customer_first_name") or "").strip()
    last = str(draft.get("customer_last_name") or "").strip()
    return bool(first or last)


def _looks_like_customer_name(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) > 60:
        return False
    low = s.replace("‌", " ")
    blocked = (
        "ثبت بازدید",
        "بازدید مجدد",
        "بازدید انجام",
        "http",
        "ماموریت",
        "پیشنهاد",
        "قدم بعدی",
        "بازاریابی",
    )
    if any(b in low for b in blocked):
        return False
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

    phone = normalize_iran_mobile(s) or s
    if is_valid_iran_mobile(phone):
        return False
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        return False
    if s.isdigit() and 1 <= int(s) <= 5:
        return False
    if not any(("\u0600" <= ch <= "\u06FF") or ch.isalpha() for ch in s):
        return False
    return True


def _format_visit_date_ask(labels: list[str]) -> str:
    lines = ["کدام تاریخ؟ فقط شماره را بفرست:"]
    for i, lab in enumerate(labels[:5], start=1):
        text = str(lab or "").strip()
        # label از list_upcoming_visit_dates خودش «۱) …» دارد
        if text and (text[0].isdigit() or text[0] in "۰۱۲۳۴۵۶۷۸۹"):
            lines.append(text)
        else:
            lines.append(f"{i}) {text}")
    return "\n".join(lines)


def _visit_call_info_ui(
    *,
    title: str,
    lines: list[str],
    note: str,
    land_code: str = "",
) -> dict[str, Any]:
    """کارت پایانی فقط برای تماس هماهنگی بازدید (بدون توکن تأیید)."""
    call_phone = _visit_coord_call_target()
    return {
        "type": "confirm_visit",
        "title": title,
        "lines": [str(x) for x in lines if str(x).strip()],
        "status": "completed",
        "state": "completed",
        "note": note,
        "show_visit_call": True,
        "call_phone": call_phone,
        "land_code": str(land_code or ""),
        "token_active": False,
    }


def _offer_complete_visit_for_open(
    *, phone: str, land_code: str, existing_visit_id: str = ""
) -> dict[str, Any]:
    """بازدید تأییدشده باز → کارت «بازدید انجام شد» + تماس هماهنگی."""
    call_phone = _visit_coord_call_target()
    out = _tool_propose_simple_tx(
        {"land_code": land_code},
        phone=phone,
        action_type="confirm_complete_visit",
    )
    if out.get("ok") and isinstance(out.get("ui_action"), dict):
        ui = dict(out["ui_action"])
        ui["show_visit_call"] = True
        ui["call_phone"] = call_phone
        out["ui_action"] = ui
        mr = dict(out.get("model_result") or {})
        mr["ok"] = True
        mr["existing_visit_id"] = existing_visit_id
        mr["speak_exactly"] = (
            f"بازدید این فایل باز است. برای هماهنگی با {call_phone} تماس بگیر. "
            "اگر بازدید انجام شده، کارت زیر را تأیید کن."
        )
        mr["instruction"] = (
            "عین speak_exactly را بفرست. نام/شماره/تاریخ جدید نپرس. "
            "کارت تأیید «بازدید انجام شد» نشان داده شده."
        )
        out["model_result"] = mr
        out["ok"] = True
        return out
    err = ""
    if isinstance(out.get("model_result"), dict):
        err = str(out["model_result"].get("error") or "")
    note = err or "وضعیت بازدید را از چت پیگیری کن."
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "open_visit_info",
            "land_code": land_code,
            "existing_visit_id": existing_visit_id,
            "speak_exactly": note,
            "instruction": "عین speak_exactly را بفرست.",
        },
        "ui_action": _visit_call_info_ui(
            title="هماهنگی بازدید",
            lines=[f"فایل: {land_code}", f"هماهنگی: {call_phone}"],
            note=note,
            land_code=land_code,
        ),
    }


def _response_for_open_visit(
    *, phone: str, land_code: str, open_rec: dict[str, Any]
) -> dict[str, Any]:
    """بازدید باز: به‌جای خطای تکراری، کارت/پیام درست بر اساس وضعیت."""
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        DONE_PENDING_STATUS,
        PENDING_STATUS,
    )

    st = str(open_rec.get("status") or "").strip()
    code = str(land_code or "").strip()
    vid = str(open_rec.get("id") or "")
    call_phone = _visit_coord_call_target()

    if st == APPROVED_STATUS:
        return _offer_complete_visit_for_open(
            phone=phone, land_code=code, existing_visit_id=vid
        )

    if st == DONE_PENDING_STATUS:
        speak = (
            "اعلام «بازدید انجام شد» قبلاً ثبت شده و منتظر تأیید ادمین است. "
            "لازم نیست دوباره بنویسی؛ بعد از تأیید می‌تونی معامله ثبت کنی."
        )
        return {
            "ok": True,
            "model_result": {
                "ok": True,
                "status": "visit_done_awaiting_admin",
                "land_code": code,
                "existing_visit_id": vid,
                "speak_exactly": speak,
                "instruction": (
                    "عین speak_exactly را بفرست. "
                    "دیگر propose_visit یا propose_complete_visit نزن."
                ),
            },
            "ui_action": _visit_call_info_ui(
                title="بازدید انجام شد — منتظر تأیید",
                lines=[f"فایل: {code}", f"هماهنگی: {call_phone}"],
                note=speak,
                land_code=code,
            ),
        }

    if st == PENDING_STATUS:
        speak = (
            f"درخواست بازدید ثبت شده و منتظر تأیید است. "
            f"برای هماهنگی با {call_phone} تماس بگیر؛ "
            "بعد از تأیید می‌تونی «بازدید انجام شد» بزنی."
        )
    else:
        speak = (
            f"برای این فایل بازدید باز دارید. "
            f"برای هماهنگی با {call_phone} تماس بگیر."
        )
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "open_visit_pending",
            "land_code": code,
            "existing_visit_id": vid,
            "speak_exactly": speak,
            "instruction": "عین speak_exactly را بفرست. نام/شماره/تاریخ جدید نپرس.",
        },
        "ui_action": _visit_call_info_ui(
            title="بازدید در جریان",
            lines=[f"فایل: {code}", f"هماهنگی: {call_phone}"],
            note=speak,
            land_code=code,
        ),
    }


def _visit_tool_to_chat_result(tool_out: dict[str, Any]) -> dict[str, Any] | None:
    """پاسخ مستقیم کاربر از نتیجهٔ ابزار بازدید (بدون متن آزاد مدل)."""
    if not isinstance(tool_out, dict):
        return None
    model = tool_out.get("model_result")
    if not isinstance(model, dict):
        model = {}
    speak = str(model.get("speak_exactly") or "").strip()
    ui = tool_out.get("ui_action") if isinstance(tool_out.get("ui_action"), dict) else None
    actions = [ui] if ui else []
    if speak:
        return {
            "ok": True,
            "reply": speak,
            "agent_actions": actions,
            "meta": {"provider": "visit_step", "forced": True},
        }
    if ui and str(ui.get("type") or "").startswith("confirm_"):
        return {
            "ok": True,
            "reply": "اگر درست است تأیید کن.",
            "agent_actions": actions,
            "meta": {"provider": "visit_step", "forced": True},
        }
    if model.get("status") == "needs_date_choice":
        labels = [str(x) for x in (model.get("available_date_labels") or []) if str(x).strip()]
        return {
            "ok": True,
            "reply": _format_visit_date_ask(labels),
            "agent_actions": actions,
            "meta": {"provider": "visit_step", "forced": True},
        }
    return None


def try_continue_visit_from_user_message(
    phone: str,
    text: str,
    *,
    audience: str = "",
    voice: str = "",
    thread_id: str | None = None,
) -> dict[str, Any] | None:
    """اگر پیش‌نویس بازدید منتظر نام/موبایل/تاریخ است، جواب کاربر را مستقیم به ابزار بده."""
    me = (phone or "").strip()
    msg = (text or "").strip()
    if not me or not msg:
        return None
    try:
        from flask import g

        g.ai_tool_thread_id = (thread_id or "").strip() or None
        g.ai_tool_audience = audience or AUDIENCE_PARTNER
        g.ai_last_user_message = msg
    except Exception:
        pass
    draft = _load_visit_draft(me)
    code = str(draft.get("land_code") or "").strip()
    if not code:
        code = resolve_conversation_land_code(me, thread_id=thread_id)
        if code:
            _save_visit_draft(me, {**draft, "land_code": code})
            draft = _load_visit_draft(me)
    if not code:
        return None

    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
    from app.express_partner.visit_requests import resolve_visit_date_choice, list_upcoming_visit_dates

    args: dict[str, Any] = {"land_code": code}
    if _visit_draft_has_name(draft):
        args["customer_name"] = (
            str(draft.get("customer_name") or "").strip()
            or f"{draft.get('customer_first_name') or ''} {draft.get('customer_last_name') or ''}".strip()
        )
    if str(draft.get("customer_phone") or "").strip():
        args["customer_phone"] = str(draft.get("customer_phone") or "").strip()

    if not _visit_draft_has_name(draft):
        if not _looks_like_customer_name(msg):
            return {
                "ok": True,
                "reply": VISIT_ASK_NAME,
                "agent_actions": [],
                "meta": {"provider": "visit_step", "forced": True},
            }
        args["customer_name"] = msg
    elif not is_valid_iran_mobile(normalize_iran_mobile(str(draft.get("customer_phone") or "")) or ""):
        phone_try = normalize_iran_mobile(msg) or msg
        if not is_valid_iran_mobile(phone_try):
            return {
                "ok": True,
                "reply": VISIT_ASK_PHONE,
                "agent_actions": [],
                "meta": {"provider": "visit_step", "forced": True},
            }
        args["customer_phone"] = phone_try
    else:
        available = list_upcoming_visit_dates(limit=5)
        vd = resolve_visit_date_choice(msg, options=available)
        if vd is None:
            labels = [str(x.get("label") or "") for x in available if str(x.get("label") or "").strip()]
            return {
                "ok": True,
                "reply": _format_visit_date_ask(labels),
                "agent_actions": [],
                "meta": {"provider": "visit_step", "forced": True},
            }
        args["customer_phone"] = str(draft.get("customer_phone") or "").strip()
        args["visit_date"] = msg.strip()

    tool_out = run_tool(
        TOOL_VISIT,
        args,
        phone=me,
        audience=audience,
        voice=voice,
        thread_id=thread_id,
    )
    return _visit_tool_to_chat_result(tool_out)


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

    # اگر پیام کاربر فایل دیگری را مشخص کرده، پیش‌نویس قبلی قاطی نشود
    hint_code = _land_code_from_user_message()
    draft = _load_visit_draft(me)
    draft_code = str(draft.get("land_code") or "").strip()
    if hint_code and draft_code and hint_code != draft_code:
        clear_visit_draft(me)
        draft = {}

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
    if hint_code and not str(merged.get("land_code") or "").strip():
        merged["land_code"] = hint_code

    code = _resolve_tool_land_code(phone, merged)
    visit_date_raw = str(merged.get("visit_date") or "").strip()
    full_name = str(merged.get("customer_name") or "").strip()
    first = str(merged.get("customer_first_name") or "").strip()
    last = str(merged.get("customer_last_name") or "").strip()
    # پیش‌نویس قدیمی first/last را به یک نام کامل تبدیل کن
    if not full_name and (first or last):
        full_name = f"{first} {last}".strip()
    # اگر ابزار نام را خالی گذاشت ولی کاربر همین الان نام را فرستاده
    if not full_name and code and draft_code == code:
        try:
            from flask import g

            guessed = str(getattr(g, "ai_last_user_message", "") or "").strip()
        except Exception:
            guessed = ""
        if _looks_like_customer_name(guessed):
            full_name = guessed
    if full_name:
        first, last = split_customer_full_name(full_name)
    phone_raw = str(merged.get("customer_phone") or "").strip()
    cust_phone = normalize_iran_mobile(phone_raw) or phone_raw

    available = list_upcoming_visit_dates(limit=5)
    available_labels = [str(x.get("label") or "") for x in available]

    # پیش‌نویس جزئی را نگه دار تا مراحل یکی‌یکی ادامه پیدا کند
    if code or full_name or phone_raw:
        _save_visit_draft(
            me,
            {
                "land_code": code,
                "customer_name": full_name,
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
            "assigned_land_codes": _active_assignment_land_codes(me),
            "instruction": (
                _never_ask_land_instruction(me)
                + " هنوز نام/شماره/تاریخ نپرس. به کاربر چیزی درباره کد فایل نگو."
            ),
            "speak_exactly": "",
        }

    # بازدید باز را قبل از نام/شماره/تاریخ بگو — وگرنه چت در حلقهٔ تاریخ می‌ماند
    try:
        visit_requests_early = load_express_visit_requests() or []
        if not isinstance(visit_requests_early, list):
            visit_requests_early = []
        open_rec_early = partner_open_visit(visit_requests_early, me, str(code))
        if open_rec_early:
            clear_visit_draft(me)
            return {
                "ok": True,
                "status": "open_visit",
                "land_code": code,
                "open_visit": open_rec_early,
                "existing_visit_id": str(open_rec_early.get("id") or ""),
            }
    except Exception:
        pass

    if not full_name:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["customer_name"],
            "land_code": code,
            "speak_exactly": VISIT_ASK_NAME,
            "instruction": (
                f"عین این جمله را بپرس و هیچ کلمه‌ای اضافه نکن: «{VISIT_ASK_NAME}». "
                "هرگز نگو نام کوچک، نام خانوادگی، یا نام و نام‌خانوادگی. "
                "نه شماره، نه تاریخ."
            ),
        }
    if not phone_raw:
        return {
            "ok": False,
            "error": "اطلاعات ناقص",
            "missing": ["customer_phone"],
            "land_code": code,
            "customer_name": full_name,
            "speak_exactly": VISIT_ASK_PHONE,
            "instruction": (
                f"عین این جمله را بپرس و هیچ کلمه‌ای اضافه نکن: «{VISIT_ASK_PHONE}». "
                "نه تاریخ."
            ),
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
            "customer_name": full_name,
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
            "customer_name": full_name,
            "available_date_labels": available_labels,
            "allowed_weekdays": visit_allowed_weekdays_summary(),
            "speak_exactly": _format_visit_date_ask(available_labels),
            "instruction": (
                f"عین speak_exactly را بفرست؛ تاریخ خودت نساز. "
                "بعد فقط visit_date=شماره را بفرست."
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
            "speak_exactly": _format_visit_date_ask(available_labels),
            "instruction": "عین speak_exactly را بفرست؛ سپس فقط visit_date بفرست.",
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
        # Chat-first: فایل اکسپرس باز را همان لحظه claim کن تا عملیات از چت قفل نشود
        try:
            from app.express_partner.partner_missions import claim_express_land_for_partner

            if claim_express_land_for_partner(me, code, source="chat_claim"):
                ctx = _express_land_partner_ctx(code, me) or ctx
        except Exception:
            pass
    if not ctx.get("my_assignment"):
        return {
            "ok": False,
            "error": "این فایل برای ثبت بازدید در دسترس نیست (فروخته/قفل همکار دیگر).",
        }

    current_status = ctx["global_status"]
    holder_phone = ctx.get("holder_phone")
    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    open_rec = partner_open_visit(visit_requests, me, str(code))
    if open_rec:
        return {
            "ok": True,
            "status": "open_visit",
            "land_code": code,
            "open_visit": open_rec,
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
    # بازدید باز: کارت/پیام وضعیت‌محور (نه خطای «بنویس بازدید انجام شد»)
    if checked.get("status") == "open_visit":
        open_rec = checked.get("open_visit") if isinstance(checked.get("open_visit"), dict) else {}
        code = str(checked.get("land_code") or args.get("land_code") or "").strip()
        return _response_for_open_visit(phone=phone, land_code=code, open_rec=open_rec)

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
    call_phone = _visit_coord_call_target()
    lines = [
        f"فایل: {payload.get('land_title')} ({payload.get('land_code')})",
        f"تاریخ شمسی: {date_show}",
        f"مشتری: {cust_show}",
        f"تماس مشتری: {masked}",
        f"هماهنگی بازدید: {call_phone}",
    ]
    ui = {
        "type": "confirm_visit",
        "token": token,
        "title": "تأیید ثبت بازدید",
        "lines": lines,
        "status": "pending",
        "land_code": str(payload.get("land_code") or ""),
        "call_phone": call_phone,
        "show_visit_call": True,
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "land_code": payload.get("land_code"),
        "visit_date_jalali": date_show,
        "instruction": (
            "کارت تأیید نشان داده شد؛ تاریخ را فقط شمسی بگو. بگو چک کند و تأیید بزند. هنوز ثبت نشده. "
            f"بعد از تأیید برای هماهنگی بازدید با {call_phone} تماس بگیرد."
        ),
    }
    return {
        "ok": True,
        "model_result": model,
        "ui_action": ui,
        "land_codes": [],
    }


def _crm_tools_gate(phone: str) -> dict[str, Any] | None:
    """None if OK; otherwise denied/error dict."""
    try:
        from app.crm.config import crm_ai_tools_enabled

        if not crm_ai_tools_enabled():
            return _denied("ابزار CRM فعلاً غیرفعال است.")
    except Exception:
        return _denied("ابزار CRM در دسترس نیست.")
    me = (phone or "").strip()
    if not me:
        return _denied("کاربر شناسایی نشد.")
    if not partner_is_approved(me):
        return _denied("برای ثبت تماس/پیگیری باید حساب همکاری تأیید شده باشد.")
    return None


def _resolve_crm_contact_payload(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
    from app.crm.service import list_partner_customers
    from app.express_partner.visit_requests import split_customer_full_name

    me = (phone or "").strip()
    phone_raw = str(args.get("customer_phone") or "").strip()
    cust = normalize_iran_mobile(phone_raw) or phone_raw
    if not cust or not is_valid_iran_mobile(cust):
        return {"ok": False, "error": "شماره مشتری معتبر نیست."}
    name = str(args.get("customer_name") or "").strip()
    first, last = ("", "")
    if name:
        first, last = split_customer_full_name(name)
    # Prefer existing contact; else prepare upsert fields
    existing = None
    for c in list_partner_customers(me, limit=500):
        if c.customer_phone == cust:
            existing = c
            break
    return {
        "ok": True,
        "partner_phone": me,
        "customer_phone": cust,
        "customer_name": name or (existing.display_name if existing else ""),
        "first_name": first or (existing.first_name if existing else ""),
        "last_name": last or (existing.last_name if existing else ""),
        "contact_id": existing.id if existing else "",
        "upsert_needed": existing is None,
    }


def _tool_propose_log_call(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _crm_tools_gate(phone)
    if gate is not None:
        return gate
    from app.crm.config import VISIT_CALL_TARGET

    resolved = _resolve_crm_contact_payload(args, phone=phone)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "model_result": {"ok": False, "error": resolved.get("error")},
            "error": str(resolved.get("error") or "نامعتبر"),
        }
    me = str(resolved["partner_phone"])
    outcome = str(args.get("outcome") or "").strip() or "other"
    notes = str(args.get("notes") or "").strip()
    to_number = str(args.get("to_number") or "").strip() or VISIT_CALL_TARGET
    payload = {
        **{k: resolved[k] for k in (
            "customer_phone", "customer_name", "first_name", "last_name",
            "contact_id", "upsert_needed",
        )},
        "outcome": outcome,
        "notes": notes,
        "to_number": to_number,
    }
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_log_call",
        payload=payload,
    )
    masked = payload["customer_phone"][:4] + "***" + payload["customer_phone"][-3:]
    lines = [
        f"مشتری: {payload.get('customer_name') or masked}",
        f"تماس: {masked}",
        f"مقصد: {to_number}",
        f"نتیجه: {outcome}",
    ]
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_log_call",
        "token": token,
        "title": "تأیید ثبت تماس",
        "lines": lines,
        "status": "pending",
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "instruction": "کارت تأیید تماس نشان داده شد؛ هنوز ثبت نشده.",
    }
    return {"ok": True, "model_result": model, "ui_action": ui, "land_codes": []}


def _tool_propose_followup(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _crm_tools_gate(phone)
    if gate is not None:
        return gate
    resolved = _resolve_crm_contact_payload(args, phone=phone)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "model_result": {"ok": False, "error": resolved.get("error")},
            "error": str(resolved.get("error") or "نامعتبر"),
        }
    me = str(resolved["partner_phone"])
    due_at = str(args.get("due_at") or "").strip()
    notes = str(args.get("notes") or "").strip()
    payload = {
        **{k: resolved[k] for k in (
            "customer_phone", "customer_name", "first_name", "last_name",
            "contact_id", "upsert_needed",
        )},
        "due_at": due_at,
        "notes": notes,
    }
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_followup",
        payload=payload,
    )
    masked = payload["customer_phone"][:4] + "***" + payload["customer_phone"][-3:]
    lines = [
        f"مشتری: {payload.get('customer_name') or masked}",
        f"تماس: {masked}",
        f"سررسید: {due_at or '—'}",
    ]
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_followup",
        "token": token,
        "title": "تأیید ثبت پیگیری",
        "lines": lines,
        "status": "pending",
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "instruction": "کارت تأیید پیگیری نشان داده شد؛ هنوز ثبت نشده.",
    }
    return {"ok": True, "model_result": model, "ui_action": ui, "land_codes": []}


def _visit_result_tools_gate(phone: str) -> dict[str, Any] | None:
    try:
        from app.visit_result.config import visit_result_ai_tools_enabled

        if not visit_result_ai_tools_enabled():
            return _denied("ابزار نتیجه بازدید فعلاً غیرفعال است.")
    except Exception:
        return _denied("ابزار نتیجه بازدید در دسترس نیست.")
    me = (phone or "").strip()
    if not me:
        return _denied("کاربر شناسایی نشد.")
    if not partner_is_approved(me):
        return _denied("برای ثبت نتیجه بازدید باید حساب همکاری تأیید شده باشد.")
    return None


def _resolve_visit_for_result_tools(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    from app.utils.storage import load_express_visit_requests
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        DONE_PENDING_STATUS,
        COMPLETED_STATUS,
        partner_visit_approved_for_deal,
        partner_visit_done_pending,
        partner_visit_completed,
    )

    me = (phone or "").strip()
    try:
        code = _resolve_tool_land_code(phone, args or {})
    except Exception:
        code = str((args or {}).get("land_code") or "").strip()
    if not code:
        code = _active_mission_land_code(me) or _land_code_from_user_message()
    if not code:
        return {
            "ok": False,
            "error": "فایل موضوع گفتگو پیدا نشد.",
            "instruction": _never_ask_land_instruction(me),
        }
    visits = load_express_visit_requests() or []
    if not isinstance(visits, list):
        visits = []
    rec = (
        partner_visit_approved_for_deal(visits, me, code)
        or partner_visit_done_pending(visits, me, code)
        or partner_visit_completed(visits, me, code)
    )
    if not rec:
        return {"ok": False, "error": "بازدید فعالی برای ثبت نتیجه یافت نشد."}
    st = str(rec.get("status") or "").strip()
    if st not in (APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS):
        return {"ok": False, "error": "وضعیت بازدید برای ثبت نتیجه مناسب نیست."}
    return {
        "ok": True,
        "land_code": code,
        "visit_request_id": str(rec.get("id") or ""),
        "partner_phone": me,
        "land_title": str(rec.get("land_title") or code),
        "status": st,
        "customer_name": str(rec.get("customer_name") or ""),
    }


def _tool_propose_visit_result(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _visit_result_tools_gate(phone)
    if gate is not None:
        return gate
    from app.visit_result.service import valid_outcome

    resolved = _resolve_visit_for_result_tools(args, phone=phone)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": str(resolved.get("error") or "نامعتبر"),
            "model_result": {"ok": False, "error": resolved.get("error")},
        }
    outcome = str(args.get("outcome") or "").strip()
    if not valid_outcome(outcome) or outcome == "no_show":
        return _denied("outcome باید interested یا not_interested یا follow_up باشد.")
    notes = str(args.get("notes") or "").strip()
    me = str(resolved["partner_phone"])
    payload = {
        "land_code": resolved["land_code"],
        "visit_request_id": resolved["visit_request_id"],
        "outcome": outcome,
        "notes": notes,
        "land_title": resolved.get("land_title") or "",
        "customer_name": resolved.get("customer_name") or "",
    }
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_visit_result",
        payload=payload,
    )
    lines = [
        f"فایل: {payload['land_title']} ({payload['land_code']})",
        f"نتیجه: {outcome}",
    ]
    if payload.get("customer_name"):
        lines.insert(1, f"مشتری: {payload['customer_name']}")
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_visit_result",
        "token": token,
        "title": "تأیید ثبت نتیجه بازدید",
        "lines": lines,
        "status": "pending",
        "land_code": payload["land_code"],
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "instruction": "کارت نتیجه بازدید نشان داده شد؛ هنوز ثبت نشده.",
    }
    return {"ok": True, "model_result": model, "ui_action": ui, "land_codes": []}


def _tool_propose_no_show(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _visit_result_tools_gate(phone)
    if gate is not None:
        return gate
    try:
        from app.visit_result.status_bridge import is_no_show_writable

        if not is_no_show_writable():
            return _denied("ثبت عدم حضور فعلاً فعال نیست.")
    except Exception:
        return _denied("ثبت عدم حضور در دسترس نیست.")

    from app.express_partner.visit_requests import APPROVED_STATUS, DONE_PENDING_STATUS

    resolved = _resolve_visit_for_result_tools(args, phone=phone)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": str(resolved.get("error") or "نامعتبر"),
            "model_result": {"ok": False, "error": resolved.get("error")},
        }
    if resolved.get("status") not in (APPROVED_STATUS, DONE_PENDING_STATUS):
        return _denied("عدم حضور فقط از وضعیت تأییدشده یا منتظر تأیید انجام ممکن است.")
    notes = str(args.get("notes") or "").strip()
    me = str(resolved["partner_phone"])
    payload = {
        "land_code": resolved["land_code"],
        "visit_request_id": resolved["visit_request_id"],
        "notes": notes,
        "land_title": resolved.get("land_title") or "",
        "customer_name": resolved.get("customer_name") or "",
    }
    token = _store_pending_action(
        user_key=me,
        action_type="confirm_no_show",
        payload=payload,
    )
    lines = [
        f"فایل: {payload['land_title']} ({payload['land_code']})",
        "وضعیت: عدم حضور مشتری (بدون پورسانت)",
    ]
    if payload.get("customer_name"):
        lines.insert(1, f"مشتری: {payload['customer_name']}")
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_no_show",
        "token": token,
        "title": "تأیید عدم حضور",
        "lines": lines,
        "status": "pending",
        "land_code": payload["land_code"],
    }
    model = {
        "ok": True,
        "status": "needs_user_confirmation",
        "instruction": "کارت عدم حضور نشان داده شد؛ هنوز ثبت نشده.",
    }
    return {"ok": True, "model_result": model, "ui_action": ui, "land_codes": []}


def _commercial_tools_gate(phone: str) -> dict[str, Any] | None:
    try:
        from app.commercial.config import commercial_ai_tools_enabled

        if not commercial_ai_tools_enabled():
            return _denied("ابزار پیشنهاد فعلاً غیرفعال است.")
    except Exception:
        return _denied("ابزار پیشنهاد در دسترس نیست.")
    me = (phone or "").strip()
    if not me:
        return _denied("کاربر شناسایی نشد.")
    if not partner_is_approved(me):
        return _denied("برای ثبت پیشنهاد باید حساب همکاری تأیید شده باشد.")
    return None


def _tool_propose_offer(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _commercial_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    try:
        amount = int(args.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return _denied("مبلغ پیشنهاد نامعتبر است.")
    land_code = str(args.get("land_code") or "").strip()
    if not land_code:
        try:
            land_code = _resolve_tool_land_code(phone, args or {})
        except Exception:
            land_code = ""
    if not land_code:
        land_code = _active_mission_land_code(me) or _land_code_from_user_message()
    if not land_code:
        return _denied(_never_ask_land_instruction(me))
    # optional prefill from AI negotiation plan
    try:
        from flask import g
        plan = getattr(g, "ai_negotiation_plan", None)
        suggested = getattr(plan, "suggested_offer", None) if plan is not None else None
        if suggested and not args.get("amount"):
            try:
                amount = int(suggested)
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    buyer_phone = str(args.get("buyer_phone") or "").strip()
    terms = str(args.get("terms") or "").strip()
    payload = {
        "land_code": land_code,
        "amount": amount,
        "buyer_phone": buyer_phone,
        "terms": terms,
    }
    token = _store_pending_action(user_key=me, action_type="confirm_offer", payload=payload)
    ui = {
        "type": "confirm_offer",
        "token": token,
        "title": "تأیید ثبت پیشنهاد",
        "lines": [
            f"فایل: {land_code}",
            f"مبلغ: {amount:,} تومان",
            *( [f"خریدار: {buyer_phone}"] if buyer_phone else [] ),
            *( [f"شرایط: {terms}"] if terms else [] ),
        ],
        "status": "pending",
        "land_code": land_code,
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت پیشنهاد نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _tool_propose_counter_offer(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _commercial_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    offer_id = str(args.get("offer_id") or "").strip()
    try:
        amount = int(args.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if not offer_id or amount <= 0:
        return _denied("offer_id و مبلغ الزامی است.")
    terms = str(args.get("terms") or "").strip()
    payload = {"offer_id": offer_id, "amount": amount, "terms": terms}
    token = _store_pending_action(user_key=me, action_type="confirm_counter_offer", payload=payload)
    ui = {
        "type": "confirm_counter_offer",
        "token": token,
        "title": "تأیید پیشنهاد متقابل",
        "lines": [f"پیشنهاد: {offer_id}", f"مبلغ متقابل: {amount:,} تومان"],
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت پیشنهاد متقابل نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _tool_propose_reservation(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _commercial_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    offer_id = str(args.get("offer_id") or "").strip()
    if not offer_id:
        return _denied("offer_id الزامی است.")
    hold_note = str(args.get("hold_note") or "").strip()
    payload = {"offer_id": offer_id, "hold_note": hold_note}
    token = _store_pending_action(user_key=me, action_type="confirm_reservation", payload=payload)
    ui = {
        "type": "confirm_reservation",
        "token": token,
        "title": "تأیید رزرو نرم",
        "lines": [
            f"پیشنهاد: {offer_id}",
            "رزرو نرم — بدون قفل assignment / بدون commission deal",
        ],
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت رزرو نرم نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _closing_tools_gate(phone: str) -> dict[str, Any] | None:
    try:
        from app.closing.config import closing_ai_tools_enabled

        if not closing_ai_tools_enabled():
            return _denied("ابزار بستن معامله فعلاً غیرفعال است.")
    except Exception:
        return _denied("ابزار بستن معامله در دسترس نیست.")
    me = (phone or "").strip()
    if not me:
        return _denied("کاربر شناسایی نشد.")
    if not partner_is_approved(me):
        return _denied("برای ثبت قرارداد/قسط باید حساب همکاری تأیید شده باشد.")
    return None


def _resolve_closing_deal_id(phone: str, args: dict[str, Any]) -> str:
    deal_id = str(args.get("deal_id") or "").strip()
    if deal_id:
        return deal_id
    land_code = str(args.get("land_code") or "").strip()
    if not land_code:
        try:
            land_code = _resolve_tool_land_code(phone, args or {})
        except Exception:
            land_code = ""
    if not land_code:
        land_code = _active_mission_land_code(phone) or _land_code_from_user_message()
    if not land_code:
        return ""
    try:
        from app.closing.service import list_partner_deals

        for d in list_partner_deals(phone, limit=20):
            if d.land_code == land_code and d.status not in ("cancelled",):
                return d.id
    except Exception:
        pass
    return ""


def _tool_propose_contract(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _closing_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    deal_id = _resolve_closing_deal_id(me, args or {})
    if not deal_id:
        return _denied("deal_id یا land_code با Deal فعال مشخص نیست.")
    title = str(args.get("title") or "").strip() or "قرارداد"
    document_ref = str(args.get("document_ref") or "").strip()
    payload = {"deal_id": deal_id, "title": title, "document_ref": document_ref}
    token = _store_pending_action(user_key=me, action_type="confirm_contract", payload=payload)
    ui = {
        "type": "confirm_contract",
        "token": token,
        "title": "تأیید ثبت قرارداد",
        "lines": [f"Deal: {deal_id}", f"عنوان: {title}"],
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت قرارداد نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _tool_propose_payment_milestone(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _closing_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    try:
        amount = int(args.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return _denied("مبلغ قسط نامعتبر است.")
    deal_id = _resolve_closing_deal_id(me, args or {})
    if not deal_id:
        return _denied("deal_id یا land_code با Deal فعال مشخص نیست.")
    milestone_label = str(args.get("milestone_label") or "").strip()
    due_at = str(args.get("due_at") or "").strip()
    payload = {
        "deal_id": deal_id,
        "amount": amount,
        "milestone_label": milestone_label,
        "due_at": due_at,
    }
    token = _store_pending_action(
        user_key=me, action_type="confirm_payment_milestone", payload=payload
    )
    ui = {
        "type": "confirm_payment_milestone",
        "token": token,
        "title": "تأیید ثبت قسط",
        "lines": [
            f"Deal: {deal_id}",
            f"مبلغ: {amount:,} تومان",
            *([f"برچسب: {milestone_label}"] if milestone_label else []),
        ],
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت قسط نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _tool_propose_settlement(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _closing_tools_gate(phone)
    if gate is not None:
        return gate
    me = (phone or "").strip()
    deal_id = _resolve_closing_deal_id(me, args or {})
    if not deal_id:
        return _denied("deal_id یا land_code با Deal فعال مشخص نیست.")
    try:
        partner_amount = int(args.get("partner_amount") or 0)
    except (TypeError, ValueError):
        partner_amount = 0
    withdrawal_id = str(args.get("withdrawal_id") or "").strip()
    payload = {
        "deal_id": deal_id,
        "partner_amount": partner_amount,
        "withdrawal_id": withdrawal_id,
    }
    token = _store_pending_action(user_key=me, action_type="confirm_settlement", payload=payload)
    ui = {
        "type": "confirm_settlement",
        "token": token,
        "title": "تأیید باز کردن تسویه",
        "lines": [
            f"Deal: {deal_id}",
            *([f"سهم همکار: {partner_amount:,} تومان"] if partner_amount else []),
            *([f"برداشت: {withdrawal_id}"] if withdrawal_id else []),
            "Withdrawal موجود جایگزین نمی‌شود — فقط لینک می‌شود.",
        ],
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت تسویه نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _integration_ai_tools_gate(phone: str) -> dict[str, Any] | None:
    """None if OK; otherwise denied/error dict."""
    try:
        from app.integration.config import integration_ai_tools_enabled

        if not integration_ai_tools_enabled():
            return _denied("ابزار یکپارچه‌سازی فعلاً غیرفعال است.")
    except Exception:
        return _denied("ابزار یکپارچه‌سازی در دسترس نیست.")
    me = (phone or "").strip()
    if not me:
        return _denied("کاربر شناسایی نشد.")
    if not partner_is_approved(me):
        return _denied("برای ثبت لید/وظیفه باید حساب همکاری تأیید شده باشد.")
    return None


def _tool_propose_lead(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _integration_ai_tools_gate(phone)
    if gate is not None:
        return gate
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
    from app.express_partner.visit_requests import split_customer_full_name

    me = (phone or "").strip()
    phone_raw = str(args.get("customer_phone") or "").strip()
    cust = normalize_iran_mobile(phone_raw) or phone_raw
    display_name = str(args.get("display_name") or "").strip()
    notes = str(args.get("notes") or "").strip()
    if cust and not is_valid_iran_mobile(cust):
        return {
            "ok": False,
            "model_result": {"ok": False, "error": "شماره مشتری معتبر نیست."},
            "error": "شماره مشتری معتبر نیست.",
        }
    if not cust and not display_name:
        return {
            "ok": False,
            "model_result": {"ok": False, "error": "شماره یا نام لید لازم است."},
            "error": "شماره یا نام لید لازم است.",
        }
    first, last = ("", "")
    if display_name:
        first, last = split_customer_full_name(display_name)
    payload = {
        "customer_phone": cust,
        "display_name": display_name,
        "first_name": first,
        "last_name": last,
        "notes": notes,
    }
    token = _store_pending_action(user_key=me, action_type="confirm_lead", payload=payload)
    masked = (cust[:4] + "***" + cust[-3:]) if cust and len(cust) >= 7 else (cust or "—")
    lines = [
        f"نام: {display_name or '—'}",
        f"تماس: {masked}",
    ]
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_lead",
        "token": token,
        "title": "تأیید ثبت لید",
        "lines": lines,
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت تأیید لید نشان داده شد؛ هنوز ثبت نشده.",
        },
        "ui_action": ui,
        "land_codes": [],
    }


def _tool_propose_task(args: dict[str, Any], *, phone: str) -> dict[str, Any]:
    gate = _integration_ai_tools_gate(phone)
    if gate is not None:
        return gate
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

    me = (phone or "").strip()
    title = str(args.get("title") or "").strip()
    if not title:
        return {
            "ok": False,
            "model_result": {"ok": False, "error": "عنوان وظیفه لازم است."},
            "error": "عنوان وظیفه لازم است.",
        }
    phone_raw = str(args.get("customer_phone") or "").strip()
    cust = normalize_iran_mobile(phone_raw) or phone_raw
    if cust and not is_valid_iran_mobile(cust):
        return {
            "ok": False,
            "model_result": {"ok": False, "error": "شماره مشتری معتبر نیست."},
            "error": "شماره مشتری معتبر نیست.",
        }
    due_at = str(args.get("due_at") or "").strip()
    notes = str(args.get("notes") or "").strip()
    payload = {
        "title": title,
        "customer_phone": cust,
        "due_at": due_at,
        "notes": notes,
    }
    token = _store_pending_action(user_key=me, action_type="confirm_task", payload=payload)
    lines = [f"عنوان: {title}", f"سررسید: {due_at or '—'}"]
    if cust:
        masked = cust[:4] + "***" + cust[-3:] if len(cust) >= 7 else cust
        lines.append(f"مشتری: {masked}")
    if notes:
        lines.append(f"یادداشت: {notes}")
    ui = {
        "type": "confirm_task",
        "token": token,
        "title": "تأیید ثبت وظیفه",
        "lines": lines,
        "status": "pending",
    }
    return {
        "ok": True,
        "model_result": {
            "ok": True,
            "status": "needs_user_confirmation",
            "instruction": "کارت تأیید وظیفه نشان داده شد؛ هنوز ثبت نشده.",
        },
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
                "instruction": _never_ask_land_instruction(phone),
            },
        }
    snap = _partner_tx_snapshot(phone, code)
    if not snap.get("ok"):
        return {"ok": False, "model_result": {"ok": False, "error": snap.get("error")}}

    mode = str(snap.get("tx_mode") or "")
    ok_modes = meta.get("tool_ok_modes") or ()
    if action_type == "confirm_deal" and not snap.get("has_assignment"):
        try:
            from app.express_partner.partner_missions import claim_express_land_for_partner

            if claim_express_land_for_partner(phone, code, source="chat_claim"):
                snap = _partner_tx_snapshot(phone, code)
                mode = str(snap.get("tx_mode") or "")
        except Exception:
            pass
    if action_type == "confirm_deal" and not snap.get("has_assignment"):
        return {
            "ok": False,
            "model_result": {
                "ok": False,
                "error": (
                    "این فایل برای ثبت معامله در دسترس نیست "
                    "(فروخته‌شده یا در معامله همکار دیگر)."
                ),
                "tx_mode": mode,
                "land_code": code,
            },
        }
    if mode not in ok_modes:
        # اعلام انجام قبلاً ثبت شده — پیام شفاف، نه خطای گیج‌کننده
        if action_type == "confirm_complete_visit" and mode == "visit_done_pending":
            speak = (
                "اعلام «بازدید انجام شد» قبلاً ثبت شده و منتظر تأیید ادمین است. "
                "لازم نیست دوباره بنویسی."
            )
            return {
                "ok": True,
                "model_result": {
                    "ok": True,
                    "status": "visit_done_awaiting_admin",
                    "land_code": code,
                    "tx_mode": mode,
                    "speak_exactly": speak,
                    "instruction": "عین speak_exactly را بفرست. دوباره propose_complete_visit نزن.",
                },
                "ui_action": _visit_call_info_ui(
                    title="بازدید انجام شد — منتظر تأیید",
                    lines=[
                        f"فایل: {snap.get('land_title')} ({code})",
                        f"هماهنگی: {_visit_coord_call_target()}",
                    ],
                    note=speak,
                    land_code=code,
                ),
                "land_codes": [],
            }
        hints = {
            "confirm_complete_visit": "الان نمی‌شود «بازدید انجام شد» زد؛ باید بازدید تأییدشده در جریان باشد.",
            "confirm_deal": {
                "visit_commission_pending": (
                    "بازدید انجام شده؛ مستقیم معامله را ثبت کن (پورسانت بازدید نداریم)."
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
    call_phone = _visit_coord_call_target()
    if err == "already_pending":
        _consume_pending_action(token)
        # به‌جای پیام خام، وضعیت واقعی + کارت مناسب
        try:
            from app.express_partner.visit_requests import partner_open_visit as _pov

            open_rec = _pov(visit_requests, me, code)
        except Exception:
            open_rec = None
        if isinstance(open_rec, dict):
            offered = _response_for_open_visit(phone=me, land_code=code, open_rec=open_rec)
            mr = offered.get("model_result") if isinstance(offered.get("model_result"), dict) else {}
            msg = str(mr.get("speak_exactly") or "").strip() or (
                f"این بازدید از قبل ثبت شده. برای هماهنگی با {call_phone} تماس بگیر."
            )
            out = {
                "ok": True,
                "already": True,
                "call_phone": call_phone,
                "show_visit_call": True,
                "message": msg,
                "land_code": code,
            }
            ui = offered.get("ui_action")
            if isinstance(ui, dict):
                out["ui_action"] = ui
            return out
        return {
            "ok": True,
            "already": True,
            "call_phone": call_phone,
            "show_visit_call": True,
            "message": (
                "این بازدید از قبل ثبت شده. "
                f"برای هماهنگی بازدید با {call_phone} تماس بگیر."
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
    # Phase 1 CRM: optional Contact upsert from Visit customer_* (flags default ON).
    try:
        from app.crm.visit_sync import sync_contact_from_visit
        sync_contact_from_visit(rec)
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
            f"برای هماهنگی بازدید همین حالا با {call_phone} تماس بگیر؛ "
            "بعد از بازدید از همین چت بگو «بازدید انجام شد» "
            "تا کارت تأیید بیاید — لازم نیست به صفحه دیگری بروی."
        ),
        "visit_id": str(rec.get("id") or ""),
        "land_code": code,
        "visit_date_jalali": vdate_j,
        "call_phone": call_phone,
        "show_visit_call": True,
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
    if action_type == "confirm_log_call":
        return _confirm_log_call(phone=me, token=token, pending=pending)
    if action_type == "confirm_followup":
        return _confirm_followup(phone=me, token=token, pending=pending)
    if action_type == "confirm_visit_result":
        return _confirm_visit_result(phone=me, token=token, pending=pending)
    if action_type == "confirm_no_show":
        return _confirm_no_show(phone=me, token=token, pending=pending)
    if action_type == "confirm_offer":
        return _confirm_offer(phone=me, token=token, pending=pending)
    if action_type == "confirm_counter_offer":
        return _confirm_counter_offer(phone=me, token=token, pending=pending)
    if action_type == "confirm_reservation":
        return _confirm_reservation(phone=me, token=token, pending=pending)
    if action_type == "confirm_contract":
        return _confirm_contract(phone=me, token=token, pending=pending)
    if action_type == "confirm_payment_milestone":
        return _confirm_payment_milestone(phone=me, token=token, pending=pending)
    if action_type == "confirm_settlement":
        return _confirm_settlement(phone=me, token=token, pending=pending)
    if action_type == "confirm_lead":
        return _confirm_lead(phone=me, token=token, pending=pending)
    if action_type == "confirm_task":
        return _confirm_task(phone=me, token=token, pending=pending)
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
        try:
            from app.express_partner.partner_missions import claim_express_land_for_partner

            if claim_express_land_for_partner(me, code, source="chat_claim"):
                snap = _partner_tx_snapshot(me, code)
                mode = str(snap.get("tx_mode") or "")
        except Exception:
            pass
    if action_type == "confirm_deal" and not snap.get("has_assignment"):
        return {
            "ok": False,
            "error": (
                "این فایل برای ثبت معامله در دسترس نیست "
                "(فروخته‌شده یا در معامله همکار دیگر)."
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


def _ensure_crm_contact_from_payload(phone: str, payload: dict[str, Any]) -> str:
    """Return contact_id, creating contact if needed."""
    from app.crm.service import upsert_contact

    cid = str(payload.get("contact_id") or "").strip()
    if cid:
        return cid
    contact = upsert_contact(
        partner_phone=phone,
        customer_phone=str(payload.get("customer_phone") or ""),
        first_name=str(payload.get("first_name") or ""),
        last_name=str(payload.get("last_name") or ""),
        display_name=str(payload.get("customer_name") or ""),
        source="manual",
    )
    return contact.id if contact else ""


def _confirm_log_call(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.crm.config import VISIT_CALL_TARGET, crm_ai_tools_enabled
    from app.crm.service import log_call

    if not crm_ai_tools_enabled():
        return {"ok": False, "error": "ابزار CRM غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    contact_id = _ensure_crm_contact_from_payload(phone, payload)
    if not contact_id:
        return {"ok": False, "error": "ثبت مشتری برای تماس ممکن نشد."}
    call = log_call(
        partner_phone=phone,
        contact_id=contact_id,
        outcome=str(payload.get("outcome") or ""),
        notes=str(payload.get("notes") or ""),
        to_number=str(payload.get("to_number") or "") or VISIT_CALL_TARGET,
    )
    if not call:
        return {"ok": False, "error": "ثبت تماس ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "تماس ثبت شد.",
        "call_id": call.id,
        "contact_id": contact_id,
    }


def _confirm_followup(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.crm.config import crm_ai_tools_enabled
    from app.crm.service import schedule_followup

    if not crm_ai_tools_enabled():
        return {"ok": False, "error": "ابزار CRM غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    contact_id = _ensure_crm_contact_from_payload(phone, payload)
    if not contact_id:
        return {"ok": False, "error": "ثبت مشتری برای پیگیری ممکن نشد."}
    fu = schedule_followup(
        partner_phone=phone,
        contact_id=contact_id,
        due_at=str(payload.get("due_at") or ""),
        notes=str(payload.get("notes") or ""),
    )
    if not fu:
        return {"ok": False, "error": "ثبت پیگیری ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "پیگیری ثبت شد.",
        "followup_id": fu.id,
        "contact_id": contact_id,
    }


def _confirm_lead(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.crm.service import create_lead, upsert_contact
    from app.integration.config import integration_ai_tools_enabled

    if not integration_ai_tools_enabled():
        return {"ok": False, "error": "ابزار یکپارچه‌سازی غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    cust = str(payload.get("customer_phone") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    lead = create_lead(
        partner_phone=phone,
        customer_phone=cust,
        first_name=str(payload.get("first_name") or ""),
        last_name=str(payload.get("last_name") or ""),
        display_name=display_name,
        notes=notes,
        metadata={"source": "ai"},
    )
    if not lead:
        return {"ok": False, "error": "ثبت لید ممکن نشد."}
    contact_id = ""
    if cust:
        contact = upsert_contact(
            partner_phone=phone,
            customer_phone=cust,
            first_name=str(payload.get("first_name") or ""),
            last_name=str(payload.get("last_name") or ""),
            display_name=display_name or lead.display_name,
            source="lead",
            lead_id=lead.id,
            notes=notes,
        )
        if contact:
            contact_id = contact.id
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "لید ثبت شد.",
        "lead_id": lead.id,
        "contact_id": contact_id,
    }


def _confirm_task(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.crm.service import create_task, list_partner_customers, upsert_contact
    from app.integration.config import integration_ai_tools_enabled

    if not integration_ai_tools_enabled():
        return {"ok": False, "error": "ابزار یکپارچه‌سازی غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "عنوان وظیفه نامعتبر است."}
    contact_id = ""
    cust = str(payload.get("customer_phone") or "").strip()
    if cust:
        for c in list_partner_customers(phone, limit=500):
            if c.customer_phone == cust:
                contact_id = c.id
                break
        if not contact_id:
            contact = upsert_contact(
                partner_phone=phone,
                customer_phone=cust,
                source="manual",
            )
            if contact:
                contact_id = contact.id
    task = create_task(
        partner_phone=phone,
        title=title,
        contact_id=contact_id,
        due_at=str(payload.get("due_at") or ""),
        notes=str(payload.get("notes") or ""),
        metadata={"source": "ai"},
    )
    if not task:
        return {"ok": False, "error": "ثبت وظیفه ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "وظیفه ثبت شد.",
        "task_id": task.id,
        "contact_id": contact_id,
    }


def _confirm_visit_result(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.visit_result.config import visit_result_ai_tools_enabled
    from app.visit_result.service import register_result, valid_outcome

    if not visit_result_ai_tools_enabled():
        return {"ok": False, "error": "ابزار نتیجه بازدید غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    outcome = str(payload.get("outcome") or "").strip()
    if not valid_outcome(outcome) or outcome == "no_show":
        return {"ok": False, "error": "نتیجه نامعتبر است."}
    result = register_result(
        visit_request_id=str(payload.get("visit_request_id") or ""),
        partner_phone=phone,
        land_code=str(payload.get("land_code") or ""),
        outcome=outcome,
        notes=str(payload.get("notes") or ""),
        actor_key=phone,
        source="ai",
    )
    if result is None:
        return {"ok": False, "error": "ثبت نتیجه بازدید ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "نتیجه بازدید ثبت شد.",
        "result_id": result.id,
        "outcome": result.outcome,
        "land_code": result.land_code,
    }


def _confirm_no_show(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.visit_result.config import visit_result_ai_tools_enabled
    from app.visit_result.service import register_no_show
    from app.visit_result.status_bridge import is_no_show_writable
    from app.utils.storage import load_express_visit_requests, save_express_visit_requests

    if not visit_result_ai_tools_enabled() or not is_no_show_writable():
        return {"ok": False, "error": "ثبت عدم حضور غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    visits = load_express_visit_requests() or []
    if not isinstance(visits, list):
        visits = []
    rec, _result, err = register_no_show(
        visits,
        visit_request_id=str(payload.get("visit_request_id") or ""),
        partner_phone=phone,
        land_code=str(payload.get("land_code") or ""),
        notes=str(payload.get("notes") or ""),
        actor_key=phone,
        source="ai",
    )
    if err or not rec:
        return {"ok": False, "error": {"disabled": "غیرفعال است.", "not_found": "بازدید یافت نشد.", "invalid_status": "وضعیت مناسب نیست."}.get(str(err), "ثبت عدم حضور ممکن نشد.")}
    try:
        save_express_visit_requests(visits)
    except Exception:
        return {"ok": False, "error": "ذخیره وضعیت ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "عدم حضور ثبت شد. می‌توانید بازدید جدید ثبت کنید.",
        "land_code": str(rec.get("land_code") or ""),
        "visit_status": "no_show",
    }


def _confirm_offer(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.commercial.config import commercial_ai_tools_enabled
    from app.commercial.service import propose_offer

    if not commercial_ai_tools_enabled():
        return {"ok": False, "error": "ابزار پیشنهاد غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    offer = propose_offer(
        land_code=str(payload.get("land_code") or ""),
        partner_phone=phone,
        buyer_phone=str(payload.get("buyer_phone") or ""),
        amount=amount,
        terms=str(payload.get("terms") or ""),
        proposed_by="ai",
    )
    if offer is None:
        return {"ok": False, "error": "ثبت پیشنهاد ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "پیشنهاد ثبت شد.",
        "offer_id": offer.id,
        "land_code": offer.land_code,
        "amount": offer.amount,
    }


def _confirm_counter_offer(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.commercial.config import commercial_ai_tools_enabled
    from app.commercial.service import propose_counter

    if not commercial_ai_tools_enabled():
        return {"ok": False, "error": "ابزار پیشنهاد غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    counter = propose_counter(
        offer_id=str(payload.get("offer_id") or ""),
        amount=amount,
        terms=str(payload.get("terms") or ""),
        proposed_by="ai",
        actor_key=phone,
    )
    if counter is None:
        return {"ok": False, "error": "ثبت پیشنهاد متقابل ممکن نشد."}
    _consume_pending_action(token)
    return {"ok": True, "message": "پیشنهاد متقابل ثبت شد.", "counter_id": counter.id}


def _confirm_reservation(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.commercial.config import commercial_ai_tools_enabled
    from app.commercial.service import hold_reservation

    if not commercial_ai_tools_enabled():
        return {"ok": False, "error": "ابزار رزرو غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    res = hold_reservation(
        offer_id=str(payload.get("offer_id") or ""),
        hold_note=str(payload.get("hold_note") or ""),
        actor_key=phone,
    )
    if res is None:
        return {"ok": False, "error": "رزرو نرم ممکن نشد (پیشنهاد باید پذیرفته باشد)."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "رزرو نرم ثبت شد (بدون قفل assignment).",
        "reservation_id": res.id,
        "land_code": res.land_code,
    }


def _confirm_contract(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.closing.config import closing_ai_tools_enabled
    from app.closing.service import create_contract, get_deal

    if not closing_ai_tools_enabled():
        return {"ok": False, "error": "ابزار قرارداد غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    deal_id = str(payload.get("deal_id") or "").strip()
    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != phone:
        return {"ok": False, "error": "معامله یافت نشد."}
    contract = create_contract(
        deal_id=deal.id,
        title=str(payload.get("title") or ""),
        document_ref=str(payload.get("document_ref") or ""),
        actor_key=phone,
    )
    if contract is None:
        return {"ok": False, "error": "ثبت قرارداد ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "قرارداد ثبت شد.",
        "contract_id": contract.id,
        "deal_id": deal.id,
    }


def _confirm_payment_milestone(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.closing.config import closing_ai_tools_enabled
    from app.closing.service import add_payment, get_deal

    if not closing_ai_tools_enabled():
        return {"ok": False, "error": "ابزار قسط غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    deal_id = str(payload.get("deal_id") or "").strip()
    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != phone:
        return {"ok": False, "error": "معامله یافت نشد."}
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    pay = add_payment(
        deal_id=deal.id,
        amount=amount,
        milestone_label=str(payload.get("milestone_label") or ""),
        due_at=str(payload.get("due_at") or ""),
        actor_key=phone,
    )
    if pay is None:
        return {"ok": False, "error": "ثبت قسط ممکن نشد."}
    _consume_pending_action(token)
    return {"ok": True, "message": "قسط ثبت شد.", "payment_id": pay.id, "amount": pay.amount}


def _confirm_settlement(*, phone: str, token: str, pending: dict[str, Any]) -> dict[str, Any]:
    from app.closing.config import closing_ai_tools_enabled
    from app.closing.service import get_deal, open_settlement

    if not closing_ai_tools_enabled():
        return {"ok": False, "error": "ابزار تسویه غیرفعال است."}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    deal_id = str(payload.get("deal_id") or "").strip()
    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != phone:
        return {"ok": False, "error": "معامله یافت نشد."}
    try:
        partner_amount = int(payload.get("partner_amount") or 0)
    except (TypeError, ValueError):
        partner_amount = 0
    withdrawal_id = str(payload.get("withdrawal_id") or "").strip()
    parties = []
    if partner_amount > 0:
        parties.append(
            {"role": "partner", "amount": partner_amount, "phone": phone, "label": "پورسانت همکار"}
        )
    settlement = open_settlement(
        deal_id=deal.id,
        parties=parties,
        withdrawal_id=withdrawal_id,
        total_amount=partner_amount,
        actor_key=phone,
    )
    if settlement is None:
        return {"ok": False, "error": "ثبت تسویه ممکن نشد."}
    _consume_pending_action(token)
    return {
        "ok": True,
        "message": "تسویه باز شد (بدون تغییر withdrawal).",
        "settlement_id": settlement.id,
        "deal_id": deal.id,
    }


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


def cancel_pending_action(
    *,
    phone: str,
    token: str,
    thread_id: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    from app.ai.card_registry import STATE_CANCELLED, result_lines_from_confirm
    from app.ai.chat_store import update_agent_action_by_token
    from app.ai.message_types import MSG_TIMELINE

    pending = _load_pending_action(token)
    me = (phone or "").strip()
    if pending and str(pending.get("user_key") or "") != me:
        return {"ok": False, "error": "دسترسی ندارید."}
    if pending:
        _consume_pending_action(token)

    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    note = "انصراف داده شد."
    lines = result_lines_from_confirm(card_type="", message=note, out={})
    updated, msgs, tid = update_agent_action_by_token(
        me,
        token,
        thread_id=thread_id,
        audience=aud,
        new_state=STATE_CANCELLED,
        event="card_cancelled",
        lines=lines,
        note=note,
        actor=me,
        result={"cancelled": True},
    )
    # Soft timeline (avoid duplicate if card not found — still ok)
    try:
        from app.ai.chat_events import emit_timeline

        if updated:
            emit_timeline(
                me,
                event="card_cancelled",
                body=note,
                audience=aud,
                thread_id=tid or (thread_id or ""),
            )
    except Exception:
        pass
    return {
        "ok": True,
        "cancelled": True,
        "card_updated": updated,
        "thread_id": tid or thread_id,
        "messages": msgs,
        "message_type": MSG_TIMELINE,
    }


def apply_confirm_result_to_chat(
    *,
    phone: str,
    token: str,
    thread_id: str | None,
    audience: str,
    confirm_out: dict[str, Any],
) -> dict[str, Any]:
    """After successful confirm: update living card + emit timeline (no dead card)."""
    from app.ai.card_registry import (
        STATE_COMPLETED,
        STATE_FAILED,
        result_lines_from_confirm,
    )
    from app.ai.chat_store import update_agent_action_by_token
    from app.ai.chat_events import emit_timeline

    me = (phone or "").strip()
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    ok = bool(confirm_out.get("ok"))
    note = str(confirm_out.get("message") or ("انجام شد." if ok else "ناموفق"))
    lines = result_lines_from_confirm(
        card_type=str(confirm_out.get("action_type") or ""),
        message=note,
        out=confirm_out,
    )
    state = STATE_COMPLETED if ok else STATE_FAILED
    updated, msgs, tid = update_agent_action_by_token(
        me,
        token,
        thread_id=thread_id,
        audience=aud,
        new_state=state,
        event="card_confirmed" if ok else "card_failed",
        result=dict(confirm_out),
        lines=lines,
        note=note,
        actor=me,
    )
    event_key = "card_confirmed"
    # Prefer domain-specific timeline labels when possible
    if ok:
        if confirm_out.get("visit_id"):
            event_key = "visit_requested"
        elif str(confirm_out.get("tx_mode") or "") in ("deal_pending", "release", "deal"):
            event_key = "deal_started"
        elif confirm_out.get("application_id"):
            event_key = "card_confirmed"
    try:
        if ok:
            emit_timeline(
                me,
                event=event_key,
                body=note,
                audience=aud,
                thread_id=tid or (thread_id or ""),
                land_code=str(confirm_out.get("land_code") or ""),
                meta={"token": token[:12], "visit_id": confirm_out.get("visit_id")},
                case_status="in_progress" if ok else None,
            )
            from app.ai.chat_store import messages_for_ui

            msgs = messages_for_ui(me, tid or thread_id, aud)
        elif not updated:
            # Backward-compatible fallback: plain assistant note
            from app.ai.chat_store import append_exchange

            msgs, tid = append_exchange(
                me,
                "",
                note,
                thread_id=tid or thread_id,
                audience=aud,
            )
    except Exception:
        if not msgs:
            try:
                from app.ai.chat_store import append_exchange

                msgs, tid = append_exchange(
                    me, "", note, thread_id=thread_id, audience=aud
                )
            except Exception:
                pass
    return {
        "card_updated": updated,
        "thread_id": tid or thread_id,
        "messages": msgs,
        "message": note,
    }


def _visit_coord_call_target() -> str:
    try:
        from app.crm.config import VISIT_CALL_TARGET

        return str(VISIT_CALL_TARGET or "09121471301").strip() or "09121471301"
    except Exception:
        return "09121471301"


def _visit_coord_call_btn_html(*, block: bool = False) -> str:
    """دکمه تماس هماهنگی بازدید — همیشه به شماره ثابت North Star."""
    phone = _visit_coord_call_target()
    cls = "ai-agent-btn ai-agent-btn--call"
    if block:
        cls += " ai-agent-btn--call-block"
    return (
        f'<a class="{cls}" href="tel:{escape(phone)}" '
        f'data-vinor-direct-action="1" dir="ltr" '
        f'aria-label="تماس برای هماهنگی بازدید">'
        f'<span aria-hidden="true">📞</span> '
        f'تماس برای هماهنگی بازدید · {escape(phone)}</a>'
    )


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
            "confirm_log_call",
            "confirm_followup",
            "confirm_visit_result",
            "confirm_no_show",
            "confirm_offer",
            "confirm_counter_offer",
            "confirm_reservation",
            "confirm_contract",
            "confirm_payment_milestone",
            "confirm_settlement",
            "confirm_lead",
            "confirm_task",
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
    from app.ai.card_registry import (
        STATE_CANCELLED,
        STATE_COMPLETED,
        STATE_CONFIRMED,
        STATE_EXPIRED,
        STATE_FAILED,
        STATE_PENDING,
        normalize_card,
    )

    action = normalize_card(action)
    atype = str(action.get("type") or "confirm_visit")
    token = str(action.get("token") or "").strip()
    card_id = str(action.get("card_id") or "").strip()
    version = int(action.get("version") or 1)
    schema_version = int(action.get("schema_version") or 1)
    defaults = {
        "confirm_visit": "تأیید ثبت بازدید",
        "confirm_complete_visit": "تأیید: بازدید انجام شد",
        "confirm_deal": "تأیید معامله",
        "confirm_release": "تأیید بستن معامله",
        "confirm_partner_application": "تأیید ثبت درخواست همکاری",
        "confirm_log_call": "تأیید ثبت تماس",
        "confirm_followup": "تأیید ثبت پیگیری",
        "confirm_visit_result": "تأیید ثبت نتیجه بازدید",
        "confirm_no_show": "تأیید عدم حضور",
        "confirm_offer": "تأیید ثبت پیشنهاد",
        "confirm_counter_offer": "تأیید پیشنهاد متقابل",
        "confirm_reservation": "تأیید رزرو نرم",
        "confirm_contract": "تأیید ثبت قرارداد",
        "confirm_payment_milestone": "تأیید ثبت قسط",
        "confirm_settlement": "تأیید باز کردن تسویه",
        "confirm_lead": "تأیید ثبت لید",
        "confirm_task": "تأیید ثبت وظیفه",
    }
    title = escape(str(action.get("title") or defaults.get(atype) or "تأیید اقدام"))
    confirm_label = escape(str(action.get("confirm_label") or "تأیید و ثبت").strip() or "تأیید و ثبت")
    cancel_label = escape(str(action.get("cancel_label") or "انصراف").strip() or "انصراف")
    status = str(action.get("state") or action.get("status") or STATE_PENDING)
    token_active = action.get("token_active", True)
    if status == STATE_PENDING and token and token_active and _load_pending_action(token) is None:
        status = STATE_EXPIRED
    lines = action.get("lines") if isinstance(action.get("lines"), list) else []
    body = "".join(
        f'<div class="ai-agent-line">{escape(str(line))}</div>' for line in lines if str(line).strip()
    )
    state_labels = {
        STATE_PENDING: "در انتظار تأیید",
        STATE_CONFIRMED: "تأیید شد",
        STATE_COMPLETED: "انجام شد",
        STATE_CANCELLED: "لغو شد",
        STATE_EXPIRED: "منقضی شد",
        STATE_FAILED: "ناموفق",
        "executing": "در حال اجرا",
    }
    badge = escape(state_labels.get(status, status))
    attrs = (
        f'data-agent-type="{escape(atype)}" '
        f'data-agent-status="{escape(status)}" '
        f'data-agent-state="{escape(status)}" '
        f'data-card-id="{escape(card_id)}" '
        f'data-card-version="{version}" '
        f'data-schema-version="{schema_version}"'
    )
    if token:
        attrs += f' data-token="{escape(token)}"'

    terminal = status in (
        STATE_CONFIRMED,
        STATE_COMPLETED,
        STATE_CANCELLED,
        STATE_EXPIRED,
        STATE_FAILED,
    ) or status != STATE_PENDING or not token or not token_active

    # بازدید نهایی / ثبت بازدید — دکمه تماس هماهنگی در همه وضعیت‌های کارت
    show_visit_call = atype == "confirm_visit" or bool(action.get("show_visit_call"))
    call_html = _visit_coord_call_btn_html() if show_visit_call else ""

    if terminal:
        note = str(action.get("note") or "").strip()
        if not note:
            if status in (STATE_CONFIRMED, STATE_COMPLETED):
                note = "انجام شد."
            elif status == STATE_CANCELLED:
                note = "انصراف داده شد."
            elif status == STATE_FAILED:
                note = "اجرا ناموفق بود."
            else:
                note = "این پیشنهاد منقضی یا دیگر فعال نیست."
        call_block = (
            f'<div class="ai-agent-card__actions ai-agent-card__actions--call">{call_html}</div>'
            if call_html
            else ""
        )
        return (
            f'<div class="ai-agent-card ai-agent-card--done ai-agent-card--{escape(status)}" {attrs}>'
            f'<div class="ai-agent-card__head">'
            f'<div class="ai-agent-card__title">{title}</div>'
            f'<span class="ai-agent-card__badge">{badge}</span>'
            f"</div>"
            f'<div class="ai-agent-card__body">{body}</div>'
            f'<div class="ai-agent-card__note" data-agent-note>{escape(note)}</div>'
            f"{call_block}"
            f"</div>"
        )
    call_pending = f"{call_html}" if call_html else ""
    return (
        f'<div class="ai-agent-card ai-agent-card--pending" {attrs}>'
        f'<div class="ai-agent-card__head">'
        f'<div class="ai-agent-card__title">{title}</div>'
        f'<span class="ai-agent-card__badge">{badge}</span>'
        f"</div>"
        f'<div class="ai-agent-card__body">{body}</div>'
        f'<div class="ai-agent-card__actions">'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--confirm" data-agent-confirm>{confirm_label}</button>'
        f'<button type="button" class="ai-agent-btn ai-agent-btn--cancel" data-agent-cancel>{cancel_label}</button>'
        f"{call_pending}"
        f"</div>"
        f'<div class="ai-agent-card__note hidden" data-agent-note></div>'
        f"</div>"
    )



def _render_next_action_card(action: dict[str, Any]) -> str:
    title = escape(str(action.get("title") or "کار بعدی"))
    subtitle = escape(str(action.get("subtitle") or ""))
    cta = escape(str(action.get("cta") or "ادامه در چت"))
    url = str(action.get("url") or "").strip()
    chat_prompt = str(action.get("chat_prompt") or "").strip()
    chat_intent = str(action.get("chat_intent") or "").strip()
    link = ""
    if chat_prompt:
        link = (
            f'<button type="button" class="ai-agent-btn ai-agent-btn--confirm" '
            f'data-agent-chat-prompt="{escape(chat_prompt)}" '
            f'data-agent-chat-intent="{escape(chat_intent)}">{cta}</button>'
        )
    elif url:
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
