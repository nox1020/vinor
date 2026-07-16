from __future__ import annotations

import threading
from typing import Any

from app.goals.config import goals_enabled
from app.goals.di import make_goal_manager
from app.goals.interfaces import GoalContext, GoalManager, GoalsBundle

_LOCK = threading.Lock()
_MANAGER: GoalManager | None = None
_FALLBACK: dict[str, Any] = {}


def get_goal_manager() -> GoalManager | None:
    global _MANAGER
    if not goals_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_goal_manager()
    return _MANAGER


def _store(bundle: GoalsBundle | None) -> None:
    global _FALLBACK
    data = bundle.to_dict() if bundle else {}
    _FALLBACK = data
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_goals = data
            g.ai_goals_obs = {
                "goal_count": len(data.get("goals") or []),
                "primary_goal_id": data.get("primary_goal_id") or "",
                "extraction_time_ms": int(data.get("extraction_time_ms") or 0),
            }
    except Exception:
        pass


def get_goals() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_goals", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK)


def run_goals(
    *,
    message: str = "",
    user_key: str = "",
    audience: str = "",
    route: str = "",
    intent: str = "",
    role: str = "",
    shared: dict[str, Any] | None = None,
) -> GoalsBundle | None:
    manager = get_goal_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        try:
            from app.conversation.service import get_conversation_obs

            obs = get_conversation_obs()
            intent = intent or str(obs.get("detected_intent") or "")
            role = role or str(obs.get("detected_role") or "")
        except Exception:
            pass
        bundle = manager.run(
            GoalContext(
                message=message,
                user_key=user_key,
                audience=audience,
                route=route,
                intent=intent,
                role=role,
                shared=shared,
            )
        )
        _store(bundle)
        shared["goals"] = bundle.to_dict()
        return bundle
    except Exception:
        return None
