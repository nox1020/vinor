from __future__ import annotations

import time
from typing import Any

from app.world_model.interfaces import (
    ConversationState,
    CustomerState,
    MarketState,
    PartnerState,
    PropertyState,
    WorldReasoner,
    WorldSnapshot,
)


def _f(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key) if d.get(key) is not None else default)
    except Exception:
        return default


class RuleWorldReasoner(WorldReasoner):
    """Assemble world state from existing shared/g objects — no text generation."""

    def snapshot(self, *, shared: dict[str, Any]) -> WorldSnapshot:
        t0 = time.perf_counter()
        shared = shared or {}
        decision = shared.get("decision") if isinstance(shared.get("decision"), dict) else {}
        bi = (
            shared.get("business_intelligence")
            if isinstance(shared.get("business_intelligence"), dict)
            else {}
        )
        signals = bi.get("signals") if isinstance(bi.get("signals"), dict) else {}
        profile = (
            shared.get("customer_profile")
            if isinstance(shared.get("customer_profile"), dict)
            else {}
        )
        goals_obj = shared.get("goals") if isinstance(shared.get("goals"), dict) else {}

        try:
            from app.decision.service import get_decision

            if not decision:
                decision = get_decision() or {}
        except Exception:
            pass
        try:
            from app.business_intelligence.service import get_business_intelligence

            if not bi:
                bi = get_business_intelligence() or {}
                signals = bi.get("signals") if isinstance(bi.get("signals"), dict) else {}
        except Exception:
            pass
        try:
            from app.goals.service import get_goals

            if not goals_obj:
                goals_obj = get_goals() or {}
        except Exception:
            pass

        selected = str(decision.get("selected_property") or shared.get("recommended_code") or "")
        codes = list(shared.get("property_codes") or shared.get("analysis_codes") or [])
        if selected and selected not in codes:
            codes = [selected] + codes

        snap = WorldSnapshot(
            property=PropertyState(
                codes=codes[:12],
                selected=selected,
                alternatives=list(decision.get("alternative_properties") or [])[:5],
                scores={
                    "decision": _f(decision, "decision_score"),
                    "property": _f(signals, "property_score")
                    or _f(bi.get("business_metrics") or {}, "property_score"),
                },
            ),
            customer=CustomerState(
                user_key=str(profile.get("user_key") or shared.get("user_key") or ""),
                relationship_score=_f(profile, "relationship_score"),
                purchase_probability=_f(signals, "customer_purchase_probability"),
                lead_quality=_f(signals, "lead_quality"),
                preferences=dict(profile.get("preferences") or {})
                if isinstance(profile.get("preferences"), dict)
                else {},
            ),
            partner=PartnerState(
                audience=str(shared.get("audience") or ""),
                partner_mode=str(shared.get("audience") or "") == "partner",
            ),
            market=MarketState(
                attractiveness=_f(signals, "market_attractiveness"),
                demand_trend=_f(signals, "demand_trend"),
                supply_trend=_f(signals, "supply_trend"),
                opportunity_score=_f(bi, "opportunity_score")
                or _f(bi.get("business_metrics") or {}, "opportunity_score"),
            ),
            conversation=ConversationState(
                intent=str(shared.get("intent") or ""),
                role=str(shared.get("role") or ""),
                workflow=str(shared.get("workflow") or ""),
                route=str(shared.get("route") or ""),
            ),
            goals=list(goals_obj.get("goals") or [])[:8],
            update_time_ms=int((time.perf_counter() - t0) * 1000),
        )
        return snap
