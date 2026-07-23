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


@admin_bp.route("/ai-console/memory", endpoint="ai_console_memory", methods=["GET", "POST"])
@login_required
def ai_console_memory():
    from app.hardening.permissions import PERM_AI_MEMORY

    denied = _ai_console_gate(PERM_AI_MEMORY)
    if denied is not None:
        return denied

    from app.ai_console import readers
    from app.ai_console.config import ai_console_mutate_enabled
    from app.hardening.permissions import has_permission

    can_mutate = bool(has_permission(PERM_AI_MEMORY) and ai_console_mutate_enabled())

    if request.method == "POST":
        if not can_mutate:
            flash("مجوز تغییر حافظه را ندارید یا mutate خاموش است.", "error")
            return redirect(url_for("admin.ai_console_memory"))
        action = (request.form.get("action") or "").strip()
        tab = (request.form.get("tab") or request.args.get("tab") or "system").strip()
        user_q = (request.form.get("user") or "").strip()

        if action == "add_system":
            out = readers.add_system_memory(
                request.form.get("key") or "",
                request.form.get("value") or "",
            )
            flash("دانش سیستم افزوده شد." if out.get("ok") else (out.get("error") or "ناموفق"), "success" if out.get("ok") else "error")
            return redirect(url_for("admin.ai_console_memory", tab="system"))

        if action == "delete_system":
            out = readers.delete_system_memory(request.form.get("id") or "")
            flash("حذف شد." if out.get("ok") else (out.get("error") or "یافت نشد"), "success" if out.get("ok") else "warning")
            return redirect(url_for("admin.ai_console_memory", tab="system"))

        if action == "add_user":
            uk = (request.form.get("user_key") or user_q or "").strip()
            out = readers.upsert_user_memory(
                uk,
                key=request.form.get("key") or "",
                value=request.form.get("value") or "",
                memory_type=request.form.get("memory_type") or "long_term",
            )
            flash("حافظه کاربر ذخیره شد." if out.get("ok") else (out.get("error") or "ناموفق"), "success" if out.get("ok") else "error")
            return redirect(url_for("admin.ai_console_memory", tab="users", user=uk, q=request.form.get("q") or ""))

        if action == "delete_user_item":
            uk = (request.form.get("user_key") or user_q or "").strip()
            out = readers.delete_user_memory_item(uk, request.form.get("id") or "")
            flash("آیتم حذف شد." if out.get("ok") else (out.get("error") or "یافت نشد"), "success" if out.get("ok") else "warning")
            return redirect(url_for("admin.ai_console_memory", tab="users", user=uk, q=request.form.get("q") or ""))

        if action == "wipe_user":
            uk = (request.form.get("user_key") or user_q or "").strip()
            out = readers.wipe_user_memory(uk)
            flash(
                f"حافظه کاربر پاک شد ({out.get('deleted') or 0} آیتم)." if out.get("ok") else (out.get("error") or "ناموفق"),
                "success" if out.get("ok") else "error",
            )
            return redirect(url_for("admin.ai_console_memory", tab="users", user=uk, q=request.form.get("q") or ""))

        flash("اقدام نامعتبر.", "warning")
        return redirect(url_for("admin.ai_console_memory", tab=tab, user=user_q or None))

    tab = (request.args.get("tab") or "system").strip()
    if tab not in ("system", "users"):
        tab = "system"
    q = (request.args.get("q") or "").strip()
    user_key = (request.args.get("user") or "").strip()

    system_items = readers.list_system_memory()
    # Always count users so the users-tab chip stays accurate on the system tab too.
    memory_user_count = readers.count_memory_users()
    memory_users = readers.list_memory_users(limit=100, q=q) if tab == "users" else []
    detail = readers.get_memory_detail(user_key) if user_key else None
    lands = readers.lands_inventory_summary()
    goal = readers.agent_goal_summary() if tab == "system" else {}
    rag = readers.knowledge_rag_status() if tab == "system" else {}

    return render_template(
        "admin/ai_console/memory.html",
        tab=tab,
        q=q,
        user_key=user_key,
        system_items=system_items,
        memory_users=memory_users,
        memory_user_count=memory_user_count,
        detail=detail,
        lands=lands,
        goal=goal,
        rag=rag,
        can_mutate=can_mutate,
        **_nav_ctx("memory"),
    )


# Legacy Mission Control pages → monitor
@admin_bp.route("/ai-console/conversations", endpoint="ai_console_conversations")
@admin_bp.route("/ai-console/workflows", endpoint="ai_console_workflows")
@admin_bp.route("/ai-console/agents", endpoint="ai_console_agents")
@admin_bp.route("/ai-console/prompts", endpoint="ai_console_prompts")
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
