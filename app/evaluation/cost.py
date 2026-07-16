from __future__ import annotations

from typing import Any

from app.evaluation.interfaces import CostCollector


class RowCostCollector(CostCollector):
    """Cost from existing analytics — no API pricing calls."""

    def collect_cost(self, analytics_row: dict[str, Any]) -> dict[str, Any]:
        row = analytics_row or {}
        try:
            cost = float(row.get("total_cost") or 0)
        except Exception:
            cost = 0.0
        prompt = int(row.get("prompt_tokens") or row.get("input_tokens") or 0)
        completion = int(row.get("output_tokens") or row.get("completion_tokens") or 0)
        total = int(row.get("total_tokens") or (prompt + completion))
        return {
            "estimated_cost": round(cost, 8),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }
