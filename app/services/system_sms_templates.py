# -*- coding: utf-8 -*-
"""رجیstry پیامک‌های سیستمی وینور — مشاهده و ویرایش از پنل ادمین."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app

from app.utils.storage import load_settings, ensure_file, _save, _SETTINGS_CACHE

_OVERRIDES_FILENAME = "system_sms_overrides.json"

# کلید تنظیمات legacy در settings.json (scope=settings)
_SETTINGS_KEYS: Dict[str, str] = {
    "partner_application": "partner_application_sms_message",
    "partner_approval": "partner_approval_sms_message",
    "admin_application": "partner_application_admin_sms_message",
    "visit_approved": "visit_approval_sms_message",
    "android_apk_update": "android_apk_update_sms_message",
}

# کلیدهای zarinpal در settings.json → zarinpal.*
_ZARINPAL_KEYS: Dict[str, str] = {
    "plus_activated": "sms_activation_message",
    "plus_renewed": "sms_renewal_message",
    "plus_expiry_reminder": "sms_expiry_reminder_message",
    "plus_expired": "sms_expired_message",
}

_CATEGORY_LABELS: Dict[str, str] = {
    "auth": "احراز هویت",
    "partner": "همکار",
    "admin": "ادمین",
    "visit": "بازدید و معامله",
    "wallet": "کیف پول",
    "plus": "وینور پلاس",
    "broadcast": "پخش گروهی",
    "celebration": "تبریک",
    "ai": "هوش مصنوعی",
    "reach": "Reach",
    "sales": "مربی فروش",
}

# default_body, placeholders, recipient, trigger, editable, delivery, history_source, config_scope
_REGISTRY: List[Dict[str, Any]] = [
    {
        "key": "otp",
        "category": "auth",
        "title": "کد تأیید (OTP)",
        "description": "ورود و ثبت‌نام — متن روی پنل sms.ir (قالب Verify)",
        "default_body": "کد تایید:\n<#> {CODE}\n@vinor.ir #{CODE}\n{HASH}",
        "placeholders": ["CODE", "HASH"],
        "recipient": "کاربر",
        "trigger": "ارسال OTP",
        "editable": False,
        "delivery": "sms_ir_verify",
        "history_source": "otp",
    },
    {
        "key": "partner_application",
        "category": "partner",
        "title": "ثبت درخواست همکاری",
        "description": "پیامک به متقاضی پس از ثبت درخواست",
        "default_body": "وینور\nدرخواست همکاری‌ت ثبت شد؛ منتظر بررسی.",
        "placeholders": [],
        "recipient": "متقاضی",
        "trigger": "ثبت درخواست همکاری",
        "editable": True,
        "config_scope": "settings",
        "history_source": "express_partner_application",
    },
    {
        "key": "partner_approval",
        "category": "partner",
        "title": "تأیید همکاری",
        "description": "فعال‌سازی پنل همکار",
        "default_body": "وینور\nپنل همکاری‌ت فعاله. بزن بریم!",
        "placeholders": [],
        "recipient": "همکار تأییدشده",
        "trigger": "تأیید ادمین",
        "editable": True,
        "config_scope": "settings",
        "history_source": "system",
    },
    {
        "key": "admin_application",
        "category": "admin",
        "title": "همکاری جدید (ادمین)",
        "description": "اطلاع ادمین از درخواست همکاری",
        "default_body": "وینور\nهمکاری جدید\n{name}\n{phone}",
        "placeholders": ["name", "phone", "partner_name", "partner_phone"],
        "recipient": "ادمین",
        "trigger": "درخواست همکاری جدید",
        "editable": True,
        "config_scope": "settings",
        "history_source": "admin_pending_action_application",
    },
    {
        "key": "admin_withdrawal",
        "category": "admin",
        "title": "درخواست برداشت (ادمین)",
        "default_body": "وینور\nبرداشت {amount} تومن\n{name} · {phone}\n{bank_summary}",
        "placeholders": ["amount", "name", "phone", "bank_summary"],
        "recipient": "ادمین",
        "trigger": "درخواست برداشت همکار",
        "editable": True,
        "history_source": "admin_pending_action_withdrawal",
    },
    {
        "key": "admin_visit",
        "category": "admin",
        "title": "بازدید جدید (ادمین)",
        "default_body": "وینور\nبازدید جدید · {land_code}\n{name} · {phone}\n{visit_date}",
        "placeholders": ["land_code", "name", "phone", "visit_date"],
        "recipient": "ادمین",
        "trigger": "ثبت بازدید",
        "editable": True,
        "history_source": "admin_pending_action_visit",
    },
    {
        "key": "admin_visit_schedule",
        "category": "admin",
        "title": "درخواست تعیین وقت (ادمین)",
        "default_body": "وینور\nدرخواست تعیین وقت بازدید\n{name}\n{notes}\nآدرس حضور: {presence_address}\n{system_date}\n{phone}",
        "placeholders": ["name", "notes", "presence_address", "system_date", "phone"],
        "recipient": "ادمین",
        "trigger": "مدال تعیین وقت خانه",
        "editable": True,
        "history_source": "admin_pending_action_visit_schedule",
    },
    {
        "key": "admin_visit_done",
        "category": "admin",
        "title": "انجام بازدید (ادمین)",
        "default_body": "وینور\nانجام بازدید · {land_code}\n{name} · {phone}",
        "placeholders": ["land_code", "name", "phone"],
        "recipient": "ادمین",
        "trigger": "ثبت انجام بازدید",
        "editable": True,
        "history_source": "admin_pending_action_visit_done",
    },
    {
        "key": "admin_commission",
        "category": "admin",
        "title": "پورسانت جدید (ادمین)",
        "default_body": "وینور\nپورسانت {amount} تومن · {land_code}\n{name} · {phone}",
        "placeholders": ["amount", "land_code", "name", "phone"],
        "recipient": "ادمین",
        "trigger": "پورسانت در انتظار تأیید",
        "editable": True,
        "history_source": "admin_pending_action_commission",
    },
    {
        "key": "admin_vinor_plus",
        "category": "admin",
        "title": "درخواست پلاس (ادمین)",
        "default_body": "وینور\nدرخواست پلاس\n{name}\n{phone}",
        "placeholders": ["name", "phone"],
        "recipient": "ادمین",
        "trigger": "درخواست Vinor Plus",
        "editable": True,
        "history_source": "admin_pending_action_vinor_plus",
    },
    {
        "key": "special_owner_visit",
        "category": "admin",
        "title": "بازدید جدید (مالک ویژه)",
        "default_body": "وینور\nبازدید جدید روی آگهی‌ت · {land_code}\nنهایی شد — از صندوق بازدید ببین",
        "placeholders": ["land_code"],
        "recipient": "مالک ویژه",
        "trigger": "بازدید روی آگهی ویژه",
        "editable": True,
        "history_source": "admin_pending_action_visit",
    },
    {
        "key": "visit_schedule",
        "category": "visit",
        "title": "تعیین وقت بازدید",
        "default_body": (
            "وینور\nوقت بازدید تعیین شد\n{when_line}\n{time_line}\n{address_line}\n"
            "{counterpart_block}\n{support_line}"
        ),
        "placeholders": [
            "weekday", "jalali_date", "visit_time", "presence_address",
            "counterpart_label", "counterpart_name", "counterpart_phone",
            "when_line", "time_line", "address_line", "counterpart_block", "support_line",
        ],
        "recipient": "همکار / پلاس",
        "trigger": "تعیین وقت بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "visit_pending",
        "category": "visit",
        "title": "بازدید نهایی شد",
        "default_body": "وینور\nبازدید نهایی شد · {land}\n{vdate}\nآدرس حضور: {presence_address}",
        "placeholders": ["land", "vdate", "presence_address"],
        "recipient": "همکار",
        "trigger": "ثبت بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "visit_approved",
        "category": "visit",
        "title": "تأیید بازدید",
        "default_body": "وینور\nبازدیدت تأیید شد · {land}\n{vdate}\nآدرس حضور: {presence_address}",
        "placeholders": ["land", "vdate", "presence_address"],
        "recipient": "همکار",
        "trigger": "تأیید بازدید ادمین",
        "editable": True,
        "config_scope": "settings",
        "history_source": "system",
    },
    {
        "key": "visit_rejected",
        "category": "visit",
        "title": "بازدید منتفی",
        "default_body": (
            "وینور\nبازدید منتفی شد · {land}\n"
            "ممنون از تلاشت. حالا بازاریابی مجدد: دیوار+نردبان+اینستا{note_line}"
        ),
        "placeholders": ["land", "note_line"],
        "recipient": "همکار",
        "trigger": "لغو بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "visit_done_pending",
        "category": "visit",
        "title": "انجام بازدید ثبت شد",
        "default_body": "وینور\nانجام بازدید ثبت شد · {land}\nمنتظر تأیید",
        "placeholders": ["land"],
        "recipient": "همکار",
        "trigger": "ثبت انجام بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "visit_done_rejected",
        "category": "visit",
        "title": "تأیید بازدید منتفی",
        "default_body": (
            "وینور\nتأیید بازدید منتفی شد · {land}\n"
            "تو تلاشت رو کردی. دوباره دیوار/اینستا و معرفی کن{note_line}"
        ),
        "placeholders": ["land", "note_line"],
        "recipient": "همکار",
        "trigger": "رد تأیید بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "visit_completed",
        "category": "visit",
        "title": "بازدید تأیید شد",
        "default_body": "وینور\nبازدید تأیید شد · {land}\nمی‌تونی معامله بزنی",
        "placeholders": ["land"],
        "recipient": "همکار",
        "trigger": "تکمیل بازدید",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "deal_started",
        "category": "visit",
        "title": "شروع معامله",
        "default_body": "وینور\nمعامله شروع شد · {land}",
        "placeholders": ["land"],
        "recipient": "همکار",
        "trigger": "شروع معامله",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "deal_released",
        "category": "visit",
        "title": "معامله منتفی",
        "default_body": (
            "وینور\nمعامله منتفی شد · {land}\n"
            "ممنون از تلاشت 🌿 دوباره دیوار+نردبان+اینستا"
        ),
        "placeholders": ["land"],
        "recipient": "همکار",
        "trigger": "لغو معامله",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "commission_approved",
        "category": "wallet",
        "title": "ورود پول (+)",
        "default_body": "وینور\n+{amount} تومن\n{title}",
        "placeholders": ["amount", "title", "land_code"],
        "recipient": "همکار",
        "trigger": "تأیید پورسانت",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "withdrawal_paid",
        "category": "wallet",
        "title": "خروج پول (−)",
        "default_body": "وینور\n−{amount} تومن\nواریز به حسابت\n{bank_summary}",
        "placeholders": ["amount", "bank_summary"],
        "recipient": "همکار",
        "trigger": "پرداخت برداشت",
        "editable": True,
        "history_source": "system",
    },
    {
        "key": "plus_activated",
        "category": "plus",
        "title": "فعال‌سازی پلاس",
        "default_body": "وینور\nVinor Plus برای شما فعال شد.\nاز امتیازهای پلاس در پنل همکاری استفاده کنید.",
        "placeholders": ["name", "expires_jalali", "days_remaining"],
        "recipient": "همکار",
        "trigger": "پرداخت پلاس",
        "editable": True,
        "config_scope": "zarinpal",
        "history_source": "vinor_plus_lifecycle",
    },
    {
        "key": "plus_renewed",
        "category": "plus",
        "title": "تمدید پلاس",
        "default_body": "وینور\nاشتراک پلاس با موفقیت تمدید شد.\nتا {expires_jalali} فعال است.",
        "placeholders": ["expires_jalali"],
        "recipient": "همکار",
        "trigger": "تمدید پلاس",
        "editable": True,
        "config_scope": "zarinpal",
        "history_source": "vinor_plus_lifecycle",
    },
    {
        "key": "plus_expiry_reminder",
        "category": "plus",
        "title": "یادآوری انقضای پلاس",
        "default_body": "وینور\nاشتراک پلاس رو به پایان است.\nلطفاً برای تمدید به پنل همکاری مراجعه کنید.",
        "placeholders": ["expires_jalali", "days_remaining"],
        "recipient": "همکار",
        "trigger": "نزدیک انقضا",
        "editable": True,
        "config_scope": "zarinpal",
        "history_source": "vinor_plus_lifecycle",
    },
    {
        "key": "plus_expired",
        "category": "plus",
        "title": "انقضای پلاس",
        "default_body": "وینور\nاشتراک پلاس منقضی شد.\nبرای ادامهٔ امتیازها، اشتراک را تمدید کنید.",
        "placeholders": [],
        "recipient": "همکار",
        "trigger": "انقضای اشتراک",
        "editable": True,
        "config_scope": "zarinpal",
        "history_source": "vinor_plus_lifecycle",
    },
    {
        "key": "new_express_land",
        "category": "broadcast",
        "title": "فایل جدید اکسپرس",
        "default_body": "وینور\nفایل جدید اومد\nپورسانت تا {commission_amount} تومن\n{detail_url}",
        "placeholders": ["commission_amount", "detail_url", "land_code"],
        "recipient": "همکاران تأییدشده",
        "trigger": "انتشار فایل اکسپرس",
        "editable": True,
        "history_source": "new_express_land_broadcast",
    },
    {
        "key": "android_apk_update",
        "category": "broadcast",
        "title": "به‌روزرسانی APK",
        "default_body": (
            "نسخه {version}\n📢 وینور بروزرسانی شد!\n"
            "برای دریافت آخرین نسخه اپلیکیشن روی لینک زیر بزنید:\n🌐 {link}"
        ),
        "placeholders": ["version", "link"],
        "recipient": "گروه گیرندگان APK",
        "trigger": "آپلود APK",
        "editable": True,
        "config_scope": "settings",
        "history_source": "android_apk_update_broadcast",
    },
    {
        "key": "user_birthday",
        "category": "celebration",
        "title": "تبریک تولد",
        "default_body": "وینور\n{name} جان، تولدت مبارک 🎂\nامروز روز خودته؛ خوش بگذره",
        "placeholders": ["name"],
        "recipient": "کاربر / همکار",
        "trigger": "تولد (روزانه)",
        "editable": True,
        "history_source": "daily_celebration",
    },
    {
        "key": "user_membership_anniversary",
        "category": "celebration",
        "title": "سالگرد عضویت",
        "default_body": "وینور\n{name} جان، {years_phrase} با هم بودیم 💚\nممنون که کنار مایی",
        "placeholders": ["name", "years_phrase"],
        "recipient": "کاربر / همکار",
        "trigger": "سالگرد عضویت",
        "editable": True,
        "history_source": "daily_celebration",
    },
    {
        "key": "ai_escalation_question",
        "category": "ai",
        "title": "سوال AI (ادمین)",
        "default_body": "وینور AI — سوال {audience}\nکاربر: {user}\nسوال: {question}\nپنل ادمین: سوالات AI",
        "placeholders": ["audience", "user", "question"],
        "recipient": "ادمین",
        "trigger": "اسکالیشن سوال AI",
        "editable": True,
        "history_source": "ai_escalation",
    },
    {
        "key": "ai_balance_depleted",
        "category": "ai",
        "title": "اتمام موجودی DeepSeek",
        "default_body": "وینور AI\nموجودی حساب DeepSeek تمام شده است.\nلطفاً حساب را شارژ کنید.\nپنل ادمین: سوالات AI",
        "placeholders": [],
        "recipient": "ادمین",
        "trigger": "موجودی AI صفر",
        "editable": True,
        "history_source": "ai_escalation",
    },
    {
        "key": "reach_deal",
        "category": "reach",
        "title": "Reach — معامله باز",
        "default_body": "وینور\nمعامله‌ت {land} هنوز بازه\nبیا تو اپ، از چت تمومش کن",
        "placeholders": ["land"],
        "recipient": "خریدار",
        "trigger": "پیگیری Reach",
        "editable": False,
        "history_source": "reach",
    },
    {
        "key": "sales_coach",
        "category": "sales",
        "title": "مربی فروش",
        "description": "متن‌ها بر اساس مرحله فروش در کد تولید می‌شوند — فقط مشاهده",
        "default_body": "وینور\n{name} جان، {land_code} رو دیوار/اینستا بذار\nپورسانت تا {amount} تومن",
        "placeholders": ["name", "land_code", "amount"],
        "recipient": "همکار",
        "trigger": "یادآوری خودکار",
        "editable": False,
        "history_source": "sales_coach",
    },
]

_REGISTRY_BY_KEY: Dict[str, Dict[str, Any]] = {t["key"]: t for t in _REGISTRY}

# نگاشت رویداد visit_sms → کلید رجیstry
VISIT_EVENT_KEYS: Dict[str, str] = {
    "visit_submitted": "visit_pending",
    "visit_pending": "visit_pending",
    "visit_approved": "visit_approved",
    "visit_rejected": "visit_rejected",
    "visit_done_pending": "visit_done_pending",
    "visit_done_rejected": "visit_done_rejected",
    "visit_completed": "visit_completed",
    "deal_started": "deal_started",
    "deal_released": "deal_released",
}

# نگاشت admin_action → کلید
ADMIN_ACTION_KEYS: Dict[str, str] = {
    "application": "admin_application",
    "withdrawal": "admin_withdrawal",
    "visit": "admin_visit",
    "visit_schedule": "admin_visit_schedule",
    "visit_done": "admin_visit_done",
    "commission": "admin_commission",
    "vinor_plus": "admin_vinor_plus",
}


def _overrides_path(app=None) -> str:
    app = app or current_app._get_current_object()
    data_dir = os.path.join(app.instance_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, _OVERRIDES_FILENAME)


def load_sms_overrides(app=None) -> Dict[str, Any]:
    path = _overrides_path(app)
    if not os.path.exists(path):
        return {"version": 1, "overrides": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "overrides": {}}
        if not isinstance(data.get("overrides"), dict):
            data["overrides"] = {}
        return data
    except Exception:
        return {"version": 1, "overrides": {}}


def save_sms_overrides(data: Dict[str, Any], app=None) -> None:
    path = _overrides_path(app)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _patch_settings(patch: Dict[str, Any], app=None) -> None:
    """به‌روزرسانی settings.json بدون وابستگی به admin.routes."""
    current = load_settings(app) or {}
    for k, v in patch.items():
        current[k] = v
    path = ensure_file("SETTINGS_FILE", "settings.json", {}, app)
    _save(path, current)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category or "", category or "—")


def _legacy_body(key: str, settings: Dict[str, Any]) -> str:
    sk = _SETTINGS_KEYS.get(key)
    if sk:
        return str(settings.get(sk) or "").strip()
    zk = _ZARINPAL_KEYS.get(key)
    if zk:
        zp = settings.get("zarinpal") if isinstance(settings.get("zarinpal"), dict) else {}
        return str(zp.get(zk) or "").strip()
    return ""


def get_template_meta(key: str) -> Optional[Dict[str, Any]]:
    return deepcopy(_REGISTRY_BY_KEY.get((key or "").strip()))


def get_template_body(key: str, *, app=None) -> str:
    """متن مؤثر: override → legacy settings → پیش‌فرض."""
    k = (key or "").strip()
    meta = _REGISTRY_BY_KEY.get(k)
    if not meta:
        return ""
    overrides = load_sms_overrides(app).get("overrides") or {}
    ov = overrides.get(k) if isinstance(overrides.get(k), dict) else {}
    if ov.get("enabled") is False:
        return ""
    body = str(ov.get("body") or "").strip()
    if body:
        return body
    settings = load_settings(app) or {}
    legacy = _legacy_body(k, settings)
    if legacy:
        return legacy
    return str(meta.get("default_body") or "").strip()


def render_system_sms(key: str, ctx: Optional[Dict[str, Any]] = None, *, app=None) -> str:
    """جایگزینی {placeholder} در متن مؤثر."""
    template = get_template_body(key, app=app)
    if not template:
        return ""
    ctx = ctx if isinstance(ctx, dict) else {}

    def _repl(match: re.Match) -> str:
        name = match.group(1)
        val = ctx.get(name)
        if val is None:
            return ""
        return str(val)

    return re.sub(r"\{(\w+)\}", _repl, template)


def sample_context(key: str) -> Dict[str, str]:
    """نمونه برای پیش‌نمایش در پنل ادمین."""
    samples: Dict[str, Dict[str, str]] = {
        "otp": {"CODE": "12345", "HASH": "4R707/AKLt0"},
        "partner_application": {},
        "admin_application": {"name": "مسعود محمد حسینی", "phone": "09101528014"},
        "admin_withdrawal": {"amount": "۱۰،۰۰۰،۰۰۰", "name": "مسعود", "phone": "09101528014", "bank_summary": "ملت ****1234"},
        "admin_visit": {"land_code": "20251101112262", "name": "مسعود", "phone": "09101528014", "visit_date": "۱۴۰۵/۰۶/۰۴"},
        "visit_approved": {"land": "20251101112262", "vdate": "۱۴۰۵/۰۶/۰۴ ساعت ۰۹:۰۰", "presence_address": "گرمابسرد — کارگزاری آسمان"},
        "visit_rejected": {"land": "20251101112262", "note_line": "\nمشتری کنسل کرد"},
        "commission_approved": {"amount": "۲۰،۰۰۰،۰۰۰", "title": "پورسانت فروش · 20251101112262"},
        "withdrawal_paid": {"amount": "۱۰،۰۰۰،۰۰۰", "bank_summary": "ملت ****1234"},
        "visit_schedule": {
            "weekday": "چهارشنبه", "jalali_date": "۱۴۰۵/۰۶/۰۴", "visit_time": "09:00",
            "presence_address": "گرمابسرد", "counterpart_label": "کاربر پلاس",
            "counterpart_name": "مسعود", "counterpart_phone": "09101528014",
            "when_line": "چهارشنبه ۱۴۰۵/۰۶/۰۴", "time_line": "ساعت 09:00",
            "address_line": "آدرس حضور: گرمابسرد",
            "counterpart_block": "کاربر پلاس: مسعود",
            "support_line": "هماهنگی با پشتیبانی: 09101528014",
        },
        "new_express_land": {"commission_amount": "۵،۰۰۰،۰۰۰", "detail_url": "https://vinor.ir/express/…", "land_code": "ABC123"},
        "android_apk_update": {"version": "1.2.0", "link": "https://vinor.ir/apk"},
        "user_birthday": {"name": "مسعود"},
        "user_membership_anniversary": {"name": "مسعود", "years_phrase": "دو سال"},
        "plus_renewed": {"expires_jalali": "۱۴۰۵/۱۲/۰۱"},
    }
    base = samples.get(key, {})
    meta = _REGISTRY_BY_KEY.get(key) or {}
    out: Dict[str, str] = {}
    for ph in meta.get("placeholders") or []:
        out[str(ph)] = base.get(str(ph), f"({ph})")
    return out


def list_system_sms_templates(*, app=None) -> List[Dict[str, Any]]:
    """لیست برای UI ادمین."""
    overrides = load_sms_overrides(app).get("overrides") or {}
    settings = load_settings(app) or {}
    out: List[Dict[str, Any]] = []
    for meta in _REGISTRY:
        k = meta["key"]
        ov = overrides.get(k) if isinstance(overrides.get(k), dict) else {}
        effective = get_template_body(k, app=app)
        default = str(meta.get("default_body") or "")
        legacy = _legacy_body(k, settings)
        customized = bool(str(ov.get("body") or "").strip()) or (
            bool(legacy) and legacy != default
        )
        preview_ctx = sample_context(k)
        preview = render_system_sms(k, preview_ctx, app=app) if effective else ""
        out.append({
            **meta,
            "category_label": category_label(meta.get("category") or ""),
            "effective_body": effective,
            "is_customized": customized,
            "is_enabled": ov.get("enabled", True) is not False,
            "preview": preview[:280],
            "updated_at": ov.get("updated_at") or "",
        })
    return out


def save_template_override(
    key: str,
    body: str,
    *,
    enabled: bool = True,
    updated_by: str = "",
    app=None,
) -> Tuple[bool, str]:
    k = (key or "").strip()
    meta = _REGISTRY_BY_KEY.get(k)
    if not meta:
        return False, "قالب نامعتبر است."
    if not meta.get("editable", True):
        return False, "این قالب فقط خواندنی است."
    body = (body or "").strip()
    if not body:
        return False, "متن پیامک نمی‌تواند خالی باشد."

    data = load_sms_overrides(app)
    overrides = data.setdefault("overrides", {})
    overrides[k] = {
        "body": body,
        "enabled": bool(enabled),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "updated_by": (updated_by or "").strip(),
    }
    save_sms_overrides(data, app)

    scope = meta.get("config_scope")
    if scope == "settings":
        sk = _SETTINGS_KEYS.get(k)
        if sk:
            _patch_settings({sk: body}, app)
    elif scope == "zarinpal":
        zk = _ZARINPAL_KEYS.get(k)
        if zk:
            settings = load_settings(app) or {}
            zp = settings.get("zarinpal") if isinstance(settings.get("zarinpal"), dict) else {}
            zp = dict(zp)
            zp[zk] = body
            _patch_settings({"zarinpal": zp}, app)
    return True, ""


def reset_template_override(key: str, *, app=None) -> Tuple[bool, str]:
    k = (key or "").strip()
    meta = _REGISTRY_BY_KEY.get(k)
    if not meta:
        return False, "قالب نامعتبر است."
    data = load_sms_overrides(app)
    overrides = data.get("overrides") or {}
    if k in overrides:
        del overrides[k]
        data["overrides"] = overrides
        save_sms_overrides(data, app)
    scope = meta.get("config_scope")
    if scope == "settings":
        sk = _SETTINGS_KEYS.get(k)
        if sk:
            _patch_settings({sk: ""}, app)
    elif scope == "zarinpal":
        zk = _ZARINPAL_KEYS.get(k)
        if zk:
            settings = load_settings(app) or {}
            zp = settings.get("zarinpal") if isinstance(settings.get("zarinpal"), dict) else {}
            zp = dict(zp)
            zp[zk] = ""
            _patch_settings({"zarinpal": zp}, app)
    return True, ""


def visit_event_body(event: str, ctx: Dict[str, Any], *, app=None) -> str:
    """متن پیامک بازدید/معامله — با پشتیبانی note_line."""
    ev = (event or "").strip()
    reg_key = VISIT_EVENT_KEYS.get(ev, ev)
    c = dict(ctx)
    land = c.get("land") or c.get("land_code") or ""
    if "land" not in c and land:
        c["land"] = land
    note = (c.get("admin_note") or c.get("note") or "").strip()
    if len(note) > 60:
        note = note[:60] + "…"
    if ev in ("visit_rejected", "visit_done_rejected"):
        c["note_line"] = f"\n{note}" if note else ""
    msg = render_system_sms(reg_key, c, app=app)
    if msg:
        if ev == "visit_approved":
            addr = str(c.get("presence_address") or "").strip()
            if addr and "آدرس حضور" not in msg:
                msg = f"{msg}\nآدرس حضور: {addr}"
        return msg
    return ""


def admin_action_body(action: str, settings: Dict[str, Any], **kw: Any) -> str:
    """متن پیامک اقدام ادمین."""
    act = (action or "").strip()
    reg_key = ADMIN_ACTION_KEYS.get(act)
    if reg_key:
        ctx = {k: v for k, v in kw.items() if v is not None}
        if act == "withdrawal":
            try:
                amt = max(0, int(kw.get("amount") or 0))
                ctx["amount"] = f"{amt:,}".replace(",", "،")
            except (TypeError, ValueError):
                ctx["amount"] = "0"
        if act == "commission":
            try:
                amt = max(0, int(kw.get("amount") or 0))
                ctx["amount"] = f"{amt:,}".replace(",", "،")
            except (TypeError, ValueError):
                ctx["amount"] = "0"
        name = (kw.get("partner_name") or "").strip() or (kw.get("partner_phone") or "").strip() or "همکار"
        phone = (kw.get("partner_phone") or "").strip()
        ctx.setdefault("name", name)
        ctx.setdefault("phone", phone)
        ctx.setdefault("partner_name", name)
        ctx.setdefault("partner_phone", phone)
        msg = render_system_sms(reg_key, ctx)
        if msg:
            return msg
    detail = (kw.get("detail") or "").strip()
    name = (kw.get("partner_name") or "").strip() or "همکار"
    return f"وینور\nاقدام لازم\n{detail or name}"


def wallet_txn_body(event: str, ctx: Dict[str, Any], *, app=None) -> str:
    ev = (event or "").strip()
    c = dict(ctx)
    try:
        amt = max(0, int(str(c.get("amount", 0)).replace(",", "").strip() or "0"))
    except (TypeError, ValueError):
        amt = 0
    c["amount"] = f"{amt:,}".replace(",", "،") if amt else "0"
    title = (c.get("title") or "").strip()
    code = str(c.get("land_code") or "").strip()
    if code and code != "referral" and code not in title:
        c["title"] = f"{title} · {code}" if title else code
    elif title:
        c["title"] = title
    return render_system_sms(ev, c, app=app)


def visit_schedule_body(
    *,
    weekday: str = "",
    jalali_date: str = "",
    visit_time: str = "",
    presence_address: str = "",
    support_phone: str = "",
    counterpart_label: str = "",
    counterpart_name: str = "",
    counterpart_phone: str = "",
    app=None,
) -> str:
    """متن پیامک تعیین وقت بازدید — از رجیstry با خطوط شرطی."""
    day = (weekday or "").strip()
    date_s = (jalali_date or "").strip()
    time_s = (visit_time or "").strip()
    when_parts = [p for p in (day, date_s) if p]
    when_line = " ".join(when_parts) if when_parts else "—"
    time_line = f"ساعت {time_s}" if time_s else ""
    addr = (presence_address or "").strip()
    address_line = f"آدرس حضور: {addr}" if addr else ""
    label_s = (counterpart_label or "").strip()
    name_s = (counterpart_name or "").strip()
    phone_s = (counterpart_phone or "").strip()
    party_lines: List[str] = []
    if label_s and (name_s or phone_s):
        shown = name_s or phone_s
        party_lines.append(f"{label_s}: {shown}")
        if phone_s and phone_s != shown:
            party_lines.append(phone_s)
    counterpart_block = "\n".join(party_lines)
    support = (support_phone or "").strip()
    support_line = f"هماهنگی با پشتیبانی: {support}" if support else ""
    ctx = {
        "weekday": day,
        "jalali_date": date_s,
        "visit_time": time_s,
        "presence_address": addr,
        "counterpart_label": label_s,
        "counterpart_name": name_s,
        "counterpart_phone": phone_s,
        "when_line": when_line,
        "time_line": time_line,
        "address_line": address_line,
        "counterpart_block": counterpart_block,
        "support_line": support_line,
    }
    msg = render_system_sms("visit_schedule", ctx, app=app)
    if not msg:
        return ""
    # حذف خطوط خالی ناشی از placeholderهای تهی
    return "\n".join(line for line in msg.splitlines() if line.strip())
