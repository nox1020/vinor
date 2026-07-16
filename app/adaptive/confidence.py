from __future__ import annotations

from app.adaptive.interfaces import ConfidenceEstimator, ConfidenceScore
from app.supervisor.interfaces import (
    ROUTE_FOLLOW_UP,
    ROUTE_GREETING,
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
)


class RuleConfidenceEstimator(ConfidenceEstimator):
    """Rule-based confidence — no LLM, no prompt tokens."""

    def estimate_prepare(
        self, *, route: str, agent_status: str, used_components: list[str]
    ) -> ConfidenceScore:
        route = route or ""
        status = (agent_status or "").strip()
        comps = set(used_components or [])
        signals: dict = {"status": status, "components": sorted(comps), "route": route}

        if status in ("skipped", "skeleton"):
            # Passthrough routes — high confidence that no agent work is needed
            return ConfidenceScore(value=0.95, reason="no_agent_needed", signals=signals)

        if status == "error":
            return ConfidenceScore(value=0.15, reason="agent_error", signals=signals)

        score = 0.45
        if "planning" in comps:
            score += 0.12
        if "memory" in comps:
            score += 0.08
        if "rag" in comps:
            score += 0.15
        if "tools" in comps:
            score += 0.10
        if "llm" in comps:
            score += 0.10
        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE) and "rag" not in comps:
            score -= 0.20
            signals["missing_rag"] = True

        score = max(0.0, min(1.0, score))
        return ConfidenceScore(value=round(score, 3), reason="prepare_components", signals=signals)

    def estimate_response(
        self,
        *,
        route: str,
        reply: str,
        land_codes: list[str],
        ok: bool,
    ) -> ConfidenceScore:
        route = route or ""
        text = (reply or "").strip()
        codes = [c for c in (land_codes or []) if str(c).strip()]
        signals: dict = {
            "ok": ok,
            "reply_len": len(text),
            "land_count": len(codes),
            "route": route,
        }

        if not ok:
            return ConfidenceScore(value=0.1, reason="response_not_ok", signals=signals)

        score = 0.35
        if text:
            score += 0.25
        if len(text) >= 24:
            score += 0.10
        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            if codes:
                score += 0.30
            else:
                score -= 0.15
                signals["no_lands"] = True
        elif route == ROUTE_GREETING:
            score += 0.25 if text else 0.0
        elif route == ROUTE_FOLLOW_UP:
            score += 0.20 if text else 0.0
        else:
            score += 0.15 if text else 0.0

        score = max(0.0, min(1.0, score))
        reason = "response_ok"
        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE) and not codes:
            reason = "search_without_lands"
        return ConfidenceScore(value=round(score, 3), reason=reason, signals=signals)
