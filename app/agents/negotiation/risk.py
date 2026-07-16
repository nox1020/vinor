from __future__ import annotations

from typing import Any

from app.agents.negotiation.interfaces import NegotiationRiskAnalyzer


class RuleNegotiationRiskAnalyzer(NegotiationRiskAnalyzer):
    """Rule-based risk from reused Analysis/Recommendation/Budget — no LLM."""

    def analyze(
        self,
        *,
        asking: int | None,
        budget_max: int | None,
        analysis_score: float,
        recommendation_score: float,
        shared: dict[str, Any],
    ) -> tuple[float, str]:
        risk = 0.35
        if asking and budget_max:
            gap = (asking - budget_max) / max(asking, 1)
            if gap > 0.25:
                risk += 0.35
            elif gap > 0.1:
                risk += 0.2
            elif gap < -0.05:
                risk -= 0.1
        elif asking and not budget_max:
            risk += 0.15

        if analysis_score < 0.4:
            risk += 0.2
        elif analysis_score >= 0.7:
            risk -= 0.1

        if recommendation_score < 0.4:
            risk += 0.1
        elif recommendation_score >= 0.75:
            risk -= 0.08

        if shared.get("workflow") == "deal" or shared.get("conversation_workflow") == "deal":
            risk -= 0.05

        risk = max(0.05, min(0.95, risk))
        if risk < 0.35:
            level = "low"
        elif risk < 0.65:
            level = "medium"
        else:
            level = "high"
        return round(risk, 3), level
