# -*- coding: utf-8 -*-
"""Phase 0 Foundation entities — Activity, Timeline, Commit contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Activity:
    """Append-only activity event (immutable once written)."""

    id: str
    created_at: str
    actor_key: str = ""
    actor_role: str = ""
    action: str = ""
    entity_type: str = ""
    entity_id: str = ""
    land_code: str = ""
    workflow_id: str = ""
    object_type: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "foundation"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Activity":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            created_at=str(d.get("created_at") or ""),
            actor_key=str(d.get("actor_key") or ""),
            actor_role=str(d.get("actor_role") or ""),
            action=str(d.get("action") or ""),
            entity_type=str(d.get("entity_type") or ""),
            entity_id=str(d.get("entity_id") or ""),
            land_code=str(d.get("land_code") or ""),
            workflow_id=str(d.get("workflow_id") or ""),
            object_type=str(d.get("object_type") or ""),
            summary=str(d.get("summary") or ""),
            payload=dict(d.get("payload") or {}) if isinstance(d.get("payload"), dict) else {},
            source=str(d.get("source") or "foundation"),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class TimelineEntry:
    """Indexed timeline row linking a subject to an activity (append-only)."""

    id: str
    created_at: str
    subject_type: str = ""
    subject_id: str = ""
    activity_id: str = ""
    action: str = ""
    summary: str = ""
    land_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "TimelineEntry":
        d = d if isinstance(d, dict) else {}
        return cls(
            id=str(d.get("id") or ""),
            created_at=str(d.get("created_at") or ""),
            subject_type=str(d.get("subject_type") or ""),
            subject_id=str(d.get("subject_id") or ""),
            activity_id=str(d.get("activity_id") or ""),
            action=str(d.get("action") or ""),
            summary=str(d.get("summary") or ""),
            land_code=str(d.get("land_code") or ""),
            metadata=dict(d.get("metadata") or {}) if isinstance(d.get("metadata"), dict) else {},
        )


@dataclass
class CommitPlan:
    """What the Workflow→Storage adapter would do (Phase 0: plan only unless persist ON)."""

    object_type: str = ""
    workflow_id: str = ""
    target_store: str = ""
    action: str = "shadow"
    fields: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommitResult:
    """Result of a workflow commit attempt — never raises into callers."""

    ok: bool = True
    committed: bool = False
    shadowed: bool = True
    persisted: bool = False
    activity_id: str = ""
    timeline_ids: list[str] = field(default_factory=list)
    plan: CommitPlan | None = None
    reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.plan is not None:
            d["plan"] = self.plan.to_dict()
        return d
