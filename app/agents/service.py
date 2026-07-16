from __future__ import annotations

import threading
from typing import Any

from app.agents.config import agents_enabled
from app.agents.di import make_agent_manager
from app.agents.interfaces import AgentContext, AgentManager, AgentOutcome

_LOCK = threading.Lock()
_MANAGER: AgentManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}


def get_agent_manager() -> AgentManager | None:
    global _MANAGER
    if not agents_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_agent_manager()
    return _MANAGER


def prepare_agent(
    *,
    message: str,
    route: str = "",
    audience: str = "",
    voice: str = "",
    chip_intent: str = "",
    user_key: str = "",
    thread_id: str | None = None,
    context_budget_chars: int = 3000,
) -> AgentOutcome | None:
    """Supervisor-driven: select & prepare at most one agent (lazy)."""
    manager = get_agent_manager()
    if manager is None:
        return None
    try:
        return manager.prepare(
            AgentContext(
                message=message or "",
                route=route or "",
                audience=audience,
                voice=voice,
                chip_intent=chip_intent or "",
                user_key=user_key,
                thread_id=thread_id,
                context_budget_chars=int(context_budget_chars or 3000),
            )
        )
    except Exception:
        return None


def set_agent_obs(outcome: AgentOutcome | None) -> None:
    global _FALLBACK_OBS
    if outcome is None:
        obs: dict[str, Any] = {}
        _FALLBACK_OBS = {}
    else:
        result = outcome.result
        obs = {
            "selected_agent": outcome.selection.selected_agent or "",
            "skipped_agents": list(outcome.selection.skipped_agents or []),
            "agent_reason": outcome.selection.reason or "",
            "agent_status": (result.status if result else ""),
            "agent_tokens": int(result.agent_tokens if result else 0),
            "agent_execution_time_ms": int(
                (result.execution_time_ms if result else 0) or outcome.execution_time_ms or 0
            ),
            "agent_used_components": list(result.used_components if result else []),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_agent_obs = dict(obs)
            g.ai_agent_outcome = outcome
    except Exception:
        pass


def get_agent_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_agent_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    if _FALLBACK_OBS:
        return dict(_FALLBACK_OBS)
    return {
        "selected_agent": "",
        "skipped_agents": [],
        "agent_reason": "",
        "agent_status": "",
        "agent_tokens": 0,
        "agent_execution_time_ms": 0,
        "agent_used_components": [],
    }


def prepare_agent_after_supervisor(
    *,
    message: str,
    route: str = "",
    audience: str = "",
    voice: str = "",
    chip_intent: str = "",
    user_key: str = "",
    thread_id: str | None = None,
    context_budget_chars: int = 3000,
) -> AgentOutcome | None:
    """Public hook used by generate_reply after Supervisor.orchestrate."""
    out = prepare_agent(
        message=message,
        route=route,
        audience=audience,
        voice=voice,
        chip_intent=chip_intent,
        user_key=user_key,
        thread_id=thread_id,
        context_budget_chars=context_budget_chars,
    )
    set_agent_obs(out)
    return out
