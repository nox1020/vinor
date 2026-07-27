"""دستهٔ مالی — نام‌ها برای registry."""
from __future__ import annotations

TOOL_NAMES = frozenset(
    {
        "propose_offer",
        "propose_counter_offer",
        "propose_reservation",
        "propose_contract",
        "propose_payment_milestone",
        "propose_settlement",
        "propose_commission_action",
    }
)
