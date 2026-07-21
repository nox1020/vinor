# -*- coding: utf-8 -*-
"""Vinor Control — sidebar badges/notifications (ops chat shell)."""
from __future__ import annotations

from flask import g, redirect, session, url_for

from .blueprint import admin_bp
from .routes import login_required


@admin_bp.context_processor
def inject_control_chrome():
    """Badges + notification preview for admin ops shell (cached per request)."""
    if not session.get("logged_in"):
        return {
            "control_badges": {},
            "control_notifs": [],
        }
    cached = getattr(g, "_vinor_control_chrome", None)
    if isinstance(cached, dict):
        return cached

    badges = {"pending": 0, "visits": 0, "errors": 0, "alerts": 0}
    notifs = []
    try:
        from app.ai_console.service import dashboard_snapshot

        snap = dashboard_snapshot() or {}
        k = snap.get("kpis") or {}
        badges["pending"] = int(k.get("pending_confirms") or 0)
        badges["errors"] = int(k.get("errors_sample") or 0)
        for p in (snap.get("pending_preview") or [])[:4]:
            notifs.append(
                {
                    "kind": "confirm",
                    "tone": "orbit",
                    "title": str(p.get("tool") or p.get("name") or p.get("action_type") or "confirm"),
                    "meta": str(p.get("token") or p.get("id") or "")[:48],
                    "ts": str(p.get("created_at") or "")[:16],
                    "url": url_for("admin.ai_console_tools"),
                }
            )
        for e in (snap.get("errors_preview") or [])[:3]:
            notifs.append(
                {
                    "kind": "error",
                    "tone": "danger",
                    "title": str(e.get("summary") or e.get("message") or "error")[:80],
                    "meta": "AI",
                    "ts": "",
                    "url": url_for("admin.ai_console_errors"),
                }
            )
    except Exception:
        pass
    try:
        from app.utils.storage import load_express_visit_requests

        visits = load_express_visit_requests() or []
        pending_v = [
            v
            for v in visits
            if isinstance(v, dict)
            and str(v.get("status") or "").strip() in ("pending", "done_pending")
        ]
        badges["visits"] = len(pending_v)
        for v in pending_v[:2]:
            notifs.append(
                {
                    "kind": "visit",
                    "tone": "warn",
                    "title": str(v.get("partner_name") or v.get("partner_phone") or "visit"),
                    "meta": str(v.get("land_title") or v.get("land_code") or "visit"),
                    "ts": str(v.get("visit_date") or v.get("created_at") or "")[:16],
                    "url": url_for("admin.express_visit_requests"),
                }
            )
    except Exception:
        pass
    badges["alerts"] = badges["pending"] + badges["errors"] + badges["visits"]
    out = {"control_badges": badges, "control_notifs": notifs[:10]}
    g._vinor_control_chrome = out
    return out


def _legacy_control_redirect():
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/control/market", endpoint="control_market")
@admin_bp.route("/control/crm", endpoint="control_crm")
@admin_bp.route("/control/people", endpoint="control_people")
@admin_bp.route("/control/analytics", endpoint="control_analytics")
@admin_bp.route("/control/observe", endpoint="control_observe")
@admin_bp.route("/control/reasoning", endpoint="control_reasoning")
@admin_bp.route("/control/evaluations", endpoint="control_evaluations")
@admin_bp.route("/control/more", endpoint="control_more")
@login_required
def control_legacy_hubs():
    """Mission Control hubs removed — redirect to ops chat home."""
    return _legacy_control_redirect()
