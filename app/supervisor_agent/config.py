# -*- coding: utf-8 -*-
"""Supervisor Agent feature flags — پیش‌فرض روشن."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def supervisor_agent_enabled() -> bool:
    """ایجنت گزارش‌دهنده چت عملیات ادمین."""
    return _env_bool("VINOR_SUPERVISOR_AGENT_ENABLED", "1")


def supervisor_agent_poll_enabled() -> bool:
    """Polling پیام‌های ناظر در چت ادمین."""
    return _env_bool("VINOR_SUPERVISOR_AGENT_POLL", "1")
