# -*- coding: utf-8 -*-
"""Vinor Control — presentation hubs (wrap existing backends, no API changes)."""
from __future__ import annotations

from flask import render_template, request, session, url_for

from .blueprint import admin_bp
from .routes import login_required


@admin_bp.context_processor
def inject_control_chrome():
    """Badges + notification preview for Vinor Control shell (cached per request)."""
    from flask import g

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


def _ai_gate():
    try:
        from app.ai_console.config import ai_console_ui_enabled

        if not ai_console_ui_enabled():
            return False
    except Exception:
        return False
    return True


@admin_bp.route("/control/market", endpoint="control_market")
@login_required
def control_market():
    """Market hub — links into existing ops endpoints."""
    return render_template(
        "admin/control/hub.html",
        hub_title_key="hub.market_title",
        hub_subtitle_key="hub.market_subtitle",
        page_title_key="hub.market_title",
        hub_sections=[
            {
                "id": "properties",
                "title_key": "hub.properties",
                "items": [
                    {"label_key": "hub.express_listings", "href": "admin.express_listings", "icon": "fa-building"},
                    {"label_key": "hub.add_listing", "href": "admin.add_express_listing", "icon": "fa-plus"},
                    {"label_key": "hub.lands", "href": "admin.lands", "icon": "fa-map"},
                    {"label_key": "hub.pending_lands", "href": "admin.pending_lands", "icon": "fa-clock"},
                ],
            },
            {
                "id": "visits",
                "title_key": "hub.visits",
                "items": [
                    {"label_key": "hub.visit_requests", "href": "admin.express_visit_requests", "icon": "fa-route"},
                ],
            },
            {
                "id": "deals",
                "title_key": "hub.deals_commissions",
                "items": [
                    {"label_key": "hub.commissions_deals", "href": "admin.express_commissions", "icon": "fa-handshake"},
                ],
            },
            {
                "id": "contracts",
                "title_key": "hub.contracts",
                "items": [
                    {
                        "label_key": "hub.closing_ai",
                        "href": "admin.ai_console_tools",
                        "icon": "fa-file-contract",
                        "note_key": "hub.closing_note",
                    },
                ],
            },
            {
                "id": "payments",
                "title_key": "hub.payments",
                "items": [
                    {
                        "label_key": "hub.payment_ai",
                        "href": "admin.ai_console_tools",
                        "icon": "fa-credit-card",
                        "note_key": "hub.payment_note",
                    },
                ],
            },
            {
                "id": "settlements",
                "title_key": "hub.settlements",
                "items": [
                    {
                        "label_key": "hub.settlement_tools",
                        "href": "admin.ai_console_tools",
                        "icon": "fa-scale-balanced",
                        "note_key": "hub.settlement_note",
                    },
                    {"label_key": "hub.withdrawals", "href": "admin.financial_withdrawals", "icon": "fa-money-bill-transfer"},
                ],
            },
        ],
    )


@admin_bp.route("/control/crm", endpoint="control_crm")
@login_required
def control_crm():
    return render_template(
        "admin/control/hub.html",
        hub_title_key="hub.crm_title",
        hub_subtitle_key="hub.crm_subtitle",
        page_title_key="hub.crm_title",
        hub_sections=[
            {
                "id": "crm",
                "title_key": "hub.crm_surfaces",
                "items": [
                    {"label_key": "hub.partners_contacts", "href": "admin.express_partners", "icon": "fa-users"},
                    {"label_key": "hub.partner_activity", "href": "admin.partners_activity", "icon": "fa-list-check"},
                    {"label_key": "hub.ai_escalations", "href": "admin.ai_questions", "icon": "fa-circle-question"},
                    {
                        "label_key": "hub.crm_ai_tools",
                        "href": "admin.ai_console_tools",
                        "icon": "fa-screwdriver-wrench",
                        "note_key": "hub.crm_ai_note",
                    },
                ],
            },
            {
                "id": "calls",
                "title_key": "hub.calls_followups",
                "items": [
                    {
                        "label_key": "hub.visit_call_workflow",
                        "href": "admin.express_visit_requests",
                        "icon": "fa-phone",
                        "note_key": "hub.visit_call_note",
                    },
                ],
            },
        ],
    )


@admin_bp.route("/control/people", endpoint="control_people")
@login_required
def control_people():
    role = (request.args.get("role") or "partners").strip().lower()
    title_keys = {
        "owner": "people.owners",
        "buyer": "people.buyers",
        "seller": "people.sellers",
        "mission": "people.missions",
        "partners": "people.partners",
    }
    return render_template(
        "admin/control/people.html",
        role=role,
        role_title_key=title_keys.get(role, "people.partners"),
        page_title_key=title_keys.get(role, "people.partners"),
    )


@admin_bp.route("/control/analytics", endpoint="control_analytics")
@login_required
def control_analytics():
    snap = {}
    os_kpis = {}
    try:
        from app.ai_console.service import dashboard_snapshot

        snap = dashboard_snapshot()
    except Exception:
        pass
    try:
        from app.hardening.config import hardening_os_kpis_enabled
        from app.hardening.service import get_os_kpis

        if hardening_os_kpis_enabled():
            os_kpis = get_os_kpis() or {}
    except Exception:
        pass
    return render_template(
        "admin/control/analytics.html",
        ai_snap=snap,
        os_kpis=os_kpis,
    )


@admin_bp.route("/control/observe", endpoint="control_observe")
@login_required
def control_observe():
    tokens = []
    evals = []
    errors = []
    if _ai_gate():
        try:
            from app.ai_console import readers

            tokens = readers.list_token_rows(limit=40)
            evals = readers.list_evaluation_rows(limit=40)
            errors = readers.extract_errors_from_logs(limit=20)
        except Exception:
            pass
    return render_template(
        "admin/control/observe.html",
        tokens=tokens,
        evals=evals,
        errors=errors,
    )


@admin_bp.route("/control/reasoning", endpoint="control_reasoning")
@login_required
def control_reasoning():
    rows = []
    if _ai_gate():
        try:
            from app.ai_console import readers

            for row in readers.list_evaluation_rows(limit=80):
                rows.append(
                    {
                        "ts": row.get("ts") or row.get("created_at") or "",
                        "intent": row.get("intent") or row.get("summary") or "—",
                        "audience": row.get("audience") or "",
                        "ok": row.get("ok") is not False and not row.get("error"),
                        "agents": row.get("agents") or row.get("agent_ids") or [],
                        "tools": row.get("tools") or row.get("tool_names") or [],
                        "gates": row.get("gates") or row.get("confirm") or "",
                    }
                )
        except Exception:
            pass
    return render_template("admin/control/reasoning.html", rows=rows)


@admin_bp.route("/control/evaluations", endpoint="control_evaluations")
@login_required
def control_evaluations():
    evals = []
    tokens = []
    if _ai_gate():
        try:
            from app.ai_console import readers

            evals = readers.list_evaluation_rows(limit=100)
            tokens = readers.list_token_rows(limit=100)
        except Exception:
            pass
    return render_template(
        "admin/control/evaluations.html",
        evals=evals,
        tokens=tokens,
    )


@admin_bp.route("/control/more", endpoint="control_more")
@login_required
def control_more():
    return render_template(
        "admin/control/hub.html",
        hub_title_key="hub.more_title",
        hub_subtitle_key="hub.more_subtitle",
        page_title_key="hub.more_title",
        hub_sections=[
            {
                "id": "more",
                "title_key": "hub.quick_links",
                "items": [
                    {"label_key": "nav.partners", "href": "admin.express_partners", "icon": "fa-users"},
                    {"label_key": "nav.crm_hub", "href": "admin.control_crm", "icon": "fa-address-book"},
                    {"label_key": "nav.analytics", "href": "admin.control_analytics", "icon": "fa-chart-line"},
                    {"label_key": "common.settings", "href": "admin.settings", "icon": "fa-gear"},
                    {"label_key": "nav.feature_flags", "href": "admin.ai_console_flags", "icon": "fa-flag"},
                    {"label_key": "nav.sms", "href": "admin.sms_colleagues", "icon": "fa-sms"},
                    {"label_key": "common.notifications", "href": "admin.notifications_colleagues", "icon": "fa-bell"},
                    {"label_key": "hub.super_admin", "href": "admin.super_admin_info", "icon": "fa-key"},
                ],
            },
        ],
    )
