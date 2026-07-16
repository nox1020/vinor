from __future__ import annotations

from typing import Any

from app.agents.customer_memory.config import customer_memory_hint_budget_chars
from app.agents.customer_memory.interfaces import (
    CustomerPreferences,
    CustomerProfile,
    CustomerProfileBuilder,
)


def _budget_label(n: int | None) -> str:
    if not n:
        return ""
    if n >= 1_000_000_000:
        v = n / 1_000_000_000
        s = f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"
        return f"{s}B"
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    return str(n)


class RuleCustomerProfileBuilder(CustomerProfileBuilder):
    def build(
        self,
        *,
        user_key: str,
        preferences: CustomerPreferences,
        relationship_score: float,
        interaction_style: str,
        last_activities: list[str],
        shared: dict[str, Any],
        budget_chars: int,
    ) -> CustomerProfile:
        pref_count = (
            (1 if preferences.budget_max else 0)
            + len(preferences.locations)
            + len(preferences.property_types)
            + len(preferences.must_have)
            + len(preferences.avoid)
        )
        confidence = min(
            0.95,
            0.25
            + pref_count * 0.08
            + relationship_score * 0.35
            + (0.1 if shared.get("reused_memory") else 0),
        )

        # Next action suggestion (outside Prompt logic)
        next_action = "continue_chat"
        if preferences.budget_max and preferences.locations and preferences.property_types:
            next_action = "recommend"
        elif preferences.budget_max or preferences.locations:
            next_action = "search"
        elif last_activities and "recommendation" in last_activities:
            next_action = "compare_or_visit"
        elif interaction_style == "exploratory":
            next_action = "clarify_prefs"

        budget_profile = {
            "max": preferences.budget_max,
            "min": preferences.budget_min,
            "label": _budget_label(preferences.budget_max),
        }

        summary_bits = []
        if preferences.budget_max:
            summary_bits.append(f"بودجه≤{_budget_label(preferences.budget_max)}")
        if preferences.locations:
            summary_bits.append(",".join(preferences.locations[:2]))
        if preferences.property_types:
            summary_bits.append(",".join(preferences.property_types[:2]))
        summary_bits.append(interaction_style[:6])
        summary_bits.append(next_action[:8])
        summary = "|".join(summary_bits)

        hint = self._compact_hint(summary, budget_chars=budget_chars)
        tokens = (len(hint) + 3) // 4 if hint else 0

        return CustomerProfile(
            user_key=user_key,
            preferences=preferences,
            budget_profile=budget_profile,
            location_preferences=list(preferences.locations),
            property_interests=list(preferences.property_types),
            interaction_style=interaction_style,
            last_activities=list(last_activities),
            relationship_score=round(relationship_score, 3),
            confidence=round(confidence, 3),
            next_suggested_action=next_action,
            preference_count=pref_count,
            summary=summary,
            compact_hint=hint,
            customer_memory_tokens=tokens,
        )

    def _compact_hint(self, summary: str, *, budget_chars: int) -> str:
        budget = max(40, min(budget_chars or customer_memory_hint_budget_chars(), 120))
        header = "=== پروفایل مشتری ===\n"
        body = (summary or "").strip()
        room = budget - len(header)
        if room < 8:
            return header.strip()
        if len(body) > room:
            body = body[: room - 1] + "…"
        return header + body
