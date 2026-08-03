from __future__ import annotations

import os

from app.evaluation.interfaces import EvaluationConfig


def evaluation_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_EVALUATION_ENABLED", default=True)


def evaluation_store_logs() -> bool:
    return (os.environ.get("VINOR_EVALUATION_STORE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_evaluation_config() -> EvaluationConfig:
    try:
        top = max(5, min(50, int(os.environ.get("VINOR_EVALUATION_TOP_QUERIES") or 20)))
    except Exception:
        top = 20
    return EvaluationConfig(
        enabled=evaluation_enabled(),
        store_logs=evaluation_store_logs(),
        max_top_queries=top,
    )
