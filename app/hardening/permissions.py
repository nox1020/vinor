# -*- coding: utf-8 -*-
"""Fine-grained admin RBAC — additive on existing admin OTP session."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, FrozenSet, TypeVar

from app.hardening.config import hardening_rbac_enabled

F = TypeVar("F", bound=Callable[..., Any])

PERM_DASHBOARD = "admin.dashboard"
PERM_PARTNERS = "admin.partners"
PERM_FINANCE = "admin.finance"
PERM_VISITS = "admin.visits"
PERM_LISTINGS = "admin.listings"
PERM_COMMS = "admin.comms"
PERM_AUDIT = "admin.audit"
PERM_SUPER = "admin.super"
PERM_AI_READ = "admin.ai.read"
PERM_AI_DEBUG = "admin.ai.debug"
PERM_AI_TOOLS = "admin.ai.tools"
PERM_AI_PROMPTS = "admin.ai.prompts"
PERM_AI_FLAGS = "admin.ai.flags"
PERM_AI_MEMORY = "admin.ai.memory"
PERM_AI_SETTINGS = "admin.ai.settings"

ALL_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        PERM_DASHBOARD,
        PERM_PARTNERS,
        PERM_FINANCE,
        PERM_VISITS,
        PERM_LISTINGS,
        PERM_COMMS,
        PERM_AUDIT,
        PERM_SUPER,
        PERM_AI_READ,
        PERM_AI_DEBUG,
        PERM_AI_TOOLS,
        PERM_AI_PROMPTS,
        PERM_AI_FLAGS,
        PERM_AI_MEMORY,
        PERM_AI_SETTINGS,
    }
)

# Logged-in admin gets ops + AI read/debug; mutate AI needs super (or explicit).
_BASE_ADMIN_PERMS: FrozenSet[str] = frozenset(
    p
    for p in ALL_PERMISSIONS
    if p
    not in (
        PERM_SUPER,
        PERM_AI_PROMPTS,
        PERM_AI_FLAGS,
        PERM_AI_MEMORY,
        PERM_AI_SETTINGS,
    )
)


def _session_logged_in(session: Any = None) -> bool:
    try:
        from flask import session as flask_session

        sess = session if session is not None else flask_session
    except Exception:
        sess = session
    if sess is None:
        return False
    try:
        return bool(sess.get("logged_in"))
    except Exception:
        return False


def list_permissions(*, session: Any = None) -> list[str]:
    """Return permission codes for current admin session."""
    if not _session_logged_in(session):
        return []
    if not hardening_rbac_enabled():
        # RBAC off → full access (legacy binary login).
        return sorted(ALL_PERMISSIONS)
    perms = set(_BASE_ADMIN_PERMS)
    try:
        from app.roles.service import is_super_admin

        if is_super_admin(session=session):
            perms.update(ALL_PERMISSIONS)
    except Exception:
        pass
    return sorted(perms)


def has_permission(permission: str, *, session: Any = None) -> bool:
    perm = (permission or "").strip()
    if not perm:
        return False
    if not hardening_rbac_enabled():
        return _session_logged_in(session)
    return perm in list_permissions(session=session)


def require_permission(permission: str) -> Callable[[F], F]:
    """Decorator for admin routes — 403 when permission missing (RBAC ON)."""

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            from flask import abort, flash, redirect, url_for

            if not hardening_rbac_enabled():
                return view(*args, **kwargs)
            if not has_permission(permission):
                try:
                    flash("دسترسی کافی برای این عملیات ندارید.", "error")
                except Exception:
                    pass
                try:
                    return redirect(url_for("admin.dashboard"))
                except Exception:
                    abort(403)
            return view(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
