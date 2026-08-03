# -*- coding: utf-8 -*-
"""Supervisor Agent feature flags — پیش‌فرض روشن."""
from __future__ import annotations


def supervisor_agent_enabled() -> bool:
    """ایجنت گزارش‌دهنده چت عملیات ادمین."""
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_SUPERVISOR_AGENT_ENABLED", default=True)


def supervisor_agent_poll_enabled() -> bool:
    """Polling پیام‌های ناظر در چت ادمین."""
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_SUPERVISOR_AGENT_POLL", default=True)
