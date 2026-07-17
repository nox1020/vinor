# -*- coding: utf-8 -*-
"""
Vinor Commercial Layer (Phase 3)

Additive Negotiation / Offer / Counter / Reservation.
All feature flags default ON — disable via env if needed. mark-in-transaction / deal commission unchanged.
"""

from app.commercial.config import (
    commercial_activity_hook_enabled,
    commercial_ai_tools_enabled,
    commercial_buyer_ui_enabled,
    commercial_enabled,
    commercial_ui_enabled,
    commercial_visit_bridge_enabled,
    commercial_workflow_enabled,
)
from app.commercial.service import (
    commercial_status,
    convert_reservation,
    get_negotiation,
    get_offer,
    hold_reservation,
    list_buyer_offers,
    list_offer_counters,
    list_partner_negotiations,
    list_partner_offers,
    list_partner_reservations,
    propose_counter,
    propose_offer,
    release_reservation,
    respond_offer,
    start_negotiation,
)
from app.commercial.visit_bridge import maybe_open_negotiation_from_visit_result

__all__ = [
    "commercial_enabled",
    "commercial_ui_enabled",
    "commercial_buyer_ui_enabled",
    "commercial_ai_tools_enabled",
    "commercial_activity_hook_enabled",
    "commercial_workflow_enabled",
    "commercial_visit_bridge_enabled",
    "commercial_status",
    "start_negotiation",
    "propose_offer",
    "respond_offer",
    "propose_counter",
    "hold_reservation",
    "release_reservation",
    "convert_reservation",
    "list_partner_negotiations",
    "list_partner_offers",
    "list_buyer_offers",
    "list_offer_counters",
    "list_partner_reservations",
    "get_offer",
    "get_negotiation",
    "maybe_open_negotiation_from_visit_result",
]
