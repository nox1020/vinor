from __future__ import annotations

import threading
from typing import Any

from app.executive.di import make_executive_ai
from app.executive.engine import executive_enabled
from app.executive.interfaces import ExecutiveAI, ExecutivePlan, ExecutiveRequest

_LOCK = threading.Lock()
_AI: ExecutiveAI | None = None
_FALLBACK: dict[str, Any] = {}


def get_executive_ai() -> ExecutiveAI | None:
    global _AI
    if not executive_enabled():
        return None
    if _AI is not None:
        return _AI
    with _LOCK:
        if _AI is None:
            _AI = make_executive_ai()
    return _AI


def plan_execution(
    *,
    message: str = "",
    audience: str = "",
    intent: str = "",
    conversation_handled: bool = False,
) -> ExecutivePlan:
    """Fail-open: if disabled, return full plan (preserve current behavior)."""
    ai = get_executive_ai()
    if ai is None:
        plan = ExecutivePlan(reason="executive_disabled_passthrough")
    else:
        try:
            plan = ai.plan(
                ExecutiveRequest(
                    message=message,
                    audience=audience,
                    intent=intent,
                    conversation_handled=conversation_handled,
                )
            )
        except Exception:
            plan = ExecutivePlan(reason="executive_error_passthrough")
    data = plan.to_dict()
    global _FALLBACK
    _FALLBACK = data
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_executive_plan = data
    except Exception:
        pass
    return plan


def get_executive_plan() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_executive_plan", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK) if _FALLBACK else ExecutivePlan().to_dict()
