from __future__ import annotations

import os


def conversation_enabled() -> bool:
    return (os.environ.get("VINOR_CONVERSATION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def conversation_early_return() -> bool:
    """When True, active COLLECTING workflows skip Supervisor/LLM (token save)."""
    return (os.environ.get("VINOR_CONVERSATION_EARLY_RETURN") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
