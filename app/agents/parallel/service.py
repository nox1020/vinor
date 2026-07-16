from __future__ import annotations

import threading
from typing import Any

from app.agents.config import agents_enabled
from app.agents.di import make_agent_registry
from app.agents.interfaces import AgentOutcome, AgentResult, AgentSelection
from app.agents.parallel.config import parallel_enabled, parallel_inject_merged_hint
from app.agents.parallel.di import make_parallel_manager
from app.agents.parallel.interfaces import (
    ExecutionContext,
    ExecutionResult,
    ParallelCollaborationManager,
)

_LOCK = threading.Lock()
_MANAGER: ParallelCollaborationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_FALLBACK_HINT: str = ""
_FALLBACK_MERGED: dict[str, Any] = {}


def get_parallel_manager() -> ParallelCollaborationManager | None:
    global _MANAGER
    if not agents_enabled() or not parallel_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_parallel_manager(make_agent_registry())
    return _MANAGER


def _store_obs(result: ExecutionResult | None) -> None:
    global _FALLBACK_OBS, _FALLBACK_HINT, _FALLBACK_MERGED
    if result is None:
        _FALLBACK_OBS = {}
        _FALLBACK_HINT = ""
        _FALLBACK_MERGED = {}
        obs: dict[str, Any] = {}
        hint = ""
        merged: dict[str, Any] = {}
    else:
        hint = result.compact_hint if parallel_inject_merged_hint() else ""
        _FALLBACK_HINT = hint
        merged = dict(result.merged or {})
        _FALLBACK_MERGED = merged
        obs = {
            "parallel_tasks": int(result.parallel_tasks or 0),
            "execution_graph": [list(w) for w in (result.waves_executed or [])],
            "parallel_execution_time_ms": int(result.execution_time_ms or 0),
            "merged_agents": list(result.merged_agents or []),
            "skipped_agents": list(result.skipped_agents or []),
            "parallel_merge_tokens": int(result.merge_tokens or 0),
            "parallel_reuse": True,
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_parallel_obs = dict(obs)
            g.ai_parallel_hint = hint
            g.ai_parallel_merge = merged
    except Exception:
        pass


def get_parallel_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_parallel_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "parallel_tasks": 0,
        "execution_graph": [],
        "parallel_execution_time_ms": 0,
        "merged_agents": [],
        "skipped_agents": [],
        "parallel_merge_tokens": 0,
        "parallel_reuse": False,
    }


def get_parallel_merge_hint() -> str:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            return str(getattr(g, "ai_parallel_hint", "") or "")
    except Exception:
        pass
    return _FALLBACK_HINT or ""


def get_parallel_merge() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_parallel_merge", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_MERGED) if _FALLBACK_MERGED else {}


def run_parallel_collaboration(
    *,
    message: str = "",
    route: str = "",
    audience: str = "",
    voice: str = "",
    chip_intent: str = "",
    user_key: str = "",
    thread_id: str | None = None,
    context_budget_chars: int = 3000,
    shared: dict[str, Any] | None = None,
    parallel: bool = True,
) -> ExecutionResult | None:
    manager = get_parallel_manager()
    if manager is None:
        return None
    try:
        result = manager.run(
            ExecutionContext(
                message=message or "",
                route=route or "",
                audience=audience or "",
                voice=voice or "",
                chip_intent=chip_intent or "",
                user_key=user_key or "",
                thread_id=thread_id,
                context_budget_chars=int(context_budget_chars or 3000),
                shared=dict(shared or {}),
                parallel=bool(parallel),
            )
        )
        _store_obs(result)
        return result
    except Exception:
        return None


def execution_result_to_outcome(result: ExecutionResult) -> AgentOutcome:
    """Adapt parallel result to existing AgentOutcome for Adaptive/obs compatibility."""
    from app.agents.interfaces import (
        AGENT_CUSTOMER_MEMORY,
        AGENT_FOLLOW_UP,
        AGENT_NEGOTIATION,
        AGENT_PROPERTY_ANALYSIS,
        AGENT_PROPERTY_SEARCH,
        AGENT_RECOMMENDATION,
    )

    depth = {
        AGENT_PROPERTY_SEARCH: 0,
        AGENT_CUSTOMER_MEMORY: 0,
        AGENT_PROPERTY_ANALYSIS: 1,
        AGENT_RECOMMENDATION: 2,
        AGENT_NEGOTIATION: 3,
        AGENT_FOLLOW_UP: 4,
    }
    primary = ""
    if result.merged_agents:
        primary = max(
            result.merged_agents,
            key=lambda a: (depth.get(a, 0), 1 if a == AGENT_PROPERTY_SEARCH else 0),
        )

    agent_tokens = int(result.merge_tokens or 0)
    status = "ready" if result.merged_agents else "skipped"
    return AgentOutcome(
        selection=AgentSelection(
            selected_agent=primary,
            skipped_agents=list(result.skipped_agents or []),
            reason=str((result.metadata or {}).get("reason") or "parallel"),
        ),
        result=AgentResult(
            agent_id=primary,
            status=status,
            ok=bool(result.ok),
            skipped=not bool(result.merged_agents),
            used_components=["parallel"] + list(result.merged_agents or []),
            agent_tokens=agent_tokens,
            execution_time_ms=int(result.execution_time_ms or 0),
            metadata={
                "parallel_tasks": result.parallel_tasks,
                "waves": result.waves_executed,
                "merged_agents": result.merged_agents,
            },
        ),
        execution_time_ms=int(result.execution_time_ms or 0),
    )
