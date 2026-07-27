"""سقف توکن و زمینهٔ prompt به‌ازای voice (ایجنت) — اولویت مصرف بهینه."""
from __future__ import annotations

from typing import Any

from .audience import VOICE_ADMIN, VOICE_LAWYER, VOICE_PARTNER, VOICE_PUBLIC, VOICE_SPECIAL
from .credits import budget_config


def agent_budget(voice: str | None) -> dict[str, Any]:
    """
    بودجهٔ هر ایجنت روی تنظیمات global (settings.json) سوار می‌شود و فقط سقف می‌زند.

    - lawyer: بدون زمینه/حافظه فروش؛ completion کوتاه‌تر
    - public: پاسخ کوتاه مهمان
    - partner/special: بازاریاب — completion متوسط
    - admin: عملیات — context محدودتر، completion کمی بیشتر
    """
    base = budget_config()
    v = (voice or "").strip().lower()
    out: dict[str, Any] = {
        "voice": v or VOICE_PUBLIC,
        "max_tokens": int(base["max_tokens"]),
        "max_history": int(base["max_history"]),
        "max_context_chars": int(base["max_context_chars"]),
        "inject_partner_context": True,
        "inject_user_memory": True,
        "inject_system_memory": True,
        "inject_funnel_hint": True,
    }

    if v == VOICE_LAWYER:
        out.update(
            {
                "max_tokens": min(int(base["max_tokens"]), 384),
                "max_history": min(int(base["max_history"]), 3),
                "inject_partner_context": False,
                "inject_user_memory": False,
                "inject_system_memory": False,
                "inject_funnel_hint": False,
            }
        )
        return out

    if v == VOICE_PUBLIC:
        out["max_tokens"] = min(int(base["max_tokens"]), 320)
        out["max_context_chars"] = min(int(base["max_context_chars"]), 2000)
        return out

    if v in (VOICE_PARTNER, VOICE_SPECIAL):
        out["max_tokens"] = min(int(base["max_tokens"]), 384)
        return out

    if v == VOICE_ADMIN:
        out.update(
            {
                "max_tokens": min(int(base["max_tokens"]), 448),
                "max_history": min(int(base["max_history"]), 3),
                "max_context_chars": min(int(base["max_context_chars"]), 1600),
                "inject_user_memory": False,
            }
        )
        return out

    return out
