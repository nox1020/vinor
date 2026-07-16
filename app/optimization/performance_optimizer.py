from __future__ import annotations

from app.optimization.interfaces import (
    OptimizationContext,
    OptimizationSuggestion,
    PerformanceOptimizer,
)


def _avg(vals: list[float], default: float = 0.0) -> float:
    return sum(vals) / len(vals) if vals else default


class RulePerformanceOptimizer(PerformanceOptimizer):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        rows = ctx.token_analytics or ctx.evaluation_records or []
        if len(rows) < 3:
            return []
        lats = [float(r.get("latency_ms") or r.get("response_time_ms") or 0) for r in rows]
        costs = [float(r.get("estimated_cost") or r.get("total_cost") or 0) for r in rows]
        toks = [float(r.get("total_tokens") or 0) for r in rows]
        parallel_ms = [float(r.get("parallel_execution_time_ms") or 0) for r in rows]
        avg_lat = _avg(lats)
        avg_cost = _avg(costs)
        avg_tok = _avg(toks)
        out: list[OptimizationSuggestion] = []
        if avg_lat >= 2500:
            out.append(
                OptimizationSuggestion(
                    area="latency_trends",
                    title="فعال‌سازی / تقویت Parallel Collaboration",
                    recommendation=(
                        "Latency میانگین بالاست؛ اطمینان از VINOR_PARALLEL_AGENTS=1 "
                        "و بررسی موج‌های سنگین پیشنهاد می‌شود."
                    ),
                    recommended_config={"VINOR_PARALLEL_AGENTS": "1"},
                    priority="high",
                    expected_impact="کاهش Latency پاسخ",
                    confidence=0.7,
                    estimated_gain=0.2,
                )
            )
        elif avg_lat >= 1200 and _avg(parallel_ms) == 0:
            out.append(
                OptimizationSuggestion(
                    area="latency_trends",
                    title="فعال‌سازی Parallel برای مسیرهای چند-Agent",
                    recommendation="Parallel غیرفعال به نظر می‌رسد؛ برای مسیرهای چندمرحله‌ای روشن کنید.",
                    recommended_config={"VINOR_PARALLEL_AGENTS": "1"},
                    priority="medium",
                    expected_impact="بهبود Latency",
                    confidence=0.55,
                    estimated_gain=0.12,
                )
            )
        if avg_cost > 0 and avg_tok >= 1500:
            out.append(
                OptimizationSuggestion(
                    area="cost_trends",
                    title="کاهش بودجه Prompt اجزای فرعی",
                    recommendation=(
                        "هزینه/توکن بالا است؛ بودجه hintهای فرعی و history را فشرده‌تر کنید."
                    ),
                    recommended_config={
                        "VINOR_HISTORY_BUDGET_HINT": "compact",
                        "VINOR_DECISION_HINT_CHARS": 50,
                    },
                    priority="medium",
                    expected_impact="کاهش Cost",
                    confidence=0.6,
                    estimated_gain=0.1,
                    cost_saving=round(avg_cost * 0.12, 8),
                )
            )
        return out
