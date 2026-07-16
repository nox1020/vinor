from __future__ import annotations

from typing import Any

from app.business_intelligence.interfaces import PropertyAnalyzer


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class RulePropertyAnalyzer(PropertyAnalyzer):
    """Property insights from decision/recommendation/metadata — no re-query."""

    def analyze(
        self,
        *,
        shared: dict[str, Any],
        decision: dict[str, Any],
        property_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        shared = shared or {}
        decision = decision or {}
        meta = property_metadata or {}

        code = str(
            decision.get("selected_property")
            or shared.get("recommended_code")
            or meta.get("code")
            or ""
        )
        d_score = _f(decision.get("decision_score"), 0.0)
        rec_items = shared.get("recommendation_items") or []
        rec_score = 0.0
        if isinstance(rec_items, list):
            for it in rec_items:
                if isinstance(it, dict) and str(it.get("property_code") or "") == code:
                    rec_score = _f(it.get("score"), 0.0)
                    break
            if rec_score <= 0 and rec_items and isinstance(rec_items[0], dict):
                rec_score = _f(rec_items[0].get("score"), 0.0)

        cats = shared.get("analysis_categories") or []
        analysis_avg = 0.5
        scores = []
        for cat in cats:
            sc = getattr(cat, "score", None)
            if sc is None and isinstance(cat, dict):
                sc = cat.get("score")
            if isinstance(sc, (int, float)):
                scores.append(float(sc))
        if scores:
            analysis_avg = sum(scores) / len(scores)

        # Listing freshness from metadata age days if present, else neutral
        age_days = meta.get("age_days")
        if age_days is None:
            age_days = meta.get("days_since_update")
        freshness = 0.55
        if isinstance(age_days, (int, float)):
            # newer listings score higher
            freshness = _clamp(1.0 - float(age_days) / 120.0)

        property_score = _clamp(
            (d_score or 0.45) * 0.35
            + (rec_score or 0.4) * 0.35
            + analysis_avg * 0.2
            + freshness * 0.1
        )

        status = str(meta.get("status") or meta.get("state") or "")
        price = meta.get("price") or meta.get("price_toman") or meta.get("amount")

        return {
            "property_code": code,
            "property_score": round(property_score, 3),
            "listing_freshness": round(freshness, 3),
            "analysis_avg": round(analysis_avg, 3),
            "recommendation_score": round(rec_score, 3),
            "status": status,
            "price": price,
            "alternatives": list(decision.get("alternative_properties") or [])[:5],
        }
