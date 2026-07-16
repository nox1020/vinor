from __future__ import annotations

import os


def recommendation_enabled() -> bool:
    return (os.environ.get("VINOR_RECOMMENDATION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def recommendation_hint_budget_chars() -> int:
    try:
        return max(40, min(160, int(os.environ.get("VINOR_RECOMMENDATION_HINT_CHARS") or 90)))
    except Exception:
        return 90


def recommendation_cache_enabled() -> bool:
    return (os.environ.get("VINOR_RECOMMENDATION_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def recommendation_inject_hint() -> bool:
    return (os.environ.get("VINOR_RECOMMENDATION_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
