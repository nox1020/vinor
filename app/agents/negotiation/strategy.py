from __future__ import annotations

from typing import Any

from app.agents.negotiation.interfaces import NegotiationStrategyBuilder


class RuleNegotiationStrategyBuilder(NegotiationStrategyBuilder):
    """Builds strategy labels/actions only — never negotiation dialogue."""

    def build(
        self,
        *,
        risk_level: str,
        risk_score: float,
        deal_probability: float,
        profile: dict[str, Any],
    ) -> tuple[str, str, list[str], str]:
        style = str(profile.get("interaction_style") or "neutral")

        if risk_level == "high":
            strategy = "walk_away_ready"
            tone = "firm"
            actions = ["confirm_budget", "request_discount", "compare_alts"]
            next_action = "lower_offer"
        elif risk_level == "low" and deal_probability >= 0.6:
            strategy = "close_fast"
            tone = "warm"
            actions = ["lock_terms", "schedule_visit", "prepare_deal"]
            next_action = "propose_close"
        elif style == "decisive":
            strategy = "anchoring"
            tone = "direct"
            actions = ["open_with_offer", "justify_value", "set_deadline"]
            next_action = "send_offer"
        else:
            strategy = "value_focus"
            tone = "calm"
            actions = ["highlight_pros", "split_gap", "ask_flexibility"]
            next_action = "probe_seller"

        if risk_score > 0.7 and "compare_alts" not in actions:
            actions.append("compare_alts")
        return strategy, tone, actions[:4], next_action
