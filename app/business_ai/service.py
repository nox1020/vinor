from __future__ import annotations

import threading
import time
from typing import Any

from app.business_ai.di import make_business_ai
from app.business_ai.engine import business_ai_enabled
from app.business_ai.interfaces import AutonomousBusinessAI, BusinessReport

_LOCK = threading.Lock()
_AI: AutonomousBusinessAI | None = None
_FALLBACK: dict[str, Any] = {}


def get_business_ai() -> AutonomousBusinessAI | None:
    global _AI
    if not business_ai_enabled():
        return None
    if _AI is not None:
        return _AI
    with _LOCK:
        if _AI is None:
            _AI = make_business_ai()
    return _AI


def run_business_ai() -> BusinessReport | None:
    """Background/manual management reports — outside request path."""
    ai = get_business_ai()
    if ai is None:
        return None
    try:
        evaluation: list[dict[str, Any]] = []
        try:
            from app.evaluation.storage import read_evaluation_records

            evaluation = read_evaluation_records(
                since_ts=int(time.time()) - 30 * 86400, limit=5000
            )
        except Exception:
            evaluation = []
        bi_rows = [
            {
                "market_score": r.get("bi_market_score"),
                "opportunity_score": r.get("bi_opportunity_score"),
            }
            for r in evaluation
            if r.get("bi_market_score") or r.get("bi_opportunity_score")
        ]
        report = ai.analyze(evaluation=evaluation, bi_rows=bi_rows)
        global _FALLBACK
        _FALLBACK = report.to_dict()
        return report
    except Exception:
        return None
