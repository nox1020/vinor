from __future__ import annotations

import time
from typing import Any

from app.agents.customer_memory.builder import RuleCustomerProfileBuilder
from app.agents.customer_memory.cache import MemoryCustomerProfileCache, cache_key_for
from app.agents.customer_memory.config import customer_memory_hint_budget_chars
from app.agents.customer_memory.interfaces import (
    CustomerMemoryCache,
    CustomerMemoryManager,
    CustomerMemoryRequest,
    CustomerProfile,
    CustomerProfileBuilder,
    PreferenceExtractor,
    RelationshipAnalyzer,
)
from app.agents.customer_memory.preferences import RulePreferenceExtractor
from app.agents.customer_memory.relationship import RuleRelationshipAnalyzer


def _conversation_obs() -> dict[str, Any]:
    try:
        from app.conversation.service import get_conversation_obs

        return get_conversation_obs() or {}
    except Exception:
        return {}


def _load_memory_items(user_key: str, shared: dict[str, Any], message: str) -> tuple[list[Any], bool]:
    """Read-only reuse of Memory Layer — never writes / never creates a store."""
    # Prefer already-fetched shared memory (no second retrieve).
    raw = shared.get("memory_items")
    if isinstance(raw, list) and raw:
        return list(raw), True

    prefs = shared.get("memory_prefs")
    if isinstance(prefs, dict) and prefs:
        # Synthetic light items from prefs already in shared
        items = [{"key": str(k), "value": str(v)} for k, v in list(prefs.items())[:12]]
        return items, True

    if shared.get("memory_text"):
        return [{"key": "memory_text", "value": str(shared.get("memory_text"))[:400]}], True

    # Fallback: Memory Layer retrieve API (existing store only).
    if not user_key:
        return [], False
    try:
        from app.memory.service import retrieve_memory_for_prompt

        result = retrieve_memory_for_prompt(
            user_key=user_key,
            query=message or "",
            audience=str(shared.get("audience") or ""),
            budget_chars=200,
        )
        return list(result.items or []), bool(result.items)
    except Exception:
        return [], False


def _session_signals(user_key: str) -> dict[str, Any]:
    if not user_key:
        return {}
    try:
        from app.conversation.session import FileSessionStore

        sess = FileSessionStore().load(user_key)
        if sess is None:
            return {}
        return {
            "workflow": sess.workflow_id,
            "workflow_state": sess.state,
            "completed_fields": list(sess.collected.keys()),
            "completed_steps": list(getattr(sess, "completed_steps", None) or []),
            "intent": sess.intent,
            "role": sess.role,
        }
    except Exception:
        return {}


class DefaultCustomerMemoryManager(CustomerMemoryManager):
    def __init__(
        self,
        *,
        extractor: PreferenceExtractor | None = None,
        analyzer: RelationshipAnalyzer | None = None,
        builder: CustomerProfileBuilder | None = None,
        cache: CustomerMemoryCache | None = None,
    ):
        self._extractor = extractor or RulePreferenceExtractor()
        self._analyzer = analyzer or RuleRelationshipAnalyzer()
        self._builder = builder or RuleCustomerProfileBuilder()
        self._cache = cache or MemoryCustomerProfileCache()

    def build(self, req: CustomerMemoryRequest) -> CustomerProfile:
        t0 = time.perf_counter()
        shared = dict(req.shared or {})
        shared.setdefault("message", req.message)
        key = cache_key_for(req.user_key, message=req.message, route=req.route)
        cached = self._cache.get(key)
        if cached is not None:
            cached.profile_build_time_ms = int((time.perf_counter() - t0) * 1000)
            return cached

        items, reused_mem = _load_memory_items(req.user_key, shared, req.message)
        conv = _conversation_obs()
        sess = _session_signals(req.user_key)
        if sess:
            for k, v in sess.items():
                conv.setdefault(k, v)

        # Reuse recommendation / analysis / workflow objects from shared or g
        reuse_rec = bool(shared.get("recommendation_items") or shared.get("recommended_code"))
        reuse_analysis = bool(shared.get("analysis_categories") or shared.get("property_analysis_agent"))
        reuse_wf = bool(conv.get("workflow") and conv.get("workflow") not in ("", "none"))
        reuse_plan = bool(shared.get("reused_planning") or shared.get("planning_land_codes"))

        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                if getattr(g, "ai_conversation_object", None):
                    reuse_wf = True
                    shared.setdefault("workflow_object", g.ai_conversation_object)
                if getattr(g, "ai_recommendation_obs", None):
                    reuse_rec = reuse_rec or True
        except Exception:
            pass

        prefs = self._extractor.extract(
            message=req.message or "",
            memory_items=items,
            shared=shared,
        )
        rel_score, style, activities = self._analyzer.analyze(
            preferences=prefs,
            memory_items=items,
            shared=shared,
            conversation_obs=conv,
        )
        budget = int(req.context_budget_chars or customer_memory_hint_budget_chars())
        profile = self._builder.build(
            user_key=req.user_key,
            preferences=prefs,
            relationship_score=rel_score,
            interaction_style=style,
            last_activities=activities,
            shared=shared,
            budget_chars=budget,
        )
        profile.reuse_memory = reused_mem or bool(shared.get("reused_memory"))
        profile.reuse_workflow = reuse_wf
        profile.reuse_recommendation = reuse_rec
        profile.reuse_analysis = reuse_analysis
        profile.reuse_planning = reuse_plan
        profile.profile_build_time_ms = int((time.perf_counter() - t0) * 1000)
        profile.metadata["memory_item_count"] = len(items)
        self._cache.put(key, profile)
        return profile
