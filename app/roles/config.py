# -*- coding: utf-8 -*-
"""Phase 5 Roles & Portals feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def roles_enabled() -> bool:
    return _env_bool("VINOR_ROLES_ENABLED", "1")


def roles_ui_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_UI_ENABLED", "1")


def roles_buyer_portal_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_BUYER_PORTAL_ENABLED", "1")


def roles_owner_portal_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_OWNER_PORTAL_ENABLED", "1")


def roles_seller_portal_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_SELLER_PORTAL_ENABLED", "1")


def roles_super_admin_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_SUPER_ADMIN_ENABLED", "1")


def roles_activity_hook_enabled() -> bool:
    if not roles_enabled():
        return False
    return _env_bool("VINOR_ROLES_ACTIVITY_HOOK_ENABLED", "1")


def super_admin_phones() -> list[str]:
    """CSV allowlist from VINOR_SUPER_ADMIN_PHONES. Empty → any logged-in admin is super_admin."""
    raw = (os.environ.get("VINOR_SUPER_ADMIN_PHONES") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out
