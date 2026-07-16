from __future__ import annotations

import os


def long_planner_enabled() -> bool:
    return (os.environ.get("VINOR_LONG_PLANNER_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
