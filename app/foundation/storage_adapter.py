# -*- coding: utf-8 -*-
"""
Adapter: Workflow Engine structured objects ↔ existing Vinor storage.

Phase 0 rules:
- Always can *plan* a commit (pure mapping, no side effects).
- Business JSON writes (visit/deal/apply/…) are never performed unless
  VINOR_WORKFLOW_COMMIT_PERSIST=1 — and even then Phase 0 keeps shadow-only
  to avoid duplicating the live HTTP/AI confirm paths.
"""
from __future__ import annotations

from typing import Any

from app.foundation.config import workflow_commit_persist_enabled
from app.foundation.interfaces import CommitPlan, CommitResult

# Known Workflow Engine object_type → logical existing store
_OBJECT_STORE_MAP = {
    "VisitRequest": "express_visit_requests",
    "DealRequest": "express_assignments+express_commissions",
    "PartnerApplication": "express_partner_applications",
    "PropertyRegistration": "lands",
    "PropertyEditing": "lands",
    "SupportTicket": "support_tickets",
    "OfferRequest": "commercial_offers",
    "VisitResultRequest": "visit_results",
    "FollowupRequest": "crm_followups",
    "ContractRequest": "closing_contracts",
}


def plan_from_structured_object(obj: dict[str, Any] | None) -> CommitPlan:
    """Map a Workflow Engine object to a CommitPlan (no IO)."""
    obj = obj if isinstance(obj, dict) else {}
    object_type = str(obj.get("type") or obj.get("object_type") or "").strip()
    workflow_id = str(obj.get("workflow_id") or "").strip()
    fields = dict(obj.get("fields") or {}) if isinstance(obj.get("fields"), dict) else {}
    target = _OBJECT_STORE_MAP.get(object_type, "")
    if not object_type:
        return CommitPlan(
            object_type="",
            workflow_id=workflow_id,
            target_store="",
            action="noop",
            fields=fields,
            notes="empty_object",
        )
    return CommitPlan(
        object_type=object_type,
        workflow_id=workflow_id,
        target_store=target or "unmapped",
        action="shadow",
        fields=fields,
        notes=(
            "phase0_shadow_only"
            if target
            else "unmapped_object_type"
        ),
    )


def execute_storage_commit(plan: CommitPlan) -> CommitResult:
    """
    Execute mapped storage write.

    Phase 0: never mutates visit/deal/partner/lands JSON.
    Returns shadowed result so callers can log Activity/Timeline safely.
    """
    if plan is None:
        return CommitResult(ok=True, shadowed=True, reason="no_plan")
    if plan.action == "noop" or not plan.object_type:
        return CommitResult(ok=True, shadowed=True, plan=plan, reason="noop")

    # Persist flag reserved for later phases — Phase 0 always shadows.
    if workflow_commit_persist_enabled():
        return CommitResult(
            ok=True,
            committed=False,
            shadowed=True,
            persisted=False,
            plan=plan,
            reason="phase0_persist_blocked",
            error="",
        )

    return CommitResult(
        ok=True,
        committed=False,
        shadowed=True,
        persisted=False,
        plan=plan,
        reason="phase0_shadow",
    )


def land_code_from_fields(fields: dict[str, Any] | None) -> str:
    fields = fields if isinstance(fields, dict) else {}
    for key in ("land_code", "code", "property_code"):
        val = str(fields.get(key) or "").strip()
        if val:
            return val
    return ""
