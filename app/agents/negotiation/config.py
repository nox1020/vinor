from __future__ import annotations

import os


def negotiation_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_NEGOTIATION_ENABLED", default=True)


def negotiation_hint_budget_chars() -> int:
    try:
        return max(30, min(60, int(os.environ.get("VINOR_NEGOTIATION_HINT_CHARS") or 55)))
    except Exception:
        return 55


def negotiation_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_NEGOTIATION_CACHE", default=True)


def negotiation_inject_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_NEGOTIATION_INJECT_HINT", default=True)
