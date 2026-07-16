from __future__ import annotations

import time
from typing import Any

from app.agents.analysis.manager import extract_property_codes, load_lands_for_codes
from app.agents.analysis.service import run_property_analysis
from app.agents.recommendation.cache import MemoryRecommendationCache, cache_key_for
from app.agents.recommendation.config import recommendation_hint_budget_chars
from app.agents.recommendation.interfaces import (
    RecommendationCache,
    RecommendationEngine,
    RecommendationManager,
    RecommendationRequest,
    RecommendationResult,
)


class DefaultRecommendationManager(RecommendationManager):
    def __init__(
        self,
        *,
        engine: RecommendationEngine,
        cache: RecommendationCache | None = None,
    ):
        self._engine = engine
        self._cache = cache or MemoryRecommendationCache()

    def run(self, req: RecommendationRequest) -> RecommendationResult:
        t0 = time.perf_counter()
        codes = list(req.property_codes) or extract_property_codes(req.message, req.shared)
        if not codes:
            return RecommendationResult(
                ok=True,
                recommendation_time_ms=int((time.perf_counter() - t0) * 1000),
                metadata={"skipped": "no_codes"},
            )

        key = cache_key_for(codes, route=req.route, message=req.message)
        cached = self._cache.get(key)
        if cached is not None:
            cached.recommendation_time_ms = int((time.perf_counter() - t0) * 1000)
            return cached

        shared = dict(req.shared or {})
        # Reuse Structured Analysis via analysis service cache — never re-search/re-RAG.
        analysis_categories = list(req.analysis_categories or [])
        reuse_analysis = bool(shared.get("analysis_categories") or analysis_categories)
        if not analysis_categories and shared.get("analysis_categories"):
            analysis_categories = list(shared.get("analysis_categories") or [])
        if not analysis_categories:
            ar = run_property_analysis(
                property_codes=codes,
                message=req.message,
                route=req.route,
                audience=req.audience,
                user_key=req.user_key,
                shared=shared,
            )
            if ar is not None:
                analysis_categories = list(ar.categories or [])
                reuse_analysis = bool(ar.cache_hit or shared.get("property_analysis_agent"))

        lands = load_lands_for_codes(codes, user_key=req.user_key, audience=req.audience)
        budget = int(req.context_budget_chars or recommendation_hint_budget_chars())
        req2 = RecommendationRequest(
            property_codes=tuple(codes),
            message=req.message,
            route=req.route,
            audience=req.audience,
            user_key=req.user_key,
            shared=shared,
            analysis_categories=analysis_categories,
            context_budget_chars=budget,
        )
        result = self._engine.rank(req2, lands)
        result.recommendation_time_ms = int((time.perf_counter() - t0) * 1000)
        result.reuse_search = bool(shared.get("search_handoff") or shared.get("property_search_agent"))
        result.reuse_analysis = reuse_analysis or bool(analysis_categories)
        result.reuse_memory = bool(shared.get("reused_memory") or shared.get("memory_prefs"))
        result.reuse_planning = bool(shared.get("reused_planning") or shared.get("planning_land_codes"))
        self._cache.put(key, result)
        return result
