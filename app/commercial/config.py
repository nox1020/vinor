# -*- coding: utf-8 -*-
"""Phase 3 Commercial feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def commercial_enabled() -> bool:
    """Master switch for Phase 3 Commercial layer."""
    return _env_bool("VINOR_COMMERCIAL_ENABLED", "1")


def commercial_ui_enabled() -> bool:
    """Partner + Special Owner commercial UI. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_UI_ENABLED", "1")


def commercial_buyer_ui_enabled() -> bool:
    """Minimal buyer /my/offers UI. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_BUYER_UI_ENABLED", "1")


def commercial_ai_tools_enabled() -> bool:
    """propose_offer / counter / reservation. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_AI_TOOLS_ENABLED", "1")


def commercial_activity_hook_enabled() -> bool:
    """Foundation Activity/Timeline on commercial writes. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_ACTIVITY_HOOK_ENABLED", "1")


def commercial_workflow_enabled() -> bool:
    """Offer form workflow in engine. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_WORKFLOW_ENABLED", "1")


def commercial_visit_bridge_enabled() -> bool:
    """Open Negotiation from VisitResult interested. Requires master."""
    if not commercial_enabled():
        return False
    return _env_bool("VINOR_COMMERCIAL_VISIT_BRIDGE_ENABLED", "1")
