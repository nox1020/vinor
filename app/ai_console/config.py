# -*- coding: utf-8 -*-
"""AI Admin Console (Mission Control) — flags default ON."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ai_console_enabled() -> bool:
    return _env_bool("VINOR_AI_CONSOLE_ENABLED", "1")


def ai_console_ui_enabled() -> bool:
    if not ai_console_enabled():
        return False
    return _env_bool("VINOR_AI_CONSOLE_UI_ENABLED", "1")


def ai_console_mutate_enabled() -> bool:
    """Allow Super Admin mutate (expire pending, purge memory)."""
    if not ai_console_enabled():
        return False
    return _env_bool("VINOR_AI_CONSOLE_MUTATE_ENABLED", "1")
