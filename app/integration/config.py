# -*- coding: utf-8 -*-
"""Phase 6 Integration feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def integration_enabled() -> bool:
    return _env_bool("VINOR_INTEGRATION_ENABLED", "1")


def integration_ui_enabled() -> bool:
    if not integration_enabled():
        return False
    return _env_bool("VINOR_INTEGRATION_UI_ENABLED", "1")


def integration_journey_enabled() -> bool:
    if not integration_enabled():
        return False
    return _env_bool("VINOR_INTEGRATION_JOURNEY_ENABLED", "1")


def integration_workflows_enabled() -> bool:
    if not integration_enabled():
        return False
    return _env_bool("VINOR_INTEGRATION_WORKFLOWS_ENABLED", "1")


def integration_ai_tools_enabled() -> bool:
    if not integration_enabled():
        return False
    return _env_bool("VINOR_INTEGRATION_AI_TOOLS_ENABLED", "1")


def integration_activity_hook_enabled() -> bool:
    if not integration_enabled():
        return False
    return _env_bool("VINOR_INTEGRATION_ACTIVITY_HOOK_ENABLED", "1")
