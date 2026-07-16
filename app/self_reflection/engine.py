from __future__ import annotations

import os
import time
from typing import Any

from app.self_reflection.interfaces import ReflectionEngine, ReflectionResult


def reflection_enabled() -> bool:
    return (os.environ.get("VINOR_REFLECTION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class RuleReflectionEngine(ReflectionEngine):
    def reflect(self, *, analytics_row: dict[str, Any], shared: dict[str, Any] | None = None) -> ReflectionResult:
        t0 = time.perf_counter()
        row = analytics_row or {}
        shared = shared or {}
        notes: list[str] = []
        ok = bool(row.get("ok", True))
        selected = str(row.get("decision_selected_property") or row.get("selected_property") or "")
        goals = shared.get("goals") if isinstance(shared.get("goals"), dict) else {}
        primary = ""
        try:
            from app.goals.service import get_goals

            if not goals:
                goals = get_goals() or {}
        except Exception:
            pass
        g0 = (goals.get("goals") or [None])[0] if goals.get("goals") else None
        if isinstance(g0, dict):
            primary = str(g0.get("goal_type") or "")

        goal_completed = bool(selected) or (ok and primary in ("general", "support", ""))
        if primary in ("search", "buy") and not selected:
            goal_completed = False
            notes.append("goal_incomplete")

        agent = str(row.get("selected_agent") or "")
        agent_ok = True
        if primary == "search" and agent and agent not in ("property_search", "recommendation", ""):
            agent_ok = False
            notes.append("agent_mismatch")

        api_rounds = int(row.get("api_rounds") or 0)
        extra_tools = api_rounds > 3
        if extra_tools:
            notes.append("extra_tools")

        cost = float(row.get("total_cost") or row.get("estimated_cost") or 0)
        tokens = int(row.get("total_tokens") or 0)
        cost_high = cost > 0.002 or tokens > 2500
        if cost_high:
            notes.append("cost_high")

        reply_ok = ok and not row.get("errors")
        if not reply_ok:
            notes.append("reply_insufficient")

        score = 0.2
        if goal_completed:
            score += 0.25
        if agent_ok:
            score += 0.15
        if not extra_tools:
            score += 0.15
        if not cost_high:
            score += 0.15
        if reply_ok:
            score += 0.1
        return ReflectionResult(
            goal_completed=goal_completed,
            agent_appropriate=agent_ok,
            extra_tools=extra_tools,
            cost_high=cost_high,
            reply_sufficient=reply_ok,
            score=round(min(1.0, score), 3),
            notes=notes[:8],
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
