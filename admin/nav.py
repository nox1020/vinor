# -*- coding: utf-8 -*-
"""Admin information architecture: one short, operations-first navigation.

Six primary sections; every secondary tool still has a home (and stays
reachable through the command palette), but the main nav stays short.
Pending-count badges come from the same cheap JSON loads the dashboard uses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import current_app, g, request, session, url_for

from .blueprint import admin_bp

# key → (label, endpoint, url kwargs, endpoints that mark it active, badge key)
NAV: List[Dict[str, Any]] = [
    {
        "key": "dashboard",
        "label": "داشبورد",
        "icon": "fa-gauge-high",
        "endpoint": "admin.dashboard",
        "match": ["admin.dashboard", "admin.admin_root"],
        "badge": "queue_total",
        "children": [],
    },
    {
        "key": "listings",
        "label": "آگهی‌ها / فایل‌ها",
        "icon": "fa-building",
        "endpoint": "admin.property_listings",
        "badge": "listings_pending",
        "children": [
            {"label": "آگهی‌های ملک (تأیید)", "endpoint": "admin.property_listings",
             "match": ["admin.property_listings", "admin.lands", "admin.pending_lands", "admin.approved_lands",
                       "admin.rejected_lands", "admin.view_land", "admin.view_land_by_index", "admin.edit_land",
                       "admin.add_land", "admin.add_land_video"],
             "badge": "listings_pending"},
            {"label": "فایل‌های همکاران پلاس", "endpoint": "admin.express_listings",
             "match": ["admin.express_listings", "admin.edit_express_listing", "admin.add_express_listing"]},
            {"label": "گزارش‌های کاربران", "endpoint": "admin.reports_list", "match": ["admin.reports_list"],
             "badge": "reports_open"},
        ],
    },
    {
        "key": "visits",
        "label": "بازدیدها و پیگیری",
        "icon": "fa-route",
        "endpoint": "admin.express_visit_requests",
        "badge": "visits_pending",
        "children": [
            {"label": "روند بازدیدها", "endpoint": "admin.express_visit_requests",
             "match": ["admin.express_visit_requests"], "badge": "visits_pending"},
            {"label": "معاملات معوق", "endpoint": "admin.express_deals_overdue",
             "match": ["admin.express_deals_overdue", "admin.express_deals_missing_pending"]},
        ],
    },
    {
        "key": "finance",
        "label": "مالی و برداشت‌ها",
        "icon": "fa-wallet",
        "endpoint": "admin.financial_withdrawals",
        "badge": "withdrawals_pending",
        "children": [
            {"label": "درخواست‌های برداشت", "endpoint": "admin.financial_withdrawals",
             "match": ["admin.financial_withdrawals"], "badge": "withdrawals_pending"},
            {"label": "پورسانت‌ها و کیف پول", "endpoint": "admin.express_commissions",
             "match": ["admin.express_commissions", "admin.express_commission_edit"]},
            {"label": "امانت فروش (اسکرو)", "endpoint": "admin.express_escrow_review",
             "match": ["admin.express_escrow_review", "admin.express_escrow_missing"]},
            {"label": "پرداخت‌ها و اشتراک پلاس", "endpoint": "admin.zarinpal_plus", "match": ["admin.zarinpal_plus"]},
        ],
    },
    {
        "key": "people",
        "label": "کاربران و همکاران",
        "icon": "fa-user-group",
        "endpoint": "admin.express_partners",
        "badge": "partners_pending",
        "children": [
            {"label": "همه افراد", "endpoint": "admin.express_partners", "kwargs": {"filter": "all"},
             "match": ["admin.express_partners", "admin.express_partner_detail"], "match_filter": ["", "all", "partners", "online"]},
            {"label": "درخواست‌های همکاری", "endpoint": "admin.express_partners", "kwargs": {"filter": "pending"},
             "match": ["admin.express_partners"], "match_filter": ["pending"], "badge": "partners_pending"},
            {"label": "کاربران سایت", "endpoint": "admin.express_partners", "kwargs": {"filter": "users"},
             "match": ["admin.express_partners"], "match_filter": ["users"]},
            {"label": "فروشنده‌های برتر", "endpoint": "admin.top_sellers", "match": ["admin.top_sellers"]},
        ],
    },
    {
        "key": "tools",
        "label": "تنظیمات و ابزارها",
        "icon": "fa-sliders",
        "endpoint": "admin.settings",
        "badge": None,
        "children": [
            {"label": "تنظیمات کلی", "endpoint": "admin.settings",
             "match": ["admin.settings", "admin.settings_apk_upload", "admin.settings_apk_sms_template"]},
            {"label": "نوار آگهی خانه", "endpoint": "admin.home_ads", "match": ["admin.home_ads"]},
            {"label": "شهرهای فعال", "endpoint": "admin.express_cities", "match": ["admin.express_cities"]},
            {"label": "پیامک و اعلان", "endpoint": "admin.sms_notifications",
             "match": ["admin.sms_notifications", "admin.sms_colleagues", "admin.sms_history", "admin.sms_campaign",
                       "admin.sms_recipients", "admin.sms_recipients_edit", "admin.sms_system_templates",
                       "admin.notifications_colleagues", "admin.notifications_broadcast", "admin.notifications_test",
                       "admin.admin_push_test"]},
            {"label": "هوش مصنوعی", "endpoint": "admin.ai_hub",
             "match": ["admin.ai_hub", "admin.ai_questions", "admin.ai_model", "admin.lawyer"]},
            {"label": "گزارش فعالیت ادمین", "endpoint": "admin.audit_log", "match": ["admin.audit_log", "admin.super_admin_info"]},
        ],
    },
]

PENDING_PARTNER_APP = ("pending", "under_review", "waiting", "review")


def queue_counts() -> Dict[str, int]:
    """Pending work counts (fail-open per source; cached per request)."""
    cached = getattr(g, "_vinor_admin_counts", None)
    if isinstance(cached, dict):
        return cached
    out = {
        "listings_pending": 0,
        "partners_pending": 0,
        "visits_pending": 0,
        "withdrawals_pending": 0,
        "reports_open": 0,
    }
    try:
        from .routes import _lands_path, expiry_meta, load_json
        from .property_listings import listing_status

        lands = load_json(_lands_path())
        out["listings_pending"] = sum(
            1 for l in (lands if isinstance(lands, list) else [])
            if isinstance(l, dict) and listing_status(l, expiry_meta(l)) == "pending"
        )
    except Exception:
        current_app.logger.debug("admin counts: listings failed", exc_info=True)
    try:
        from app.utils.storage import load_express_partner_apps

        out["partners_pending"] = sum(
            1 for a in (load_express_partner_apps() or [])
            if isinstance(a, dict) and str(a.get("status") or "").strip().lower() in PENDING_PARTNER_APP
        )
    except Exception:
        current_app.logger.debug("admin counts: partners failed", exc_info=True)
    try:
        from app.utils.storage import load_express_visit_requests

        out["visits_pending"] = sum(
            1 for v in (load_express_visit_requests() or [])
            if isinstance(v, dict) and str(v.get("status") or "").strip() in ("pending", "done_pending")
        )
    except Exception:
        current_app.logger.debug("admin counts: visits failed", exc_info=True)
    try:
        from app.utils.storage import load_partner_withdrawals

        out["withdrawals_pending"] = sum(
            1 for w in (load_partner_withdrawals() or [])
            if isinstance(w, dict) and str(w.get("status") or "").strip() == "pending"
        )
    except Exception:
        current_app.logger.debug("admin counts: withdrawals failed", exc_info=True)
    try:
        from app.utils.storage import load_reports

        out["reports_open"] = sum(
            1 for r in (load_reports() or [])
            if isinstance(r, dict) and str(r.get("status") or "open").strip() != "resolved"
        )
    except Exception:
        current_app.logger.debug("admin counts: reports failed", exc_info=True)
    out["queue_total"] = (
        out["listings_pending"] + out["partners_pending"] + out["visits_pending"] + out["withdrawals_pending"]
    )
    g._vinor_admin_counts = out
    return out


def _url(endpoint: str, kwargs: Optional[Dict[str, Any]] = None) -> str:
    try:
        return url_for(endpoint, **(kwargs or {}))
    except Exception:
        return ""


def build_nav(endpoint: str, counts: Dict[str, int], current_filter: str = "") -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for sec in NAV:
        children = []
        sec_active = endpoint in (sec.get("match") or [])
        for ch in sec.get("children") or []:
            url = _url(ch["endpoint"], ch.get("kwargs"))
            if not url:
                continue
            active = endpoint in (ch.get("match") or [])
            if active and ch.get("match_filter") is not None:
                active = current_filter in ch["match_filter"]
            if endpoint in (ch.get("match") or []):
                sec_active = True
            children.append({
                "label": ch["label"],
                "url": url,
                "active": active,
                "count": int(counts.get(ch.get("badge") or "", 0) or 0),
            })
        url = _url(sec["endpoint"], sec.get("kwargs"))
        if not url:
            continue
        sections.append({
            "key": sec["key"],
            "label": sec["label"],
            "icon": sec["icon"],
            "url": url,
            "active": sec_active,
            "count": int(counts.get(sec.get("badge") or "", 0) or 0),
            "children": children,
        })
    return sections


def command_items(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Command palette groups mirror the nav (labels are Persian, no i18n keys)."""
    groups = []
    for sec in sections:
        items = [{"label": sec["label"], "href": sec["url"], "icon": sec["icon"]}]
        seen = {sec["url"]}
        for ch in sec["children"]:
            if ch["url"] in seen:
                continue
            seen.add(ch["url"])
            items.append({"label": ch["label"], "href": ch["url"], "icon": "fa-angle-left"})
        groups.append({"name": sec["label"], "items": items})
    return groups


@admin_bp.context_processor
def inject_admin_nav():
    if not session.get("logged_in"):
        return {"admin_nav": [], "admin_counts": {}, "admin_cmd": []}
    cached = getattr(g, "_vinor_admin_nav", None)
    if isinstance(cached, dict):
        return cached
    counts = queue_counts()
    flt = (request.args.get("filter") or "").strip().lower()
    nav = build_nav(request.endpoint or "", counts, flt)
    out = {"admin_nav": nav, "admin_counts": counts, "admin_cmd": command_items(nav)}
    g._vinor_admin_nav = out
    return out
