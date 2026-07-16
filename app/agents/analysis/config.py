from __future__ import annotations

import os


def analysis_enabled() -> bool:
    return (os.environ.get("VINOR_ANALYSIS_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def analysis_hint_budget_chars() -> int:
    try:
        return max(40, min(180, int(os.environ.get("VINOR_ANALYSIS_HINT_CHARS") or 100)))
    except Exception:
        return 100


def analysis_cache_enabled() -> bool:
    return (os.environ.get("VINOR_ANALYSIS_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def analysis_inject_hint() -> bool:
    return (os.environ.get("VINOR_ANALYSIS_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
