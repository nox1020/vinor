from __future__ import annotations

import os


def recommendation_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_RECOMMENDATION_ENABLED", default=True)


def recommendation_hint_budget_chars() -> int:
    try:
        return max(40, min(160, int(os.environ.get("VINOR_RECOMMENDATION_HINT_CHARS") or 90)))
    except Exception:
        return 90


def recommendation_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_RECOMMENDATION_CACHE", default=True)


def recommendation_inject_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_RECOMMENDATION_INJECT_HINT", default=True)
