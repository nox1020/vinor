from __future__ import annotations

import os


def customer_memory_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_MEMORY_ENABLED", default=True)


def customer_memory_hint_budget_chars() -> int:
    try:
        return max(40, min(100, int(os.environ.get("VINOR_CUSTOMER_MEMORY_HINT_CHARS") or 55)))
    except Exception:
        return 55


def customer_memory_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_MEMORY_CACHE", default=True)


def customer_memory_inject_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_MEMORY_INJECT_HINT", default=True)
