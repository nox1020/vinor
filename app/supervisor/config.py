from __future__ import annotations

import os


def supervisor_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_SUPERVISOR_ENABLED", default=True)


def supervisor_default_context_budget() -> int:
    try:
        return max(800, min(2400, int(os.environ.get("VINOR_SUPERVISOR_CONTEXT_BUDGET") or 2400)))
    except Exception:
        return 2400


def funnel_watch_enabled() -> bool:
    """ناظر قیف فروش — پیش‌فرض ON."""
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_FUNNEL_WATCH_ENABLED", default=True)


def funnel_stall_hours() -> float:
    try:
        return max(1.0, min(168.0, float(os.environ.get("VINOR_FUNNEL_STALL_HOURS") or 24)))
    except Exception:
        return 24.0
