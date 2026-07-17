# -*- coding: utf-8 -*-
"""VisitResult interested → open Negotiation (fail-open, no Visit mutation)."""
from __future__ import annotations

from typing import Any, Optional

from app.commercial.config import commercial_enabled, commercial_visit_bridge_enabled
from app.commercial.interfaces import Negotiation


def maybe_open_negotiation_from_visit_result(
    result: Any,
    *,
    visit_rec: dict[str, Any] | None = None,
) -> Optional[Negotiation]:
    """
    When VisitResult outcome is interested, open/reuse Negotiation.
    Does not mutate Visit or VisitResult.
    """
    if not commercial_enabled() or not commercial_visit_bridge_enabled():
        return None
    if result is None:
        return None
    try:
        outcome = str(getattr(result, "outcome", "") or "").strip()
        if outcome != "interested":
            return None
        partner_phone = str(getattr(result, "partner_phone", "") or "").strip()
        land_code = str(getattr(result, "land_code", "") or "").strip()
        visit_id = str(getattr(result, "visit_request_id", "") or "").strip()
        buyer_phone = ""
        if isinstance(visit_rec, dict):
            buyer_phone = str(visit_rec.get("customer_phone") or "").strip()
            if not partner_phone:
                partner_phone = str(visit_rec.get("partner_phone") or "").strip()
            if not land_code:
                land_code = str(visit_rec.get("land_code") or "").strip()
            if not visit_id:
                visit_id = str(visit_rec.get("id") or "").strip()
        if not partner_phone or not land_code:
            return None

        from app.commercial.service import start_negotiation

        return start_negotiation(
            land_code=land_code,
            partner_phone=partner_phone,
            buyer_phone=buyer_phone,
            visit_request_id=visit_id,
            source="visit",
            notes="auto from visit result interested",
        )
    except Exception:
        return None
