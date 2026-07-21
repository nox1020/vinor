"""Facade ناظر قیف — برای چت، حافظه و رسدکننده."""
from __future__ import annotations

from typing import Any

from app.supervisor.funnel import (
    FunnelSnapshot,
    clear_reach_signal,
    list_reach_signals,
    load_snapshot,
    update_funnel,
)


def watch_user(
    user_key: str,
    *,
    audience: str = "",
    voice: str = "",
) -> FunnelSnapshot | None:
    return update_funnel(user_key, audience=audience, voice=voice)


def current_stage(user_key: str) -> str:
    snap = load_snapshot(user_key)
    return str(snap.stage or "") if snap else ""


def current_progress(user_key: str) -> float:
    snap = load_snapshot(user_key)
    return float(snap.progress) if snap else 0.0


def chat_hint(user_key: str) -> str:
    """Hint داخلی برای چت — ناظر پیام نمی‌فرستد."""
    snap = load_snapshot(user_key)
    if not snap or not snap.next_hint:
        return ""
    try:
        from app.ai.goal import wrap_internal_hint

        return wrap_internal_hint(f"ناظر قیف: {snap.next_hint}")
    except Exception:
        return f"ناظر قیف: {snap.next_hint}"


def funnel_obs(user_key: str) -> dict[str, Any]:
    snap = load_snapshot(user_key)
    if not snap:
        return {}
    return {
        "funnel_stage": snap.stage,
        "funnel_progress": snap.progress,
        "funnel_stalled": snap.stalled,
        "funnel_signal_reach": snap.signal_reach,
        "funnel_land": snap.land_code,
        "funnel_idle_hours": snap.idle_hours,
    }


__all__ = [
    "FunnelSnapshot",
    "watch_user",
    "current_stage",
    "current_progress",
    "chat_hint",
    "funnel_obs",
    "list_reach_signals",
    "clear_reach_signal",
    "load_snapshot",
]
