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

    me_phone = ""
    if has_request_context():
        me_phone = (session.get("user_phone") or "").strip()

    lands = load_ads_cached() or []
    from .special_listings import resolve_listing_for_viewer

    land, _mode = resolve_listing_for_viewer(lands, code_s, me_phone)
    if not land or not isinstance(land, dict):
        return None, False

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


def _listing_image_urls(land: Dict[str, Any]) -> list[str]:
    out: list[str] = []
    raws = land.get("images") if isinstance(land.get("images"), list) else []
    for raw in raws:
        s = str(raw or "").strip()
        if not s:
            continue
        if s.startswith("http://") or s.startswith("https://") or s.startswith("/"):
            url = s
        else:
            url = "/uploads/" + s.lstrip("/")
        if url not in out:
            out.append(url)
        if len(out) >= 8:
            break
    return out


def _listing_spec_rows(land: Dict[str, Any], *, is_divar: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        lab = str(label or "").strip()
        val = str(value or "").strip()
        if not lab or not val or val in ("—", "-", "–"):
            return
        if any(r.get("label") == lab and r.get("value") == val for r in rows):
            return
        rows.append({"label": lab, "value": val})

    if is_divar:
        for item in land.get("_divar_rows") or []:
            if isinstance(item, dict):
                add(item.get("label") or item.get("title") or "", item.get("value") or item.get("text") or "")
        return rows

    st = str(land.get("_assignment_status") or "").strip()
    if st == "in_transaction":
        add("وضعیت معامله", "در حال معامله")
    elif st == "sold":
        add("وضعیت معامله", "فروخته‌شده")
    if land.get("category"):
        add("نوع", land.get("category"))
    if land.get("size"):
        add("متراژ", land.get("size"))
    if land.get("delivery") or land.get("handover") or land.get("delivery_days"):
        add(
            "تحویل",
            land.get("delivery")
            or land.get("handover")
            or (str(land.get("delivery_days")) + " روز کاری"),
        )
    if land.get("docs_status"):
        add("وضعیت سند", land.get("docs_status"))
    if land.get("payment_method"):
        add("نحوه پرداخت", land.get("payment_method"))
    try:
        from app.land_category_specs import land_category_detail_rows

        for item in land_category_detail_rows(land) or []:
            if isinstance(item, dict):
                add(item.get("label") or "", item.get("value") or "")
    except Exception:
        pass
    return rows[:18]


def _unpublish_confirm_payload(code: str) -> Dict[str, Any]:
    """پاسخ ۲۰۰ برای تأیید توقف، فقط وقتی جلسه مالک همین ملک است.

    اپ موفقیت را از ``published_for_sale: false`` می‌فهمد. ``ok: false`` تا
    صفحهٔ جزئیات عنوان آگهی نسازد. دیگران از همین مسیر ۴۰۴ می‌گیرند.
    """
    return {
        "ok": False,
        "error": "آگهی پیدا نشد.",
        "code": str(code or "").strip(),
        "published_for_sale": False,
        "sale_publish_expires_at": None,
        "sale_publish_remaining_seconds": None,
        "is_mine": True,
        "can_publish": True,
    }


def _sale_clock(land: Dict[str, Any], published: bool) -> Dict[str, Any]:
    """ساعت ۳۰روزه فقط وقتی خود آگهی برای فروش روشن است. پرچم جزئیاتِ آگهی عادی نیست."""
    empty = {
        "sale_publish_expires_at": None,
        "sale_publish_remaining_seconds": None,
    }
    if not published:
        return dict(empty)
    try:
        from app.listings.sale_publish_window import sale_publish_fields

        return sale_publish_fields(land)
    except Exception:
        return dict(empty)


def native_listing_detail_payload(
    code: str,
    *,
    source_hint: str = "",
    confirm_unpublish: bool = False,
) -> Optional[Dict[str, Any]]:
    """جزئیات آگهی برای صفحهٔ نیتیو وب و اپ — وینور یا دیوار."""
    raw = str(code or "").strip()
    if not raw:
        return None
    hint = str(source_hint or "").strip().lower()
    is_divar = hint == "divar" or raw.lower().startswith("divar:")
    if is_divar:
        tok = raw.split(":", 1)[-1].strip() if raw.lower().startswith("divar:") else raw
        land, _approved = prepare_divar_for_chat_detail(tok)
    else:
        land, _approved = prepare_land_for_chat_detail(raw)
        tok = ""
    if confirm_unpublish and not is_divar:
        from flask import has_request_context

        from ..utils.storage import load_ads_cached
        from .special_listings import unpublished_owner_home_only, viewer_owns_private_home

        lands = load_ads_cached() or []
        if unpublished_owner_home_only(lands, raw):
            me = str(session.get("user_phone") or "") if has_request_context() else ""
            if viewer_owns_private_home(lands, raw, me):
                return _unpublish_confirm_payload(raw)
            return None
    if not land:
        return None
    source = "divar" if (is_divar or str(land.get("_source") or "") == "divar") else "vinor"
    images = _listing_image_urls(land)
    try:
        price_toman = int(land.get("price_total") or land.get("price") or 0)
    except (TypeError, ValueError):
        price_toman = 0
    try:
        commission_amount = int(land.get("_commission_amount") or 0)
    except (TypeError, ValueError):
        commission_amount = 0
    divar_url = str(land.get("_divar_url") or "").strip()
    if source == "divar" and not divar_url and tok:
        try:
            from .divar_pro_ads import divar_public_url

            divar_url = divar_public_url(tok)
        except Exception:
            divar_url = f"https://divar.ir/v/{tok}"
    code_out = str(land.get("code") or raw).strip()
    city = str(land.get("city") or "").strip()
    location = str(land.get("location") or "").strip()
    size = str(land.get("size") or "").strip()
    category = str(land.get("category") or "").strip()
    meta_parts = [city, location, size, category]
    if source != "divar" and code_out:
        meta_parts.append(code_out)
    is_mine = False
    published = False
    sale_flag = True
    try:
        from flask import has_request_context as _has_req
        from .special_listings import (
            _same_phone,
            detail_sale_flag,
            is_my_property_record,
            is_published_for_sale,
        )

        me = ""
        if _has_req():
            me = str(session.get("user_phone") or "")
        owner = str(land.get("owner") or land.get("user_phone") or "")
        is_mine = bool(me and owner and _same_phone(me, owner) and is_my_property_record(land))
        published = is_published_for_sale(land)
        sale_flag = detail_sale_flag(land)
    except Exception:
        is_mine = False
        published = False
        sale_flag = True
    return {
        "ok": True,
        "source": source,
        "code": code_out,
        "title": str(land.get("title") or "").strip() or ("آگهی دیوار" if source == "divar" else "جزئیات آگهی"),
        "price": str(land.get("_price_display") or "").strip(),
        "price_toman": max(0, price_toman),
        "city": city,
        "location": location,
        "size": size,
        "category": category,
        "meta": " · ".join(p for p in meta_parts if p),
        "description": str(land.get("description") or land.get("body") or "").strip(),
        "images": images,
        "image_url": images[0] if images else "",
        "rows": _listing_spec_rows(land, is_divar=source == "divar"),
        "divar_url": divar_url,
        "divar_token": tok if source == "divar" else "",
        "commission_amount": max(0, commission_amount),
        "commission_pct": land.get("_commission_pct") or 0,
        "show_divar": source == "divar" and bool(divar_url),
        "can_favorite": source == "vinor",
        "is_mine": is_mine,
        "published_for_sale": sale_flag,
        **_sale_clock(land, published),
        "can_publish": bool(is_mine and not published),
        "owner_badge": (
            "منتشرشده" if is_mine and published else ("خصوصی" if is_mine else "")
        ),
    }
