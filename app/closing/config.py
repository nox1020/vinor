# -*- coding: utf-8 -*-
"""Phase 4 Closing & Finance feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def closing_enabled() -> bool:
    """Master switch for Phase 4 Closing & Finance layer."""
    return _env_bool("VINOR_CLOSING_ENABLED", "1")


def closing_ui_enabled() -> bool:
    """Partner deals UI. Requires master."""
    if not closing_enabled():
        return False
    return _env_bool("VINOR_CLOSING_UI_ENABLED", "1")


def closing_ai_tools_enabled() -> bool:
    """propose_contract / payment / settlement. Requires master."""
    if not closing_enabled():
        return False
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_CLOSING_AI_TOOLS_ENABLED", default=True)


def closing_activity_hook_enabled() -> bool:
    """Foundation Activity/Timeline on closing writes. Requires master."""
    if not closing_enabled():
        return False
    return _env_bool("VINOR_CLOSING_ACTIVITY_HOOK_ENABLED", "1")


def closing_deal_bridge_enabled() -> bool:
    """Sync Deal from mark-in-tx / commission. Requires master."""
    if not closing_enabled():
        return False
    return _env_bool("VINOR_CLOSING_DEAL_BRIDGE_ENABLED", "1")


def closing_reservation_bridge_enabled() -> bool:
    """Link reservation converted → Deal (no mark-in-tx). Requires master."""
    if not closing_enabled():
        return False
    return _env_bool("VINOR_CLOSING_RESERVATION_BRIDGE_ENABLED", "1")
