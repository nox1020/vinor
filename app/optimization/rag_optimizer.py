from __future__ import annotations

from app.optimization.interfaces import OptimizationContext, OptimizationSuggestion, RagOptimizer


def _avg(vals: list[float], default: float = 0.0) -> float:
    return sum(vals) / len(vals) if vals else default


class RuleRagOptimizer(RagOptimizer):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        rows = ctx.token_analytics or ctx.evaluation_records or []
        if len(rows) < 3:
            return []
        rag_toks = [float(r.get("rag_tokens") or r.get("context_tokens") or 0) for r in rows]
        total = [float(r.get("total_tokens") or r.get("prompt_tokens") or 1) for r in rows]
        avg_rag = _avg(rag_toks)
        avg_total = _avg(total) or 1.0
        ratio = avg_rag / avg_total
        out: list[OptimizationSuggestion] = []
        if ratio >= 0.35 or avg_rag >= 400:
            out.append(
                OptimizationSuggestion(
                    area="rag_top_k",
                    title="کاهش RAG Top-K / بودجه Context",
                    recommendation=(
                        "سهم RAG از Prompt بالاست؛ کاهش Top-K یا budget context پیشنهاد می‌شود."
                    ),
                    recommended_config={
                        "VINOR_RAG_TOP_K_HINT": 4,
                        "VINOR_CONTEXT_BUDGET_CHARS_HINT": 2400,
                    },
                    priority="high" if ratio >= 0.45 else "medium",
                    expected_impact="کاهش Prompt Tokens و هزینه",
                    confidence=min(0.85, 0.45 + ratio),
                    estimated_gain=round(min(0.3, ratio * 0.4), 3),
                    cost_saving=round(avg_rag * 0.15 * 0.27 / 1_000_000, 8),
                )
            )
        elif avg_rag < 40 and avg_total > 800:
            out.append(
                OptimizationSuggestion(
                    area="rag_top_k",
                    title="افزایش ملایم RAG Top-K در مسیر Search",
                    recommendation=(
                        "RAG بسیار کم استفاده شده؛ برای Search ممکن است Top-K کمی افزایش یابد."
                    ),
                    recommended_config={"VINOR_RAG_TOP_K_HINT": 6},
                    priority="low",
                    expected_impact="بهبود پوشش نتایج",
                    confidence=0.4,
                    estimated_gain=0.05,
                )
            )
        return out
