from __future__ import annotations

import os


def adaptive_enabled() -> bool:
    return (os.environ.get("VINOR_ADAPTIVE_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def confidence_low_threshold() -> float:
    try:
        return max(0.1, min(0.95, float(os.environ.get("VINOR_ADAPTIVE_CONF_THRESHOLD") or 0.55)))
    except Exception:
        return 0.55


def max_retries() -> int:
    try:
        return max(0, min(1, int(os.environ.get("VINOR_ADAPTIVE_MAX_RETRIES") or 1)))
    except Exception:
        return 1
