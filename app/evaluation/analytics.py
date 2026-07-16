from __future__ import annotations

from collections import Counter
from typing import Any

from app.evaluation.interfaces import AnalyticsAggregator, AnalyticsSummary


class RuleAnalyticsAggregator(AnalyticsAggregator):
    """Daily / weekly / monthly rollups from stored evaluation logs."""

    def summarize(
        self, *, records: list[dict[str, Any]], period: str, period_key: str
    ) -> AnalyticsSummary:
        rows = [r for r in (records or []) if isinstance(r, dict)]
        n = len(rows)
        if n == 0:
            return AnalyticsSummary(period=period, period_key=period_key)

        failed = [r for r in rows if not r.get("ok", True) or r.get("errors")]
        costs = [float(r.get("estimated_cost") or 0) for r in rows]
        tokens = [float(r.get("total_tokens") or 0) for r in rows]
        lats = [float(r.get("latency_ms") or 0) for r in rows]
        quals = [
            float((r.get("quality") or {}).get("overall") or 0)
            if isinstance(r.get("quality"), dict)
            else 0.0
            for r in rows
        ]
        conflicts = [
            float((r.get("quality") or {}).get("conflict_rate") or 0)
            if isinstance(r.get("quality"), dict)
            else float(r.get("conflict_count") or 0) / 5.0
            for r in rows
        ]

        intent_counter: Counter[str] = Counter()
        agent_counter: Counter[str] = Counter()
        for r in rows:
            intent = str(r.get("intent") or r.get("workflow") or "unknown")
            intent_counter[intent] += 1
            for a in r.get("selected_agents") or []:
                s = str(a).strip()
                if s:
                    agent_counter[s] += 1
            for a in (r.get("execution_graph") or []):
                if isinstance(a, str) and a.strip():
                    agent_counter[a.strip()] += 1
                elif isinstance(a, (list, tuple)):
                    for x in a:
                        xs = str(x).strip()
                        if xs:
                            agent_counter[xs] += 1

        top_queries = [
            {"query_key": k, "count": c} for k, c in intent_counter.most_common(20)
        ]
        failed_queries = [
            {
                "request_id": str(r.get("request_id") or ""),
                "intent": str(r.get("intent") or ""),
                "errors": list(r.get("errors") or [])[:3],
            }
            for r in failed[:20]
        ]
        most_used = [
            {"agent": k, "count": c} for k, c in agent_counter.most_common(15)
        ]

        return AnalyticsSummary(
            period=period,
            period_key=period_key,
            request_count=n,
            failed_count=len(failed),
            avg_cost=round(sum(costs) / n, 8),
            avg_token=round(sum(tokens) / n, 2),
            avg_latency_ms=round(sum(lats) / n, 2),
            top_queries=top_queries,
            failed_queries=failed_queries,
            most_used_agents=most_used,
            avg_quality=round(sum(quals) / n, 3),
            avg_conflict_rate=round(sum(conflicts) / n, 3),
        )
