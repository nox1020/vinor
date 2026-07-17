# -*- coding: utf-8 -*-
"""
Deal bridge — sync Closing Deal from commission / assignment path (fail-open).

Never mutates assignment, commission, or withdrawal records.
"""
from __future__ import annotations

from typing import Any, Optional

from app.closing.config import (
    closing_deal_bridge_enabled,
    closing_enabled,
    closing_reservation_bridge_enabled,
)
from app.closing.interfaces import Deal


def maybe_sync_deal_from_commission(
    *,
    partner_phone: str,
    land_code: str,
    commission_id: str = "",
    sale_amount: int = 0,
    assignment_status: str = "in_transaction",
    deal_status: str = "in_transaction",
    buyer_phone: str = "",
    metadata: dict[str, Any] | None = None,
) -> Optional[Deal]:
    """Upsert Deal after mark-in-tx creates (or updates) a deal commission."""
    if not closing_enabled() or not closing_deal_bridge_enabled():
        return None
    try:
        from app.closing.service import upsert_deal

        return upsert_deal(
            land_code=land_code,
            partner_phone=partner_phone,
            buyer_phone=buyer_phone,
            assignment_status=assignment_status,
            commission_id=str(commission_id or ""),
            sale_amount=int(sale_amount or 0),
            status=deal_status,
            metadata=metadata,
        )
    except Exception:
        return None


def maybe_sync_deal_on_commission_status(
    *,
    partner_phone: str,
    land_code: str,
    commission_id: str = "",
    commission_status: str = "",
    sale_amount: int = 0,
) -> Optional[Deal]:
    """Map commission approve/reject/paid → Deal status. Does not change commission."""
    if not closing_enabled() or not closing_deal_bridge_enabled():
        return None
    st = (commission_status or "").strip().lower()
    if st in ("approved", "paid"):
        deal_status = "closed"
        assignment_status = "sold"
    elif st == "rejected":
        deal_status = "cancelled"
        assignment_status = ""
    elif st == "pending":
        deal_status = "in_transaction"
        assignment_status = "in_transaction"
    else:
        return None
    return maybe_sync_deal_from_commission(
        partner_phone=partner_phone,
        land_code=land_code,
        commission_id=commission_id,
        sale_amount=sale_amount,
        assignment_status=assignment_status,
        deal_status=deal_status,
        metadata={"commission_status": st},
    )


def maybe_link_reservation_to_deal(
    *,
    reservation_id: str,
    partner_phone: str,
    land_code: str,
    offer_id: str = "",
    buyer_phone: str = "",
) -> Optional[Deal]:
    """
    When a commercial reservation is marked converted, link it on a Deal.
    Never calls mark_in_transaction.
    """
    if not closing_enabled() or not closing_reservation_bridge_enabled():
        return None
    try:
        from app.closing import store
        from app.closing.service import upsert_deal

        rid = (reservation_id or "").strip()
        if not rid:
            return None
        existing = store.list_deals(
            partner_phone=partner_phone,
            land_code=land_code,
            limit=5,
        )
        for deal in existing:
            if deal.status not in ("closed", "cancelled"):
                return store.patch_deal(
                    deal.id,
                    reservation_id=rid,
                    offer_id=offer_id or None,
                    buyer_phone=buyer_phone or None,
                )
        return upsert_deal(
            land_code=land_code,
            partner_phone=partner_phone,
            buyer_phone=buyer_phone,
            reservation_id=rid,
            offer_id=offer_id,
            status="draft",
            metadata={"source": "reservation_converted"},
        )
    except Exception:
        return None
