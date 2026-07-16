from __future__ import annotations

import re
from typing import Any

from app.agents.analysis.config import analysis_hint_budget_chars
from app.agents.analysis.interfaces import (
    AnalysisCategoryResult,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStrategy,
)

_PRICE_RE = re.compile(r"[\d٫,،.]+")


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().replace(",", "").replace("،", "").replace("٫", "")
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _amenities_blob(land: dict[str, Any]) -> str:
    parts = []
    for key in (
        "amenities",
        "features",
        "facilities",
        "description",
        "desc",
        "villa_amenities",
    ):
        v = land.get(key)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


class RuleAnalysisStrategy(AnalysisStrategy):
    """Rule-first property analysis — no LLM calls, compact hint only."""

    def analyze(self, req: AnalysisRequest, lands: list[dict[str, Any]]) -> AnalysisResult:
        if not lands:
            codes = list(req.property_codes)
            if not codes:
                return AnalysisResult(
                    ok=True,
                    property_codes=[],
                    compact_hint="",
                    analysis_tokens=0,
                    metadata={"empty": True},
                )
            # Codes known (from Search/Planning) but land payload reused elsewhere —
            # keep a tiny rule hint without re-fetching RAG/search.
            budget = max(40, min(analysis_hint_budget_chars(), int(req.context_budget_chars or 100)))
            body = f"کدها={','.join(codes[:3])} | تحلیل:از_context_موجود"
            hint = "=== تحلیل فایل ===\n" + body
            if len(hint) > budget:
                hint = hint[: budget - 1] + "…"
            return AnalysisResult(
                ok=True,
                property_codes=codes,
                compact_hint=hint,
                analysis_tokens=max(0, (len(hint) + 3) // 4),
                metadata={"codes_only": True, "rule_first": True},
            )

        categories: list[AnalysisCategoryResult] = []
        for land in lands[:3]:
            categories.extend(self._analyze_one(land))

        comparison = ""
        if len(lands) >= 2:
            comparison = self._compare(lands[:3])

        hint = self._compact_hint(lands, categories, comparison, budget=req.context_budget_chars)
        # Rough token estimate: ~chars/4 for Persian mix
        tokens = max(0, (len(hint) + 3) // 4) if hint else 0

        return AnalysisResult(
            ok=True,
            property_codes=[str(L.get("code") or "").strip() for L in lands if L.get("code")],
            categories=categories,
            comparison=comparison,
            compact_hint=hint,
            analysis_tokens=tokens,
            metadata={"lands": len(lands), "rule_first": True},
        )

    def _analyze_one(self, land: dict[str, Any]) -> list[AnalysisCategoryResult]:
        code = str(land.get("code") or "").strip()
        city = str(land.get("city") or "").strip()
        loc = str(land.get("location") or "").strip()
        cat = str(land.get("category") or "").strip()
        price = _to_int(land.get("price_total") or land.get("price"))
        area = _to_int(
            land.get("villa_built_area")
            or land.get("built_area")
            or land.get("size")
            or land.get("villa_land_area")
            or land.get("land_area")
        )
        amen = _amenities_blob(land)
        ppm = (price // area) if price and area and area > 0 else None

        # 1) Price
        price_pros, price_cons = [], []
        price_score = 0.55
        if price and price > 0:
            if price < 8_000_000_000:
                price_pros.append("قیمت نسبتاً دسترس‌پذیر")
                price_score += 0.1
            elif price > 25_000_000_000:
                price_cons.append("قیمت بالا نسبت به میانگین محلی")
                price_score -= 0.15
            else:
                price_pros.append("در بازه رایج منطقه")
            if ppm and ppm < 80_000_000:
                price_pros.append("ارزش خرید مناسب به‌ازای متراژ")
                price_score += 0.1
            elif ppm and ppm > 180_000_000:
                price_cons.append("قیمت هر متر بالاست")
                price_score -= 0.1
        else:
            price_cons.append("قیمت نامشخص")
            price_score = 0.35

        # 2) Location
        loc_pros, loc_cons = [], []
        loc_score = 0.55
        loc_l = f"{city} {loc}".lower()
        if any(x in loc_l for x in ("دماوند", "گرمابسرد", "لواسان", "رودهن")):
            loc_pros.append("موقعیت شناخته‌شده در بازار محلی")
            loc_score += 0.15
        if any(x in loc_l for x in ("جاده", "اتوبان", "دسترسی")):
            loc_pros.append("اشاره به دسترسی")
            loc_score += 0.05
        if not city and not loc:
            loc_cons.append("موقعیت ناقص")
            loc_score -= 0.2

        # 3) Amenities
        am_pros, am_cons = [], []
        am_score = 0.5
        for kw, label in (
            ("استخر", "استخر"),
            ("پارکینگ", "پارکینگ"),
            ("آسانسور", "آسانسور"),
            ("باغ", "فضای سبز/باغ"),
            ("انباری", "انباری"),
            ("سالن", "سالن"),
        ):
            if kw in amen:
                am_pros.append(label)
                am_score += 0.06
        if len(am_pros) == 0:
            am_cons.append("امکانات برجسته ثبت نشده")
            am_score -= 0.05
        am_score = max(0.0, min(1.0, am_score))

        # 4) Investment
        inv_pros, inv_cons = [], []
        inv_score = 0.5
        if cat and any(x in cat for x in ("ویلا", "زمین", "باغ")):
            inv_pros.append("نوع ملک مناسب بازار محلی")
            inv_score += 0.1
        if price_score >= 0.6 and loc_score >= 0.6:
            inv_pros.append("ترکیب قیمت/موقعیت مناسب سرمایه‌گذاری")
            inv_score += 0.15
        if price_score < 0.4:
            inv_cons.append("از نظر قیمت ریسک دارد")
            inv_score -= 0.1
        if am_score >= 0.6:
            inv_pros.append("برای سکونت امکانات قابل قبول")
        else:
            inv_cons.append("برای سکونت امکانات محدود")

        tag = code or "?"
        return [
            AnalysisCategoryResult(
                name="price",
                summary=f"{tag}:قیمت",
                pros=price_pros[:3],
                cons=price_cons[:3],
                score=max(0.0, min(1.0, price_score)),
                signals={"price": price, "ppm": ppm},
            ),
            AnalysisCategoryResult(
                name="location",
                summary=f"{tag}:موقعیت",
                pros=loc_pros[:3],
                cons=loc_cons[:3],
                score=max(0.0, min(1.0, loc_score)),
                signals={"city": city, "location": loc},
            ),
            AnalysisCategoryResult(
                name="amenities",
                summary=f"{tag}:امکانات",
                pros=am_pros[:4],
                cons=am_cons[:2],
                score=am_score,
            ),
            AnalysisCategoryResult(
                name="investment",
                summary=f"{tag}:سرمایه/سکونت",
                pros=inv_pros[:3],
                cons=inv_cons[:3],
                score=max(0.0, min(1.0, inv_score)),
            ),
        ]

    def _compare(self, lands: list[dict[str, Any]]) -> str:
        rows = []
        for L in lands:
            code = str(L.get("code") or "?")
            price = _to_int(L.get("price_total") or L.get("price")) or 0
            city = str(L.get("city") or "—")
            rows.append((code, price, city))
        rows.sort(key=lambda r: r[1] or 10**18)
        cheapest = rows[0][0]
        bits = [f"{c}:{p or '—'}:{city}" for c, p, city in rows]
        return f"مقایسه[{','.join(bits)}] ارزان‌تر={cheapest}"

    def _compact_hint(
        self,
        lands: list[dict[str, Any]],
        categories: list[AnalysisCategoryResult],
        comparison: str,
        *,
        budget: int,
    ) -> str:
        budget = max(40, min(analysis_hint_budget_chars(), int(budget or 100)))
        codes = [str(L.get("code") or "").strip() for L in lands if L.get("code")]
        # Aggregate short signals
        price_c = next((c for c in categories if c.name == "price"), None)
        loc_c = next((c for c in categories if c.name == "location"), None)
        inv_c = next((c for c in categories if c.name == "investment"), None)

        bits = []
        if codes:
            bits.append("کدها=" + ",".join(codes[:3]))
        if price_c:
            tip = (price_c.pros or price_c.cons or ["—"])[0]
            bits.append(f"قیمت:{tip}")
        if loc_c and (loc_c.pros or loc_c.cons):
            tip = (loc_c.pros or loc_c.cons)[0]
            bits.append(f"موقعیت:{tip}")
        if inv_c:
            label = "سرمایه+" if inv_c.score >= 0.55 else "ریسک"
            bits.append(f"ارزش:{label}")
        if comparison:
            bits.append(comparison[:60])

        body = " | ".join(bits)
        header = "=== تحلیل فایل ===\n"
        out = header + body
        if len(out) > budget:
            out = out[: budget - 1] + "…"
        return out
