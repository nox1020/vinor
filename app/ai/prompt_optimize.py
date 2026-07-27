"""کنترل بهینه‌سازی توکن prompt — پیش‌فرض روشن؛ با VINOR_AI_TOKEN_OPTIMIZE=0 خاموش."""
from __future__ import annotations

import os
from typing import Any


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def token_optimize_enabled() -> bool:
    return _env_bool("VINOR_AI_TOKEN_OPTIMIZE", "1")


def use_compact_prompts() -> bool:
    return token_optimize_enabled()


def skip_redundant_tool_hint() -> bool:
    """وقتی schema ابزار به API می‌رود، hint تکراری مسیر ابزار حذف می‌شود."""
    return token_optimize_enabled()


def skip_redundant_sales_hints() -> bool:
    """چیپ/قیف وقتی ابزار فعال است همان مسیر را تکرار می‌کنند."""
    return token_optimize_enabled()


def use_compact_land_focus() -> bool:
    """فوکوس چت: فقط کد فایل، بدون تکرار خلاصهٔ کامل در system context."""
    return token_optimize_enabled()


def use_compact_tool_schemas() -> bool:
    return token_optimize_enabled()


def prompt_cache_ttl_sec() -> float:
    if token_optimize_enabled():
        try:
            return max(20.0, float(os.environ.get("VINOR_AI_PROMPT_CACHE_TTL") or 90.0))
        except (TypeError, ValueError):
            return 90.0
    return 20.0


def system_memory_char_budget(default: int) -> int:
    if not token_optimize_enabled():
        return default
    try:
        cap = int(os.environ.get("VINOR_SYSTEM_MEMORY_BUDGET_CHARS_OPTIMIZED") or 720)
    except (TypeError, ValueError):
        cap = 720
    return max(200, min(default, cap))


def effective_history_params(keep_last: int) -> dict[str, int]:
    """پنجرهٔ تاریخچه + خلاصه — بدون افزایش پیام‌های خام ارسالی."""
    k = max(1, int(keep_last))
    if token_optimize_enabled():
        return {
            "keep_last": k,
            "window_extra": 10,
            "summary_pick": 8,
            "summary_char_cap": 72,
        }
    return {
        "keep_last": k,
        "window_extra": 6,
        "summary_pick": 6,
        "summary_char_cap": 80,
    }


def land_query_limits(*, assigned_default: int, public_default: int) -> dict[str, int]:
    if token_optimize_enabled():
        return {
            "assigned_default": min(assigned_default, 3),
            "public_default": min(public_default, 2),
            "match_limit_assigned": 4,
            "match_limit_public": 3,
        }
    return {
        "assigned_default": assigned_default,
        "public_default": public_default,
        "match_limit_assigned": 6,
        "match_limit_public": 4,
    }
