# -*- coding: utf-8 -*-
"""Action-first dashboard data: what needs a decision now, then a few core KPIs.

Every source is fail-open so one broken JSON store never blanks the page.
Finance rows (names, amounts) are only included for admins with PERM_FINANCE.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from flask import current_app, url_for

from .nav import queue_counts

VISIT_STATUS = {
    "pending": ("در انتظار تأیید", "warn"),
    "approved": ("تأیید شده", "info"),
    "done_pending": ("منتظر تأیید انجام", "warn"),
    "completed": ("انجام شد", "ok"),
    "cancelled": ("بسته شده", "muted"),
    "no_show": ("عدم حضور", "danger"),
}
WITHDRAW_STATUS = {
    "pending": ("در انتظار بررسی", "warn"),
    "approved": ("تأیید شده", "info"),
    "processing": ("در حال پردازش", "violet"),
    "paid": ("پرداخت شده", "ok"),
    "rejected": ("رد شده", "danger"),
    "cancelled": ("لغو شده", "muted"),
}


def _ts(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v)
    return ""


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        current_app.logger.debug("dashboard source failed", exc_info=True)
        return default


def _finance_allowed() -> bool:
    try:
        from app.hardening.permissions import PERM_FINANCE, has_permission

        return bool(has_permission(PERM_FINANCE))
    except Exception:
        return False


def _partner_names() -> Dict[str, str]:
    from app.utils.storage import load_express_partners

    out: Dict[str, str] = {}
    for p in load_express_partners() or []:
        if isinstance(p, dict) and p.get("phone"):
            out[str(p["phone"]).strip()] = str(p.get("name") or "").strip()
    return out


def build_overview() -> Dict[str, Any]:
    counts = dict(queue_counts())
    names = _safe(_partner_names, {})
    ov: Dict[str, Any] = {
        "counts": counts,
        "queue_total": counts.get("queue_total", 0),
        "queues": [
            {"key": "listings", "label": "آگهی منتظر تأیید", "hint": "آگهی‌های ملک ثبت‌شده توسط کاربران",
             "icon": "fa-building", "count": counts.get("listings_pending", 0),
             "url": url_for("admin.property_listings", status="pending")},
            {"key": "visits", "label": "بازدید نیازمند اقدام", "hint": "درخواست جدید یا تأیید انجام بازدید",
             "icon": "fa-route", "count": counts.get("visits_pending", 0),
             "url": url_for("admin.express_visit_requests", filter="actions")},
            {"key": "withdrawals", "label": "برداشت در انتظار", "hint": "تسویه با همکاران",
             "icon": "fa-money-bill-transfer", "count": counts.get("withdrawals_pending", 0),
             "url": url_for("admin.financial_withdrawals", filter="pending")},
            {"key": "partners", "label": "درخواست همکاری", "hint": "متقاضیان بازاریابی و همکاری",
             "icon": "fa-user-plus", "count": counts.get("partners_pending", 0),
             "url": url_for("admin.express_partners", filter="pending")},
        ],
        "kpis": [],
        "visits": [],
        "withdrawals": [],
        "listings": [],
        "applications": [],
        "finance_allowed": _finance_allowed(),
        "reports_open": counts.get("reports_open", 0),
    }

    # --- KPIs -------------------------------------------------------------
    def _kpis() -> List[Dict[str, Any]]:
        from app.utils.storage import load_express_partners, load_express_visit_requests
        from app.express_partner.partner_roles import partner_is_approved, partner_is_special
        from .routes import _lands_path, expiry_meta, load_json
        from .property_listings import listing_status

        lands = load_json(_lands_path())
        lands = lands if isinstance(lands, list) else []
        live = sum(1 for l in lands if isinstance(l, dict) and listing_status(l, expiry_meta(l)) == "approved")
        partners = [p for p in (load_express_partners() or []) if isinstance(p, dict)]
        approved = sum(1 for p in partners if partner_is_approved(p))
        plus = sum(1 for p in partners if partner_is_special(p))
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        from .ui_filters import parse_any_dt

        visits_week = 0
        for v in load_express_visit_requests() or []:
            if not isinstance(v, dict):
                continue
            dt = parse_any_dt(_ts(v, "created_at"))
            if dt and dt >= week_ago:
                visits_week += 1
        return [
            {"label": "آگهی فعال", "value": live, "url": url_for("admin.property_listings", status="approved")},
            {"label": "همکار تأییدشده", "value": approved, "url": url_for("admin.express_partners", filter="partners")},
            {"label": "همکار پلاس فعال", "value": plus, "url": url_for("admin.express_listings", filter="plus")},
            {"label": "بازدید ۷ روز اخیر", "value": visits_week, "url": url_for("admin.express_visit_requests", filter="all")},
        ]

    ov["kpis"] = _safe(_kpis, [])

    # --- recent visits ------------------------------------------------------
    def _visits() -> List[Dict[str, Any]]:
        from app.utils.storage import load_express_visit_requests

        rows = [v for v in (load_express_visit_requests() or []) if isinstance(v, dict)]
        rows.sort(key=lambda v: _ts(v, "updated_at", "created_at"), reverse=True)
        out = []
        for v in rows[:6]:
            st = str(v.get("status") or "pending").strip()
            label, tone = VISIT_STATUS.get(st, (st or "—", "muted"))
            phone = str(v.get("partner_phone") or "").strip()
            out.append({
                "title": str(v.get("land_title") or ("فایل " + str(v.get("land_code") or "—"))),
                "who": str(v.get("partner_name") or names.get(phone) or phone or "همکار"),
                "customer": str(v.get("customer_name") or ""),
                "status": label, "tone": tone,
                "needs_action": st in ("pending", "done_pending"),
                "ts": _ts(v, "updated_at", "created_at"),
            })
        return out

    ov["visits"] = _safe(_visits, [])

    # --- withdrawals (finance permission only) --------------------------------
    def _withdrawals() -> List[Dict[str, Any]]:
        from app.utils.storage import load_partner_withdrawals

        rows = [w for w in (load_partner_withdrawals() or []) if isinstance(w, dict)]
        order = {"pending": 0, "approved": 1, "processing": 2}
        rows.sort(key=lambda w: _ts(w, "created_at"), reverse=True)
        rows.sort(key=lambda w: order.get(str(w.get("status") or ""), 9))
        out = []
        for w in rows[:5]:
            st = str(w.get("status") or "pending").strip()
            label, tone = WITHDRAW_STATUS.get(st, (st, "muted"))
            phone = str(w.get("phone") or "").strip()
            out.append({
                "who": str(w.get("partner_name") or names.get(phone) or w.get("holder_name") or phone or "همکار"),
                "bank": str(w.get("bank_name") or ""),
                "amount": int(float(w.get("amount") or 0)),
                "status": label, "tone": tone,
                "ts": _ts(w, "created_at"),
            })
        return out

    if ov["finance_allowed"]:
        ov["withdrawals"] = _safe(_withdrawals, [])

    # --- listings waiting for approval -----------------------------------------
    def _listings() -> List[Dict[str, Any]]:
        from .routes import _lands_path, expiry_meta, load_json
        from .property_listings import collect_rows

        lands = load_json(_lands_path())
        rows, _ = collect_rows(lands if isinstance(lands, list) else [], expiry_meta)
        pend = [r for r in rows if r.get("status") == "pending"]
        pend.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return pend[:5]

    ov["listings"] = _safe(_listings, [])

    # --- partner applications -------------------------------------------------
    def _apps() -> List[Dict[str, Any]]:
        from app.utils.storage import load_express_partner_apps
        from .nav import PENDING_PARTNER_APP

        apps = [a for a in (load_express_partner_apps() or [])
                if isinstance(a, dict) and str(a.get("status") or "").strip().lower() in PENDING_PARTNER_APP]
        apps.sort(key=lambda a: _ts(a, "created_at"), reverse=True)
        return [{"name": str(a.get("name") or "بدون نام"), "phone": str(a.get("phone") or ""),
                 "city": str(a.get("city") or ""), "ts": _ts(a, "created_at")} for a in apps[:5]]

    ov["applications"] = _safe(_apps, [])
    return ov
