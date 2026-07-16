from __future__ import annotations

from app.optimization.interfaces import (
    MemoryOptimizer,
    OptimizationContext,
    OptimizationSuggestion,
)


def _avg(vals: list[float], default: float = 0.0) -> float:
    return sum(vals) / len(vals) if vals else default


class RuleMemoryOptimizer(MemoryOptimizer):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        rows = ctx.token_analytics or ctx.evaluation_records or []
        if len(rows) < 3:
            return []
        mem = [float(r.get("memory_tokens") or 0) for r in rows]
        used = [float(r.get("memory_used") or 0) for r in rows]
        retrieved = [float(r.get("memory_retrieved") or 0) for r in rows]
        avg_mem = _avg(mem)
        avg_used = _avg(used)
        avg_ret = _avg(retrieved)
        out: list[OptimizationSuggestion] = []
        if avg_mem >= 120:
            out.append(
                OptimizationSuggestion(
                    area="memory_budget",
                    title="کاهش بودجه Memory در Prompt",
                    recommendation=(
                        "memory_tokens بالاست؛ بودجه فشرده‌سازی Memory را کاهش دهید."
                    ),
                    recommended_config={"VINOR_MEMORY_BUDGET_CHARS_HINT": 600},
                    priority="medium",
                    expected_impact="کاهش Token Memory",
                    confidence=0.6,
                    estimated_gain=0.1,
                    cost_saving=round(avg_mem * 0.2 * 0.27 / 1_000_000, 8),
                )
            )
        if avg_ret > 0 and avg_used / max(avg_ret, 1) < 0.35:
            out.append(
                OptimizationSuggestion(
                    area="memory_budget",
                    title="کاهش retrieval و افزایش precision",
                    recommendation=(
                        "نسبت memory_used/retrieved پایین است؛ "
                        "تعداد آیتم‌های بازیابی‌شده را کمتر کنید."
                    ),
                    recommended_config={"VINOR_MEMORY_TOP_K_HINT": 3},
                    priority="low",
                    expected_impact="بازده بهتر Memory",
                    confidence=0.5,
                    estimated_gain=0.07,
                )
            )
        return out
