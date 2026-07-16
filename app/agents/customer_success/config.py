from __future__ import annotations

import os


def customer_success_enabled() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_SUCCESS_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def customer_success_hint_budget_chars() -> int:
    try:
        return max(30, min(60, int(os.environ.get("VINOR_CUSTOMER_SUCCESS_HINT_CHARS") or 55)))
    except Exception:
        return 55


def customer_success_cache_enabled() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_SUCCESS_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def customer_success_inject_hint() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_SUCCESS_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
