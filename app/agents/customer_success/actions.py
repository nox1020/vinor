from __future__ import annotations

from typing import Any

from app.agents.customer_success.interfaces import NextActionBuilder


class RuleNextActionBuilder(NextActionBuilder):
    """Builds next-action labels only — never follow-up message text."""

    def build(
        self,
        *,
        stage: str,
        conversion_probability: float,
        negotiation: dict[str, Any],
        profile: dict[str, Any],
        workflow: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        if stage == "ready" or conversion_probability >= 0.7:
            return "propose_close", "deal_push", "4h", "high", "high"
        if stage == "negotiating":
            neg_next = str(negotiation.get("next_action") or "")
            if neg_next in ("send_offer", "propose_close", "lower_offer"):
                return neg_next, "offer_follow", "1d", "high", "normal"
            return "continue_negotiation", "offer_follow", "1d", "high", "normal"
        if stage == "evaluating":
            return "schedule_visit", "visit_reminder", "1d", "medium", "normal"
        if stage == "interested":
            return "share_recommendation", "check_in", "2d", "medium", "normal"
        if stage == "dormant":
            return "reactivate", "reactivate", "7d", "low", "low"
        if stage == "won":
            return "onboard", "check_in", "3d", "medium", "low"

        style = str(profile.get("interaction_style") or "neutral")
        if style == "exploratory":
            return "clarify_prefs", "check_in", "2d", "low", "low"
        return "nurture", "check_in", "3d", "low", "normal"
