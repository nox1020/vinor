from __future__ import annotations

import re
import time
from typing import Any

from app.agents.analysis.cache import MemoryAnalysisCache, cache_key_for
from app.agents.analysis.config import analysis_hint_budget_chars
from app.agents.analysis.interfaces import (
    AnalysisCache,
    AnalysisManager,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStrategy,
)

_CODE_RE = re.compile(r"\b(\d{8,16})\b")


def extract_property_codes(message: str, shared: dict[str, Any] | None = None) -> list[str]:
    """Prefer shared/search/planning codes — never re-run search."""
    codes: list[str] = []
    shared = shared or {}
    for key in ("property_codes", "land_codes", "analysis_codes"):
        raw = shared.get(key)
        if isinstance(raw, (list, tuple)):
            for c in raw:
                s = str(c).strip()
                if s and s not in codes:
                    codes.append(s)
    for c in _CODE_RE.findall(message or ""):
        if c not in codes:
            codes.append(c)
    return codes[:5]


def load_lands_for_codes(
    codes: list[str],
    *,
    user_key: str = "",
    audience: str = "",
) -> list[dict[str, Any]]:
    """Reuse existing land accessors — no new RAG/search."""
    if not codes:
        return []
    try:
        from app.ai.land_cards import accessible_lands_map

        amap = accessible_lands_map(user_key or "", audience=audience or None)
    except Exception:
        amap = {}
    out: list[dict[str, Any]] = []
    for code in codes:
        land = amap.get(code)
        if isinstance(land, dict):
            out.append(land)
    return out


class DefaultAnalysisManager(AnalysisManager):
    def __init__(self, *, strategy: AnalysisStrategy, cache: AnalysisCache | None = None):
        self._strategy = strategy
        self._cache = cache or MemoryAnalysisCache()

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        t0 = time.perf_counter()
        codes = list(req.property_codes) or extract_property_codes(req.message, req.shared)
        if not codes:
            # Soft fail — nothing to analyze (lazy)
            return AnalysisResult(
                ok=True,
                property_codes=[],
                compact_hint="",
                analysis_tokens=0,
                analysis_time_ms=int((time.perf_counter() - t0) * 1000),
                metadata={"skipped": "no_codes"},
            )

        key = cache_key_for(codes, route=req.route, message=req.message)
        cached = self._cache.get(key)
        if cached is not None:
            cached.analysis_time_ms = int((time.perf_counter() - t0) * 1000)
            return cached

        lands = load_lands_for_codes(codes, user_key=req.user_key, audience=req.audience)
        budget = int(req.context_budget_chars or analysis_hint_budget_chars())
        req2 = AnalysisRequest(
            property_codes=tuple(codes),
            message=req.message,
            route=req.route,
            audience=req.audience,
            user_key=req.user_key,
            shared=dict(req.shared or {}),
            context_budget_chars=budget,
        )
        result = self._strategy.analyze(req2, lands)
        result.analysis_time_ms = int((time.perf_counter() - t0) * 1000)

        # Reuse flags from shared supervisor/agent context (no re-execution)
        shared = req.shared or {}
        result.reused_context = bool(shared.get("property_search_agent") or shared.get("pipeline"))
        result.reused_rag = bool(shared.get("reused_rag") or "rag" in str(shared.get("pipeline") or ""))
        result.reused_memory = bool(shared.get("reused_memory") or "memory" in str(shared.get("pipeline") or ""))
        result.reused_planning = bool(shared.get("reused_planning") or shared.get("planning_land_codes"))

        self._cache.put(key, result)
        return result
