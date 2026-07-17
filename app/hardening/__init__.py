# -*- coding: utf-8 -*-
"""
Vinor Hardening Layer (Phase 7)

Admin audit, fine-grained RBAC, OS KPIs on BI, soft-cleanup registry.
Does not remove propose_deal / mark_in_transaction / commissions.
All feature flags default ON.
"""

from app.hardening.audit import audit_admin_action, record_admin_audit
from app.hardening.config import (
    hardening_audit_enabled,
    hardening_audit_required,
    hardening_enabled,
    hardening_os_kpis_enabled,
    hardening_rbac_enabled,
    hardening_soft_cleanup_enabled,
    hardening_ui_enabled,
)
from app.hardening.deprecate import (
    deprecate_registry,
    prefer_new_partner_nav_order,
    warn_deprecated_path,
)
from app.hardening.permissions import (
    PERM_AUDIT,
    PERM_COMMS,
    PERM_DASHBOARD,
    PERM_FINANCE,
    PERM_LISTINGS,
    PERM_PARTNERS,
    PERM_SUPER,
    PERM_VISITS,
    has_permission,
    list_permissions,
    require_permission,
)
from app.hardening.service import get_os_kpis, hardening_status, list_admin_audit

__all__ = [
    "hardening_enabled",
    "hardening_audit_enabled",
    "hardening_audit_required",
    "hardening_rbac_enabled",
    "hardening_os_kpis_enabled",
    "hardening_soft_cleanup_enabled",
    "hardening_ui_enabled",
    "record_admin_audit",
    "audit_admin_action",
    "has_permission",
    "list_permissions",
    "require_permission",
    "PERM_DASHBOARD",
    "PERM_PARTNERS",
    "PERM_FINANCE",
    "PERM_VISITS",
    "PERM_LISTINGS",
    "PERM_COMMS",
    "PERM_AUDIT",
    "PERM_SUPER",
    "hardening_status",
    "list_admin_audit",
    "get_os_kpis",
    "deprecate_registry",
    "warn_deprecated_path",
    "prefer_new_partner_nav_order",
]
