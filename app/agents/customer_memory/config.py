from __future__ import annotations

import os


def customer_memory_enabled() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_MEMORY_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def customer_memory_hint_budget_chars() -> int:
    try:
        return max(40, min(100, int(os.environ.get("VINOR_CUSTOMER_MEMORY_HINT_CHARS") or 55)))
    except Exception:
        return 55


def customer_memory_cache_enabled() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_MEMORY_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def customer_memory_inject_hint() -> bool:
    return (os.environ.get("VINOR_CUSTOMER_MEMORY_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
