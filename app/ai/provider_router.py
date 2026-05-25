"""انتخاب DeepSeek API در شرایط خاص؛ در بقیهٔ موارد مدل آفلاین."""
from __future__ import annotations

import os
import re
from typing import Any

from .audience import AUDIENCE_PARTNER
from .escalations import has_pending_answers
from .credits import is_api_balance_depleted
from .offline_engine import offline_available

# موضوعات حساس / پیچیده → ترجیح API
_API_TRIGGER_PATTERNS = (
    r"مقایسه",
    r"تحلیل",
    r"بهترین\s+فایل",
    r"پیشنهاد\s+.*فایل",
    r"چند\s+.*ملک",
    r"قرارداد",
    r"حقوقی",
    r"سند\s+ملک",
    r"پورسانت\s+دقیق",
    r"محاسبه\s+پورسانت",
    r"مذاکره",
    r"معامله\s+در\s+جریان",
)


def provider_mode() -> str:
    """offline | api | auto"""
    raw = (os.environ.get("VINOR_AI_PROVIDER") or "auto").strip().lower()
    if raw in ("offline", "local", "gguf"):
        return "offline"
    if raw in ("api", "deepseek", "cloud"):
        return "api"
    return "auto"


def _has_admin_pending(user_key: str, audience: str) -> bool:
    if not user_key:
        return False
    try:
        return has_pending_answers(user_key, audience=audience)
    except Exception:
        return False


def _message_needs_api(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, ""

    max_offline_len = int(os.environ.get("VINOR_AI_API_IF_LONGER_THAN", "420"))
    if len(t) > max_offline_len:
        return True, "long_message"

    if re.search(r"\[\[LAND:", t, flags=re.I):
        return True, "explicit_land_marker"

    if re.search(r"\b[A-Z]{1,3}-?\d{3,}\b", t):
        return True, "land_code_in_question"

    for pat in _API_TRIGGER_PATTERNS:
        if re.search(pat, t, flags=re.I):
            return True, "complex_topic"

    force_kw = (os.environ.get("VINOR_AI_FORCE_API_KEYWORDS") or "").strip()
    if force_kw:
        for kw in force_kw.split(","):
            kw = kw.strip()
            if kw and kw in t:
                return True, "force_keyword"

    return False, ""


def should_use_deepseek(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    user_key: str | None = None,
    audience: str | None = None,
) -> tuple[bool, str]:
    """
    True = فراخوانی DeepSeek
    False = مدل آفلاین (اگر نصب باشد)
    """
    mode = provider_mode()
    if mode == "api":
        return True, "mode_api"
    if mode == "offline":
        return False, "mode_offline"

    if not offline_available():
        return True, "offline_missing"

    if is_api_balance_depleted():
        return False, "api_balance_depleted"

    needs, why = _message_needs_api(message)
    if needs:
        return True, why

    if _has_admin_pending(user_key or "", audience or AUDIENCE_PARTNER):
        return True, "admin_answers_pending"

    hist = history or []
    if len(hist) >= int(os.environ.get("VINOR_AI_API_IF_HISTORY_GE", "14")):
        return True, "long_conversation"

    if (message or "").strip().lower() in ("!api", "/api"):
        return True, "user_force_api"

    return False, "default_offline"


def allow_api_fallback_after_offline_fail() -> bool:
    return os.environ.get("VINOR_AI_OFFLINE_FALLBACK_API", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def allow_offline_fallback_after_api_fail() -> bool:
    return os.environ.get("VINOR_AI_API_FALLBACK_OFFLINE", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def route_info(use_api: bool, reason: str) -> dict[str, Any]:
    return {
        "use_api": use_api,
        "reason": reason,
        "mode": provider_mode(),
        "offline_ready": offline_available(),
    }
