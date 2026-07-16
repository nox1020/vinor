from __future__ import annotations

import os

from app.decision.interfaces import DecisionConfig


def decision_enabled() -> bool:
    return (os.environ.get("VINOR_DECISION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def decision_inject_hint() -> bool:
    return (os.environ.get("VINOR_DECISION_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except Exception:
        return default


def load_decision_config() -> DecisionConfig:
    try:
        hint = max(40, min(70, int(os.environ.get("VINOR_DECISION_HINT_CHARS") or 60)))
    except Exception:
        hint = 60
    try:
        margin = float(os.environ.get("VINOR_DECISION_CONFLICT_MARGIN") or 0.08)
    except Exception:
        margin = 0.08
    cfg = DecisionConfig(
        search_weight=_f("VINOR_DECISION_W_SEARCH", 0.10),
        analysis_weight=_f("VINOR_DECISION_W_ANALYSIS", 0.20),
        recommendation_weight=_f("VINOR_DECISION_W_RECOMMENDATION", 0.30),
        negotiation_weight=_f("VINOR_DECISION_W_NEGOTIATION", 0.20),
        customer_memory_weight=_f("VINOR_DECISION_W_MEMORY", 0.10),
        customer_success_weight=_f("VINOR_DECISION_W_SUCCESS", 0.10),
        conflict_margin=margin,
        hint_budget_chars=hint,
    )
    return cfg.normalized()
