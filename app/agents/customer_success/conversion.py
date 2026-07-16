from __future__ import annotations

from typing import Any

from app.agents.customer_success.interfaces import ConversionAnalyzer


class RuleConversionAnalyzer(ConversionAnalyzer):
    """Rule-based stage + conversion from reused agent outputs — no LLM."""

    def analyze(
        self,
        *,
        profile: dict[str, Any],
        negotiation: dict[str, Any],
        recommendation: dict[str, Any],
        workflow: dict[str, Any],
        shared: dict[str, Any],
    ) -> tuple[float, str]:
        p = 0.25
        stage = "aware"

        rel = profile.get("relationship_score")
        if isinstance(rel, (int, float)):
            p += float(rel) * 0.2

        deal_p = negotiation.get("deal_probability")
        if isinstance(deal_p, (int, float)):
            p += float(deal_p) * 0.35
            if float(deal_p) >= 0.65:
                stage = "ready"
            elif float(deal_p) >= 0.4:
                stage = "negotiating"

        risk = negotiation.get("risk_score")
        if isinstance(risk, (int, float)) and float(risk) > 0.7:
            p -= 0.15

        rec_score = recommendation.get("score")
        if isinstance(rec_score, (int, float)):
            p += float(rec_score) * 0.15
            if stage == "aware" and float(rec_score) >= 0.6:
                stage = "interested"

        if shared.get("analysis_categories") or shared.get("property_analysis_agent"):
            p += 0.05
            if stage in ("aware", "interested"):
                stage = "evaluating"

        wf = str(workflow.get("workflow") or shared.get("workflow") or "")
        st = str(workflow.get("workflow_state") or "")
        if wf == "visit" or "visit" in str(shared.get("last_activities") or []):
            p += 0.1
            stage = "evaluating" if stage in ("aware", "interested") else stage
        if wf == "deal" or st in ("COMPLETED", "READY"):
            p += 0.12
            stage = "ready" if p >= 0.55 else stage
        if negotiation.get("recommended_strategy") == "close_fast":
            stage = "ready"
            p += 0.08
        if negotiation.get("recommended_strategy") == "walk_away_ready":
            stage = "dormant" if p < 0.35 else "negotiating"
            p -= 0.05

        next_sug = str(profile.get("next_suggested_action") or "")
        if next_sug == "recommend" and stage == "aware":
            stage = "interested"

        p = max(0.05, min(0.95, p))
        if p >= 0.75 and stage not in ("won",):
            stage = "ready"
        return round(p, 3), stage
