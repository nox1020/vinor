from __future__ import annotations

import os


def memory_enabled() -> bool:
    return (os.environ.get("VINOR_MEMORY_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def memory_budget_chars() -> int:
    try:
        return max(80, min(600, int(os.environ.get("VINOR_MEMORY_BUDGET_CHARS") or 280)))
    except Exception:
        return 280


def memory_top_k() -> int:
    try:
        return max(1, min(16, int(os.environ.get("VINOR_MEMORY_TOP_K") or 8)))
    except Exception:
        return 8


def memory_store_backend() -> str:
    return (os.environ.get("VINOR_MEMORY_STORE") or "file").strip().lower()
