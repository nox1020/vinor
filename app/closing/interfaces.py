# -*- coding: utf-8 -*-
"""Phase 4 Closing entities — Deal, Contract, Payment, Settlement."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List


@dataclass
class Deal:
    id: str
    land_code: str = ""
    partner_phone: str = ""
    buyer_phone: str = ""
    assignment_status: str = ""  # mirror only: in_transaction | sold | …
    commission_id: str = ""
    reservation_id: str = ""
    offer_id: str = ""
    sale_amount: int = 0
    status: str = "draft"  # draft|in_transaction|contracted|settling|closed|cancelled
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Deal":
        d = d if isinstance(d, dict) else {}
        try:
            sale_amount = int(d.get("sale_amount") or 0)
        except (TypeError, ValueError):
            sale_amount = 0
        return cls(
            id=str(d.get("id") or ""),
            land_code=str(d.get("land_code") or "").strip(),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            buyer_phone=str(d.get("buyer_phone") or "").strip(),
            assignment_status=str(d.get("assignment_status") or "").strip(),
            commission_id=str(d.get("commission_id") or "").strip(),
            reservation_id=str(d.get("reservation_id") or "").strip(),
            offer_id=str(d.get("offer_id") or "").strip(),
            sale_amount=max(0, sale_amount),
            status=str(d.get("status") or "draft").strip() or "draft",
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Contract:
    id: str
    deal_id: str = ""
    title: str = ""
    document_status: str = "draft"  # draft|sent|signed|void
    document_ref: str = ""
    signed_at: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Contract":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            deal_id=str(d.get("deal_id") or "").strip(),
            title=str(d.get("title") or "").strip(),
            document_status=str(d.get("document_status") or "draft").strip() or "draft",
            document_ref=str(d.get("document_ref") or "").strip(),
            signed_at=str(d.get("signed_at") or ""),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Payment:
    id: str
    deal_id: str = ""
    contract_id: str = ""
    amount: int = 0
    due_at: str = ""
    status: str = "planned"  # planned|due|paid|waived|cancelled
    milestone_label: str = ""
    paid_at: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Payment":
        d = d if isinstance(d, dict) else {}
        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        return cls(
            id=str(d.get("id") or ""),
            deal_id=str(d.get("deal_id") or "").strip(),
            contract_id=str(d.get("contract_id") or "").strip(),
            amount=max(0, amount),
            due_at=str(d.get("due_at") or ""),
            status=str(d.get("status") or "planned").strip() or "planned",
            milestone_label=str(d.get("milestone_label") or "").strip(),
            paid_at=str(d.get("paid_at") or ""),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class SettlementParty:
    role: str = ""  # partner | owner | platform | buyer
    amount: int = 0
    phone: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SettlementParty":
        d = d if isinstance(d, dict) else {}
        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        return cls(
            role=str(d.get("role") or "").strip(),
            amount=max(0, amount),
            phone=str(d.get("phone") or "").strip(),
            label=str(d.get("label") or "").strip(),
        )


@dataclass
class Settlement:
    id: str
    deal_id: str = ""
    parties: List[SettlementParty] = field(default_factory=list)
    withdrawal_id: str = ""  # optional link to existing partner withdrawal
    status: str = "open"  # open|partial|settled|cancelled
    total_amount: int = 0
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Settlement":
        d = d if isinstance(d, dict) else {}
        parties_raw = d.get("parties") if isinstance(d.get("parties"), list) else []
        parties = [SettlementParty.from_dict(p) for p in parties_raw if isinstance(p, dict)]
        try:
            total_amount = int(d.get("total_amount") or 0)
        except (TypeError, ValueError):
            total_amount = 0
        if total_amount <= 0 and parties:
            total_amount = sum(p.amount for p in parties)
        return cls(
            id=str(d.get("id") or ""),
            deal_id=str(d.get("deal_id") or "").strip(),
            parties=parties,
            withdrawal_id=str(d.get("withdrawal_id") or "").strip(),
            status=str(d.get("status") or "open").strip() or "open",
            total_amount=max(0, total_amount),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )
