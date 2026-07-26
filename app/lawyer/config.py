# -*- coding: utf-8 -*-
"""وکیل ملکی وینور — تنظیمات قابل‌ویرایش از پنل ادمین."""
from __future__ import annotations

import os
from typing import Any


DEFAULT_WELCOME = (
    "سلام، من وکیل ملکی وینور هستم.\n"
    "دربارهٔ خرید و فروش، قولنامه، مبایعه‌نامه، سند، رهن و اجاره، "
    "کمیسیون، مالیات نقل‌وانتقال، افراز، سرقفلی و اختلافات ملکی در ایران بپرسید.\n"
    "پاسخ‌ها جنبهٔ راهنمایی حقوقی دارند و جایگزین وکالت رسمی یا رأی دادگاه نیستند."
)

DEFAULT_SYSTEM_PROMPT = """تو وکیل مشاور ملکی وینور هستی — متخصص حقوق املاک ایران.
مخاطب: کاربر اپ وینور (بازاریاب/خریدار/فروشنده). لحن: حرفه‌ای، واضح، فارسی معیار، بدون لاتین‌بازی.

دامنه:
- معاملات ملکی (قولنامه، مبایعه‌نامه، سند رسمی، وکالت فروش)
- رهن و اجاره، تمدید، تخلیه، سرقفلی
- پیش‌فروش ساختمان، مشارکت در ساخت
- کمیسیون مشاور املاک، تعهدات طرفین
- مالیات نقل‌وانتقال، عوارض، ارزش افزوده مرتبط با ملک (در حد آگاهی عمومی)
- افراز، تفکیک، مشاع، حق ریشه، نسق، اراضی کشاورزی (کلیات)
- چک و تضمین در معاملات ملکی، فسخ و اقاله
- نکات ثبتی و دفترخانه (رویهٔ رایج، نه جایگزین استعلام ثبت)

قوانین پاسخ:
- همیشه بر اساس قوانین و رویه‌های رایج جمهوری اسلامی ایران صحبت کن؛ اگر قانون اخیراً عوض شده یا مبهم است صریح بگو و توصیه کن از وکیل محلی/استعلام رسمی استفاده شود.
- پاسخ ساخت‌یافته و کاربردی: ۱) جمع‌بندی کوتاه ۲) نکات قانونی ۳) ریسک‌ها ۴) اقدام پیشنهادی.
- عدد و ماده را فقط وقتی مطمئنی ذکر کن؛ حدس نزن.
- برای پروندهٔ خاص کاربر، مدرک و جزئیات بخواه قبل از نتیجه‌گیری قطعی.
- هر پاسخ را با یادآوری کوتاه تمام کن که این راهنمایی عمومی است و وکالت رسمی نیست.
- لینک/URL نده مگر ادمین در دانش سیستم گذاشته باشد.
- فروش فایل وینور/پیشنهاد ملک نکن مگر کاربر صریحاً بخواهد به چت فروش برگردد.
- نگو هوش مصنوعی هستی؛ بگو وکیل مشاور ملکی وینور.
"""

DEFAULT_KNOWLEDGE = (
    "یادداشت ادمین (قابل ویرایش در پنل):\n"
    "- هنگام ابهام در قانون جدید، کاربر را به استعلام از دفترخانه / اداره ثبت / وکیل محلی ارجاع بده.\n"
    "- برای معاملات بزرگ: تنظیم سند رسمی، احراز هویت، استعلام بازداشت و ممنوع‌المعامله الزامی است.\n"
)


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def lawyer_feature_enabled() -> bool:
    """فلگ قابلیت — پیش‌فرض روشن."""
    return _env_bool("VINOR_LAWYER_ENABLED", "1")


def default_lawyer_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "display_name": "وکیل ملکی",
        "welcome": DEFAULT_WELCOME,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "knowledge_notes": DEFAULT_KNOWLEDGE,
        "show_disclaimer": True,
    }


def _coerce(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_lawyer_settings()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw and raw["enabled"] is not None:
        if isinstance(raw["enabled"], bool):
            out["enabled"] = raw["enabled"]
        else:
            out["enabled"] = str(raw["enabled"]).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
    if "show_disclaimer" in raw and raw["show_disclaimer"] is not None:
        if isinstance(raw["show_disclaimer"], bool):
            out["show_disclaimer"] = raw["show_disclaimer"]
        else:
            out["show_disclaimer"] = str(raw["show_disclaimer"]).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
    for key in ("display_name", "welcome", "system_prompt", "knowledge_notes"):
        if key in raw and raw[key] is not None:
            val = str(raw[key]).strip()
            if val:
                out[key] = val
    return out


def get_lawyer_settings() -> dict[str, Any]:
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("lawyer")
    except Exception:
        stored = None
    out = _coerce(stored if isinstance(stored, dict) else None)
    if not lawyer_feature_enabled():
        out["enabled"] = False
    return out


def lawyer_enabled() -> bool:
    return bool(get_lawyer_settings().get("enabled"))


def save_lawyer_settings(patch: dict[str, Any]) -> dict[str, Any]:
    import json

    from app.utils.storage import _SETTINGS_CACHE, ensure_file, load_settings

    current = dict(load_settings() or {})
    raw = current.get("lawyer") if isinstance(current.get("lawyer"), dict) else {}
    merged = _coerce({**raw, **(patch or {})})
    current["lawyer"] = merged
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return merged


def build_lawyer_system_prompt() -> str:
    cfg = get_lawyer_settings()
    parts = [str(cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()]
    notes = str(cfg.get("knowledge_notes") or "").strip()
    if notes:
        parts.append("=== دانش/یادداشت ادمین برای وکیل ===\n" + notes)
    if cfg.get("show_disclaimer", True):
        parts.append(
            "در هر پاسخ جدی، یک خط یادآوری کن: راهنمایی عمومی است و جایگزین وکالت رسمی نیست."
        )
    return "\n\n".join(parts)


def lawyer_welcome_text() -> str:
    return str(get_lawyer_settings().get("welcome") or DEFAULT_WELCOME).strip()


def lawyer_display_name() -> str:
    return str(get_lawyer_settings().get("display_name") or "وکیل ملکی").strip() or "وکیل ملکی"
