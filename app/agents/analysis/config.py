from __future__ import annotations

import os


def analysis_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_ANALYSIS_ENABLED", default=True)


def analysis_hint_budget_chars() -> int:
    try:
        return max(40, min(180, int(os.environ.get("VINOR_ANALYSIS_HINT_CHARS") or 100)))
    except Exception:
        return 100


def analysis_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_ANALYSIS_CACHE", default=True)


def analysis_inject_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_ANALYSIS_INJECT_HINT", default=True)
