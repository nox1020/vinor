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
    """Supervisor-driven agent prepare — Parallel Collaboration when enabled (Phase 16)."""
    # Parallel Multi-Agent path (fail-open to sequential single-agent).
    try:
        from app.agents.parallel.config import parallel_enabled
        from app.agents.parallel.service import (
            execution_result_to_outcome,
            run_parallel_collaboration,
        )

        if parallel_enabled():
            pre = run_parallel_collaboration(
                message=message,
                route=route,
                audience=audience,
                voice=voice,
                chip_intent=chip_intent,
                user_key=user_key,
                thread_id=thread_id,
                context_budget_chars=context_budget_chars,
                parallel=True,
            )
            if pre is not None:
                # Decision Engine (Phase 17): finalize after parallel — no agent re-run.
                try:
                    from app.agents.parallel.service import get_parallel_merge
                    from app.decision.service import run_decision

                    pm = get_parallel_merge() or dict(pre.merged or {})
                    shared = dict((pre.metadata or {}).get("shared") or {})
                    shared.update(pm)
                    if pre.merged.get("recommendation"):
                        shared.setdefault("recommended_code", pre.merged.get("recommendation"))
                    try:
                        from app.executive.service import get_executive_plan

                        eplan = get_executive_plan()
                        run_dec = eplan.get("run_decision", True) if eplan else True
                        run_bi = eplan.get("run_bi", True) if eplan else True
                        run_wm = eplan.get("run_world_model", True) if eplan else True
                        run_lp = eplan.get("run_long_plan", True) if eplan else True
                    except Exception:
                        run_dec = run_bi = run_wm = run_lp = True
                    if run_dec:
                        run_decision(
                            message=message,
                            route=route,
                            shared=shared,
                            parallel_merge=pm,
                        )
                    if run_bi:
                        try:
                            from app.business_intelligence.service import run_business_intelligence

                            run_business_intelligence(
                                message=message, route=route, shared=shared
                            )
                        except Exception:
                            pass
                    if run_wm:
                        try:
                            from app.world_model.service import update_world_model

                            update_world_model(shared=shared)
                        except Exception:
                            pass
                    if run_lp:
                        try:
                            from app.long_planner.service import build_long_plan

                            build_long_plan(shared=shared, route=route)
                        except Exception:
                            pass
                except Exception:
                    pass
                return execution_result_to_outcome(pre)
    except Exception:
        pass

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
    """Hook داخلی بعد از Supervisor — هویت محصول همان یک بازاریاب چت است."""
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
