# -*- coding: utf-8 -*-
"""Public Visit Result service — register result / no-show (fail-open when flags OFF)."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.visit_result import store
from app.visit_result.activity_hook import record_visit_result_event
from app.visit_result.config import (
    OUTCOMES,
    visit_no_show_status_enabled,
    visit_result_activity_hook_enabled,
    visit_result_ai_tools_enabled,
    visit_result_enabled,
    visit_result_ui_enabled,
)
from app.visit_result.interfaces import VisitResult
from app.visit_result.status_bridge import is_no_show_writable


def visit_result_status() -> dict[str, Any]:
    return {
        "visit_result_enabled": visit_result_enabled(),
        "visit_result_ui_enabled": visit_result_ui_enabled(),
        "visit_result_ai_tools_enabled": visit_result_ai_tools_enabled(),
        "visit_no_show_status_enabled": visit_no_show_status_enabled(),
        "visit_result_activity_hook_enabled": visit_result_activity_hook_enabled(),
        "phase": 2,
    }


def register_result(
    *,
    visit_request_id: str,
    partner_phone: str = "",
    land_code: str = "",
    outcome: str = "",
    notes: str = "",
    actor_key: str = "",
    source: str = "partner",
    metadata: dict[str, Any] | None = None,
) -> Optional[VisitResult]:
    result = store.upsert_visit_result(
        visit_request_id=visit_request_id,
        partner_phone=partner_phone,
        land_code=land_code,
        outcome=outcome,
        notes=notes,
        actor_key=actor_key or partner_phone,
        source=source,
        metadata=metadata,
    )
    if result is not None:
        record_visit_result_event(
            action="visit_result_registered",
            actor_key=result.actor_key or result.partner_phone,
            entity_type="visit_result",
            entity_id=result.id,
            land_code=result.land_code,
            summary=f"Visit result: {result.outcome}",
            payload={
                "visit_request_id": result.visit_request_id,
                "outcome": result.outcome,
                "source": result.source,
            },
            subjects=[
                ("visit_result", result.id),
                ("visit", result.visit_request_id),
                ("partner", result.partner_phone),
            ],
        )
        # Phase 3 Commercial: optional Negotiation from interested (flags default ON).
        try:
            from app.commercial.visit_bridge import maybe_open_negotiation_from_visit_result

            maybe_open_negotiation_from_visit_result(result)
        except Exception:
            pass
    return result


def register_no_show(
    requests: list,
    *,
    visit_request_id: str = "",
    partner_phone: str = "",
    land_code: str = "",
    notes: str = "",
    actor_key: str = "",
    source: str = "partner",
) -> Tuple[Optional[dict], Optional[VisitResult], Optional[str]]:
    """
    Mark visit as no_show + upsert VisitResult(outcome=no_show).
    Never creates commission. Returns (visit_rec, result, error).
    """
    if not is_no_show_writable():
        return None, None, "disabled"
    try:
        from app.express_partner.visit_requests import mark_visit_no_show
    except Exception:
        return None, None, "unavailable"

    rec, err = mark_visit_no_show(
        requests,
        visit_request_id=visit_request_id,
        partner_phone=partner_phone,
        land_code=land_code,
    )
    if err or not rec:
        return None, None, err or "failed"

    result = register_result(
        visit_request_id=str(rec.get("id") or visit_request_id),
        partner_phone=str(rec.get("partner_phone") or partner_phone),
        land_code=str(rec.get("land_code") or land_code),
        outcome="no_show",
        notes=notes,
        actor_key=actor_key or partner_phone,
        source=source,
    )
    if result is not None:
        record_visit_result_event(
            action="visit_no_show",
            actor_key=actor_key or str(rec.get("partner_phone") or ""),
            entity_type="visit",
            entity_id=str(rec.get("id") or ""),
            land_code=str(rec.get("land_code") or ""),
            summary="Visit marked no-show",
            payload={"visit_request_id": str(rec.get("id") or "")},
        )
    return rec, result, None


def get_result(visit_request_id: str) -> Optional[VisitResult]:
    return store.get_result_for_visit(visit_request_id)


def list_partner_results(partner_phone: str, *, limit: int = 200) -> List[VisitResult]:
    return store.list_results(partner_phone=partner_phone, limit=limit)


def valid_outcome(outcome: str) -> bool:
    return (outcome or "").strip() in OUTCOMES
