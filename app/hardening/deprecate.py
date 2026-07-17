# -*- coding: utf-8 -*-
"""Soft-cleanup registry — warnings only; primary paths retained."""
from __future__ import annotations

import logging
from typing import Any

from app.hardening.config import hardening_soft_cleanup_enabled

logger = logging.getLogger(__name__)

# Primary production paths — MUST NOT be removed.
RETAINED_PRIMARY_PATHS = (
    "propose_deal",
    "mark_in_transaction",
    "express_commissions",
    "partner_withdrawals",
    "complete_visit",
)

# Additive preferred for post-lock / funnel lifecycle (dual-read OK).
ADDITIVE_PREFERRED_PATHS = (
    "closing_deal",
    "closing_settlement",
    "commercial_offer",
    "visit_result",
    "integration_journey",
)

# Misconceptions that should log a soft warning when detected.
_SOFT_WARN_ALIASES = {
    "closing_deal_as_lock": (
        "Closing Deal is a mirror of mark_in_transaction; "
        "assignment in_transaction + commission remain source of truth for file lock."
    ),
    "settlement_as_payout": (
        "Settlement links optional withdrawal_id; partner payout SoT remains withdrawals/commissions."
    ),
}


def deprecate_registry() -> dict[str, Any]:
    return {
        "retained_primary": list(RETAINED_PRIMARY_PATHS),
        "additive_preferred": list(ADDITIVE_PREFERRED_PATHS),
        "hard_delete": False,
        "soft_cleanup_enabled": hardening_soft_cleanup_enabled(),
    }


def warn_deprecated_path(name: str, *, detail: str = "") -> None:
    """Log info/debug when a misconception or dual-path touch is noted. Never raises."""
    if not hardening_soft_cleanup_enabled():
        return
    key = (name or "").strip()
    msg = _SOFT_WARN_ALIASES.get(key) or detail or f"soft-cleanup note: {key}"
    try:
        logger.info("hardening soft-cleanup: %s", msg)
    except Exception:
        pass


def prefer_new_partner_nav_order() -> bool:
    """When True, Partner settings should list journey/deals before legacy-only copy."""
    return hardening_soft_cleanup_enabled()
