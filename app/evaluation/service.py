from __future__ import annotations

import threading
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any

from app.evaluation.analytics import RuleAnalyticsAggregator
from app.evaluation.config import evaluation_enabled
from app.evaluation.di import make_evaluation_manager
from app.evaluation.interfaces import EvaluationManager, EvaluationRecord
from app.evaluation.storage import read_evaluation_records

_LOCK = threading.Lock()
_MANAGER: EvaluationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}


def get_evaluation_manager() -> EvaluationManager | None:
    global _MANAGER
    if not evaluation_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_evaluation_manager()
    return _MANAGER


def _store_obs(record: EvaluationRecord | None) -> None:
    global _FALLBACK_OBS
    if record is None:
        obs: dict[str, Any] = {}
        _FALLBACK_OBS = {}
    else:
        obs = {
            "request_id": record.request_id,
            "overall_quality": float(record.quality.overall or 0),
            "accuracy": float(record.quality.accuracy or 0),
            "conflict_rate": float(record.quality.conflict_rate or 0),
            "decision_quality": float(record.quality.decision_quality or 0),
            "total_tokens": int(record.total_tokens or 0),
            "estimated_cost": float(record.estimated_cost or 0),
            "latency_ms": int(record.latency_ms or 0),
            "ok": bool(record.ok),
        }
        _FALLBACK_OBS = dict(obs)
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_evaluation_obs = dict(obs)
            if record is not None:
                g.ai_evaluation = record.to_dict()
    except Exception:
        pass


def get_evaluation_obs() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_evaluation_obs", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {}


def record_evaluation(
    *, analytics_row: dict[str, Any], request_id: str = ""
) -> EvaluationRecord | None:
    """Fail-open public API — never injects into prompt."""
    manager = get_evaluation_manager()
    if manager is None:
        return None
    try:
        record = manager.evaluate_request(
            analytics_row=analytics_row, request_id=request_id
        )
        _store_obs(record)
        return record
    except Exception:
        return None


def clear_evaluation() -> None:
    _store_obs(None)


def _period_bounds(period: str, when: datetime | None = None) -> tuple[int, int, str]:
    now = when or datetime.now(timezone.utc)
    if period == "weekly":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start - timedelta(days=start.weekday())
        end = int((start + timedelta(days=7)).timestamp()) - 1
        iso = start.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        return int(start.timestamp()), end, key
    if period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last = monthrange(start.year, start.month)[1]
        end_dt = start.replace(day=last, hour=23, minute=59, second=59)
        key = f"{start.year}-{start.month:02d}"
        return int(start.timestamp()), int(end_dt.timestamp()), key
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = int((start + timedelta(days=1)).timestamp()) - 1
    key = start.strftime("%Y-%m-%d")
    return int(start.timestamp()), end, key


def get_analytics_summary(period: str = "daily") -> dict[str, Any]:
    """period: daily | weekly | monthly — reads evaluation logs only."""
    p = (period or "daily").strip().lower()
    if p not in ("daily", "weekly", "monthly"):
        p = "daily"
    since, until, key = _period_bounds(p)
    records = read_evaluation_records(since_ts=since, until_ts=until, limit=10000)
    mgr = get_evaluation_manager()
    agg = mgr.aggregator if mgr is not None else RuleAnalyticsAggregator()
    return agg.summarize(records=records, period=p, period_key=key).to_dict()
