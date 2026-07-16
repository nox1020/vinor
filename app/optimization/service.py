from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from app.optimization.config import load_optimization_config, optimization_enabled
from app.optimization.di import make_optimization_manager
from app.optimization.interfaces import OptimizationContext, OptimizationManager, OptimizationReport
from app.optimization.storage import list_optimization_reports, load_optimization_report

_LOCK = threading.Lock()
_MANAGER: OptimizationManager | None = None
_FALLBACK_OBS: dict[str, Any] = {}
_SCHEDULER_STARTED = False


def get_optimization_manager() -> OptimizationManager | None:
    global _MANAGER
    if not optimization_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_optimization_manager()
    return _MANAGER


def _store_obs(report: OptimizationReport | None) -> None:
    global _FALLBACK_OBS
    if report is None:
        obs: dict[str, Any] = {}
        _FALLBACK_OBS = {}
    else:
        obs = {
            "optimization_duration_ms": int(report.optimization_duration_ms or 0),
            "optimization_count": len(report.suggestions or []),
            "recommended_changes": len(report.recommended_config_changes or {}),
            "estimated_gain": float(report.estimated_gain or 0),
            "cost_saving": float(report.cost_saving or 0),
            "report_id": str(report.report_id or ""),
            "applied": False,
        }
        _FALLBACK_OBS = dict(obs)


def get_optimization_obs() -> dict[str, Any]:
    return dict(_FALLBACK_OBS) if _FALLBACK_OBS else {
        "optimization_duration_ms": 0,
        "optimization_count": 0,
        "recommended_changes": 0,
        "estimated_gain": 0.0,
        "cost_saving": 0.0,
        "applied": False,
    }


def _read_jsonl(path: str, *, since_ts: int, limit: int = 5000) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = int(row.get("ts") or row.get("created_at") or 0)
                if ts and ts < since_ts:
                    continue
                out.append(row)
                if len(out) >= limit:
                    break
    except Exception:
        return out
    return out


def _instance_data_file(name: str) -> str:
    try:
        from flask import current_app

        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance")
        )
    return os.path.join(base, "data", name)


def build_optimization_context(*, lookback_hours: int | None = None) -> OptimizationContext:
    """Load historical logs only — no live agent/RAG/search."""
    cfg = load_optimization_config()
    hours = int(lookback_hours if lookback_hours is not None else cfg.lookback_hours)
    since = int(time.time()) - hours * 3600
    evaluation = []
    try:
        from app.evaluation.storage import read_evaluation_records

        evaluation = read_evaluation_records(since_ts=since, limit=5000)
    except Exception:
        evaluation = _read_jsonl(_instance_data_file("ai_evaluation.jsonl"), since_ts=since)

    analytics = _read_jsonl(_instance_data_file("ai_token_analytics.jsonl"), since_ts=since)

    # Soft BI / decision samples from evaluation/analytics fields
    bi_snapshots: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for r in evaluation + analytics:
        if r.get("bi_opportunity_score") or r.get("opportunity_score"):
            bi_snapshots.append(
                {
                    "opportunity_score": r.get("bi_opportunity_score") or r.get("opportunity_score"),
                    "market_score": r.get("bi_market_score"),
                    "lead_score": r.get("bi_lead_score"),
                }
            )
        if r.get("decision_score") or r.get("decision_selected_property") or r.get("property_selected"):
            decisions.append(
                {
                    "decision_score": r.get("decision_score"),
                    "confidence": r.get("decision_confidence"),
                    "selected_property": r.get("decision_selected_property")
                    or r.get("property_selected"),
                    "conflict_count": r.get("conflict_count"),
                }
            )
    return OptimizationContext(
        evaluation_records=evaluation,
        token_analytics=analytics,
        bi_snapshots=bi_snapshots,
        decision_samples=decisions,
        lookback_hours=hours,
    )


def run_optimization(*, lookback_hours: int | None = None) -> OptimizationReport | None:
    """Manual / scheduled entrypoint — NOT for request path."""
    manager = get_optimization_manager()
    if manager is None:
        return None
    try:
        ctx = build_optimization_context(lookback_hours=lookback_hours)
        cfg = load_optimization_config()
        if len(ctx.evaluation_records) + len(ctx.token_analytics) < cfg.min_samples:
            # Still produce a minimal report for observability
            pass
        report = manager.run(ctx)
        _store_obs(report)
        return report
    except Exception:
        return None


def get_latest_optimization_report() -> dict[str, Any] | None:
    rows = list_optimization_reports(limit=1)
    if not rows:
        return None
    rid = str(rows[0].get("report_id") or "")
    if not rid:
        return None
    return load_optimization_report(rid)


def list_reports_for_admin(limit: int = 20) -> list[dict[str, Any]]:
    """Admin/manual visibility only — no prompt injection."""
    return list_optimization_reports(limit=limit)
