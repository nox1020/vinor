from __future__ import annotations

import re
from typing import Any

from app.agents.recommendation.config import recommendation_hint_budget_chars
from app.agents.recommendation.interfaces import (
    RecommendationEngine,
    RecommendationItem,
    RecommendationRequest,
    RecommendationResult,
)

_BUDGET_RE = re.compile(
    r"(?:تا|بودجه|زیر|کمتر از)\s*([\d۰-۹]+(?:[.,٫،][\d۰-۹]+)*)\s*(میلیارد|میلیون)?",
    re.I,
)
_CITY_RE = re.compile(r"(دماوند|گرمابسرد|لواسان|رودهن|آبسرد)", re.I)
_TYPE_RE = re.compile(r"(ویلا|زمین|باغ|آپارتمان)", re.I)


def _fa_digits(s: str) -> str:
    return str(s).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


def _parse_budget(message: str) -> int | None:
    m = _BUDGET_RE.search(message or "")
    if not m:
        return None
    num = _fa_digits(m.group(1)).replace(",", "").replace("،", "").replace(".", "")
    try:
        val = int(re.sub(r"\D", "", num) or "0")
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


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    digits = re.sub(r"[^\d]", "", str(val))
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _analysis_score_for(code: str, categories: list[Any]) -> tuple[float, list[str], list[str]]:
    """Aggregate Structured Analysis categories for one code — no re-analysis."""
    pros: list[str] = []
    cons: list[str] = []
    scores: list[float] = []
    for cat in categories or []:
        name = getattr(cat, "name", None) or (cat.get("name") if isinstance(cat, dict) else "")
        summary = getattr(cat, "summary", None) or (cat.get("summary") if isinstance(cat, dict) else "")
        if code and code not in str(summary):
            # category may be tagged with code in summary like "CODE:قیمت"
            if summary and ":" in str(summary) and not str(summary).startswith(code):
                continue
        score = getattr(cat, "score", None)
        if score is None and isinstance(cat, dict):
            score = cat.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
        p = getattr(cat, "pros", None) or (cat.get("pros") if isinstance(cat, dict) else []) or []
        c = getattr(cat, "cons", None) or (cat.get("cons") if isinstance(cat, dict) else []) or []
        pros.extend([str(x) for x in list(p)[:2]])
        cons.extend([str(x) for x in list(c)[:2]])
    if not scores:
        return 0.5, pros[:3], cons[:3]
    return sum(scores) / len(scores), pros[:3], cons[:3]


class RuleRecommendationEngine(RecommendationEngine):
    """Rule ranking over reused Search/Analysis/Planning signals — no new I/O."""

    def rank(self, req: RecommendationRequest, lands: list[dict[str, Any]]) -> RecommendationResult:
        codes = list(req.property_codes)
        if not codes and lands:
            codes = [str(L.get("code") or "").strip() for L in lands if L.get("code")]
        if not codes:
            return RecommendationResult(ok=True, metadata={"skipped": "no_codes"})

        budget = _parse_budget(req.message)
        city_pref = None
        cm = _CITY_RE.search(req.message or "")
        if cm:
            city_pref = cm.group(1)
        type_pref = None
        tm = _TYPE_RE.search(req.message or "")
        if tm:
            type_pref = tm.group(1)

        # Soft memory prefs already in shared (never re-fetch memory)
        shared = req.shared or {}
        mem_prefs = shared.get("memory_prefs") if isinstance(shared.get("memory_prefs"), dict) else {}
        if not city_pref and mem_prefs.get("city"):
            city_pref = str(mem_prefs.get("city"))
        if budget is None and mem_prefs.get("budget"):
            budget = _to_int(mem_prefs.get("budget"))

        land_by_code = {
            str(L.get("code") or "").strip(): L for L in (lands or []) if L.get("code")
        }
        items: list[RecommendationItem] = []
        rejected: list[str] = []

        for i, code in enumerate(codes[:5]):
            land = land_by_code.get(code) or {"code": code}
            a_score, a_pros, a_cons = _analysis_score_for(code, req.analysis_categories)
            score = 0.35 + 0.35 * a_score
            reasons = list(a_pros[:2])
            weaknesses = list(a_cons[:2])

            price = _to_int(land.get("price_total") or land.get("price"))
            if budget and price:
                if price <= budget:
                    score += 0.15
                    reasons.append("در بودجه")
                else:
                    score -= 0.25
                    weaknesses.append("بالاتر از بودجه")
                    if price > budget * 1.25:
                        rejected.append(code)
                        continue
            city = str(land.get("city") or "")
            if city_pref and city_pref in city:
                score += 0.12
                reasons.append(f"منطقه={city_pref}")
            elif city_pref and city and city_pref not in city:
                score -= 0.08
                weaknesses.append("منطقه متفاوت")
            cat = str(land.get("category") or "")
            if type_pref and type_pref in cat:
                score += 0.08
                reasons.append(f"نوع={type_pref}")

            score = max(0.0, min(1.0, score))
            conf = min(0.95, 0.45 + 0.15 * len(reasons) + (0.2 if a_score != 0.5 else 0))
            items.append(
                RecommendationItem(
                    property_code=code,
                    score=round(score, 3),
                    match_reasons=reasons[:4] or ["reuse_analysis"],
                    weaknesses=weaknesses[:3],
                    priority=0,
                    confidence=round(conf, 3),
                )
            )

        items.sort(key=lambda x: x.score, reverse=True)
        for idx, it in enumerate(items):
            it.priority = idx + 1

        selected = items[0].property_code if items else ""
        alternate = items[1].property_code if len(items) > 1 else ""
        hint = self._compact_hint(items, selected, alternate, budget=req.context_budget_chars)
        tokens = max(0, (len(hint) + 3) // 4) if hint else 0

        return RecommendationResult(
            ok=True,
            items=items,
            selected_property=selected,
            alternate_property=alternate,
            rejected=rejected[:5],
            compact_hint=hint,
            recommendation_tokens=tokens,
            top_score=items[0].score if items else 0.0,
            metadata={"ranked": len(items), "rule_engine": True},
        )

    def _compact_hint(
        self,
        items: list[RecommendationItem],
        selected: str,
        alternate: str,
        *,
        budget: int,
    ) -> str:
        budget = max(40, min(recommendation_hint_budget_chars(), int(budget or 90)))
        if not items:
            return ""
        top = items[0]
        reasons = "/".join(top.match_reasons[:2]) if top.match_reasons else "—"
        bits = [f"پیشنهاد={selected}", f"امتیاز={top.score:.2f}", f"علت={reasons}"]
        if alternate:
            bits.append(f"جایگزین={alternate}")
        if len(items) > 2:
            bits.append(f"سایر={len(items)-1}")
        body = " | ".join(bits)
        out = "=== پیشنهاد فایل ===\n" + body
        if len(out) > budget:
            out = out[: budget - 1] + "…"
        return out
