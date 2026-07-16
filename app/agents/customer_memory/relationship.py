from __future__ import annotations

from typing import Any

from app.agents.customer_memory.interfaces import CustomerPreferences, RelationshipAnalyzer


class RuleRelationshipAnalyzer(RelationshipAnalyzer):
    """Scores relationship from reused Memory + Conversation/Workflow signals — no LLM."""

    def analyze(
        self,
        *,
        preferences: CustomerPreferences,
        memory_items: list[Any],
        shared: dict[str, Any],
        conversation_obs: dict[str, Any],
    ) -> tuple[float, str, list[str]]:
        score = 0.15
        activities: list[str] = []

        n_mem = len(memory_items or [])
        score += min(0.35, n_mem * 0.05)

        pref_bits = 0
        if preferences.budget_max:
            pref_bits += 1
        pref_bits += len(preferences.locations)
        pref_bits += len(preferences.property_types)
        score += min(0.25, pref_bits * 0.04)

        if shared.get("recommended_code") or shared.get("recommendation_items"):
            score += 0.08
            activities.append("recommendation")
        if shared.get("analysis_categories") or shared.get("property_analysis_agent"):
            score += 0.06
            activities.append("analysis")
        if shared.get("search_handoff") or shared.get("property_search_agent"):
            score += 0.06
            activities.append("search")
        if shared.get("reused_planning") or shared.get("planning_land_codes"):
            score += 0.04
            activities.append("planning")

        wf = str(conversation_obs.get("workflow") or conversation_obs.get("workflow_name") or "")
        st = str(conversation_obs.get("workflow_state") or conversation_obs.get("conversation_state") or "")
        if wf and wf not in ("", "none"):
            score += 0.08
            activities.append(f"workflow:{wf}")
        if st in ("COMPLETED", "READY"):
            score += 0.05
            activities.append("workflow_completed")

        completed = conversation_obs.get("completed_fields") or conversation_obs.get("completed_steps") or []
        if completed:
            activities.append(f"fields:{len(completed)}")

        # Interaction style heuristics
        msg_len = len(str(shared.get("last_user_message") or shared.get("message") or ""))
        style = "neutral"
        if msg_len and msg_len < 40:
            style = "short"
        elif msg_len > 160:
            style = "detailed"
        if preferences.budget_max and preferences.locations:
            style = "decisive" if style == "short" else style
        if not preferences.property_types and n_mem < 2:
            style = "exploratory"

        score = max(0.0, min(1.0, score))
        return score, style, activities[:8]
