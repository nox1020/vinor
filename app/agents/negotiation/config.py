from __future__ import annotations

import os


def negotiation_enabled() -> bool:
    return (os.environ.get("VINOR_NEGOTIATION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def negotiation_hint_budget_chars() -> int:
    try:
        return max(30, min(60, int(os.environ.get("VINOR_NEGOTIATION_HINT_CHARS") or 55)))
    except Exception:
        return 55


def negotiation_cache_enabled() -> bool:
    return (os.environ.get("VINOR_NEGOTIATION_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def negotiation_inject_hint() -> bool:
    return (os.environ.get("VINOR_NEGOTIATION_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
