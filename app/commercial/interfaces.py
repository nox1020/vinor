# -*- coding: utf-8 -*-
"""Phase 3 Commercial entities — Negotiation, Offer, CounterOffer, Reservation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Negotiation:
    id: str
    land_code: str = ""
    partner_phone: str = ""
    buyer_phone: str = ""
    visit_request_id: str = ""
    contact_id: str = ""
    status: str = "open"  # open | accepted | rejected | expired | cancelled
    source: str = "manual"  # visit | manual | ai | special
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Negotiation":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            land_code=str(d.get("land_code") or "").strip(),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            buyer_phone=str(d.get("buyer_phone") or "").strip(),
            visit_request_id=str(d.get("visit_request_id") or "").strip(),
            contact_id=str(d.get("contact_id") or "").strip(),
            status=str(d.get("status") or "open").strip() or "open",
            source=str(d.get("source") or "manual").strip() or "manual",
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Offer:
    id: str
    negotiation_id: str = ""
    amount: int = 0
    currency: str = "IRR"
    terms: str = ""
    proposed_by: str = "partner"  # partner | buyer | special | ai
    status: str = "pending"  # pending | countered | accepted | rejected | withdrawn | expired
    land_code: str = ""
    partner_phone: str = ""
    buyer_phone: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Offer":
        d = d if isinstance(d, dict) else {}
        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        return cls(
            id=str(d.get("id") or ""),
            negotiation_id=str(d.get("negotiation_id") or "").strip(),
            amount=max(0, amount),
            currency=str(d.get("currency") or "IRR").strip() or "IRR",
            terms=str(d.get("terms") or "").strip(),
            proposed_by=str(d.get("proposed_by") or "partner").strip() or "partner",
            status=str(d.get("status") or "pending").strip() or "pending",
            land_code=str(d.get("land_code") or "").strip(),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            buyer_phone=str(d.get("buyer_phone") or "").strip(),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class CounterOffer:
    id: str
    offer_id: str = ""
    negotiation_id: str = ""
    amount: int = 0
    terms: str = ""
    proposed_by: str = "buyer"
    status: str = "pending"  # pending | accepted | rejected | withdrawn | expired
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "CounterOffer":
        d = d if isinstance(d, dict) else {}
        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        return cls(
            id=str(d.get("id") or ""),
            offer_id=str(d.get("offer_id") or "").strip(),
            negotiation_id=str(d.get("negotiation_id") or "").strip(),
            amount=max(0, amount),
            terms=str(d.get("terms") or "").strip(),
            proposed_by=str(d.get("proposed_by") or "buyer").strip() or "buyer",
            status=str(d.get("status") or "pending").strip() or "pending",
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Reservation:
    id: str
    negotiation_id: str = ""
    offer_id: str = ""
    land_code: str = ""
    buyer_phone: str = ""
    partner_phone: str = ""
    status: str = "held"  # held | expired | released | converted
    expires_at: str = ""
    hold_note: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Reservation":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            negotiation_id=str(d.get("negotiation_id") or "").strip(),
            offer_id=str(d.get("offer_id") or "").strip(),
            land_code=str(d.get("land_code") or "").strip(),
            buyer_phone=str(d.get("buyer_phone") or "").strip(),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            status=str(d.get("status") or "held").strip() or "held",
            expires_at=str(d.get("expires_at") or ""),
            hold_note=str(d.get("hold_note") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )
