"""اولویت همیشه با مدل آفلاین؛ DeepSeek فقط در حالت صریح یا نبود آفلاین."""
from __future__ import annotations

import os
import re
from typing import Any

from .audience import AUDIENCE_PARTNER
from .credits import is_api_balance_depleted
from .offline_engine import offline_available


def provider_mode() -> str:
    """پیش‌فرض: offline — اولویت همیشه مدل محلی."""
    raw = (os.environ.get("VINOR_AI_PROVIDER") or "offline").strip().lower()
    if raw in ("offline", "local", "gguf"):
        return "offline"
    if raw in ("api", "deepseek", "cloud"):
        return "api"
    if raw == "auto":
        return "auto"
    return "offline"


def _use_api_for_complex_enabled() -> bool:
    """فقط اگر صریحاً فعال شده — در حالت پیش‌فرض خاموش."""
    return os.environ.get("VINOR_AI_USE_API_FOR_COMPLEX", "0").lower() in (
        "1",
        "true",
        "yes",
    )


def _message_needs_api(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, ""

    max_offline_len = int(os.environ.get("VINOR_AI_API_IF_LONGER_THAN", "2000"))
    if len(t) > max_offline_len:
        return True, "long_message"

    if re.search(r"\[\[LAND:", t, flags=re.I):
        return True, "explicit_land_marker"

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
    False = مدل آفلاین (پیش‌فرض)
    """
    mode = provider_mode()

    if (message or "").strip().lower() in ("!api", "/api"):
        return True, "user_force_api"

    if mode == "api":
        return True, "mode_api"

    if mode == "offline":
        return False, "mode_offline"

    # auto = همان offline-first مگر تنظیمات پیچیده فعال باشد
    if offline_available():
        if is_api_balance_depleted():
            return False, "api_balance_depleted"

        if _use_api_for_complex_enabled():
            needs, why = _message_needs_api(message)
            if needs:
                return True, why

        return False, "default_offline"

    return True, "offline_missing"


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
