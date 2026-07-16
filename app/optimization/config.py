from __future__ import annotations

import os

from app.optimization.interfaces import OptimizationConfig


def optimization_enabled() -> bool:
    return (os.environ.get("VINOR_OPTIMIZATION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def optimization_scheduler_enabled() -> bool:
    # Default OFF — background opt-in only
    return (os.environ.get("VINOR_OPTIMIZATION_SCHEDULER") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_optimization_config() -> OptimizationConfig:
    try:
        interval = max(300, int(os.environ.get("VINOR_OPTIMIZATION_INTERVAL_SEC") or 3600))
    except Exception:
        interval = 3600
    try:
        lookback = max(1, int(os.environ.get("VINOR_OPTIMIZATION_LOOKBACK_HOURS") or 24))
    except Exception:
        lookback = 24
    try:
        min_samples = max(1, int(os.environ.get("VINOR_OPTIMIZATION_MIN_SAMPLES") or 5))
    except Exception:
        min_samples = 5
    return OptimizationConfig(
        enabled=optimization_enabled(),
        scheduler_enabled=optimization_scheduler_enabled(),
        interval_seconds=interval,
        lookback_hours=lookback,
        min_samples=min_samples,
        auto_apply=False,
    )
