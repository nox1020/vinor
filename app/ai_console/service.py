# -*- coding: utf-8 -*-
"""AI Mission Control public service."""
from __future__ import annotations

from typing import Any

from app.ai_console import catalog, readers
from app.ai_console.config import (
    ai_console_enabled,
    ai_console_mutate_enabled,
    ai_console_ui_enabled,
)


def console_status() -> dict[str, Any]:
    return {
        "ai_console_enabled": ai_console_enabled(),
        "ai_console_ui_enabled": ai_console_ui_enabled(),
        "ai_console_mutate_enabled": ai_console_mutate_enabled(),
    }


def dashboard_snapshot() -> dict[str, Any]:
    pending = readers.list_pending_confirms(limit=200)
    pending_alive = [p for p in pending if p.get("status") != "expired"]
    escalations = readers.list_escalations(limit=100)
    open_esc = [
        e
        for e in escalations
        if str(e.get("status") or "").lower() not in ("done", "resolved", "closed")
    ]
    tokens = readers.list_token_rows(limit=200)
    evals = readers.list_evaluation_rows(limit=200)
    sessions = readers.list_workflow_sessions(limit=200)
    active_wf = [
        s
        for s in sessions
        if str(s.get("state") or "").upper()
        not in ("COMPLETED", "FAILED", "CANCELLED", "NONE", "")
    ]
    errors = readers.extract_errors_from_logs(limit=50)

    # latency / cost heuristics from token rows
    latencies: list[float] = []
    cost_sum = 0.0
    for row in tokens:
        try:
            ms = float(row.get("latency_ms") or row.get("duration_ms") or 0)
            if ms > 0:
                latencies.append(ms)
        except (TypeError, ValueError):
            pass
        try:
            cost_sum += float(row.get("cost") or row.get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) >= 2 else (latencies[-1] if latencies else 0.0)

    agents = catalog.list_agents()
    return {
        "kpis": {
            "requests_sample": len(tokens) or len(evals),
            "latency_p50_ms": round(p50, 1),
            "latency_p95_ms": round(p95, 1),
            "token_cost_sample": round(cost_sum, 4),
            "pending_confirms": len(pending_alive),
            "escalations_open": len(open_esc),
            "errors_sample": len(errors),
            "active_workflows": len(active_wf),
            "conversations_indexed": len(readers.list_conversation_index(limit=500)),
        },
        "agents": agents,
        "pending_preview": pending_alive[:8],
        "errors_preview": errors[:8],
        "escalations_preview": open_esc[:5],
        "status": console_status(),
    }
