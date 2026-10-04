# -*- coding: utf-8 -*-
"""Public Roles & Portals service."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, List, Optional, TypeVar

from app.roles import store
from app.roles.config import (
    roles_activity_hook_enabled,
    roles_buyer_portal_enabled,
    roles_enabled,
    roles_owner_portal_enabled,
    roles_seller_portal_enabled,
    roles_super_admin_enabled,
    roles_ui_enabled,
)
from app.roles.identity_bridge import map_roles_from_identity
from app.roles.interfaces import (
    ALL_PORTAL_ROLES,
    PORTAL_BUYER,
    PORTAL_OWNER,
    PORTAL_SELLER,
    PORTAL_SUPER_ADMIN,
    ResolvedPortals,
    RoleAssignment,
)

F = TypeVar("F", bound=Callable[..., Any])

SESSION_PORTAL_ROLES_KEY = "VINOR_PORTAL_ROLES"


def roles_status() -> dict[str, Any]:
    return {
        "roles_enabled": roles_enabled(),
        "roles_ui_enabled": roles_ui_enabled(),
        "roles_buyer_portal_enabled": roles_buyer_portal_enabled(),
        "roles_owner_portal_enabled": roles_owner_portal_enabled(),
        "roles_seller_portal_enabled": roles_seller_portal_enabled(),
        "roles_super_admin_enabled": roles_super_admin_enabled(),
        "roles_activity_hook_enabled": roles_activity_hook_enabled(),
        "phase": 5,
    }


def resolve_portals(
    phone: str = "",
    *,
    session: Any = None,
    partner_profile: dict[str, Any] | None = None,
) -> ResolvedPortals:
    if not roles_enabled():
        return ResolvedPortals(phone=(phone or "").strip())
    mapped = map_roles_from_identity(
        phone=phone, session=session, partner_profile=partner_profile
    )
    explicit: list[str] = []
    try:
        assign = store.get_assignment(phone or "")
        if assign is not None:
            explicit = list(assign.roles)
    except Exception:
        explicit = []
    union: list[str] = []
    seen: set[str] = set()
    for r in list(mapped) + list(explicit):
        if r in ALL_PORTAL_ROLES and r not in seen:
            seen.add(r)
            union.append(r)
    return ResolvedPortals(
        phone=(phone or "").strip(),
        roles=union,
        mapped=list(mapped),
        explicit=list(explicit),
        is_buyer=PORTAL_BUYER in seen,
        is_owner=PORTAL_OWNER in seen,
        is_seller=PORTAL_SELLER in seen,
        is_super_admin=PORTAL_SUPER_ADMIN in seen,
    )


def assign_roles(
    phone: str,
    roles: list[str],
    *,
    notes: str = "",
) -> Optional[RoleAssignment]:
    assignment = store.upsert_assignment(
        phone=phone, roles=roles, notes=notes, source="explicit"
    )
    if assignment is not None:
        try:
            from app.roles.activity_hook import record_roles_event

            record_roles_event(
                action="roles_assigned",
                actor_key=assignment.phone,
                actor_role="admin",
                entity_type="role_assignment",
                entity_id=assignment.phone,
                summary=f"Roles: {', '.join(assignment.roles)}",
                payload={"roles": list(assignment.roles), "notes": notes},
                subjects=[("partner", assignment.phone)],
            )
        except Exception:
            pass
    return assignment


def cache_portal_roles_in_session(session: Any, resolved: ResolvedPortals) -> None:
    """Optional cache only — source of truth remains resolve_portals."""
    if session is None:
        return
    try:
        session[SESSION_PORTAL_ROLES_KEY] = list(resolved.roles)
        session.modified = True
    except Exception:
        pass


def clear_portal_roles_cache(session: Any) -> None:
    if session is None:
        return
    try:
        session.pop(SESSION_PORTAL_ROLES_KEY, None)
        session.modified = True
    except Exception:
        pass


def refresh_session_portal_roles(session: Any = None) -> ResolvedPortals:
    try:
        from flask import session as flask_session

        sess = session if session is not None else flask_session
    except Exception:
        sess = session
    phone = ""
    if sess is not None:
        try:
            phone = str(sess.get("user_phone") or "").strip()
        except Exception:
            phone = ""
    resolved = resolve_portals(phone, session=sess)
    cache_portal_roles_in_session(sess, resolved)
    return resolved


def portal_allowed(role: str, resolved: ResolvedPortals) -> bool:
    r = (role or "").strip()
    if r == PORTAL_BUYER:
        return roles_buyer_portal_enabled() and resolved.is_buyer
    if r == PORTAL_OWNER:
        return roles_owner_portal_enabled() and resolved.is_owner
    if r == PORTAL_SELLER:
        return roles_seller_portal_enabled() and resolved.is_seller
    if r == PORTAL_SUPER_ADMIN:
        return roles_super_admin_enabled() and resolved.is_super_admin
    return False


def require_portal_role(role: str) -> Callable[[F], F]:
    """Decorator for portal routes — 404 when UI/role not available."""

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            from flask import abort, redirect, session, url_for

            if not roles_ui_enabled():
                abort(404)
            phone = str(session.get("user_phone") or "").strip()
            if role != PORTAL_SUPER_ADMIN and not phone:
                nxt = "/"
                try:
                    from app.utils.safe_redirect import safe_request_target

                    nxt = safe_request_target()
                except Exception:
                    nxt = "/"
                return redirect(url_for("express_partner.login", next=nxt))
            resolved = resolve_portals(phone, session=session)
            if not portal_allowed(role, resolved):
                abort(404)
            return view(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def is_super_admin(*, session: Any = None) -> bool:
    if not roles_super_admin_enabled():
        return False
    try:
        from flask import session as flask_session

        sess = session if session is not None else flask_session
    except Exception:
        sess = session
    if sess is None or not sess.get("logged_in"):
        return False
    resolved = resolve_portals("", session=sess)
    return resolved.is_super_admin


def require_super_admin(view: F) -> F:
    """Admin-only gate on top of existing login_required — does not replace it."""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        from flask import abort, flash, redirect, url_for

        if not is_super_admin():
            try:
                flash("دسترسی Super Admin لازم است.", "error")
            except Exception:
                pass
            try:
                return redirect(url_for("admin.dashboard"))
            except Exception:
                abort(403)
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def list_assignments(limit: int = 500) -> List[RoleAssignment]:
    return store.list_assignments(limit=limit)
