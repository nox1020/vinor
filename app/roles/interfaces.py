# -*- coding: utf-8 -*-
"""Phase 5 portal role entities — parallel to conversation ROLE_* (unchanged)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List

PORTAL_BUYER = "buyer"
PORTAL_OWNER = "owner"
PORTAL_SELLER = "seller"
PORTAL_SUPER_ADMIN = "super_admin"

ALL_PORTAL_ROLES = frozenset(
    {PORTAL_BUYER, PORTAL_OWNER, PORTAL_SELLER, PORTAL_SUPER_ADMIN}
)


@dataclass
class RoleAssignment:
    id: str
    phone: str = ""
    roles: List[str] = field(default_factory=list)
    source: str = "explicit"  # explicit | mapped
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RoleAssignment":
        d = d if isinstance(d, dict) else {}
        roles_raw = d.get("roles") if isinstance(d.get("roles"), list) else []
        roles = [str(r).strip() for r in roles_raw if str(r).strip() in ALL_PORTAL_ROLES]
        return cls(
            id=str(d.get("id") or ""),
            phone=str(d.get("phone") or "").strip(),
            roles=roles,
            source=str(d.get("source") or "explicit").strip() or "explicit",
            notes=str(d.get("notes") or "").strip(),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class ResolvedPortals:
    phone: str = ""
    roles: List[str] = field(default_factory=list)
    mapped: List[str] = field(default_factory=list)
    explicit: List[str] = field(default_factory=list)
    is_buyer: bool = False
    is_owner: bool = False
    is_seller: bool = False
    is_super_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def has(self, role: str) -> bool:
        return (role or "").strip() in self.roles
