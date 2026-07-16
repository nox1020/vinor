from __future__ import annotations

import os


def self_learning_enabled() -> bool:
    return (os.environ.get("VINOR_SELF_LEARNING_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
