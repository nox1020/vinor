from __future__ import annotations

import os


def supervisor_enabled() -> bool:
    return (os.environ.get("VINOR_SUPERVISOR_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def supervisor_default_context_budget() -> int:
    try:
        return max(800, min(6000, int(os.environ.get("VINOR_SUPERVISOR_CONTEXT_BUDGET") or 3000)))
    except Exception:
        return 3000
