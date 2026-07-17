# -*- coding: utf-8 -*-
"""Public Hardening service — status, audit list, OS KPIs."""
from __future__ import annotations

from typing import Any, List

from app.hardening.config import (
    hardening_audit_enabled,
    hardening_audit_required,
    hardening_enabled,
    hardening_os_kpis_enabled,
    hardening_rbac_enabled,
    hardening_soft_cleanup_enabled,
    hardening_ui_enabled,
)
from app.hardening.deprecate import deprecate_registry
from app.hardening.os_kpis import compute_os_kpis


def hardening_status() -> dict[str, Any]:
    return {
        "hardening_enabled": hardening_enabled(),
        "hardening_audit_enabled": hardening_audit_enabled(),
        "hardening_audit_required": hardening_audit_required(),
        "hardening_rbac_enabled": hardening_rbac_enabled(),
        "hardening_os_kpis_enabled": hardening_os_kpis_enabled(),
        "hardening_soft_cleanup_enabled": hardening_soft_cleanup_enabled(),
        "hardening_ui_enabled": hardening_ui_enabled(),
        "deprecate": deprecate_registry(),
        "phase": 7,
    }


def list_admin_audit(*, limit: int = 100) -> List[dict[str, Any]]:
    """Newest-first admin audit rows (source=admin or actor_role=admin)."""
    if not hardening_enabled() or not hardening_audit_enabled():
        return []
    try:
        from app.foundation.activity_store import list_activities

        rows = list_activities(limit=max(limit * 3, 100))
        out: List[dict[str, Any]] = []
        for a in rows:
            src = str(getattr(a, "source", "") or "").strip().lower()
            role = str(getattr(a, "actor_role", "") or "").strip().lower()
            if src != "admin" and role != "admin":
                continue
            out.append(a.to_dict() if hasattr(a, "to_dict") else dict(a))
            if len(out) >= max(1, int(limit or 100)):
                break
        return out
    except Exception:
        return []


def get_os_kpis() -> dict[str, Any]:
    return compute_os_kpis()
