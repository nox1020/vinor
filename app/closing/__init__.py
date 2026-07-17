# -*- coding: utf-8 -*-
"""
Vinor Closing & Finance Layer (Phase 4)

Additive Deal / Contract / Payment / Settlement.
All feature flags default ON — disable via env if needed.
Does not replace mark-in-transaction, commissions, or withdrawals.
"""

from app.closing.config import (
    closing_activity_hook_enabled,
    closing_ai_tools_enabled,
    closing_deal_bridge_enabled,
    closing_enabled,
    closing_reservation_bridge_enabled,
    closing_ui_enabled,
)
from app.closing.deal_bridge import (
    maybe_link_reservation_to_deal,
    maybe_sync_deal_from_commission,
    maybe_sync_deal_on_commission_status,
)
from app.closing.service import (
    add_payment,
    closing_status,
    create_contract,
    get_contract,
    get_deal,
    get_payment,
    list_deal_contracts,
    list_deal_payments,
    list_deal_settlements,
    list_partner_deals,
    mark_payment_paid,
    open_settlement,
    update_contract_document,
    upsert_deal,
)

__all__ = [
    "closing_enabled",
    "closing_ui_enabled",
    "closing_ai_tools_enabled",
    "closing_activity_hook_enabled",
    "closing_deal_bridge_enabled",
    "closing_reservation_bridge_enabled",
    "closing_status",
    "upsert_deal",
    "create_contract",
    "update_contract_document",
    "add_payment",
    "mark_payment_paid",
    "open_settlement",
    "list_partner_deals",
    "list_deal_contracts",
    "list_deal_payments",
    "list_deal_settlements",
    "get_deal",
    "get_contract",
    "get_payment",
    "maybe_sync_deal_from_commission",
    "maybe_sync_deal_on_commission_status",
    "maybe_link_reservation_to_deal",
]
