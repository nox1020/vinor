from __future__ import annotations

from typing import Any

from app.business_intelligence.interfaces import CustomerAnalyzer


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class RuleCustomerAnalyzer(CustomerAnalyzer):
    """Customer / lead signals from profile + negotiation + success plans."""

    def analyze(self, *, shared: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        shared = shared or {}
        profile = shared.get("customer_profile") if isinstance(shared.get("customer_profile"), dict) else {}
        neg = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}
        success = (
            shared.get("customer_success") if isinstance(shared.get("customer_success"), dict) else {}
        )

        rel = _f(profile.get("relationship_score"), 0.4)
        conf = _f(profile.get("confidence"), 0.4)
        pref_count = int(profile.get("preference_count") or 0)
        deal_p = _f(neg.get("deal_probability"), 0.45)
        risk = _f(neg.get("risk_score"), 0.4)
        conv = _f(success.get("conversion_probability"), 0.4)
        cs_conf = _f(success.get("confidence") or success.get("customer_success_confidence"), 0.4)

        purchase_p = _clamp(rel * 0.25 + deal_p * 0.35 + conv * 0.3 + conf * 0.1)
        # Seller flexibility: inverse risk + strategy presence
        flex = _clamp(0.35 + (1.0 - risk) * 0.45 + (0.1 if neg.get("recommended_strategy") else 0))
        lead_quality = _clamp(
            0.25
            + min(0.25, pref_count * 0.06)
            + rel * 0.2
            + purchase_p * 0.2
            + cs_conf * 0.1
        )

        return {
            "customer_purchase_probability": round(purchase_p, 3),
            "seller_flexibility_score": round(flex, 3),
            "lead_quality": round(lead_quality, 3),
            "relationship_score": round(rel, 3),
            "preference_count": pref_count,
            "next_action": str(
                success.get("next_action") or neg.get("next_action") or profile.get("next_suggested_action") or ""
            ),
            "interaction_style": str(profile.get("interaction_style") or ""),
            "decision_confidence": round(_f(decision.get("confidence"), 0), 3),
        }
