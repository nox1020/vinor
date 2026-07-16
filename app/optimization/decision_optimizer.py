from __future__ import annotations

from typing import Any

from app.optimization.interfaces import (
    DecisionOptimizer,
    OptimizationContext,
    OptimizationSuggestion,
)


def _avg(vals: list[float], default: float = 0.0) -> float:
    return sum(vals) / len(vals) if vals else default


class RuleDecisionOptimizer(DecisionOptimizer):
    """Suggest decision weight tweaks — never applies."""

    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        rows = ctx.evaluation_records or ctx.token_analytics or []
        if len(rows) < 3:
            return []
        conflict_rates = []
        decision_quality = []
        for r in rows:
            q = r.get("quality") if isinstance(r.get("quality"), dict) else {}
            if q:
                conflict_rates.append(float(q.get("conflict_rate") or 0))
                decision_quality.append(float(q.get("decision_quality") or 0))
            else:
                conflict_rates.append(min(1.0, float(r.get("conflict_count") or 0) / 5.0))
                decision_quality.append(float(r.get("decision_confidence") or 0))
        avg_c = _avg(conflict_rates)
        avg_q = _avg(decision_quality)
        out: list[OptimizationSuggestion] = []
        if avg_c >= 0.25:
            out.append(
                OptimizationSuggestion(
                    area="decision_weights",
                    title="کاهش حاشیه Conflict / افزایش وزن Recommendation",
                    recommendation=(
                        "نرخ Conflict بالاست؛ افزایش VINOR_DECISION_W_RECOMMENDATION "
                        "و کمی کاهش VINOR_DECISION_CONFLICT_MARGIN پیشنهاد می‌شود."
                    ),
                    recommended_config={
                        "VINOR_DECISION_W_RECOMMENDATION": 0.35,
                        "VINOR_DECISION_W_NEGOTIATION": 0.18,
                        "VINOR_DECISION_CONFLICT_MARGIN": 0.06,
                    },
                    priority="high",
                    expected_impact="کاهش Conflict Rate و پایداری Decision",
                    confidence=min(0.9, 0.5 + avg_c),
                    estimated_gain=round(avg_c * 0.4, 3),
                )
            )
        if avg_q and avg_q < 0.5:
            out.append(
                OptimizationSuggestion(
                    area="decision_weights",
                    title="تقویت وزن Analysis و Customer Memory",
                    recommendation=(
                        "کیفیت Decision پایین است؛ وزن Analysis و Memory را افزایش دهید."
                    ),
                    recommended_config={
                        "VINOR_DECISION_W_ANALYSIS": 0.25,
                        "VINOR_DECISION_W_MEMORY": 0.15,
                    },
                    priority="medium",
                    expected_impact="بهبود Decision Quality",
                    confidence=0.55,
                    estimated_gain=0.12,
                )
            )
        # Business signal weights soft suggestion from BI snapshots
        bi = ctx.bi_snapshots or []
        if bi:
            opps = [float(b.get("opportunity_score") or 0) for b in bi if isinstance(b, dict)]
            if opps and _avg(opps) < 0.45:
                out.append(
                    OptimizationSuggestion(
                        area="business_signal_weights",
                        title="بازبینی وزن سیگنال‌های Business Intelligence",
                        recommendation=(
                            "Opportunity Score میانگین پایین است؛ "
                            "Lead Quality و Purchase Probability را در تصمیم‌گیری پررنگ‌تر کنید "
                            "(پیشنهاد پیکربندی — بدون اعمال خودکار)."
                        ),
                        recommended_config={
                            "BI_LEAD_WEIGHT_HINT": 0.25,
                            "BI_PURCHASE_WEIGHT_HINT": 0.25,
                        },
                        priority="low",
                        expected_impact="بهبود هم‌راستایی Decision با BI",
                        confidence=0.45,
                        estimated_gain=0.08,
                    )
                )
        return out
