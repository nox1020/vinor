from __future__ import annotations

import os


def customer_success_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_SUCCESS_ENABLED", default=True)


def customer_success_hint_budget_chars() -> int:
    try:
        return max(30, min(60, int(os.environ.get("VINOR_CUSTOMER_SUCCESS_HINT_CHARS") or 55)))
    except Exception:
        return 55


def customer_success_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_SUCCESS_CACHE", default=True)


def customer_success_inject_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CUSTOMER_SUCCESS_INJECT_HINT", default=True)
