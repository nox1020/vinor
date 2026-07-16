from __future__ import annotations

from typing import Any

from app.business_intelligence.interfaces import MarketAnalyzer


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class RuleMarketAnalyzer(MarketAnalyzer):
    """Market signals from existing shared/decision — no new search."""

    def analyze(self, *, shared: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        shared = shared or {}
        decision = decision or {}
        profile = shared.get("customer_profile") if isinstance(shared.get("customer_profile"), dict) else {}
        locs = list(profile.get("location_preferences") or [])
        if not locs and isinstance(profile.get("preferences"), dict):
            locs = list((profile.get("preferences") or {}).get("locations") or [])

        codes = list(shared.get("property_codes") or shared.get("analysis_codes") or [])
        selected = str(decision.get("selected_property") or shared.get("recommended_code") or "")
        if selected and selected not in codes:
            codes = [selected] + codes

        # Region popularity: more location prefs / more codes → higher local demand signal
        region_popularity = _clamp(0.35 + min(0.4, len(locs) * 0.12) + min(0.2, len(codes) * 0.04))
        if locs:
            region_popularity = _clamp(region_popularity + 0.05)

        # Price competitiveness from negotiation risk/deal + budget fit
        neg = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}
        deal_p = _f(neg.get("deal_probability"), 0.45)
        risk = _f(neg.get("risk_score"), 0.4)
        price_competitiveness = _clamp(0.3 + deal_p * 0.45 + (1.0 - risk) * 0.25)

        # Market attractiveness blends region + price + decision confidence
        d_conf = _f(decision.get("confidence"), 0.4)
        market_attractiveness = _clamp(
            region_popularity * 0.35 + price_competitiveness * 0.4 + d_conf * 0.25
        )

        return {
            "market_attractiveness": round(market_attractiveness, 3),
            "region_popularity": round(region_popularity, 3),
            "price_competitiveness": round(price_competitiveness, 3),
            "regions": [str(x) for x in locs[:5]],
            "listing_count_signal": min(8, len(codes)),
            "primary_region": str(locs[0]) if locs else "",
        }
