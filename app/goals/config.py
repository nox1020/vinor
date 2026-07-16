from __future__ import annotations

import os


def goals_enabled() -> bool:
    return (os.environ.get("VINOR_GOALS_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
