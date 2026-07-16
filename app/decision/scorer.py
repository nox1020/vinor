from __future__ import annotations

from typing import Any

from app.decision.interfaces import DecisionConfig, DecisionScorer, ScoredCandidate


def _to_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _analysis_score_for(code: str, categories: list[Any]) -> float:
    scores: list[float] = []
    for cat in categories or []:
        summary = getattr(cat, "summary", None) or (cat.get("summary") if isinstance(cat, dict) else "")
        score = getattr(cat, "score", None)
        if score is None and isinstance(cat, dict):
            score = cat.get("score")
        if code and summary and code not in str(summary) and ":" in str(summary):
            if not str(summary).startswith(code):
                continue
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        # global avg if untagged
        for cat in categories or []:
            score = getattr(cat, "score", None)
            if score is None and isinstance(cat, dict):
                score = cat.get("score")
            if isinstance(score, (int, float)):
                scores.append(float(score))
        if not scores:
            return 0.5
    return sum(scores) / len(scores)


class RuleDecisionScorer(DecisionScorer):
    """Weighted multi-agent scoring — no LLM / no re-query."""

    def score_candidates(
        self, *, shared: dict[str, Any], config: DecisionConfig
    ) -> list[ScoredCandidate]:
        codes: list[str] = []
        rec_scores: dict[str, float] = {}

        items = shared.get("recommendation_items") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                code = str(it.get("property_code") or "").strip()
                if not code:
                    continue
                if code not in codes:
                    codes.append(code)
                rec_scores[code] = _to_float(it.get("score"), 0.5)

        rec_code = str(shared.get("recommended_code") or "").strip()
        if rec_code and rec_code not in codes:
            codes.insert(0, rec_code)
            rec_scores.setdefault(rec_code, 0.6)

        for key in ("property_codes", "land_codes", "planning_land_codes", "analysis_codes"):
            raw = shared.get(key)
            if isinstance(raw, (list, tuple)):
                for c in raw:
                    s = str(c).strip()
                    if s and s not in codes:
                        codes.append(s)

        if not codes:
            return []

        cats = list(shared.get("analysis_categories") or [])
        neg = shared.get("negotiation_plan") if isinstance(shared.get("negotiation_plan"), dict) else {}
        profile = shared.get("customer_profile") if isinstance(shared.get("customer_profile"), dict) else {}
        success = shared.get("customer_success") if isinstance(shared.get("customer_success"), dict) else {}
        search_boost = 0.55 if shared.get("property_search_agent") or shared.get("search_handoff") else 0.35
        rel = _to_float(profile.get("relationship_score"), 0.4)
        deal_p = _to_float(neg.get("deal_probability"), 0.45)
        risk = _to_float(neg.get("risk_score"), 0.4)
        conv = _to_float(success.get("conversion_probability"), 0.4)
        neg_code = str(neg.get("property_code") or "").strip()

        ranked: list[ScoredCandidate] = []
        for code in codes[:8]:
            parts: dict[str, float] = {}
            reasons: list[str] = []
            warnings: list[str] = []

            parts["search"] = search_boost
            if shared.get("property_search_agent"):
                reasons.append("search_hit")

            a_score = _analysis_score_for(code, cats)
            parts["analysis"] = a_score
            if a_score >= 0.65:
                reasons.append("analysis_strong")
            elif a_score < 0.4:
                warnings.append("analysis_weak")

            r_score = rec_scores.get(code, 0.4 if code != rec_code else 0.55)
            if code == rec_code:
                r_score = max(r_score, 0.7)
                reasons.append("recommended")
            parts["recommendation"] = r_score

            n_score = deal_p * (1.0 - risk * 0.35)
            if neg_code and neg_code == code:
                n_score = max(n_score, deal_p)
                reasons.append("negotiation_focus")
            elif neg_code and neg_code != code:
                n_score *= 0.85
                warnings.append("neg_other_code")
            parts["negotiation"] = max(0.05, min(0.95, n_score))

            parts["customer_memory"] = rel
            if rel >= 0.6:
                reasons.append("profile_fit")

            parts["customer_success"] = conv
            if success.get("next_action"):
                reasons.append(f"cs:{success.get('next_action')}")

            score = (
                parts["search"] * config.search_weight
                + parts["analysis"] * config.analysis_weight
                + parts["recommendation"] * config.recommendation_weight
                + parts["negotiation"] * config.negotiation_weight
                + parts["customer_memory"] * config.customer_memory_weight
                + parts["customer_success"] * config.customer_success_weight
            )
            ranked.append(
                ScoredCandidate(
                    property_code=code,
                    score=round(score, 4),
                    parts=parts,
                    reasons=reasons[:6],
                    warnings=warnings[:4],
                )
            )

        ranked.sort(key=lambda c: c.score, reverse=True)
        return ranked
