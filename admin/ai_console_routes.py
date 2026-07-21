# -*- coding: utf-8 -*-
"""AI ops observe — monitor, flags, pending confirms, errors (AGENT_GOAL buried scope)."""
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
            flash("دسترسی AI observe ندارید.", "error")
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
    return redirect(url_for("admin.ai_console_monitor"))


@admin_bp.route("/ai-console/monitor", endpoint="ai_console_monitor")
@login_required
def ai_console_monitor():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers

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


# Legacy Mission Control pages → monitor
@admin_bp.route("/ai-console/conversations", endpoint="ai_console_conversations")
@admin_bp.route("/ai-console/workflows", endpoint="ai_console_workflows")
@admin_bp.route("/ai-console/agents", endpoint="ai_console_agents")
@admin_bp.route("/ai-console/prompts", endpoint="ai_console_prompts")
@admin_bp.route("/ai-console/memory", endpoint="ai_console_memory")
@admin_bp.route("/ai-console/analytics", endpoint="ai_console_analytics")
@admin_bp.route("/ai-console/timeline", endpoint="ai_console_timeline")
@admin_bp.route("/ai-console/audit", endpoint="ai_console_audit")
@admin_bp.route("/ai-console/settings", endpoint="ai_console_settings")
@login_required
def ai_console_legacy_pages():
    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    return redirect(url_for("admin.ai_console_monitor"))
