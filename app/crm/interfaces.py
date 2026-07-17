# -*- coding: utf-8 -*-
"""Phase 1 CRM entities — Lead, Contact, CallLog, FollowUp, Task."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Contact:
    id: str
    partner_phone: str = ""
    customer_phone: str = ""
    first_name: str = ""
    last_name: str = ""
    display_name: str = ""
    source: str = "manual"  # visit | manual | lead
    visit_ids: list[str] = field(default_factory=list)
    lead_id: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Contact":
        d = d if isinstance(d, dict) else {}
        visit_ids = d.get("visit_ids") or []
        if not isinstance(visit_ids, list):
            visit_ids = []
        return cls(
            id=str(d.get("id") or ""),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            customer_phone=str(d.get("customer_phone") or "").strip(),
            first_name=str(d.get("first_name") or "").strip(),
            last_name=str(d.get("last_name") or "").strip(),
            display_name=str(d.get("display_name") or "").strip(),
            source=str(d.get("source") or "manual").strip() or "manual",
            visit_ids=[str(x) for x in visit_ids if str(x).strip()],
            lead_id=str(d.get("lead_id") or "").strip(),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Lead:
    id: str
    partner_phone: str = ""
    customer_phone: str = ""
    first_name: str = ""
    last_name: str = ""
    display_name: str = ""
    status: str = "open"  # open | converted | lost
    contact_id: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Lead":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            customer_phone=str(d.get("customer_phone") or "").strip(),
            first_name=str(d.get("first_name") or "").strip(),
            last_name=str(d.get("last_name") or "").strip(),
            display_name=str(d.get("display_name") or "").strip(),
            status=str(d.get("status") or "open").strip() or "open",
            contact_id=str(d.get("contact_id") or "").strip(),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class CallLog:
    id: str
    partner_phone: str = ""
    contact_id: str = ""
    lead_id: str = ""
    called_at: str = ""
    outcome: str = ""
    notes: str = ""
    to_number: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "CallLog":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            contact_id=str(d.get("contact_id") or "").strip(),
            lead_id=str(d.get("lead_id") or "").strip(),
            called_at=str(d.get("called_at") or ""),
            outcome=str(d.get("outcome") or "").strip(),
            notes=str(d.get("notes") or "").strip(),
            to_number=str(d.get("to_number") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class FollowUp:
    id: str
    partner_phone: str = ""
    contact_id: str = ""
    lead_id: str = ""
    due_at: str = ""
    status: str = "pending"  # pending | done | cancelled
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "FollowUp":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            contact_id=str(d.get("contact_id") or "").strip(),
            lead_id=str(d.get("lead_id") or "").strip(),
            due_at=str(d.get("due_at") or ""),
            status=str(d.get("status") or "pending").strip() or "pending",
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class Task:
    id: str
    partner_phone: str = ""
    contact_id: str = ""
    lead_id: str = ""
    title: str = ""
    status: str = "pending"  # pending | done | cancelled
    due_at: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Task":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            contact_id=str(d.get("contact_id") or "").strip(),
            lead_id=str(d.get("lead_id") or "").strip(),
            title=str(d.get("title") or "").strip(),
            status=str(d.get("status") or "pending").strip() or "pending",
            due_at=str(d.get("due_at") or ""),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )
