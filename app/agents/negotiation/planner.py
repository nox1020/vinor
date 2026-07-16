from __future__ import annotations

import re
from typing import Any

from app.agents.negotiation.config import negotiation_hint_budget_chars
from app.agents.negotiation.interfaces import (
    NegotiationPlan,
    NegotiationPlanner,
    NegotiationRequest,
    NegotiationRiskAnalyzer,
    NegotiationStrategyBuilder,
    PriceBand,
)
from app.agents.negotiation.risk import RuleNegotiationRiskAnalyzer
from app.agents.negotiation.strategy import RuleNegotiationStrategyBuilder

_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_BUDGET_RE = re.compile(
    r"(?:تا|بودجه|زیر|کمتر از|حداکثر)\s*([\d۰-۹]+(?:[.,٫،][\d۰-۹]+)*)\s*(میلیارد|میلیون)?",
    re.I,
)


def _fa(s: str) -> str:
    return (s or "").translate(_DIGIT)


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    digits = re.sub(r"[^\d]", "", _fa(str(val)))
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _parse_budget(text: str) -> int | None:
    m = _BUDGET_RE.search(text or "")
    if not m:
        return None
    num = re.sub(r"[^\d]", "", _fa(m.group(1)))
    try:
        val = int(num or "0")
    except Exception:
        return None
    unit = (m.group(2) or "").lower()
    if "میلیارد" in unit:
        return val * 1_000_000_000
    if "میلیون" in unit:
        return val * 1_000_000
    if val < 1000:
        return val * 1_000_000_000
    return val


def _short_price(n: int | None) -> str:
    if not n:
        return "-"
    if n >= 1_000_000_000:
        v = n / 1_000_000_000
        s = f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"
        return f"{s}B"
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    return str(n)


def _analysis_avg(categories: list[Any]) -> float:
    scores: list[float] = []
    for cat in categories or []:
        score = getattr(cat, "score", None)
        if score is None and isinstance(cat, dict):
            score = cat.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


class RuleNegotiationPlanner(NegotiationPlanner):
    def __init__(
        self,
        *,
        risk: NegotiationRiskAnalyzer | None = None,
        strategy: NegotiationStrategyBuilder | None = None,
    ):
        self._risk = risk or RuleNegotiationRiskAnalyzer()
        self._strategy = strategy or RuleNegotiationStrategyBuilder()

    def plan(self, req: NegotiationRequest) -> NegotiationPlan:
        shared = dict(req.shared or {})
        code, asking, reuse_flags = self._resolve_property(shared, req)
        profile = self._resolve_profile(shared)
        budget = self._resolve_budget(profile, shared, req.message)
        rec_score = self._recommendation_score(shared)
        analysis_score = _analysis_avg(list(shared.get("analysis_categories") or []))

        band = self._price_band(asking=asking, budget_max=budget, analysis_score=analysis_score)
        risk_score, risk_level = self._risk.analyze(
            asking=asking,
            budget_max=budget,
            analysis_score=analysis_score,
            recommendation_score=rec_score,
            shared=shared,
        )
        deal_p = self._deal_probability(
            risk_score=risk_score,
            analysis_score=analysis_score,
            recommendation_score=rec_score,
            asking=asking,
            budget_max=budget,
            profile=profile,
        )
        strategy, tone, actions, next_action = self._strategy.build(
            risk_level=risk_level,
            risk_score=risk_score,
            deal_probability=deal_p,
            profile=profile,
        )
        confidence = min(
            0.95,
            0.3
            + (0.2 if asking else 0)
            + (0.15 if budget else 0)
            + (0.15 if reuse_flags.get("reuse_recommendation") else 0)
            + (0.1 if reuse_flags.get("reuse_analysis") else 0)
            + (0.1 if reuse_flags.get("reuse_customer_profile") else 0)
            + deal_p * 0.15,
        )
        hint = self._compact_hint(
            target=band.target,
            offer=band.suggested_offer,
            risk_level=risk_level,
            strategy=strategy,
            budget_chars=int(req.context_budget_chars or negotiation_hint_budget_chars()),
        )
        return NegotiationPlan(
            property_code=code,
            target_price=band.target,
            minimum_price=band.minimum,
            maximum_price=band.maximum,
            suggested_offer=band.suggested_offer,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=round(confidence, 3),
            recommended_strategy=strategy,
            recommended_tone=tone,
            suggested_actions=actions,
            deal_probability=round(deal_p, 3),
            next_action=next_action,
            compact_hint=hint,
            negotiation_tokens=(len(hint) + 3) // 4 if hint else 0,
            reuse_analysis=bool(reuse_flags.get("reuse_analysis")),
            reuse_recommendation=bool(reuse_flags.get("reuse_recommendation")),
            reuse_customer_profile=bool(reuse_flags.get("reuse_customer_profile")),
            reuse_workflow=bool(reuse_flags.get("reuse_workflow")),
            reuse_planning=bool(reuse_flags.get("reuse_planning")),
            metadata={"asking": asking, "budget_max": budget},
        )

    def _resolve_property(
        self, shared: dict[str, Any], req: NegotiationRequest
    ) -> tuple[str, int | None, dict[str, bool]]:
        flags = {
            "reuse_analysis": bool(shared.get("analysis_categories") or shared.get("property_analysis_agent")),
            "reuse_recommendation": bool(
                shared.get("recommended_code") or shared.get("recommendation_items")
            ),
            "reuse_customer_profile": bool(shared.get("customer_profile") or shared.get("memory_prefs")),
            "reuse_workflow": False,
            "reuse_planning": bool(shared.get("reused_planning") or shared.get("planning_land_codes")),
        }
        code = str(shared.get("recommended_code") or "").strip()
        if not code:
            items = shared.get("recommendation_items") or []
            if items and isinstance(items[0], dict):
                code = str(items[0].get("property_code") or "").strip()
        if not code:
            for key in ("property_codes", "land_codes", "planning_land_codes"):
                raw = shared.get(key)
                if isinstance(raw, (list, tuple)) and raw:
                    code = str(raw[0]).strip()
                    break
        if not code:
            m = re.search(r"\b(\d{8,16})\b", req.message or "")
            if m:
                code = m.group(1)

        asking = _to_int(shared.get("asking_price") or shared.get("property_price"))
        if asking is None and code:
            try:
                from app.agents.analysis.manager import load_lands_for_codes

                lands = load_lands_for_codes(
                    [code], user_key=req.user_key, audience=req.audience
                )
                if lands:
                    asking = _to_int(lands[0].get("price_total") or lands[0].get("price"))
            except Exception:
                pass

        try:
            from app.conversation.service import get_conversation_obs

            conv = get_conversation_obs() or {}
            if conv.get("workflow") and conv.get("workflow") not in ("", "none"):
                flags["reuse_workflow"] = True
            shared.setdefault("workflow", conv.get("workflow"))
        except Exception:
            pass

        return code, asking, flags

    def _resolve_profile(self, shared: dict[str, Any]) -> dict[str, Any]:
        prof = shared.get("customer_profile")
        if isinstance(prof, dict) and prof:
            return prof
        try:
            from app.agents.customer_memory.service import get_customer_profile

            p = get_customer_profile()
            if p:
                return p
        except Exception:
            pass
        prefs = shared.get("memory_prefs") if isinstance(shared.get("memory_prefs"), dict) else {}
        return {
            "interaction_style": prefs.get("style") or "neutral",
            "preferences": {"budget_max": prefs.get("budget_max")},
            "budget_profile": {"max": prefs.get("budget_max")},
        }

    def _resolve_budget(self, profile: dict[str, Any], shared: dict[str, Any], message: str) -> int | None:
        prefs = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
        budget = _to_int(prefs.get("budget_max"))
        if budget is None:
            bp = profile.get("budget_profile") if isinstance(profile.get("budget_profile"), dict) else {}
            budget = _to_int(bp.get("max"))
        if budget is None:
            mp = shared.get("memory_prefs") if isinstance(shared.get("memory_prefs"), dict) else {}
            budget = _to_int(mp.get("budget_max") or mp.get("budget"))
        if budget is None:
            budget = _parse_budget(message or "")
        return budget

    def _recommendation_score(self, shared: dict[str, Any]) -> float:
        items = shared.get("recommendation_items") or []
        if items and isinstance(items[0], dict):
            try:
                return float(items[0].get("score") or 0.5)
            except Exception:
                return 0.5
        try:
            from app.agents.recommendation.service import get_recommendation_obs

            obs = get_recommendation_obs() or {}
            return float(obs.get("recommendation_score") or 0.5)
        except Exception:
            return 0.5

    def _price_band(
        self, *, asking: int | None, budget_max: int | None, analysis_score: float
    ) -> PriceBand:
        if asking and asking > 0:
            # Better analysis → slightly lower target discount
            discount = 0.08 if analysis_score >= 0.65 else 0.12 if analysis_score >= 0.45 else 0.18
            target = int(asking * (1 - discount * 0.5))
            offer = int(asking * (1 - discount))
            minimum = int(asking * (1 - discount - 0.05))
            maximum = asking
            if budget_max:
                target = min(target, budget_max)
                offer = min(offer, int(budget_max * 0.97))
                maximum = min(maximum, budget_max)
            return PriceBand(
                asking=asking,
                target=target,
                minimum=max(minimum, 0),
                maximum=maximum,
                suggested_offer=max(offer, 0),
            )
        if budget_max:
            return PriceBand(
                asking=None,
                target=int(budget_max * 0.95),
                minimum=int(budget_max * 0.85),
                maximum=budget_max,
                suggested_offer=int(budget_max * 0.9),
            )
        return PriceBand()

    def _deal_probability(
        self,
        *,
        risk_score: float,
        analysis_score: float,
        recommendation_score: float,
        asking: int | None,
        budget_max: int | None,
        profile: dict[str, Any],
    ) -> float:
        p = 0.35
        p += analysis_score * 0.2
        p += recommendation_score * 0.2
        p -= risk_score * 0.25
        if asking and budget_max and asking <= budget_max * 1.05:
            p += 0.15
        elif asking and budget_max and asking > budget_max * 1.2:
            p -= 0.15
        rel = profile.get("relationship_score")
        if isinstance(rel, (int, float)):
            p += float(rel) * 0.1
        return max(0.05, min(0.95, p))

    def _compact_hint(
        self,
        *,
        target: int | None,
        offer: int | None,
        risk_level: str,
        strategy: str,
        budget_chars: int,
    ) -> str:
        budget = max(30, min(budget_chars or 55, 60))
        header = "=== مذاکره === "
        body = f"هدف:{_short_price(target)}|پیشنهاد:{_short_price(offer)}|{risk_level[:1]}|{strategy[:8]}"
        room = budget - len(header)
        if room < 8:
            return (header + body)[:budget]
        if len(body) > room:
            body = body[: room - 1] + "…"
        return header + body
