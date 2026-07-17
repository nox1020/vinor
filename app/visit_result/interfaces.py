# -*- coding: utf-8 -*-
"""Phase 2 Visit Result entity."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class VisitResult:
    id: str
    visit_request_id: str = ""
    partner_phone: str = ""
    land_code: str = ""
    outcome: str = ""  # interested | not_interested | follow_up | no_show
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    actor_key: str = ""
    source: str = "partner"  # partner | ai | admin | special
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "VisitResult":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            visit_request_id=str(d.get("visit_request_id") or "").strip(),
            partner_phone=str(d.get("partner_phone") or "").strip(),
            land_code=str(d.get("land_code") or "").strip(),
            outcome=str(d.get("outcome") or "").strip(),
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            actor_key=str(d.get("actor_key") or "").strip(),
            source=str(d.get("source") or "partner").strip() or "partner",
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )
