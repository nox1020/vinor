"""جزئیات فایل برای تزریق در چت (بدون صفحه جدا)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import render_template, session

_PLUS_OUTCOME_LABELS = {
    "interested": "علاقه‌مند",
    "not_interested": "بی‌علاقه",
    "follow_up": "نیاز به پیگیری",
    "no_show": "عدم حضور",
}


def _attach_plus_feedback(land: Dict[str, Any], visit_row: Optional[Dict[str, Any]]) -> None:
    """نام کاربر پلاس و بازخورد ثبت‌شده روی کارت فایل چت."""
    land["_plus_user_name"] = ""
    land["_plus_user_phone"] = ""
    land["_plus_feedback"] = None
    if not isinstance(visit_row, dict):
        return
    land["_plus_user_name"] = str(visit_row.get("plus_user_name") or "").strip()
    land["_plus_user_phone"] = str(visit_row.get("plus_user_phone") or "").strip()
    vid = str(visit_row.get("id") or "").strip()
    if not vid:
        return
    try:
        from app.visit_result.store import get_result_for_visit

        vr = get_result_for_visit(vid)
    except Exception:
        vr = None
    if vr is None:
        return
    oc = str(getattr(vr, "outcome", "") or "").strip()
    if not oc:
        return
    tone = "ok"
    if oc in ("not_interested", "no_show"):
        tone = "down"
    elif oc == "follow_up":
        tone = "wait"
    land["_plus_feedback"] = {
        "outcome": oc,
        "label": _PLUS_OUTCOME_LABELS.get(oc, oc),
        "notes": str(getattr(vr, "notes", "") or "").strip(),
        "tone": tone,
    }


def _tune_land_chat_cta(cta: Dict[str, Any], *, can_revisit: bool) -> Dict[str, Any]:
    """برچسب دکمه‌های کارت فایل داخل چت — بدون پرامپت سفر."""
    out = dict(cta or {})
    action = str(out.get("action") or "").strip()
    label = str(out.get("label") or "").strip()
    if action == "visit" and label in ("ادامه", ""):
        out["label"] = "ثبت بازدید"
        out["icon"] = str(out.get("icon") or "").strip() or "fa-calendar-days"
    if action == "complete_visit":
        out["label"] = "بازدید انجام شد"
        out["icon"] = "fa-check-double"
    sec = str(out.get("secondary_action") or "").strip()
    sec_label = str(out.get("secondary_label") or "").strip()
    if sec == "visit" and not sec_label:
        out["secondary_label"] = "بازدید مجدد" if can_revisit else "ثبت بازدید"
        out["secondary_icon"] = str(out.get("secondary_icon") or "").strip() or "fa-calendar-plus"
    if sec and not str(out.get("secondary_label") or "").strip():
        out["secondary_action"] = ""
        out["secondary_icon"] = ""
        out["secondary_prompt"] = ""
    return out


def prepare_land_for_chat_detail(code: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """آماده‌سازی dict فایل + is_approved برای قالب جزئیات چت."""
    from flask import has_request_context

    from ..utils.images import sanitize_land_media
    from ..utils.storage import (
        load_ads_cached,
        load_express_assignments,
        load_express_commissions_cached,
        load_express_visit_requests,
    )
    from .new_land_sms import attach_express_land_commission
    from .sales_coach import build_journey_chat_cta
    from .visit_requests import (
        PENDING_STATUS,
        partner_active_visit_record,
        resolve_partner_land_tx_state,
        visit_progress_steps,
        visit_progress_summary,
    )

    # helpers اختصاصی در routes (بدون import دایره‌ای سطح ماژول)
    from . import routes as ep_routes

    code_s = (code or "").strip()
    if not code_s:
        return None, False

    lands = load_ads_cached() or []
    land = next(
        (l for l in lands if l.get("code") == code_s and l.get("is_express")),
        None,
    )
    if not land or not isinstance(land, dict):
        return None, False

    me_phone = ""
    if has_request_context():
        me_phone = (session.get("user_phone") or "").strip()
    partner_profile = ep_routes._partner_profile_for_phone(me_phone) if me_phone else None
    try:
        is_approved = ep_routes._is_partner_approved(partner_profile)
    except Exception:
        is_approved = False

    assignments = load_express_assignments() or []
    by_land_status, my_assign_by_code = ep_routes._express_assignment_indexes(
        assignments, me_phone
    )
    assignment = my_assign_by_code.get(code_s)
    global_assignment_status = by_land_status.get(code_s, "active")
    if ep_routes._express_land_marked_sold(land):
        global_assignment_status = "sold"

    land = dict(land)
    if assignment:
        land["_assignment_id"] = assignment.get("id")
    land["_assignment_status"] = global_assignment_status

    if is_approved:
        attach_express_land_commission(land)

    visit_requests_list = load_express_visit_requests() or []
    if not isinstance(visit_requests_list, list):
        visit_requests_list = []
    commissions_for_tx = load_express_commissions_cached() or []
    if not isinstance(commissions_for_tx, list):
        commissions_for_tx = []

    tx_state = resolve_partner_land_tx_state(
        me_phone=me_phone,
        land_code=code_s,
        assignments=assignments,
        visit_requests=visit_requests_list,
        is_partner_approved=is_approved,
        global_assignment_status=global_assignment_status,
        commissions=commissions_for_tx,
        visit_commission_required=ep_routes._visit_commission_required_for(
            commissions_for_tx, me_phone, code_s
        ),
    )
    land["_visit_date"] = tx_state.get("visit_date") or ""
    land["_visit_date_jalali"] = tx_state.get("visit_date_jalali") or ""
    land["_visit_status"] = tx_state.get("visit_status") or ""
    land["_visit_customer_phone"] = tx_state.get("customer_phone") or ""
    land["_visit_customer_name"] = tx_state.get("customer_name") or ""
    land["_tx_button_mode"] = tx_state.get("tx_mode") or "visit"
    land["_can_revisit"] = bool(tx_state.get("can_revisit"))

    visit_row = None
    if is_approved and me_phone:
        visit_row = partner_active_visit_record(visit_requests_list, me_phone, code_s)
    _attach_plus_feedback(land, visit_row)

    try:
        land["_chat_cta"] = _tune_land_chat_cta(
            build_journey_chat_cta(
                code=code_s,
                title=str(land.get("title") or "").strip(),
                tx_mode=str(land.get("_tx_button_mode") or ""),
                stage_label="",
                can_revisit=bool(land.get("_can_revisit")),
            ),
            can_revisit=bool(land.get("_can_revisit")),
        )
    except Exception:
        land["_chat_cta"] = {
            "label": "ثبت بازدید",
            "icon": "fa-calendar-days",
            "action": "visit",
            "prompt": (
                f"فایل {code_s}: قدم بعدی فروش را از چت پیش ببر و اگر ثبت لازم است "
                "ابزار مربوطه را با کارت تأیید پیشنهاد بده."
            ),
        }

    land["_visit_progress_steps"] = []
    land["_visit_progress_summary"] = {}
    if is_approved and me_phone:
        progress_row = visit_row
        if progress_row is None:
            progress_row = {
                "partner_phone": me_phone,
                "land_code": code_s,
                "status": PENDING_STATUS,
                "visit_requested": False,
            }
        progress_row = dict(progress_row)
        progress_row["visit_commission_required"] = ep_routes._visit_commission_required_for(
            commissions_for_tx, me_phone, code_s
        )
        progress_steps = visit_progress_steps(
            progress_row,
            commissions_for_tx,
            partner_phone=me_phone,
            visit_requests=visit_requests_list,
        )
        land["_visit_progress_steps"] = progress_steps
        land["_visit_progress_summary"] = visit_progress_summary(progress_steps)

    land = sanitize_land_media(land)
    return land, is_approved


def render_land_chat_detail_html(code: str) -> Optional[Dict[str, str]]:
    """HTML جزئیات برای حباب چت. None اگر فایل پیدا نشد."""
    raw = str(code or "").strip()
    if raw.lower().startswith("divar:"):
        return render_divar_chat_detail_html(raw.split(":", 1)[-1].strip())
    land, is_approved = prepare_land_for_chat_detail(raw)
    if not land:
        return None
    try:
        from app.crm.config import VISIT_CALL_TARGET

        visit_call_target = str(VISIT_CALL_TARGET or "09121471301").strip()
    except Exception:
        visit_call_target = "09121471301"
    html = render_template(
        "express_partner/partials/land_chat_detail.html",
        land=land,
        is_approved=is_approved,
        visit_call_target=visit_call_target,
    )
    return {
        "code": str(land.get("code") or code).strip(),
        "title": str(land.get("title") or "").strip(),
        "html": html,
    }


def prepare_divar_for_chat_detail(token: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """آگهی دیوار را به شکل کارت جزئیات چت وینور درمی‌آورد."""
    from flask import has_request_context

    from .divar_pro_ads import divar_ad_detail_payload, sanitize_divar_post_token
    from . import routes as ep_routes

    tok = sanitize_divar_post_token(token)
    if not tok:
        return None, False
    ad = divar_ad_detail_payload(tok)
    if not ad:
        return None, False

    me_phone = ""
    if has_request_context():
        me_phone = (session.get("user_phone") or "").strip()
    partner_profile = ep_routes._partner_profile_for_phone(me_phone) if me_phone else None
    try:
        is_approved = ep_routes._is_partner_approved(partner_profile)
    except Exception:
        is_approved = False

    images = [str(u).strip() for u in (ad.get("images") or []) if str(u or "").strip()]
    if not images and str(ad.get("image_url") or "").strip():
        images = [str(ad.get("image_url")).strip()]

    try:
        price_toman = int(ad.get("price_toman") or 0)
    except (TypeError, ValueError):
        price_toman = 0
    try:
        commission_amount = int(ad.get("commission_amount") or 0)
    except (TypeError, ValueError):
        commission_amount = 0

    land: Dict[str, Any] = {
        "code": f"divar:{tok}",
        "title": str(ad.get("title") or "آگهی دیوار").strip(),
        "city": "",
        "location": str(ad.get("location") or "").strip(),
        "images": images,
        "description": str(ad.get("description") or "").strip(),
        "price_total": price_toman,
        "price": price_toman,
        "_price_display": str(ad.get("price") or "").strip(),
        "_source": "divar",
        "_divar_url": str(ad.get("divar_url") or ad.get("url") or "").strip(),
        "_divar_rows": list(ad.get("rows") or []),
        "_commission_amount": max(0, commission_amount),
        "_commission_pct": ad.get("commission_pct") or 0,
        "_assignment_status": "",
        "_chat_cta": {},
        "_visit_progress_steps": [],
        "_visit_progress_summary": {},
    }
    return land, is_approved


def render_divar_chat_detail_html(token: str) -> Optional[Dict[str, str]]:
    land, is_approved = prepare_divar_for_chat_detail(token)
    if not land:
        return None
    try:
        from app.crm.config import VISIT_CALL_TARGET

        visit_call_target = str(VISIT_CALL_TARGET or "09121471301").strip()
    except Exception:
        visit_call_target = "09121471301"
    html = render_template(
        "express_partner/partials/land_chat_detail.html",
        land=land,
        is_approved=is_approved,
        visit_call_target=visit_call_target,
    )
    return {
        "code": str(land.get("code") or "").strip(),
        "title": str(land.get("title") or "").strip(),
        "html": html,
    }


def track_land_view_async(code: str) -> None:
    """ثبت بازدید پس‌زمینه (همان منطق صفحه قدیم)."""
    import threading
    from datetime import datetime

    from flask import current_app, request

    from ..utils.storage import load_express_partner_views, save_express_partner_views

    code_s = (code or "").strip()
    if not code_s:
        return
    try:
        app_obj = current_app._get_current_object()
        visitor_ip = request.remote_addr or ""
        user_agent = (request.headers.get("User-Agent", "") or "")[:200]

        def _worker() -> None:
            with app_obj.app_context():
                try:
                    views = load_express_partner_views() or []
                    if not isinstance(views, list):
                        views = []
                    now = datetime.utcnow()
                    today_str = now.strftime("%Y-%m-%d")
                    already = False
                    for v in reversed(views):
                        try:
                            if (v.get("ip") or "") != visitor_ip or (v.get("code") or "") != code_s:
                                continue
                            if (v.get("timestamp") or "")[:10] == today_str:
                                already = True
                                break
                        except Exception:
                            continue
                    if not already and visitor_ip and code_s:
                        views.append(
                            {
                                "timestamp": now.isoformat(),
                                "code": code_s,
                                "ip": visitor_ip,
                                "user_agent": user_agent,
                            }
                        )
                        if len(views) > 50000:
                            views = views[-50000:]
                        save_express_partner_views(views)
                except Exception:
                    app_obj.logger.exception(
                        "Error tracking express partner listing view code=%s", code_s
                    )

        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        pass
