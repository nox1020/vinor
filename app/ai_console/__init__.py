# -*- coding: utf-8 -*-
"""
Vinor AI Admin Console (Mission Control)

Additive admin UI under /admin/ai-console/*
Read-mostly over existing AI stores. Flags default ON.
"""

from app.ai_console.config import (
    ai_console_enabled,
    ai_console_mutate_enabled,
    ai_console_ui_enabled,
)
from app.ai_console.service import console_status, dashboard_snapshot

__all__ = [
    "ai_console_enabled",
    "ai_console_ui_enabled",
    "ai_console_mutate_enabled",
    "console_status",
    "dashboard_snapshot",
]
