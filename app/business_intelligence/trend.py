from __future__ import annotations

from typing import Any

from app.business_intelligence.interfaces import TrendAnalyzer


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class RuleTrendAnalyzer(TrendAnalyzer):
    """Demand/supply/recommendation success from existing evaluation + shared."""

    def analyze(
        self,
        *,
        shared: dict[str, Any],
        evaluation: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        shared = shared or {}
        evaluation = evaluation or {}
        decision = decision or {}

        codes = list(shared.get("property_codes") or shared.get("analysis_codes") or [])
        rec_items = shared.get("recommendation_items") or []
        selected = str(decision.get("selected_property") or "")
        conflicts = int(decision.get("conflict_count") or 0)

        # Demand: customer intent intensity + lead signals
        profile = shared.get("customer_profile") if isinstance(shared.get("customer_profile"), dict) else {}
        prefs = int(profile.get("preference_count") or 0)
        demand = _clamp(0.4 + min(0.35, prefs * 0.08) + (0.1 if selected else 0))

        # Supply: more codes / alts → higher supply signal
        alts = list(decision.get("alternative_properties") or [])
        supply = _clamp(0.35 + min(0.4, len(codes) * 0.06) + min(0.2, len(alts) * 0.05))

        # Recommendation success rate proxy: selected + score + low conflicts
        d_score = _f(decision.get("decision_score"), 0)
        rec_ok = 0.45
        if selected:
            rec_ok = _clamp(0.5 + d_score * 0.35 - min(0.2, conflicts * 0.05))
        elif isinstance(rec_items, list) and rec_items:
            rec_ok = 0.5

        # Soft from evaluation quality if present
        quality = evaluation.get("quality") if isinstance(evaluation.get("quality"), dict) else {}
        if quality:
            overall = _f(quality.get("overall"), 0)
            rec_q = _f(quality.get("recommendation_quality"), 0)
            if overall > 0:
                rec_ok = _clamp(rec_ok * 0.6 + overall * 0.2 + rec_q * 0.2)

        trend_score = _clamp(demand * 0.4 + (1.0 - abs(demand - supply)) * 0.2 + rec_ok * 0.4)

        return {
            "demand_trend": round(demand, 3),
            "supply_trend": round(supply, 3),
            "recommendation_success_rate": round(rec_ok, 3),
            "trend_score": round(trend_score, 3),
            "balance": round(_clamp(1.0 - abs(demand - supply)), 3),
            "conflict_pressure": min(1.0, conflicts / 5.0),
        }
