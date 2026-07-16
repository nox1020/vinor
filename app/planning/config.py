from __future__ import annotations

import os


def planning_enabled() -> bool:
    return (os.environ.get("VINOR_PLANNING_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def planning_inject_hint() -> bool:
    # Compact executor findings only — never full plan object.
    return (os.environ.get("VINOR_PLANNING_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def planning_hint_budget_chars() -> int:
    try:
        return max(40, min(220, int(os.environ.get("VINOR_PLANNING_HINT_CHARS") or 120)))
    except Exception:
        return 120


def planning_seed_tool_messages() -> bool:
    # Seed tool results into agent loop to avoid duplicate tool rounds.
    return (os.environ.get("VINOR_PLANNING_SEED_TOOLS") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
