from __future__ import annotations

from collections import Counter

from app.optimization.interfaces import (
    OptimizationContext,
    OptimizationSuggestion,
    WorkflowOptimizer,
)


def _avg(vals: list[float], default: float = 0.0) -> float:
    return sum(vals) / len(vals) if vals else default


class RuleWorkflowOptimizer(WorkflowOptimizer):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        rows = ctx.token_analytics or ctx.evaluation_records or []
        if len(rows) < 3:
            return []
        out: list[OptimizationSuggestion] = []
        # Agent selection frequency
        agents: Counter[str] = Counter()
        retries = []
        validation_errs = 0
        for r in rows:
            sa = str(r.get("selected_agent") or "").strip()
            if sa:
                agents[sa] += 1
            for a in r.get("selected_agents") or []:
                if str(a).strip():
                    agents[str(a).strip()] += 1
            retries.append(float(r.get("retry_count") or 0))
            errs = r.get("validation_errors") or r.get("errors") or []
            if errs:
                validation_errs += 1
        avg_retry = _avg(retries)
        if avg_retry >= 0.4:
            out.append(
                OptimizationSuggestion(
                    area="planning_thresholds",
                    title="افزایش آستانه اطمینان Planning / Adaptive",
                    recommendation=(
                        "Retry زیاد است؛ آستانه Planning را سخت‌گیرانه‌تر کنید "
                        "تا مسیرهای نامطمئن زودتر کوتاه شوند."
                    ),
                    recommended_config={"VINOR_PLANNING_CONFIDENCE_THRESHOLD_HINT": 0.55},
                    priority="medium",
                    expected_impact="کاهش Retry و Latency",
                    confidence=min(0.8, 0.4 + avg_retry),
                    estimated_gain=round(min(0.25, avg_retry * 0.3), 3),
                )
            )
        if validation_errs >= max(2, len(rows) // 5):
            out.append(
                OptimizationSuggestion(
                    area="workflow_bottlenecks",
                    title="بازبینی Validation Workflow",
                    recommendation=(
                        "خطاهای Validation مکرر است؛ قوانین Step/Field را ساده یا پیام‌ها را شفاف‌تر کنید."
                    ),
                    recommended_config={"WORKFLOW_VALIDATION_REVIEW": True},
                    priority="high",
                    expected_impact="کاهش Failed Workflows",
                    confidence=0.65,
                    estimated_gain=0.15,
                )
            )
        # Agent selection rules
        if agents:
            top, cnt = agents.most_common(1)[0]
            share = cnt / max(1, sum(agents.values()))
            if share >= 0.7 and len(agents) >= 2:
                out.append(
                    OptimizationSuggestion(
                        area="agent_selection_rules",
                        title="تنوع‌بخشی به انتخاب Agent",
                        recommendation=(
                            f"Agent غالب «{top}» ({share:.0%}) است؛ "
                            "قوانین routing را برای مسیرهای Analysis/Recommendation بازبینی کنید."
                        ),
                        recommended_config={"AGENT_ROUTING_REVIEW": top},
                        priority="low",
                        expected_impact="پوشش بهتر intentهای متنوع",
                        confidence=0.5,
                        estimated_gain=0.06,
                    )
                )
        return out
