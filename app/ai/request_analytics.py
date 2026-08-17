"""ثبت مصرف/تحلیل یک درخواست چت — بیرون از prompt، بدون اثر توکنی.

ستون‌های لایه‌های قدیمی (agents/supervisor/decision/…) حفظ شده‌اند چون کنسول
ادمین همان‌ها را می‌خواند؛ وقتی آن لایه‌ها در مسیر درخواست اجرا نشوند مقدارشان
صفر می‌ماند. قبلاً `services._record_request_analytics` بود.
"""
from __future__ import annotations

import time
from typing import Any

from .prompts import get_memory_obs, get_planning_obs
from .runtime_settings import thinking_enabled
from .token_analytics import (
    estimate_messages_tokens,
    estimate_tokens,
    record_token_analytics,
    usage_cost,
)


def _obs(path: str, func: str) -> dict[str, Any]:
    """خواندن observability یک لایه — fail-open به دیکشنری خالی."""
    try:
        module = __import__(path, fromlist=[func])
        out = getattr(module, func)()
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def record_request_analytics(
    *,
    user_key: str,
    audience: str,
    voice: str,
    messages: list[dict[str, Any]],
    prompt_parts: dict[str, int],
    result: dict[str, Any],
    started: float,
) -> None:
    try:
        from .agent_budget import agent_budget

        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or 0) or estimate_messages_tokens(
            messages
        )
        output_tokens = int(usage.get("completion_tokens") or 0) or estimate_tokens(
            result.get("reply") or ""
        )
        reasoning_tokens = 0
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            try:
                reasoning_tokens = int(details.get("reasoning_tokens") or 0)
            except Exception:
                reasoning_tokens = 0
        if not reasoning_tokens:
            try:
                reasoning_tokens = int(usage.get("reasoning_tokens") or 0)
            except Exception:
                reasoning_tokens = 0
        try:
            cache_hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        except Exception:
            cache_hit = 0
        try:
            cache_miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        except Exception:
            cache_miss = 0

        mem_obs = get_memory_obs()
        plan_obs = get_planning_obs()
        sup_obs = _obs("app.supervisor.service", "get_supervisor_obs")
        agent_obs = _obs("app.agents.service", "get_agent_obs")
        adaptive_obs = _obs("app.adaptive.service", "get_adaptive_obs")
        analysis_obs = _obs("app.agents.analysis.service", "get_analysis_obs")
        rec_obs = _obs("app.agents.recommendation.service", "get_recommendation_obs")
        cm_obs = _obs("app.agents.customer_memory.service", "get_customer_memory_obs")
        neg_obs = _obs("app.agents.negotiation.service", "get_negotiation_obs")
        cs_obs = _obs("app.agents.customer_success.service", "get_customer_success_obs")
        parallel_obs = _obs("app.agents.parallel.service", "get_parallel_obs")
        decision_obs = _obs("app.decision.service", "get_decision_obs")
        bi_obs = _obs("app.business_intelligence.service", "get_bi_obs")
        conv_obs = _obs("app.conversation.service", "get_conversation_obs")

        def part_or(key: str, obs: dict[str, Any], obs_key: str) -> int:
            return int(prompt_parts.get(key) or obs.get(obs_key) or 0)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        row = {
            "user": user_key,
            "audience": audience,
            "voice": voice,
            "agent_completion_cap": int(agent_budget(voice).get("max_tokens") or 0),
            "ok": bool(result.get("ok")),
            "provider": meta.get("provider") or "",
            "model": meta.get("model") or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "system_prompt_tokens": int(prompt_parts.get("system_prompt_tokens") or 0),
            "context_tokens": int(prompt_parts.get("context_tokens") or 0),
            "history_tokens": int(prompt_parts.get("history_tokens") or 0),
            "rag_tokens": int(prompt_parts.get("context_tokens") or 0),
            "memory_retrieved": int(mem_obs.get("memory_retrieved") or 0),
            "memory_used": int(mem_obs.get("memory_used") or 0),
            "memory_tokens": part_or("memory_tokens", mem_obs, "memory_tokens"),
            "planning_time_ms": int(plan_obs.get("planning_time_ms") or 0),
            "tasks_count": int(plan_obs.get("tasks_count") or 0),
            "executed_tasks": int(plan_obs.get("executed_tasks") or 0),
            "planning_tokens": part_or("planning_tokens", plan_obs, "planning_tokens"),
            "execution_tokens": part_or(
                "execution_tokens", plan_obs, "execution_tokens"
            ),
            "plan_type": str(plan_obs.get("plan_type") or ""),
            "routed_workflow": str(sup_obs.get("routed_workflow") or ""),
            "executed_components": list(sup_obs.get("executed_components") or []),
            "skipped_components": list(sup_obs.get("skipped_components") or []),
            "routing_time_ms": int(sup_obs.get("routing_time_ms") or 0),
            "selected_agent": str(agent_obs.get("selected_agent") or ""),
            "skipped_agents": list(agent_obs.get("skipped_agents") or []),
            "agent_status": str(agent_obs.get("agent_status") or ""),
            "agent_tokens": int(agent_obs.get("agent_tokens") or 0),
            "agent_execution_time_ms": int(agent_obs.get("agent_execution_time_ms") or 0),
            "analysis_time_ms": int(analysis_obs.get("analysis_time_ms") or 0),
            "analysis_tokens": part_or("analysis_tokens", analysis_obs, "analysis_tokens"),
            "analysis_cache_hit": bool(analysis_obs.get("analysis_cache_hit")),
            "analysis_reused_context": bool(analysis_obs.get("analysis_reused_context")),
            "analysis_reused_rag": bool(analysis_obs.get("analysis_reused_rag")),
            "analysis_reused_memory": bool(analysis_obs.get("analysis_reused_memory")),
            "analysis_reused_planning": bool(analysis_obs.get("analysis_reused_planning")),
            "recommendation_time_ms": int(rec_obs.get("recommendation_time_ms") or 0),
            "recommendation_tokens": part_or(
                "recommendation_tokens", rec_obs, "recommendation_tokens"
            ),
            "recommendation_score": float(rec_obs.get("recommendation_score") or 0),
            "selected_property": str(rec_obs.get("selected_property") or ""),
            "recommendation_cache_hit": bool(rec_obs.get("recommendation_cache_hit")),
            "recommendation_reuse_search": bool(rec_obs.get("recommendation_reuse_search")),
            "recommendation_reuse_analysis": bool(
                rec_obs.get("recommendation_reuse_analysis")
            ),
            "recommendation_reuse_memory": bool(rec_obs.get("recommendation_reuse_memory")),
            "profile_build_time_ms": int(cm_obs.get("profile_build_time_ms") or 0),
            "relationship_score": float(cm_obs.get("relationship_score") or 0),
            "preference_count": int(cm_obs.get("preference_count") or 0),
            "profile_confidence": float(cm_obs.get("profile_confidence") or 0),
            "customer_memory_tokens": part_or(
                "customer_memory_tokens", cm_obs, "customer_memory_tokens"
            ),
            "customer_memory_cache_hit": bool(cm_obs.get("customer_memory_cache_hit")),
            "customer_memory_reuse_memory": bool(cm_obs.get("customer_memory_reuse_memory")),
            "customer_memory_reuse_workflow": bool(
                cm_obs.get("customer_memory_reuse_workflow")
            ),
            "customer_memory_reuse_recommendation": bool(
                cm_obs.get("customer_memory_reuse_recommendation")
            ),
            "negotiation_time_ms": int(neg_obs.get("negotiation_time_ms") or 0),
            "negotiation_tokens": part_or(
                "negotiation_tokens", neg_obs, "negotiation_tokens"
            ),
            "negotiation_confidence": float(neg_obs.get("negotiation_confidence") or 0),
            "negotiation_risk": float(neg_obs.get("negotiation_risk") or 0),
            "deal_probability": float(neg_obs.get("deal_probability") or 0),
            "negotiation_cache_hit": bool(neg_obs.get("negotiation_cache_hit")),
            "negotiation_reuse_analysis": bool(neg_obs.get("negotiation_reuse_analysis")),
            "negotiation_reuse_recommendation": bool(
                neg_obs.get("negotiation_reuse_recommendation")
            ),
            "negotiation_reuse_customer_profile": bool(
                neg_obs.get("negotiation_reuse_customer_profile")
            ),
            "customer_success_time_ms": int(cs_obs.get("customer_success_time_ms") or 0),
            "customer_success_tokens": part_or(
                "customer_success_tokens", cs_obs, "customer_success_tokens"
            ),
            "customer_stage": str(cs_obs.get("customer_stage") or ""),
            "cs_conversion_probability": float(cs_obs.get("conversion_probability") or 0),
            "cs_next_action": str(cs_obs.get("next_action") or ""),
            "cs_priority": str(cs_obs.get("priority") or ""),
            "customer_success_confidence": float(
                cs_obs.get("customer_success_confidence") or 0
            ),
            "customer_success_cache_hit": bool(cs_obs.get("customer_success_cache_hit")),
            "customer_success_reuse_analysis": bool(
                cs_obs.get("customer_success_reuse_analysis")
            ),
            "customer_success_reuse_recommendation": bool(
                cs_obs.get("customer_success_reuse_recommendation")
            ),
            "customer_success_reuse_negotiation": bool(
                cs_obs.get("customer_success_reuse_negotiation")
            ),
            "customer_success_reuse_customer_profile": bool(
                cs_obs.get("customer_success_reuse_customer_profile")
            ),
            "parallel_tasks": int(parallel_obs.get("parallel_tasks") or 0),
            "parallel_execution_time_ms": int(
                parallel_obs.get("parallel_execution_time_ms") or 0
            ),
            "parallel_merge_tokens": part_or(
                "parallel_merge_tokens", parallel_obs, "parallel_merge_tokens"
            ),
            "merged_agents": list(parallel_obs.get("merged_agents") or []),
            "parallel_skipped_agents": list(parallel_obs.get("skipped_agents") or []),
            "execution_graph": list(parallel_obs.get("execution_graph") or []),
            "decision_time_ms": int(decision_obs.get("decision_time_ms") or 0),
            "decision_score": float(decision_obs.get("decision_score") or 0),
            "decision_confidence": float(decision_obs.get("decision_confidence") or 0),
            "conflict_count": int(decision_obs.get("conflict_count") or 0),
            "alternative_count": int(decision_obs.get("alternative_count") or 0),
            "decision_selected_property": str(decision_obs.get("selected_property") or ""),
            "decision_tokens": part_or("decision_tokens", decision_obs, "decision_tokens"),
            "conflict_resolve_time_ms": int(
                decision_obs.get("conflict_resolve_time_ms") or 0
            ),
            "decision_next_step": str(decision_obs.get("next_step") or ""),
            "bi_market_score": float(bi_obs.get("market_score") or 0),
            "bi_property_score": float(bi_obs.get("property_score") or 0),
            "bi_lead_score": float(bi_obs.get("lead_score") or 0),
            "bi_trend_score": float(bi_obs.get("trend_score") or 0),
            "bi_opportunity_score": float(bi_obs.get("opportunity_score") or 0),
            "bi_analysis_time_ms": int(bi_obs.get("analysis_time_ms") or 0),
            "detected_role": str(conv_obs.get("detected_role") or ""),
            "detected_intent": str(conv_obs.get("detected_intent") or ""),
            "conversation_workflow": str(conv_obs.get("workflow") or ""),
            "workflow_name": str(conv_obs.get("workflow_name") or ""),
            "conversation_state": str(
                conv_obs.get("workflow_state") or conv_obs.get("conversation_state") or ""
            ),
            "conversation_step": str(conv_obs.get("current_step") or ""),
            "completed_fields": list(conv_obs.get("completed_fields") or []),
            "completed_steps": list(conv_obs.get("completed_steps") or []),
            "missing_fields": list(conv_obs.get("missing_fields") or []),
            "missing_steps": list(conv_obs.get("missing_steps") or []),
            "validation_errors": list(conv_obs.get("validation_errors") or []),
            "conversation_extra_tokens": int(conv_obs.get("conversation_extra_tokens") or 0),
            "workflow_extra_tokens": int(conv_obs.get("workflow_extra_tokens") or 0),
            "workflow_state": str(
                conv_obs.get("workflow_state") or adaptive_obs.get("workflow_state") or ""
            ),
            "confidence_score": float(adaptive_obs.get("confidence_score") or 0),
            "retry_count": int(adaptive_obs.get("retry_count") or 0),
            "recovery_count": int(adaptive_obs.get("recovery_count") or 0),
            "skipped_steps": list(adaptive_obs.get("skipped_steps") or []),
            "adaptive_extra_tokens": int(adaptive_obs.get("adaptive_extra_tokens") or 0),
            "total_tokens": input_tokens + output_tokens,
            "total_prompt_tokens": input_tokens,
            "prompt_tokens": input_tokens,
            "reasoning_tokens": reasoning_tokens,
            "prompt_cache_hit_tokens": cache_hit,
            "prompt_cache_miss_tokens": cache_miss,
            "thinking_enabled": thinking_enabled(),
            "total_cost": usage_cost(usage),
            "response_time_ms": elapsed_ms,
            "latency_ms": elapsed_ms,
            "api_rounds": int(result.get("api_rounds") or 0),
            "cache_hit": bool(
                (meta.get("provider") == "cache") if isinstance(meta, dict) else False
            ),
        }
        record_token_analytics(row)
        _record_token_breakdown(
            messages,
            row=row,
            user_key=user_key,
            audience=audience,
            voice=voice,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_rounds=int(result.get("api_rounds") or 0),
        )
    except Exception:
        pass


def _record_token_breakdown(
    messages: list[dict[str, Any]],
    *,
    row: dict[str, Any],
    user_key: str,
    audience: str,
    voice: str,
    input_tokens: int,
    output_tokens: int,
    api_rounds: int,
) -> None:
    try:
        from flask import g

        from .token_diag import breakdown_prompt_sections, record_token_breakdown

        tools_for_diag = getattr(g, "ai_tools_schema", None)
        fixes_applied = getattr(g, "ai_token_fixes_applied", None)
        tool_selection = getattr(g, "ai_tool_selection", None)
        bd = breakdown_prompt_sections(
            messages,
            tools=tools_for_diag if isinstance(tools_for_diag, list) else None,
            api_input_tokens=input_tokens,
        )
        if (
            isinstance(tool_selection, dict)
            and int(tool_selection.get("tool_schema_tokens") or 0) > 0
        ):
            bd["tool_schema_tokens"] = int(tool_selection["tool_schema_tokens"])
        record_token_breakdown(
            bd,
            user_key=user_key,
            audience=audience,
            voice=voice,
            output_tokens=output_tokens,
            fixes_applied=fixes_applied if isinstance(fixes_applied, dict) else None,
            tool_selection=tool_selection if isinstance(tool_selection, dict) else None,
        )
        from .payload_profiler import (
            finalize_payload_profile_request,
            payload_profiler_enabled,
        )

        profiler_rounds = getattr(g, "ai_payload_profiler_rounds", None)
        if (
            payload_profiler_enabled()
            and isinstance(profiler_rounds, list)
            and profiler_rounds
        ):
            finalize_payload_profile_request(
                profiler_rounds,
                user_key=user_key,
                audience=audience,
                voice=voice,
                api_rounds=api_rounds,
                request_id=str(row.get("request_id") or ""),
            )
    except Exception:
        pass
