# -*- coding: utf-8 -*-
"""Public Closing service — Deal / Contract / Payment / Settlement."""
from __future__ import annotations

from typing import Any, List, Optional

from app.closing import store
from app.closing.activity_hook import record_closing_event
from app.closing.config import (
    closing_activity_hook_enabled,
    closing_ai_tools_enabled,
    closing_deal_bridge_enabled,
    closing_enabled,
    closing_reservation_bridge_enabled,
    closing_ui_enabled,
)
from app.closing.interfaces import Contract, Deal, Payment, Settlement


def closing_status() -> dict[str, Any]:
    return {
        "closing_enabled": closing_enabled(),
        "closing_ui_enabled": closing_ui_enabled(),
        "closing_ai_tools_enabled": closing_ai_tools_enabled(),
        "closing_activity_hook_enabled": closing_activity_hook_enabled(),
        "closing_deal_bridge_enabled": closing_deal_bridge_enabled(),
        "closing_reservation_bridge_enabled": closing_reservation_bridge_enabled(),
        "phase": 4,
    }


def upsert_deal(
    *,
    land_code: str,
    partner_phone: str,
    buyer_phone: str = "",
    assignment_status: str = "",
    commission_id: str = "",
    reservation_id: str = "",
    offer_id: str = "",
    sale_amount: int = 0,
    status: str = "draft",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> Optional[Deal]:
    deal = store.upsert_deal(
        land_code=land_code,
        partner_phone=partner_phone,
        buyer_phone=buyer_phone,
        assignment_status=assignment_status,
        commission_id=commission_id,
        reservation_id=reservation_id,
        offer_id=offer_id,
        sale_amount=sale_amount,
        status=status,
        notes=notes,
        metadata=metadata,
    )
    if deal is not None:
        record_closing_event(
            action="closing_deal_upserted",
            actor_key=deal.partner_phone,
            entity_type="deal",
            entity_id=deal.id,
            land_code=deal.land_code,
            summary=f"Deal {deal.status} for land {deal.land_code}",
            payload={
                "status": deal.status,
                "commission_id": deal.commission_id,
                "sale_amount": deal.sale_amount,
            },
            subjects=[("deal", deal.id), ("partner", deal.partner_phone)],
        )
    return deal


def create_contract(
    *,
    deal_id: str,
    title: str = "",
    document_status: str = "draft",
    document_ref: str = "",
    notes: str = "",
    actor_key: str = "",
) -> Optional[Contract]:
    deal = store.get_deal(deal_id)
    if deal is None:
        return None
    contract = store.create_contract(
        deal_id=deal.id,
        title=title,
        document_status=document_status,
        document_ref=document_ref,
        notes=notes,
    )
    if contract is None:
        return None
    if deal.status in ("draft", "in_transaction"):
        store.update_deal_status(deal.id, "contracted")
    record_closing_event(
        action="closing_contract_created",
        actor_key=actor_key or deal.partner_phone,
        entity_type="contract",
        entity_id=contract.id,
        land_code=deal.land_code,
        summary=f"Contract {contract.document_status}",
        payload={"deal_id": deal.id, "document_status": contract.document_status},
        subjects=[("contract", contract.id), ("deal", deal.id)],
    )
    return contract


def update_contract_document(
    contract_id: str,
    *,
    document_status: str = "",
    document_ref: str = "",
    title: str = "",
    actor_key: str = "",
) -> Optional[Contract]:
    contract = store.update_contract_document(
        contract_id,
        document_status=document_status,
        document_ref=document_ref,
        title=title,
    )
    if contract is None:
        return None
    deal = store.get_deal(contract.deal_id)
    record_closing_event(
        action="closing_contract_updated",
        actor_key=actor_key or (deal.partner_phone if deal else ""),
        entity_type="contract",
        entity_id=contract.id,
        land_code=deal.land_code if deal else "",
        summary=f"Contract → {contract.document_status}",
        payload={"document_status": contract.document_status, "deal_id": contract.deal_id},
        subjects=[("contract", contract.id), ("deal", contract.deal_id)],
    )
    return contract


def add_payment(
    *,
    deal_id: str,
    amount: int,
    contract_id: str = "",
    due_at: str = "",
    status: str = "planned",
    milestone_label: str = "",
    notes: str = "",
    actor_key: str = "",
) -> Optional[Payment]:
    deal = store.get_deal(deal_id)
    if deal is None:
        return None
    pay = store.create_payment(
        deal_id=deal.id,
        amount=amount,
        contract_id=contract_id,
        due_at=due_at,
        status=status,
        milestone_label=milestone_label,
        notes=notes,
    )
    if pay is None:
        return None
    record_closing_event(
        action="closing_payment_added",
        actor_key=actor_key or deal.partner_phone,
        entity_type="payment",
        entity_id=pay.id,
        land_code=deal.land_code,
        summary=f"Payment milestone {pay.amount}",
        payload={"deal_id": deal.id, "amount": pay.amount, "label": pay.milestone_label},
        subjects=[("payment", pay.id), ("deal", deal.id)],
    )
    return pay


def mark_payment_paid(
    payment_id: str,
    *,
    actor_key: str = "",
) -> Optional[Payment]:
    pay = store.update_payment_status(payment_id, "paid")
    if pay is None:
        return None
    deal = store.get_deal(pay.deal_id)
    record_closing_event(
        action="closing_payment_paid",
        actor_key=actor_key or (deal.partner_phone if deal else ""),
        entity_type="payment",
        entity_id=pay.id,
        land_code=deal.land_code if deal else "",
        summary="Payment marked paid",
        payload={"deal_id": pay.deal_id, "amount": pay.amount},
        subjects=[("payment", pay.id), ("deal", pay.deal_id)],
    )
    return pay


def open_settlement(
    *,
    deal_id: str,
    parties: list[dict[str, Any]] | None = None,
    withdrawal_id: str = "",
    total_amount: int = 0,
    notes: str = "",
    actor_key: str = "",
) -> Optional[Settlement]:
    deal = store.get_deal(deal_id)
    if deal is None:
        return None
    settlement = store.create_settlement(
        deal_id=deal.id,
        parties=parties,
        withdrawal_id=withdrawal_id,
        total_amount=total_amount,
        notes=notes,
    )
    if settlement is None:
        return None
    if deal.status not in ("closed", "cancelled"):
        store.update_deal_status(deal.id, "settling")
    record_closing_event(
        action="closing_settlement_opened",
        actor_key=actor_key or deal.partner_phone,
        entity_type="settlement",
        entity_id=settlement.id,
        land_code=deal.land_code,
        summary=f"Settlement {settlement.total_amount}",
        payload={
            "deal_id": deal.id,
            "withdrawal_id": settlement.withdrawal_id,
            "total_amount": settlement.total_amount,
        },
        subjects=[("settlement", settlement.id), ("deal", deal.id)],
    )
    return settlement


def list_partner_deals(partner_phone: str, *, limit: int = 200) -> List[Deal]:
    return store.list_deals(partner_phone=partner_phone, limit=limit)


def get_deal(deal_id: str) -> Optional[Deal]:
    return store.get_deal(deal_id)


def list_deal_contracts(deal_id: str) -> List[Contract]:
    return store.list_contracts(deal_id=deal_id)


def list_deal_payments(deal_id: str) -> List[Payment]:
    return store.list_payments(deal_id=deal_id)


def list_deal_settlements(deal_id: str) -> List[Settlement]:
    return store.list_settlements(deal_id=deal_id)


def get_contract(contract_id: str) -> Optional[Contract]:
    return store.get_contract(contract_id)


def get_payment(payment_id: str) -> Optional[Payment]:
    return store.get_payment(payment_id)
