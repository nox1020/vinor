from __future__ import annotations

import os


def world_model_enabled() -> bool:
    return (os.environ.get("VINOR_WORLD_MODEL_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
