# -*- coding: utf-8 -*-
"""صفحهٔ واحد مدیریت هوش مصنوعی — /admin/ai با تب‌ها.

یک صفحه، هفت تب: مرور زنده، پیام‌ها و مدل، ابزار و صف تأیید، حافظه، مصرف،
خطاها، فلگ‌ها. آدرس‌های قدیمی `/admin/ai-console/*` و `/admin/ai-questions`
حذف نشده‌اند: GET به تب مربوطه redirect می‌شود و POSTها سر جای خود کار می‌کنند
تا فرم‌های موجود (فلگ، حافظه، منقضی‌کردن pending، مدل، پاسخ escalation) نشکنند.

دستیار عملیات روی `/admin` می‌ماند؛ اینجا فقط مدیریت است.
"""
from __future__ import annotations

from typing import Any

from flask import abort, flash, redirect, render_template, request, url_for

from .blueprint import admin_bp
from .routes import login_required

AI_TABS: list[dict[str, str]] = [
    {"id": "overview", "label": "مرور زنده", "icon": "fa-heart-pulse"},
    {"id": "messages", "label": "پیام‌ها و مدل", "icon": "fa-microchip"},
    {"id": "tools", "label": "ابزار و تأییدها", "icon": "fa-wrench"},
    {"id": "memory", "label": "حافظه", "icon": "fa-brain"},
    {"id": "usage", "label": "مصرف و مکالمات", "icon": "fa-chart-column"},
    {"id": "errors", "label": "خطاها", "icon": "fa-triangle-exclamation"},
    {"id": "flags", "label": "فلگ‌ها", "icon": "fa-toggle-on"},
]
_TAB_IDS = frozenset(t["id"] for t in AI_TABS)


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


def _hub_url(tab: str, **params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    return url_for("admin.ai_hub", tab=tab, **clean)


def _redirect_to_hub(tab: str, *, sub_from_tab: bool = False, keep: tuple[str, ...] = ()):
    """GET قدیمی → تب جدید، با حفظ آرگومان‌های لینک‌های موجود."""
    params: dict[str, Any] = {}
    if sub_from_tab:
        params["sub"] = (request.args.get("tab") or "").strip()
    for name in keep:
        params[name] = (request.args.get(name) or "").strip()
    return redirect(_hub_url(tab, **params))


# -----------------------------------------------------------------------------
# صفحهٔ واحد
# -----------------------------------------------------------------------------
@admin_bp.route("/ai", endpoint="ai_hub")
@login_required
def ai_hub():
    tab = (request.args.get("tab") or "overview").strip().lower()
    if tab not in _TAB_IDS:
        tab = "overview"
    permission = "admin.ai.read"
    if tab == "memory":
        try:
            from app.hardening.permissions import PERM_AI_MEMORY

            permission = PERM_AI_MEMORY
        except Exception:
            permission = "admin.ai.read"
    denied = _ai_console_gate(permission)
    if denied is not None:
        return denied

    builders = {
        "overview": _overview_context,
        "messages": _messages_context,
        "tools": _tools_context,
        "memory": _memory_context,
        "usage": _usage_context,
        "errors": _errors_context,
        "flags": _flags_context,
    }
    try:
        ctx = builders[tab]()
    except Exception:
        ctx = {}
        flash("بارگذاری این بخش ناموفق بود.", "error")
    return render_template(
        "admin/ai/index.html",
        ai_tab=tab,
        ai_tabs=AI_TABS,
        ai_badges=_ai_badges(),
        **ctx,
    )


def _ai_badges() -> dict[str, int]:
    try:
        from app.ai_console.service import dashboard_snapshot

        kpis = (dashboard_snapshot() or {}).get("kpis") or {}
        return {
            "pending": int(kpis.get("pending_confirms") or 0),
            "errors": int(kpis.get("errors_sample") or 0),
        }
    except Exception:
        return {"pending": 0, "errors": 0}


# -----------------------------------------------------------------------------
# زمینهٔ هر تب — همان readerهای قبلی
# -----------------------------------------------------------------------------
def _overview_context() -> dict[str, Any]:
    from app.ai_console import readers

    events: list[dict[str, Any]] = []
    for row in readers.list_token_rows(limit=80):
        events.append(
            {
                "ts": str(row.get("ts") or row.get("created_at") or ""),
                "source": "tokens",
                "audience": str(row.get("audience") or ""),
                "latency_ms": row.get("latency_ms") or row.get("duration_ms") or "",
                "status": "error"
                if row.get("error") or row.get("ok") is False
                else "ok",
                "summary": str(row.get("model") or row.get("route") or "token")[:80],
            }
        )
    for row in readers.list_evaluation_rows(limit=40):
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
    return {"events": events[:100]}


def _errors_context() -> dict[str, Any]:
    from app.ai_console import readers

    return {"errors": readers.extract_errors_from_logs(limit=80)}


def _tools_context() -> dict[str, Any]:
    from app.ai_console import catalog, readers
    from app.ai_console.config import ai_console_mutate_enabled

    sub = (request.args.get("sub") or "catalog").strip()
    return {
        "tools": catalog.list_tools(),
        "pending": readers.list_pending_confirms(limit=100),
        "tab": sub,
        "can_mutate": ai_console_mutate_enabled(),
    }


def _flags_context() -> dict[str, Any]:
    from app.ai_console import catalog
    from app.ai_console.config import ai_console_mutate_enabled
    from app.ai_console.followup_settings import (
        DEFAULT_HOURS,
        followup_hours_env_locked,
        followup_hours_source,
        get_followup_hours,
        hours_for_display,
    )

    flags = catalog.list_ai_flags()
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in flags:
        groups.setdefault(f.get("group") or "other", []).append(f)
    followup_hours = list(get_followup_hours())
    return {
        "groups": groups,
        "can_mutate": _can_mutate_flags(),
        "flags_on": sum(1 for f in flags if f.get("value") is True),
        "flags_off": sum(1 for f in flags if f.get("value") is False),
        "flags_total": len(flags),
        "followup_hours": followup_hours,
        "followup_hour_rows": hours_for_display(selected=followup_hours),
        "followup_hours_source": followup_hours_source(),
        "followup_hours_locked": followup_hours_env_locked(),
        "followup_hours_default": list(DEFAULT_HOURS),
    }


def _memory_context() -> dict[str, Any]:
    from app.ai_console import readers

    sub = (request.args.get("sub") or "system").strip()
    if sub not in ("system", "users"):
        sub = "system"
    q = (request.args.get("q") or "").strip()
    user_key = (request.args.get("user") or "").strip()
    # لینک مستقیم به حافظهٔ یک کاربر (از صفحهٔ افراد) باید تب کاربران را باز کند
    if user_key and not (request.args.get("sub") or "").strip():
        sub = "users"
    return {
        "tab": sub,
        "q": q,
        "user_key": user_key,
        "system_items": readers.list_system_memory(),
        "memory_user_count": readers.count_memory_users(),
        "memory_users": readers.list_memory_users(limit=100, q=q)
        if sub == "users"
        else [],
        "detail": readers.get_memory_detail(user_key) if user_key else None,
        "lands": readers.lands_inventory_summary(),
        "goal": readers.agent_goal_summary() if sub == "system" else {},
        "rag": readers.knowledge_rag_status() if sub == "system" else {},
        "can_mutate": _can_mutate_memory(),
    }


def _usage_context() -> dict[str, Any]:
    from app.ai_console import readers

    sub = (request.args.get("sub") or "network").strip()
    if sub not in ("network", "users", "chats"):
        sub = "network"
    q = (request.args.get("q") or "").strip()
    user_key = (request.args.get("user") or "").strip()
    audience = (request.args.get("audience") or "").strip()
    thread_id = (request.args.get("thread") or "").strip()
    try:
        days = max(0, min(365, int((request.args.get("days") or "30").strip())))
    except Exception:
        days = 30
    if user_key and not (request.args.get("sub") or "").strip():
        sub = "chats" if audience else "users"

    since_ts = 0
    if days > 0:
        from time import time as _time

        since_ts = int(_time()) - days * 86400

    aud_norm = audience if audience in ("public", "partner", "admin") else ""
    filter_user = user_key if sub in ("users", "chats") else ""

    report = readers.token_usage_report(
        limit=5000,
        user=filter_user,
        audience=aud_norm if sub != "chats" else (aud_norm if filter_user else ""),
        since_ts=since_ts,
    )
    users_count = len(report.get("users") or [])
    if filter_user:
        users_count = len(
            readers.token_usage_report(limit=5000, since_ts=since_ts).get("users") or []
        )

    conversations: list[dict[str, Any]] = []
    conversation = None
    if sub == "chats":
        conversations = readers.list_conversation_index(
            limit=120,
            audience=audience if audience in ("public", "partner") else "",
            q=user_key or q,
        )
        if user_key and audience in ("public", "partner", "admin"):
            conversation = readers.get_conversation(
                audience=audience,
                user_key=user_key,
                thread_id=thread_id,
            )
    return {
        "tab": sub,
        "q": q,
        "user_key": user_key,
        "audience": audience,
        "thread_id": thread_id,
        "days": days,
        "report": report,
        "users_count": users_count,
        "conversations": conversations,
        "conversation": conversation,
    }


def _messages_context() -> dict[str, Any]:
    """پیام‌های ارجاعی + وضعیت/مدل/کلید API — همان دادهٔ صفحهٔ ai-questions."""
    from app.ai.credits import get_last_balance_probe, is_api_balance_depleted
    from app.ai.escalations import (
        count_pending_balance_deferred,
        list_pending_for_admin,
        list_recent_answered,
    )
    from app.ai.runtime_settings import (
        force_flash_enabled,
        get_ai_settings,
        get_stored_ai_api_key,
        mask_api_key,
        model_choice_options,
    )
    from app.ai.services import ai_config
    from app.keys import get_deepseek_api_key

    from .routes import _lands_path, counts_by_status, get_settings, load_json

    import os

    stored_api_key = get_stored_ai_api_key()
    active_api_key = get_deepseek_api_key()
    env_ai = os.environ.get("VINOR_AI_ENABLED")

    last_probe = get_last_balance_probe()
    if last_probe.get("probed_at"):
        try:
            from datetime import datetime

            last_probe = dict(last_probe)
            last_probe["probed_at_label"] = datetime.fromtimestamp(
                float(last_probe["probed_at"])
            ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            last_probe["probed_at_label"] = ""
    try:
        lands = load_json(_lands_path())
        pending_c, approved_c, rejected_c = counts_by_status(
            lands if isinstance(lands, list) else []
        )
    except Exception:
        pending_c, approved_c, rejected_c = 0, 0, 0
    try:
        balance_deferred_count = count_pending_balance_deferred()
    except Exception:
        balance_deferred_count = 0

    return {
        "pending": list_pending_for_admin(),
        "answered": list_recent_answered(),
        "pending_count": pending_c,
        "approved_count": approved_c,
        "rejected_count": rejected_c,
        "ai_settings": get_ai_settings(),
        "ai_status": ai_config(),
        "ai_model_options": model_choice_options(),
        "site_settings": get_settings(),
        "api_key_masked": mask_api_key(active_api_key),
        "api_key_source": "settings"
        if stored_api_key
        else ("file" if active_api_key else "none"),
        "has_stored_api_key": bool(stored_api_key),
        "force_flash": force_flash_enabled(),
        "balance_depleted": is_api_balance_depleted(),
        "last_balance_probe": last_probe,
        "balance_deferred_count": balance_deferred_count,
        "ai_enabled_env_locked": env_ai is not None and str(env_ai).strip() != "",
    }


def _can_mutate_flags() -> bool:
    from app.ai_console.config import ai_console_mutate_enabled

    try:
        from app.hardening.permissions import PERM_AI_FLAGS, has_permission

        return bool(has_permission(PERM_AI_FLAGS) and ai_console_mutate_enabled())
    except Exception:
        return bool(ai_console_mutate_enabled())


def _can_mutate_memory() -> bool:
    from app.ai_console.config import ai_console_mutate_enabled

    try:
        from app.hardening.permissions import PERM_AI_MEMORY, has_permission

        return bool(has_permission(PERM_AI_MEMORY) and ai_console_mutate_enabled())
    except Exception:
        return bool(ai_console_mutate_enabled())


# -----------------------------------------------------------------------------
# آدرس‌های قدیمی — GET redirect، POST سر جای خود
# -----------------------------------------------------------------------------
@admin_bp.route("/ai-console", endpoint="ai_console_dashboard")
@admin_bp.route("/ai-console/monitor", endpoint="ai_console_monitor")
@admin_bp.route("/ai-console/workflows", endpoint="ai_console_workflows")
@admin_bp.route("/ai-console/agents", endpoint="ai_console_agents")
@admin_bp.route("/ai-console/prompts", endpoint="ai_console_prompts")
@admin_bp.route("/ai-console/timeline", endpoint="ai_console_timeline")
@admin_bp.route("/ai-console/audit", endpoint="ai_console_audit")
@admin_bp.route("/ai-console/settings", endpoint="ai_console_settings")
@login_required
def ai_console_legacy_pages():
    return _redirect_to_hub("overview")


@admin_bp.route("/ai-console/errors", endpoint="ai_console_errors")
@login_required
def ai_console_errors():
    return _redirect_to_hub("errors")


@admin_bp.route("/ai-console/conversations", endpoint="ai_console_conversations")
@login_required
def ai_console_conversations_redirect():
    return redirect(_hub_url("usage", sub="chats"))


@admin_bp.route("/ai-console/analytics", endpoint="ai_console_analytics")
@login_required
def ai_console_analytics_redirect():
    return redirect(_hub_url("usage", sub="network"))


@admin_bp.route("/ai-console/usage", endpoint="ai_console_usage")
@login_required
def ai_console_usage():
    return _redirect_to_hub(
        "usage",
        sub_from_tab=True,
        keep=("user", "audience", "thread", "days", "q"),
    )


@admin_bp.route(
    "/ai-console/tools", endpoint="ai_console_tools", methods=["GET", "POST"]
)
@login_required
def ai_console_tools():
    if request.method == "GET":
        return _redirect_to_hub("tools", sub_from_tab=True)

    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console import readers
    from app.ai_console.config import ai_console_mutate_enabled

    try:
        from app.hardening.permissions import PERM_AI_TOOLS, has_permission

        allowed = has_permission(PERM_AI_TOOLS) and ai_console_mutate_enabled()
    except Exception:
        allowed = False
    if not allowed:
        flash("مجوز expire کردن pending را ندارید.", "error")
        return redirect(_hub_url("tools", sub="pending"))

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
    return redirect(_hub_url("tools", sub="pending"))


@admin_bp.route(
    "/ai-console/flags", endpoint="ai_console_flags", methods=["GET", "POST"]
)
@login_required
def ai_console_flags():
    if request.method == "GET":
        return _redirect_to_hub("flags")

    denied = _ai_console_gate("admin.ai.read")
    if denied is not None:
        return denied
    from app.ai_console.followup_settings import set_followup_hours

    back = _hub_url("flags")
    if not _can_mutate_flags():
        flash("مجوز تغییر فلگ را ندارید یا mutate خاموش است.", "error")
        return redirect(back)

    action = (request.form.get("action") or "").strip()
    if action == "save_followup_hours":
        out = set_followup_hours(request.form.getlist("hour"))
        if out.get("ok"):
            _audit("ai_followup_hours", "hours", f"Follow-up hours → {out.get('hours')}")
            hrs = "، ".join(f"{int(h):02d}:00" for h in (out.get("hours") or []))
            flash(f"ساعت‌های پیگیری ذخیره شد: {hrs} (تهران)", "success")
        elif out.get("error") == "env_locked":
            flash(
                f"ساعت‌ها با env قفل است ({out.get('env')}) — از پنل قابل تغییر نیست.",
                "warning",
            )
        elif out.get("error") == "invalid_hours":
            flash("حداقل یک ساعت معتبر (۰ تا ۲۳) انتخاب کنید.", "error")
        else:
            flash(out.get("error") or "ذخیره ساعت‌ها ناموفق بود.", "error")
        return redirect(back)

    flag = (request.form.get("flag") or "").strip()
    if action == "toggle" and flag:
        from app.ai_console.flag_settings import set_feature_flag

        want_on = (request.form.get("enable") or "").strip() in (
            "1",
            "true",
            "on",
            "yes",
        )
        out = set_feature_flag(flag, want_on)
        if out.get("ok"):
            _audit(
                "ai_flag_toggle",
                flag[:64],
                f"AI flag {flag} → {'on' if want_on else 'off'}",
                entity_type="ai_feature_flag",
            )
            flash(f"{'فعال' if want_on else 'غیرفعال'} شد: {flag}", "success")
        elif out.get("error") == "env_locked":
            flash(
                f"این فلگ با env قفل است ({out.get('env')}) — از پنل قابل تغییر نیست.",
                "warning",
            )
        else:
            flash(out.get("error") or "تغییر ناموفق.", "error")
    else:
        flash("اقدام نامعتبر.", "warning")
    return redirect(back)


@admin_bp.route(
    "/ai-console/memory", endpoint="ai_console_memory", methods=["GET", "POST"]
)
@login_required
def ai_console_memory():
    if request.method == "GET":
        return _redirect_to_hub("memory", sub_from_tab=True, keep=("user", "q"))

    try:
        from app.hardening.permissions import PERM_AI_MEMORY

        permission = PERM_AI_MEMORY
    except Exception:
        permission = "admin.ai.read"
    denied = _ai_console_gate(permission)
    if denied is not None:
        return denied

    from app.ai_console import readers

    if not _can_mutate_memory():
        flash("مجوز تغییر حافظه را ندارید یا mutate خاموش است.", "error")
        return redirect(_hub_url("memory"))

    action = (request.form.get("action") or "").strip()
    q = (request.form.get("q") or "").strip()
    user_key = (request.form.get("user_key") or request.form.get("user") or "").strip()

    if action == "add_system":
        out = readers.add_system_memory(
            request.form.get("key") or "",
            request.form.get("value") or "",
        )
        _flash_result(out, "دانش سیستم افزوده شد.")
        return redirect(_hub_url("memory", sub="system"))

    if action == "delete_system":
        out = readers.delete_system_memory(request.form.get("id") or "")
        _flash_result(out, "حذف شد.", warn=True)
        return redirect(_hub_url("memory", sub="system"))

    if action == "add_user":
        out = readers.upsert_user_memory(
            user_key,
            key=request.form.get("key") or "",
            value=request.form.get("value") or "",
            memory_type=request.form.get("memory_type") or "long_term",
        )
        _flash_result(out, "حافظه کاربر ذخیره شد.")
        return redirect(_hub_url("memory", sub="users", user=user_key, q=q))

    if action == "delete_user_item":
        out = readers.delete_user_memory_item(user_key, request.form.get("id") or "")
        _flash_result(out, "آیتم حذف شد.", warn=True)
        return redirect(_hub_url("memory", sub="users", user=user_key, q=q))

    if action == "wipe_user":
        out = readers.wipe_user_memory(user_key)
        if out.get("ok"):
            flash(f"حافظه کاربر پاک شد ({out.get('deleted') or 0} آیتم).", "success")
        else:
            flash(out.get("error") or "ناموفق", "error")
        return redirect(_hub_url("memory", sub="users", user=user_key, q=q))

    flash("اقدام نامعتبر.", "warning")
    return redirect(_hub_url("memory", user=user_key))


def _flash_result(out: dict[str, Any], ok_message: str, *, warn: bool = False) -> None:
    if out.get("ok"):
        flash(ok_message, "success")
        return
    flash(out.get("error") or ("یافت نشد" if warn else "ناموفق"), "warning" if warn else "error")


def _audit(
    action: str,
    entity_id: str,
    summary: str,
    *,
    entity_type: str = "ai_followup_hours",
) -> None:
    try:
        from app.hardening.audit import record_admin_audit

        record_admin_audit(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
        )
    except Exception:
        pass
