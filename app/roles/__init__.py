# -*- coding: utf-8 -*-
"""
Vinor Roles & Portals Layer (Phase 5)

Additive Buyer / Owner / Seller / Super Admin portals on top of existing OTP.
Conversation ROLE_* unchanged. Special Partner maps to Owner without migration.
All feature flags default ON — disable via env if needed.
"""

from app.roles.config import (
    roles_activity_hook_enabled,
    roles_buyer_portal_enabled,
    roles_enabled,
    roles_owner_portal_enabled,
    roles_seller_portal_enabled,
    roles_super_admin_enabled,
    roles_ui_enabled,
)
from app.roles.interfaces import (
    PORTAL_BUYER,
    PORTAL_OWNER,
    PORTAL_SELLER,
    PORTAL_SUPER_ADMIN,
)
from app.roles.activity_hook import record_roles_event
from app.roles.service import (
    SESSION_PORTAL_ROLES_KEY,
    assign_roles,
    clear_portal_roles_cache,
    is_super_admin,
    refresh_session_portal_roles,
    require_portal_role,
    require_super_admin,
    resolve_portals,
    roles_status,
)

__all__ = [
    "roles_enabled",
    "roles_ui_enabled",
    "roles_buyer_portal_enabled",
    "roles_owner_portal_enabled",
    "roles_seller_portal_enabled",
    "roles_super_admin_enabled",
    "roles_activity_hook_enabled",
    "PORTAL_BUYER",
    "PORTAL_OWNER",
    "PORTAL_SELLER",
    "PORTAL_SUPER_ADMIN",
    "SESSION_PORTAL_ROLES_KEY",
    "roles_status",
    "resolve_portals",
    "assign_roles",
    "refresh_session_portal_roles",
    "clear_portal_roles_cache",
    "require_portal_role",
    "require_super_admin",
    "is_super_admin",
    "record_roles_event",
]
