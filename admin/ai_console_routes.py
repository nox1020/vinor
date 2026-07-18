# -*- coding: utf-8 -*-
"""AI Mission Control — additive routes under /admin/ai-console/*."""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for

from .blueprint import admin_bp
from .routes import login_required


def _ai_console_gate(permission: str = "admin.ai.read"):
    try:
        from app.ai_console.config import ai_console_ui_enabled

        if not ai_console_ui_enabled():
            abort(404)
    except Exception:
        abort(404)
    try:
        from app.hardening.permissions import has_permission

        if not has_permission(permission):
            flash("دسترسی AI Mission Control ندارید.", "error")
            return redirect(url_for("admin.dashboard"))
    except Exception:
        pass
    return None


def _nav_ctx(active: str) -> dict:
    return {"ai_console_active": active, "ai_console_nav": True}


@admin_bp.route("/ai-console", endpoint="ai_console_dashboard")
@login_required
def ai_console_dashboard():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console.service import dashboard_snapshot

    snap = dashboard_snapshot()
    return render_template(
        "admin/ai_console/dashboard.html",
        snap=snap,
        **_nav_ctx("dashboard"),
    )


@admin_bp.route("/ai-console/monitor", endpoint="ai_console_monitor")
@login_required
def ai_console_monitor():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers

    # Poll-based monitor from recent token/eval rows (no websocket yet)
    tokens = readers.list_token_rows(limit=80)
    evals = readers.list_evaluation_rows(limit=40)
    events = []
    for row in tokens:
        events.append(
            {
                "ts": str(row.get("ts") or row.get("created_at") or ""),
                "source": "tokens",
                "audience": str(row.get("audience") or ""),
                "latency_ms": row.get("latency_ms") or row.get("duration_ms") or "",
                "status": "error" if row.get("error") or row.get("ok") is False else "ok",
                "summary": str(row.get("model") or row.get("route") or "token")[:80],
            }
        )
    for row in evals:
        events.append(
            {
                "ts": str(row.get("ts") or row.get("created_at") or ""),
                "source": "eval",
                "audience": str(row.get("audience") or ""),
                "latency_ms": row.get("latency_ms") or "",
                "status": "error" if row.get("ok") is False else "ok",
                "summary": str(row.get("summary") or row.get("intent") or "eval")[:80],
            }
        )
    events.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    return render_template(
        "admin/ai_console/monitor.html",
        events=events[:100],
        **_nav_ctx("monitor"),
    )


@admin_bp.route("/ai-console/conversations", endpoint="ai_console_conversations")
@login_required
def ai_console_conversations():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers

    audience = (request.args.get("audience") or "").strip()
    q = (request.args.get("q") or "").strip()
    items = readers.list_conversation_index(limit=100, audience=audience, q=q)
    detail = None
    aud = (request.args.get("aud") or "").strip()
    uk = (request.args.get("user") or "").strip()
    tid = (request.args.get("thread") or "").strip()
    if aud and uk:
        denied_d = _ai_console_gate("admin.ai.debug")
        if denied_d is None:
            detail = readers.get_conversation(audience=aud, user_key=uk, thread_id=tid)
    return render_template(
        "admin/ai_console/conversations.html",
        items=items,
        detail=detail,
        audience=audience,
        q=q,
        **_nav_ctx("conversations"),
    )


@admin_bp.route("/ai-console/workflows", endpoint="ai_console_workflows")
@login_required
def ai_console_workflows():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import catalog, readers

    return render_template(
        "admin/ai_console/workflows.html",
        definitions=catalog.list_workflow_definitions(),
        sessions=readers.list_workflow_sessions(limit=100),
        **_nav_ctx("workflows"),
    )


@admin_bp.route("/ai-console/agents", endpoint="ai_console_agents")
@login_required
def ai_console_agents():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import catalog

    return render_template(
        "admin/ai_console/agents.html",
        agents=catalog.list_agents(),
        **_nav_ctx("agents"),
    )


@admin_bp.route("/ai-console/tools", endpoint="ai_console_tools", methods=["GET", "POST"])
@login_required
def ai_console_tools():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import catalog, readers
    from app.ai_console.config import ai_console_mutate_enabled

    if request.method == "POST":
        try:
            from app.hardening.permissions import PERM_AI_TOOLS, has_permission

            if not has_permission(PERM_AI_TOOLS) or not ai_console_mutate_enabled():
                flash("مجوز expire کردن pending را ندارید.", "error")
                return redirect(url_for("admin.ai_console_tools"))
        except Exception:
            flash("مجوز کافی نیست.", "error")
            return redirect(url_for("admin.ai_console_tools"))
        token = (request.form.get("token") or "").strip()
        if token and readers.expire_pending_token(token):
            try:
                from app.hardening.audit import record_admin_audit

                record_admin_audit(
                    action="ai_pending_expire",
                    entity_type="ai_pending",
                    entity_id=token[:16],
                    summary="Expired AI pending confirm",
                )
            except Exception:
                pass
            flash("Pending منقضی/حذف شد.", "success")
        else:
            flash("Pending یافت نشد.", "warning")
        return redirect(url_for("admin.ai_console_tools", tab="pending"))

    tab = (request.args.get("tab") or "catalog").strip()
    return render_template(
        "admin/ai_console/tools.html",
        tools=catalog.list_tools(),
        pending=readers.list_pending_confirms(limit=100),
        tab=tab,
        can_mutate=ai_console_mutate_enabled(),
        **_nav_ctx("tools"),
    )


@admin_bp.route("/ai-console/prompts", endpoint="ai_console_prompts")
@login_required
def ai_console_prompts():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import catalog

    return render_template(
        "admin/ai_console/prompts.html",
        prompts=catalog.list_prompts(),
        **_nav_ctx("prompts"),
    )


@admin_bp.route("/ai-console/memory", endpoint="ai_console_memory")
@login_required
def ai_console_memory():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers

    users = readers.list_memory_users(limit=100)
    detail = None
    uk = (request.args.get("user") or "").strip()
    if uk:
        detail = readers.get_memory_detail(uk)
    return render_template(
        "admin/ai_console/memory.html",
        users=users,
        detail=detail,
        **_nav_ctx("memory"),
    )


@admin_bp.route("/ai-console/flags", endpoint="ai_console_flags")
@login_required
def ai_console_flags():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import catalog

    flags = catalog.list_ai_flags()
    groups: dict = {}
    for f in flags:
        groups.setdefault(f.get("group") or "other", []).append(f)
    return render_template(
        "admin/ai_console/flags.html",
        groups=groups,
        **_nav_ctx("flags"),
    )


@admin_bp.route("/ai-console/analytics", endpoint="ai_console_analytics")
@login_required
def ai_console_analytics():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers
    from app.ai_console.service import dashboard_snapshot

    snap = dashboard_snapshot()
    return render_template(
        "admin/ai_console/analytics.html",
        snap=snap,
        tokens=readers.list_token_rows(limit=50),
        evals=readers.list_evaluation_rows(limit=50),
        **_nav_ctx("analytics"),
    )


@admin_bp.route("/ai-console/errors", endpoint="ai_console_errors")
@login_required
def ai_console_errors():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers

    return render_template(
        "admin/ai_console/errors.html",
        errors=readers.extract_errors_from_logs(limit=80),
        **_nav_ctx("errors"),
    )


@admin_bp.route("/ai-console/timeline", endpoint="ai_console_timeline")
@login_required
def ai_console_timeline():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    phone = (request.args.get("phone") or "").strip()
    land = (request.args.get("land_code") or "").strip()
    events = []
    if phone or land:
        try:
            from app.integration.service import journey_as_dicts

            events = journey_as_dicts(partner_phone=phone, land_code=land, limit=100)
        except Exception:
            events = []
    return render_template(
        "admin/ai_console/timeline.html",
        events=events,
        phone=phone,
        land_code=land,
        **_nav_ctx("timeline"),
    )


@admin_bp.route("/ai-console/audit", endpoint="ai_console_audit")
@login_required
def ai_console_audit():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    rows = []
    try:
        from app.hardening.service import list_admin_audit

        rows = [
            r
            for r in list_admin_audit(limit=150)
            if str(r.get("action") or "").startswith("ai_")
            or str(r.get("entity_type") or "").startswith("ai")
        ]
    except Exception:
        rows = []
    return render_template(
        "admin/ai_console/audit.html",
        events=rows,
        **_nav_ctx("audit"),
    )


@admin_bp.route("/ai-console/settings", endpoint="ai_console_settings")
@login_required
def ai_console_settings():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    runtime = {}
    try:
        from app.ai import runtime_settings

        if hasattr(runtime_settings, "load_ai_runtime_settings"):
            runtime = runtime_settings.load_ai_runtime_settings() or {}
        elif hasattr(runtime_settings, "get_ai_settings"):
            runtime = runtime_settings.get_ai_settings() or {}
    except Exception:
        runtime = {}
    from app.ai_console.service import console_status

    return render_template(
        "admin/ai_console/settings.html",
        runtime=runtime if isinstance(runtime, dict) else {},
        status=console_status(),
        escalations_url=url_for("admin.ai_questions"),
        **_nav_ctx("settings"),
    )
