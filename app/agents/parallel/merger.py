from __future__ import annotations

from typing import Any

from app.agents.interfaces import (
    AGENT_CUSTOMER_MEMORY,
    AGENT_FOLLOW_UP,
    AGENT_NEGOTIATION,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
    AgentResult,
)
from app.agents.parallel.config import parallel_merge_hint_chars
from app.agents.parallel.interfaces import AgentResultMerger


class CompactAgentResultMerger(AgentResultMerger):
    """Merges agent outputs into one object + one compact hint (no per-agent prompts)."""

    def merge(
        self,
        *,
        results: dict[str, AgentResult],
        shared: dict[str, Any],
        budget_chars: int = 80,
    ) -> tuple[dict[str, Any], str, int]:
        merged_agents = [
            aid for aid, r in results.items() if r and not r.skipped and r.status == "ready"
        ]
        obj: dict[str, Any] = {
            "merged_agents": merged_agents,
            "search": bool(shared.get("property_search_agent") or AGENT_PROPERTY_SEARCH in merged_agents),
            "analysis": bool(shared.get("property_analysis_agent") or AGENT_PROPERTY_ANALYSIS in merged_agents),
            "recommendation": str(shared.get("recommended_code") or ""),
            "profile": bool(shared.get("customer_profile") or AGENT_CUSTOMER_MEMORY in merged_agents),
            "negotiation": bool(shared.get("negotiation_plan") or AGENT_NEGOTIATION in merged_agents),
            "customer_success": bool(shared.get("customer_success") or AGENT_FOLLOW_UP in merged_agents),
            "next_action": "",
            "scores": {},
        }
        if isinstance(shared.get("customer_success"), dict):
            obj["next_action"] = str(shared["customer_success"].get("next_action") or "")
            obj["scores"]["conversion"] = shared["customer_success"].get("conversion_probability")
        if isinstance(shared.get("negotiation_plan"), dict):
            obj["scores"]["deal"] = shared["negotiation_plan"].get("deal_probability")
            if not obj["next_action"]:
                obj["next_action"] = str(shared["negotiation_plan"].get("next_action") or "")
        if isinstance(shared.get("customer_profile"), dict):
            obj["scores"]["relationship"] = shared["customer_profile"].get("relationship_score")

        # Pull structured objects by reference (already outside prompt).
        for key in (
            "customer_profile",
            "negotiation_plan",
            "customer_success",
            "recommendation_items",
            "analysis_categories",
        ):
            if key in shared:
                obj[key] = shared.get(key)

        hint = self._compact_hint(obj, budget_chars=budget_chars or parallel_merge_hint_chars())
        tokens = (len(hint) + 3) // 4 if hint else 0
        return obj, hint, tokens

    def _compact_hint(self, obj: dict[str, Any], *, budget_chars: int) -> str:
        budget = max(40, min(budget_chars or 80, 100))
        header = "=== همکاری === "
        bits = []
        agents = obj.get("merged_agents") or []
        if agents:
            short = ",".join(
                {
                    AGENT_PROPERTY_SEARCH: "S",
                    AGENT_PROPERTY_ANALYSIS: "A",
                    AGENT_RECOMMENDATION: "R",
                    AGENT_CUSTOMER_MEMORY: "M",
                    AGENT_NEGOTIATION: "N",
                    AGENT_FOLLOW_UP: "C",
                }.get(a, a[:1])
                for a in agents
            )
            bits.append(short)
        if obj.get("recommendation"):
            bits.append(f"rec:{str(obj['recommendation'])[-6:]}")
        if obj.get("next_action"):
            bits.append(str(obj["next_action"])[:10])
        body = "|".join(bits) if bits else "ok"
        room = budget - len(header)
        if len(body) > room:
            body = body[: max(0, room - 1)] + "…"
        return (header + body)[:budget]
