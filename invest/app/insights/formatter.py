"""Format insights for UI consumption (strings only)."""

from __future__ import annotations

from app.insights.models import Insight, InsightViewModel


def format_insight_for_ui(insight: Insight) -> InsightViewModel:
    metrics_parts: list[str] = []
    for key, value in insight.metrics.items():
        if isinstance(value, float):
            metrics_parts.append(f"{key}={value:.2f}")
        else:
            metrics_parts.append(f"{key}={value}")
    return InsightViewModel(
        id=insight.id,
        title=insight.title,
        summary=insight.summary,
        description=insight.description,
        action=insight.action,
        category=insight.category.value,
        severity=insight.severity.label,
        severity_level=int(insight.severity),
        priority=insight.priority,
        related_assets=insight.related_assets,
        metrics_text=", ".join(metrics_parts),
        created_at=insight.created_at,
    )
