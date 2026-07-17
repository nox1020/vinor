from __future__ import annotations

import os

from app.business_intelligence.interfaces import BusinessIntelligenceConfig


def bi_enabled() -> bool:
    return (os.environ.get("VINOR_BI_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def bi_inject_hint() -> bool:
    # Default ON — disable with VINOR_BI_INJECT_HINT=0 if needed
    return (os.environ.get("VINOR_BI_INJECT_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_bi_config() -> BusinessIntelligenceConfig:
    return BusinessIntelligenceConfig(
        enabled=bi_enabled(),
        inject_hint=bi_inject_hint(),
    )
