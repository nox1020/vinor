from __future__ import annotations

from app.adaptive.interfaces import ConfidenceScore, QualityEvaluator, QualityReport
from app.supervisor.interfaces import (
    ROUTE_GREETING,
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
)


class RuleQualityEvaluator(QualityEvaluator):
    """Post-response quality checks — rule-based, no LLM."""

    def evaluate(
        self,
        *,
        route: str,
        reply: str,
        land_codes: list[str],
        ok: bool,
        confidence: ConfidenceScore,
    ) -> QualityReport:
        text = (reply or "").strip()
        codes = [c for c in (land_codes or []) if str(c).strip()]
        route = route or ""
        signals: dict = {
            "ok": ok,
            "reply_len": len(text),
            "land_count": len(codes),
            "confidence": confidence.value,
        }

        if not ok:
            return QualityReport(
                complete=False,
                found_suitable=False,
                needs_continue=False,
                reason="not_ok",
                signals=signals,
            )

        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            found = bool(codes)
            complete = bool(text) and found
            needs = bool(text) and not found
            reason = "search_ok" if complete else ("search_partial" if needs else "search_empty")
            return QualityReport(
                complete=complete,
                found_suitable=found,
                needs_continue=needs,
                reason=reason,
                signals=signals,
            )

        if route == ROUTE_GREETING:
            return QualityReport(
                complete=bool(text),
                found_suitable=True,
                needs_continue=False,
                reason="greeting",
                signals=signals,
            )

        complete = bool(text) and len(text) >= 8
        return QualityReport(
            complete=complete,
            found_suitable=True,
            needs_continue=not complete and bool(text),
            reason="general",
            signals=signals,
        )
