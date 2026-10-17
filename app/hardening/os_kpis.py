# -*- coding: utf-8 -*-
"""North Star OS KPIs — read-only from CRM / visits / deals / commissions."""
from __future__ import annotations

import os
from typing import Any, List

from app.hardening.config import hardening_os_kpis_enabled


def _safe_rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(float(num) / float(den), 4)


def _load_json_list(file_name: str) -> List[dict[str, Any]]:
    try:
        from app.utils.storage import _load, data_dir

        raw = _load(os.path.join(data_dir(), file_name))
        if not isinstance(raw, list):
            return []
        return [r for r in raw if isinstance(r, dict)]
    except Exception:
        return []


def compute_os_kpis(*, limit: int = 5000) -> dict[str, Any]:
    """
    Compute Visit Call / Booking / Visit→Deal / Deal Close / Sales Volume.
    Fail-open: returns zeros on any store error.
    """
    empty = {
        "visit_call_rate": 0.0,
        "visit_booking_rate": 0.0,
        "visit_to_deal_rate": 0.0,
        "deal_close_rate": 0.0,
        "sales_volume_count": 0,
        "sales_volume_amount": 0,
        "contacts_count": 0,
        "calls_to_target_count": 0,
        "visit_requests_count": 0,
        "visits_completed_count": 0,
        "deals_count": 0,
        "deals_closed_count": 0,
        "publish_to_visit_7d_rate": 0.0,
        "published_measured_count": 0,
        "published_with_visit_7d_count": 0,
    }
    if not hardening_os_kpis_enabled():
        return dict(empty)

    out = dict(empty)
    try:
        from app.crm.config import VISIT_CALL_TARGET

        target = (VISIT_CALL_TARGET or "").strip()
        contacts = _load_json_list("crm_contacts.json")[:limit]
        calls = _load_json_list("crm_call_logs.json")[:limit]
        contact_n = len(contacts)
        contact_ids_with_call: set[str] = set()
        calls_to_target = 0
        for c in calls:
            to_n = str(c.get("to_number") or "").strip()
            if target and to_n != target:
                continue
            calls_to_target += 1
            cid = str(c.get("contact_id") or "").strip()
            if cid:
                contact_ids_with_call.add(cid)
        out["contacts_count"] = contact_n
        out["calls_to_target_count"] = calls_to_target
        if contact_n > 0:
            out["visit_call_rate"] = _safe_rate(
                len(contact_ids_with_call) or min(calls_to_target, contact_n),
                contact_n,
            )
        else:
            out["visit_call_rate"] = 0.0
    except Exception:
        pass

    try:
        visits = _load_json_list("express_visit_requests.json")[:limit]
        out["visit_requests_count"] = len(visits)
        completed = 0
        for v in visits:
            st = str(v.get("status") or "").strip().lower()
            if st in ("done", "completed", "visit_done", "confirmed_done"):
                completed += 1
            elif v.get("visit_done") or v.get("completed_at"):
                completed += 1
        out["visits_completed_count"] = completed
        den = int(out["contacts_count"] or out["calls_to_target_count"] or 0)
        if den > 0:
            out["visit_booking_rate"] = _safe_rate(len(visits), den)
        elif visits:
            out["visit_booking_rate"] = 1.0
        else:
            out["visit_booking_rate"] = 0.0
    except Exception:
        pass

    deals_n = 0
    deals_closed = 0
    sales_amount = 0
    try:
        deals = _load_json_list("closing_deals.json")[:limit]
        deals_n = len(deals)
        for d in deals:
            st = str(d.get("status") or "").strip().lower()
            if st in ("closed", "sold", "approved", "completed", "won"):
                deals_closed += 1
            try:
                amt = int(d.get("sale_amount") or 0)
            except (TypeError, ValueError):
                amt = 0
            if amt > 0:
                sales_amount += amt
    except Exception:
        pass

    try:
        commissions = _load_json_list("express_commissions.json")[:limit]
        deal_comms = []
        for c in commissions:
            kind = str(
                c.get("kind") or c.get("type") or c.get("commission_type") or ""
            ).strip().lower()
            if kind in ("deal", "sale") or (not kind and (c.get("land_code") or c.get("code"))):
                deal_comms.append(c)
        if deals_n == 0:
            deals_n = len(deal_comms)
        if deals_closed == 0:
            for c in deal_comms:
                st = str(c.get("status") or "").strip().lower()
                if st in ("approved", "paid", "sold", "closed"):
                    deals_closed += 1
        if sales_amount == 0:
            for c in deal_comms:
                try:
                    sales_amount += int(c.get("amount") or c.get("sale_amount") or 0)
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass

    out["deals_count"] = deals_n
    out["deals_closed_count"] = deals_closed
    out["deal_close_rate"] = _safe_rate(deals_closed, deals_n)
    completed = int(out.get("visits_completed_count") or 0)
    if completed > 0:
        out["visit_to_deal_rate"] = _safe_rate(min(deals_n, completed), completed)
    elif deals_n > 0:
        out["visit_to_deal_rate"] = 1.0
    else:
        out["visit_to_deal_rate"] = 0.0
    out["sales_volume_count"] = deals_closed or deals_n
    out["sales_volume_amount"] = sales_amount
    try:
        from app.listings.performance import publish_to_visit_7d_kpi

        out.update(publish_to_visit_7d_kpi(limit=limit))
    except Exception:
        pass
    return out
