from __future__ import annotations

import time
import uuid
from typing import Any

from app.optimization.interfaces import (
    OptimizationContext,
    OptimizationReport,
    OptimizationReportBuilder,
    OptimizationSuggestion,
)


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


class DefaultOptimizationReportBuilder(OptimizationReportBuilder):
    def build(
        self,
        *,
        suggestions: list[OptimizationSuggestion],
        ctx: OptimizationContext,
        duration_ms: int,
        report_id: str,
    ) -> OptimizationReport:
        suggestions = sorted(
            suggestions,
            key=lambda s: (_PRIORITY_RANK.get(s.priority, 9), -s.confidence),
        )
        config_changes: dict[str, Any] = {}
        for s in suggestions:
            for k, v in (s.recommended_config or {}).items():
                config_changes.setdefault(k, v)

        perf_findings: list[str] = []
        cost_findings: list[str] = []
        rows = ctx.token_analytics or ctx.evaluation_records or []
        if rows:
            lats = [float(r.get("latency_ms") or 0) for r in rows]
            costs = [float(r.get("estimated_cost") or r.get("total_cost") or 0) for r in rows]
            toks = [float(r.get("total_tokens") or 0) for r in rows]
            if lats:
                avg_l = sum(lats) / len(lats)
                perf_findings.append(f"avg_latency_ms={avg_l:.1f}")
            if toks:
                perf_findings.append(f"avg_total_tokens={sum(toks)/len(toks):.0f}")
            if costs:
                avg_c = sum(costs) / len(costs)
                cost_findings.append(f"avg_cost={avg_c:.8f}")
            failed = sum(1 for r in rows if not r.get("ok", True))
            if failed:
                perf_findings.append(f"failed_requests={failed}/{len(rows)}")

        for s in suggestions:
            if s.area in ("latency_trends", "workflow_bottlenecks", "planning_thresholds"):
                perf_findings.append(f"{s.area}:{s.title}")
            if s.area in ("cost_trends", "rag_top_k", "memory_budget") and s.cost_saving:
                cost_findings.append(f"{s.area}:save≈{s.cost_saving}")

        return OptimizationReport(
            report_id=report_id or uuid.uuid4().hex[:16],
            created_at=int(time.time()),
            sample_count=len(rows),
            suggestions=suggestions[:30],
            performance_findings=perf_findings[:20],
            cost_findings=cost_findings[:20],
            recommended_config_changes=config_changes,
            optimization_duration_ms=int(duration_ms or 0),
            estimated_gain=round(sum(s.estimated_gain for s in suggestions), 3),
            cost_saving=round(sum(s.cost_saving for s in suggestions), 8),
            metadata={
                "lookback_hours": ctx.lookback_hours,
                "auto_apply": False,
                "evaluation_samples": len(ctx.evaluation_records or []),
                "analytics_samples": len(ctx.token_analytics or []),
                "bi_samples": len(ctx.bi_snapshots or []),
            },
            applied=False,
        )
