from __future__ import annotations

import os
import json
import threading
from datetime import datetime
from typing import Any, Dict, List

from flask import (
    render_template, request, redirect, url_for, session,
    send_from_directory, current_app, abort, flash, g,
    has_request_context,
)
from functools import wraps
import random, re, time

from . import express_partner_bp
from .display import partner_avatar_initials, phone_last4


@express_partner_bp.app_template_filter("avatar_initials")
def _avatar_initials_filter(value: str | None) -> str:
    return partner_avatar_initials(value)


@express_partner_bp.app_template_filter("image_thumb_url")
def _image_thumb_url_filter(value: str | None) -> str:
    from ..utils.images import gallery_display_url
    return gallery_display_url(value)


@express_partner_bp.app_template_filter("dashboard_card_thumb_url")
def _dashboard_card_thumb_url_filter(value: str | None) -> str:
    from ..utils.images import gallery_display_url
    return gallery_display_url(value, max_width=420, quality=72)


@express_partner_bp.app_template_filter("image_display_full_url")
def _image_display_full_url_filter(value: str | None) -> str:
    from ..utils.images import normalize_upload_url
    return normalize_upload_url(value)


@express_partner_bp.app_template_filter("avatar_display_url")
def _avatar_display_url_filter(value: str | None, version: Any = "") -> str:
    from ..utils.images import display_avatar_url
    return display_avatar_url(value, version)


from ..utils.storage import (
    load_express_partner_apps, save_express_partner_apps,
    load_express_partners, load_express_partners_cached, save_express_partners, load_partner_notes, save_partner_notes,
    load_partner_sales, save_partner_sales,
    load_partner_files_meta, save_partner_files_meta,
    load_express_assignments, save_express_assignments, load_express_commissions, load_express_commissions_cached, save_express_commissions,
    load_express_reposts, save_express_reposts,
    load_ads_cached, load_active_cities, load_express_lands_cached,
    load_sms_history, save_sms_history,
    load_settings,
    load_express_partner_views, save_express_partner_views,
    load_partner_routines, load_partner_routines_cached, save_partner_routines,
    load_partner_bank_accounts, save_partner_bank_accounts,
    load_partner_withdrawals, save_partner_withdrawals,
    load_express_visit_requests, save_express_visit_requests,
    load_support_tickets, save_support_tickets,
)
from .partner_bank_accounts import (
    validate_new_account,
    public_account_dict,
    accounts_for_phone,
    catalog_public,
    apply_account_fields,
)
from .partner_withdrawals import (
    withdrawable_balance,
    available_for_new_withdrawal,
    validate_new_request,
    admin_row_dict,
    withdrawals_for_phone,
    reserved_withdrawal_total,
    active_withdrawals_for_phone,
    build_partner_txn_feed,
    partner_txn_feed_summary,
    partner_commission_dashboard,
    reconcile_paid_withdrawals,
    cancel_partner_withdrawal,
    MIN_WITHDRAWAL_AMOUNT,
)
from .routine_auto import (
    merge_routine_steps_for_phone,
    routine_detail_for_phone,
    ROUTINE_STEP_MARKETING,
    ROUTINE_STEP_VISIT,
    ROUTINE_STEP_DEAL,
)
from .visit_requests import (
    create_visit_request as record_visit_request,
    partner_open_visit,
    partner_visit_approved_for_deal,
    partner_visit_completed,
    request_visit_done_confirmation,
    restore_visit_approved_after_deal_release,
    visit_commission_ready_for_deal,
    visit_progress_steps,
    visit_progress_summary,
    visit_date_min_iso,
    visit_allowed_weekdays_for_js,
    resolve_partner_land_tx_state,
    PENDING_STATUS,
    APPROVED_STATUS,
    DONE_PENDING_STATUS,
    COMPLETED_STATUS,
    CANCELLED_STATUS,
)
from .commissions_flow import commission_blocks_new_deal_record, commission_is_deal, commission_is_visit
from .support_tickets import (
    MESSAGE_MAX_LEN,
    MESSAGE_MIN_LEN,
    TICKET_CATEGORIES,
    create_support_ticket,
    partner_ticket_error_message,
    partner_ticket_stats,
    tickets_for_phone,
)
from .admin_action_sms import notify_admin_pending_action
from ..utils.dates import format_iso_date_jalali
from ..services.notifications import get_user_notifications, unread_count, mark_read, mark_all_read
from ..services.sms import (
    send_sms_direct,
    normalize_iran_mobile,
    is_valid_iran_mobile,
    sms_is_infrastructure_error,
)
from app.services.sms_config import get_sms_line_number
from flask import jsonify, make_response


def _express_land_marked_sold(land: Dict[str, Any] | None) -> bool:
    if not land or not isinstance(land, dict):
        return False
    return str(land.get('express_status') or '').strip().lower() == 'sold'


def _effective_land_status(global_status: str, land: Dict[str, Any]) -> str:
    if _express_land_marked_sold(land):
        return 'sold'
    return (global_status or 'active').strip().lower() or 'active'


def _sort_by_created_at_desc(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..utils.dates import parse_datetime_safe
    return sorted(items, key=lambda x: parse_datetime_safe(x.get('created_at', '1970-01-01')), reverse=True)


def _sort_dashboard_lands_sold_last(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """فایل‌های فروخته‌شده در انتهای لیست داشبورد؛ بقیه بر اساس تاریخ (جدیدتر اول)."""
    from ..utils.dates import parse_datetime_safe

    active: List[Dict[str, Any]] = []
    sold: List[Dict[str, Any]] = []
    for item in items:
        st = (str(item.get('_assignment_status') or 'active')).strip().lower()
        if st == 'sold':
            sold.append(item)
        else:
            active.append(item)
    key_fn = lambda x: parse_datetime_safe(x.get('created_at', '1970-01-01'))
    active.sort(key=key_fn, reverse=True)
    sold.sort(key=key_fn, reverse=True)
    return active + sold


def _is_land_sold(land: Dict[str, Any]) -> bool:
    return (str(land.get('_assignment_status') or 'active')).strip().lower() == 'sold'


def _truncate_dashboard_lands(
    items: List[Dict[str, Any]], limit: int
) -> tuple[List[Dict[str, Any]], bool]:
    """نمایش اولیه: جدیدترین فایل‌ها تا سقف limit."""
    sorted_items = _sort_by_created_at_desc(items)
    if len(sorted_items) <= limit:
        return sorted_items, False
    return sorted_items[:limit], True


def _build_partner_dashboard_lands(
    me_phone: str,
    is_approved: bool,
    *,
    search_query: str = '',
    selected_cities: Optional[List[str]] = None,
    filter_tag: str = '',
    filter_cat: str = '',
) -> tuple[List[Dict[str, Any]], int]:
    """لیست کارت‌های داشبورد همکار (همه فایل‌های اکسپرس + وضعیت تخصیص)."""
    from ..utils.dates import is_ad_expired
    from ..utils.images import sanitize_land_media

    ph = (me_phone or '').strip()
    cities = selected_cities or []
    q = (search_query or '').strip().lower()
    tag = (filter_tag or '').strip().lower()
    cat = (filter_cat or '').strip()

    try:
        assignments = load_express_assignments() or []
        _maybe_auto_release_expired_transactions(assignments)
    except Exception:
        assignments = []

    my_assignments = [
        a for a in assignments
        if str(a.get('partner_phone')) == ph
        and a.get('status') in (None, 'active', 'pending', 'approved', 'in_transaction', 'sold')
    ]
    lands_all = load_ads_cached() or []
    code_to_land = {str(l.get('code')): l for l in lands_all}
    expired_count = 0

    try:
        my_reposts = [r for r in (load_express_reposts() or []) if str(r.get('partner_phone')) == ph]
        my_reposted_codes = {str(r.get('code')) for r in my_reposts}
    except Exception:
        my_reposted_codes = set()

    code_to_assigned: Dict[str, Dict[str, Any]] = {}
    for a in my_assignments:
        land = code_to_land.get(str(a.get('land_code')))
        if not land:
            continue
        is_expired = is_ad_expired(land)
        if is_expired:
            expired_count += 1
        item = dict(land)
        item['_assignment_id'] = a.get('id')
        item['_assignment_status'] = _assignment_display_status(a)
        item['_is_expired'] = is_expired
        if not item.get('created_at'):
            item['created_at'] = land.get('created_at') or '1970-01-01'
        from .new_land_sms import attach_express_land_commission
        if is_approved:
            attach_express_land_commission(item)
        item['_share_url'] = ''
        item['_share_token'] = ''
        item['_reposted_by_me'] = str(item.get('code')) in my_reposted_codes
        code_to_assigned[str(item.get('code'))] = item

    try:
        display_lands = load_express_lands_cached() or []
    except Exception:
        display_lands = []

    if cities:
        city_set = set(cities)
        display_lands = [l for l in display_lands if str(l.get('city') or '').strip() in city_set]

    if q:
        terms = q.split()

        def _matches(ln: Dict[str, Any]) -> bool:
            text = ' '.join([
                str(ln.get('title') or ''),
                str(ln.get('location') or ''),
                str(ln.get('city') or ''),
                str(ln.get('category') or ''),
                str(ln.get('description') or ''),
            ]).lower()
            return all(t in text for t in terms)

        display_lands = [l for l in display_lands if _matches(l)]

    def _land_text_blob(ln: Dict[str, Any]) -> str:
        parts = [
            str(ln.get('title') or ''),
            str(ln.get('description') or ''),
            str(ln.get('features') or ''),
            str(ln.get('location') or ''),
            str(ln.get('category') or ''),
            str(ln.get('payment_method') or ''),
        ]
        return ' '.join(parts).lower()

    if cat == 'land_garden':
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('category') or '').strip() in ('زمین', 'باغ')
        ]
    elif cat:
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('category') or '').strip() == cat
        ]

    if tag == 'pool':
        display_lands = [ln for ln in display_lands if 'استخر' in _land_text_blob(ln)]
    elif tag == 'forest':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('جنگل', 'جنگلی', 'بوستان'))
        ]
    elif tag == 'town':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('شهرک', 'شهرکی', 'مجتمع'))
        ]
    elif tag == 'urgent':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('فوری', 'فرصت', 'فوریت'))
        ]
    elif tag == 'deed':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('سند', 'سنددار', 'تک‌برگ', 'تک برگ'))
        ]
    elif tag == 'invest':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('سرمایه', 'سرمایه‌گذاری', 'سودآور'))
        ]
    elif tag == 'installment':
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('payment_method') or '').strip() == 'اقساطی'
            or 'قسط' in _land_text_blob(ln)
        ]

    display_lands = _sort_by_created_at_desc(display_lands)

    code_to_global_status: Dict[str, str] = {}
    status_priority = {
        'sold': 5,
        'in_transaction': 4,
        'closed': 3,
        'pending': 2,
        'approved': 1,
        'active': 0,
        '': 0,
    }
    for a in assignments:
        code_key = str(a.get('land_code') or '')
        if not code_key:
            continue
        status = _assignment_display_status(a)
        current = code_to_global_status.get(code_key, 'active')
        if status_priority.get(status, 0) > status_priority.get(current, 0):
            code_to_global_status[code_key] = status

    assigned_lands: List[Dict[str, Any]] = []
    for land in display_lands:
        code = str(land.get('code') or '')
        item = dict(land)
        assigned_item = code_to_assigned.get(code)
        global_status = _effective_land_status(
            code_to_global_status.get(code, item.get('_assignment_status') or 'active'),
            item,
        )
        if assigned_item and is_approved:
            item['_assignment_id'] = assigned_item.get('_assignment_id')
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_is_expired'] = assigned_item.get('_is_expired', False)
            item['_share_url'] = assigned_item.get('_share_url', '')
            item['_share_token'] = assigned_item.get('_share_token', '')
            item['_reposted_by_me'] = assigned_item.get('_reposted_by_me', False)
            item['_detail_url'] = url_for('express_partner.land_detail', code=code)
        else:
            item.setdefault('created_at', land.get('created_at') or '1970-01-01')
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_detail_url'] = url_for('express_partner.land_detail', code=code)
        if is_approved:
            from .new_land_sms import attach_express_land_commission
            attach_express_land_commission(item)
        assigned_lands.append(sanitize_land_media(item))

    return _sort_by_created_at_desc(assigned_lands), expired_count


def _express_partners_cached() -> List[Dict[str, Any]]:
    """در هر درخواست فقط یک‌بار لیست همکاران از دیسک خوانده می‌شود."""
    cached = getattr(g, '_express_partners_list_cached', None)
    if cached is not None:
        return cached
    try:
        lst = load_express_partners_cached() or []
    except Exception:
        lst = []
    g._express_partners_list_cached = lst
    return lst


def _partner_profile_for_phone(phone: str) -> Dict[str, Any] | None:
    """پروفایل یک همکار از لیست کش‌شدهٔ درخواست (بدون خواندن مجدد فایل)."""
    phone = (phone or '').strip()
    if not phone:
        return None
    norm = _normalize_phone(phone)
    by_phone = getattr(g, '_express_partner_by_phone', None)
    if by_phone is None:
        partners = _express_partners_cached()
        by_phone = {}
        for p in partners:
            if not isinstance(p, dict):
                continue
            p_phone = str(p.get('phone') or '').strip()
            if not p_phone:
                continue
            by_phone[p_phone] = p
            pn = _normalize_phone(p_phone)
            if pn:
                by_phone.setdefault(pn, p)
        g._express_partner_by_phone = by_phone
    return by_phone.get(phone) or (by_phone.get(norm) if norm else None)


def _find_partner_record(partners: List[Dict[str, Any]], phone: str) -> Dict[str, Any] | None:
    """یافتن رکورد همکار با تطبیق نرمال‌شدهٔ شماره."""
    raw = (phone or '').strip()
    if not raw:
        return None
    norm = _normalize_phone(raw)
    for p in partners:
        if not isinstance(p, dict):
            continue
        p_phone = str(p.get('phone') or '').strip()
        if not p_phone:
            continue
        if p_phone == raw or p_phone == norm or _normalize_phone(p_phone) == norm:
            return p
    return None


def _canonical_partner_phone(phone: str) -> str:
    raw = (phone or '').strip()
    return _normalize_phone(raw) or raw


def _get_or_create_partner_record(partners: List[Dict[str, Any]], phone: str) -> Dict[str, Any]:
    """رکورد همکار برای ذخیره — یک شمارهٔ کانonical در JSON."""
    prof = _find_partner_record(partners, phone)
    canonical = _canonical_partner_phone(phone)
    if prof:
        if canonical and str(prof.get('phone') or '').strip() != canonical:
            prof['phone'] = canonical
        return prof
    prof = {'phone': canonical}
    partners.append(prof)
    return prof


def _ensure_session_partner_on_g() -> None:
    """یک‌بار در هر درخواست: پروفایل همکار جاری روی g."""
    if getattr(g, '_express_partner_ctx_ready', False):
        return
    g._express_partner_ctx_ready = True
    me_phone = (session.get('user_phone') or '').strip()
    if not me_phone:
        g.express_partner_profile = None
        return
    g.express_partner_profile = _partner_profile_for_phone(me_phone)


def _express_commissions_cached() -> List[Dict[str, Any]]:
    if getattr(g, '_express_commissions_cached', None) is not None:
        return g._express_commissions_cached
    try:
        lst = load_express_commissions_cached() or []
    except Exception:
        lst = []
    if not isinstance(lst, list):
        lst = []
    g._express_commissions_cached = lst
    return lst


def _commissions_for_phone(phone: str) -> List[Dict[str, Any]]:
    phone = (phone or '').strip()
    if not phone:
        return []
    from .partner_withdrawals import partner_phones_match

    cache_key = '_express_my_comms_' + phone
    cached = getattr(g, cache_key, None)
    if cached is not None:
        return cached
    mine = [
        c for c in _express_commissions_cached()
        if isinstance(c, dict) and partner_phones_match(c.get('partner_phone'), phone)
    ]
    setattr(g, cache_key, mine)
    return mine


def _partner_withdrawals_raw() -> List[Dict[str, Any]]:
    items = load_partner_withdrawals() or []
    return items if isinstance(items, list) else []


def _reconcile_partner_commissions(phone: str) -> None:
    """هم‌تراز کردن برداشت‌های paid با پورسانت‌ها (در صورت نیاز ذخیره)."""
    ph = (phone or '').strip()
    if not ph:
        return
    wd = _partner_withdrawals_raw()
    all_comms = _express_commissions_cached() or []
    dirty = reconcile_paid_withdrawals(all_comms, wd, ph)
    if dirty:
        try:
            save_express_commissions(all_comms)
            save_partner_withdrawals(wd)
        except Exception:
            current_app.logger.exception('reconcile_paid_withdrawals failed')


def _partner_commission_stats(phone: str, commissions: List[Dict[str, Any]]) -> Dict[str, Any]:
    _reconcile_partner_commissions(phone)
    ph = (phone or '').strip()
    wd = _partner_withdrawals_raw()
    all_comms = _express_commissions_cached() or []
    return partner_commission_dashboard(all_comms, wd, ph)


def _partner_withdrawable_balance(phone: str) -> int:
    ph = (phone or '').strip()
    if not ph:
        return 0
    _reconcile_partner_commissions(ph)
    return withdrawable_balance(_express_commissions_cached() or [], _partner_withdrawals_raw(), ph)


def _partner_requestable_balance(phone: str) -> int:
    ph = (phone or '').strip()
    if not ph:
        return 0
    _reconcile_partner_commissions(ph)
    return available_for_new_withdrawal(_express_commissions_cached() or [], _partner_withdrawals_raw(), ph)


def _partner_withdrawal_items(phone: str) -> List[Dict[str, Any]]:
    return active_withdrawals_for_phone(_partner_withdrawals_raw(), phone)


def _partner_txn_items(phone: str, commissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return build_partner_txn_feed(commissions, _partner_withdrawals_raw(), phone)


def _partner_pending_withdrawal_total(phone: str) -> int:
    return reserved_withdrawal_total(_partner_withdrawals_raw(), phone)


def _partner_display_name(phone: str) -> str:
    ph = (phone or '').strip()
    if not ph:
        return ''
    try:
        profile = getattr(g, 'express_partner_profile', None)
        if profile and isinstance(profile, dict) and str(profile.get('phone') or '').strip() == ph:
            name = (str(profile.get('name') or '')).strip()
            if name:
                return name
    except Exception:
        pass
    try:
        for p in _express_partners_cached():
            if str(p.get('phone') or '').strip() == ph:
                return (str(p.get('name') or '')).strip()
    except Exception:
        pass
    return ph[-4:] if len(ph) >= 4 else ph


def _attach_commission_txn_labels(my_comms: List[Dict[str, Any]]) -> None:
    codes = {str(c.get('land_code') or '').strip() for c in my_comms if c.get('land_code')}
    lo: Dict[str, Dict[str, Any]] = {}
    if codes:
        try:
            lands = load_express_lands_cached() or []
            lo = {
                str(x.get('code')): x
                for x in lands
                if str(x.get('code') or '') in codes
            }
        except Exception:
            lo = {}
    for c in my_comms:
        if (c.get('commission_type') or '').strip() == 'manual_adjustment':
            c['_txn_label'] = 'تعدیل موجودی'
            note = (str(c.get('admin_note') or '')).strip()
            prev = c.get('adjustment_previous')
            tgt = c.get('adjustment_target')
            if note:
                c['_txn_meta'] = note
            elif prev is not None and tgt is not None:
                c['_txn_meta'] = f'از {int(prev):,} به {int(tgt):,} تومان'
            else:
                c['_txn_meta'] = 'توسط ادمین'
            continue
        if (c.get('commission_type') or '').strip() == 'referral':
            c['_txn_label'] = 'پورسانت دعوت'
            name = (str(c.get('referred_name') or '')).strip()
            phone = (str(c.get('referred_phone') or '')).strip()
            c['_txn_meta'] = name or phone or ''
            continue
        L = lo.get(str(c.get('land_code', '') or ''))
        c['_txn_label'] = 'پورسانت فروش'
        code = str(c.get('land_code') or '').strip()
        if L:
            title = (str(L.get('title') or L.get('category') or '')).strip()
            city = (str(L.get('city') or '')).strip()
            parts = []
            if code:
                parts.append(code)
            if title and title != 'ملک':
                parts.append(title)
            if city:
                parts.append(city)
            c['_txn_meta'] = ' · '.join(parts) if parts else code
        else:
            c['_txn_meta'] = code


def _invalidate_partner_session_cache() -> None:
    """پس از تغییر پروفایل: کش درخواست و پرچم نقش در سشن."""
    for key in (
        '_express_partners_list_cached',
        '_express_partner_by_phone',
        '_express_partner_ctx_ready',
        'express_partner_profile',
        '_express_commissions_cached',
    ):
        if hasattr(g, key):
            try:
                delattr(g, key)
            except Exception:
                pass
    try:
        session.pop('VINOR_IS_EXPRESS_PARTNER', None)
    except Exception:
        pass


def _active_cities_cached() -> List[str]:
    """لیست شهرهای فعال — یک‌بار در هر درخواست."""
    cached = getattr(g, '_active_cities_cached', None)
    if cached is not None:
        return cached
    try:
        cities = load_active_cities() or []
    except Exception:
        cities = []
    if not isinstance(cities, list):
        cities = []
    g._active_cities_cached = cities
    return cities


def _express_settings_cached() -> Dict[str, Any]:
    """در هر درخواست یک‌بار تنظیمات (برای پروفایل و غیره)."""
    if getattr(g, '_express_settings_loaded', False):
        return getattr(g, '_express_settings_data', {}) or {}
    g._express_settings_loaded = True
    try:
        data = load_settings() or {}
    except Exception:
        data = {}
    g._express_settings_data = data
    return data


def _append_partner_tab_prefetch(resp):
    """غیرفعال: prefetch سه صفحهٔ HTML همزمان ناوبری را کند می‌کرد."""
    return resp


DASHBOARD_INITIAL_CARD_LIMIT = 12


def _is_mobile_partner_client() -> bool:
    """موبایل / WebView اپ — برای حذف HTML دسکتاپ از پاسخ اول."""
    ua = (request.headers.get("User-Agent") or "").lower()
    compact = ua.replace(" ", "")
    if "vinorapp" in compact:
        return True
    return any(
        tok in ua
        for tok in ("iphone", "ipod", "ipad", "android", "mobile", "webos", "opera mini", "iemobile")
    )


def _dashboard_request_has_filters(search_query: str, selected_cities: list, filter_tag: str, filter_cat: str) -> bool:
    return bool(search_query or selected_cities or filter_tag or filter_cat)


OTP_TTL_SECONDS = 600  # ۱۰ دقیقه — هر کد فقط برای همان شماره و همان بازهٔ زمانی


def _normalize_phone(phone: str) -> str:
    """Normalize phone number - استفاده از همان تابع notifications"""
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(phone)


def _otp_canonical_phone(phone: str) -> str:
    """یکسان‌سازی شماره برای ذخیره/تطبیق OTP."""
    from ..services.sms import normalize_iran_mobile

    raw = _normalize_phone(phone)
    return normalize_iran_mobile(raw) or raw


def _otp_session_phone() -> str:
    return _otp_canonical_phone(str(session.get('otp_phone') or ''))


def _otp_session_expired() -> bool:
    ts = session.get('otp_created_at')
    if ts is None:
        return False
    try:
        return (time.time() - float(ts)) > OTP_TTL_SECONDS
    except (TypeError, ValueError):
        return True


def _otp_code_matches_session(code: str) -> bool:
    """تطبیق کد OTP با سشن فعلی (بدون بررسی شماره — فقط برای resend داخلی)."""
    if not code:
        return False
    from ..services.sms import normalize_otp_code

    sess_code = normalize_otp_code(str(session.get('otp_code') or ''))
    norm_code = normalize_otp_code(code)
    sess_phone = _otp_session_phone()
    return (
        len(norm_code) == 5
        and len(sess_code) == 5
        and sess_code == norm_code
        and bool(sess_phone)
    )


def _otp_session_matches(code: str, phone: str) -> bool:
    """کد و شماره باید هر دو با سشن OTP یکسان باشند."""
    if not code or not phone:
        return False
    if _otp_session_expired():
        return False
    norm_phone = _otp_canonical_phone(phone)
    sess_phone = _otp_session_phone()
    if not norm_phone or not sess_phone or norm_phone != sess_phone:
        return False
    return _otp_code_matches_session(code)


def _verify_otp_for_phone(code: str, phone: str) -> str | None:
    """
    تأیید OTP برای شمارهٔ مشخص.
    در صورت موفقیت شمارهٔ canonical برمی‌گرداند؛ در غیر این صورت None.
    """
    if _otp_session_expired():
        _clear_otp_session()
        return None
    if not _otp_session_matches(code, phone):
        return None
    return _canonical_partner_phone(_otp_session_phone())


def _clear_otp_session() -> None:
    session.pop('otp_code', None)
    session.pop('otp_phone', None)
    session.pop('otp_created_at', None)


def _auth_wants_json() -> bool:
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return False
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


def _store_otp_session(phone: str, code: str) -> None:
    _clear_otp_session()
    canonical = _otp_canonical_phone(phone)
    session.permanent = True
    session.update({
        'otp_code': str(code),
        'otp_phone': canonical,
        'otp_created_at': time.time(),
    })
    try:
        session.modified = True
    except Exception:
        pass


def _dispatch_otp_sms(phone: str, code: str) -> None:
    """ارسال OTP در پس‌زمینه — پاسخ HTTP بلافاصله برگردد."""
    app = current_app._get_current_object()

    def _worker() -> None:
        with app.app_context():
            try:
                from ..services.sms import send_sms_code

                result = send_sms_code(phone, code)
                if not result.get('ok'):
                    app.logger.error(
                        'async OTP SMS failed | phone=%s | status=%s | body=%s',
                        phone,
                        result.get('status'),
                        result.get('body'),
                    )
            except Exception:
                app.logger.exception('async OTP SMS exception | phone=%s', phone)

    threading.Thread(target=_worker, daemon=True).start()


def _ensure_user_record_background(phone: str) -> None:
    app = current_app._get_current_object()

    def _worker() -> None:
        with app.app_context():
            try:
                from ..utils.storage import load_users, save_users

                users = load_users()
                if any(u.get('phone') == phone for u in users):
                    return
                users.append({
                    'phone': phone,
                    'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
                save_users(users)
            except Exception:
                app.logger.exception('background user record failed | phone=%s', phone)

    threading.Thread(target=_worker, daemon=True).start()


def _login_next_preserve():
    nxt = (request.args.get('next') or request.form.get('next') or '').strip()
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return None


def _session_next_safe():
    raw = session.get('next')
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith('/') and not raw.startswith('//'):
            return raw
    return None


def _post_login_path_only(url: str) -> str:
    raw = (url or '').strip()
    if not raw:
        return '/'
    if '://' in raw:
        try:
            from urllib.parse import urlparse
            raw = urlparse(raw).path or '/'
        except Exception:
            pass
    path = raw.split('?', 1)[0].strip()
    return path.rstrip('/') or '/'


def _is_generic_post_login_next(url: str) -> bool:
    """مسیرهایی که فقط «بعد از ورود به پنل» هستند، نه deep link واقعی."""
    path = _post_login_path_only(url)
    if path in ('/', '/express/partner'):
        return True
    if path == _post_login_path_only(url_for('express_partner.dashboard')):
        return True
    if path.startswith('/express/partner/login'):
        return True
    return False


def _is_express_soft_nav_request() -> bool:
    return (request.headers.get('X-Requested-With') or '').strip() == 'XMLHttpRequest'


def _is_dashboard_refresh_from_self() -> bool:
    try:
        ref = (request.referrer or '').strip()
        if not ref:
            return False
        from urllib.parse import urlparse
        ref_path = _post_login_path_only(urlparse(ref).path or '/')
        dash_path = _post_login_path_only(url_for('express_partner.dashboard'))
        return ref_path == dash_path
    except Exception:
        return False


def _is_express_partner_in_app_referrer() -> bool:
    """کلیک تب پایین یا لینک داخلی — داشبورد نباید به پورسانت ریدایرکت شود."""
    try:
        ref = (request.referrer or '').strip()
        if not ref:
            return False
        from urllib.parse import urlparse
        ref_path = _post_login_path_only(urlparse(ref).path or '/')
        if not ref_path.startswith('/express/partner'):
            return False
        if ref_path.startswith('/express/partner/login'):
            return False
        return True
    except Exception:
        return False


def _should_redirect_partner_default_to_commissions() -> bool:
    """ورود مستقیم/باز کردن اپ → پورسانت؛ ناوبری داخلی یا رفرش داشبورد → بدون ریدایرکت."""
    if _is_express_soft_nav_request():
        return False
    if _is_dashboard_refresh_from_self():
        return False
    if _is_express_partner_in_app_referrer():
        return False
    return True


def _is_phone_approved_partner(phone: str) -> bool:
    """همکار تأییدشده — از کش درون‌پردازشی partners (بدون I/O تکراری)."""
    phone = (phone or '').strip()
    if not phone:
        return False
    try:
        prof = _partner_profile_for_phone(phone)
        if _is_partner_approved(prof):
            return True
        partners = _express_partners_cached()
        prof = _find_partner_record(partners, phone)
        return _is_partner_approved(prof)
    except Exception:
        return False


def _cache_session_partner_role(is_partner: bool) -> None:
    try:
        session['VINOR_IS_EXPRESS_PARTNER'] = bool(is_partner)
        session.modified = True
    except Exception:
        pass


def _default_post_login_url(phone: str) -> str:
    """پیش‌فرض بعد از ورود: همکار → پورسانت، کاربر عادی → داشبورد."""
    is_partner = _is_phone_approved_partner(phone)
    _cache_session_partner_role(is_partner)
    if is_partner:
        return url_for('express_partner.commissions')
    return url_for('express_partner.dashboard')


def _redirect_after_login(phone: str | None = None) -> str:
    """deep link صریح اولویت دارد؛ مسیرهای عمومی برای همکار → پورسانت."""
    nxt = _login_next_preserve() or _session_next_safe()
    ph = _canonical_partner_phone(phone or session.get('user_phone') or '')
    is_partner = _is_phone_approved_partner(ph)
    _cache_session_partner_role(is_partner)
    if nxt and not (is_partner and _is_generic_post_login_next(nxt)):
        try:
            session.pop('next', None)
        except Exception:
            pass
        return nxt
    try:
        session.pop('next', None)
    except Exception:
        pass
    return _default_post_login_url(ph)


def _finalize_partner_login(phone: str) -> str:
    canonical = _canonical_partner_phone(phone)
    session['user_id'] = canonical
    session['user_phone'] = canonical
    session.permanent = True
    _clear_otp_session()
    _ensure_user_record_background(phone)
    try:
        from .referrals import stash_referrer_from_request
        stash_referrer_from_request(phone)
    except Exception:
        pass
    try:
        session.pop('VINOR_IS_EXPRESS_PARTNER', None)
        session.modified = True
    except Exception:
        pass
    return _redirect_after_login(canonical)


def _login_otp_redirect_url() -> str:
    return url_for('express_partner.login_otp')


def _is_prefetch_request() -> bool:
    """درخواست prefetch مرورگر — نباید به‌عنوان بازدید واقعی فایل شمرده شود."""
    if (request.headers.get("X-Vinor-Prefetch") or "").strip() == "1":
        return True
    purpose = (request.headers.get("Purpose") or request.headers.get("Sec-Purpose") or "").lower()
    return "prefetch" in purpose


def _login_change_clears_otp() -> bool:
    """پاک‌کردن OTP فقط برای ناوبری واقعی «تغییر شماره»، نه prefetch پس‌زمینه."""
    return not _is_prefetch_request()


def _routine_auto_tick(phone: str, *step_ids: str) -> None:
    """ثبت خودکار تیک روتین برای همکار تأییدشده (مستقل از باز شدن صفحه روتین)."""
    ph = (phone or "").strip()
    if not ph or not step_ids:
        return
    try:
        partners = load_express_partners_cached() or []
        prof = next(
            (p for p in partners if str(p.get("phone") or "").strip() == ph),
            None,
        )
        if not _is_partner_approved(prof):
            return
        today = datetime.now().strftime("%Y-%m-%d")
        have = set(routine_detail_for_phone(ph, today))
        to_add = [
            str(s).strip()
            for s in step_ids
            if str(s).strip() in ("1", "2", "3") and str(s).strip() not in have
        ]
        if not to_add:
            return
        merge_routine_steps_for_phone(ph, *to_add)
    except Exception:
        current_app.logger.exception("routine auto tick failed phone=%s steps=%s", ph, step_ids)


def _defer_routine_auto_tick(phone: str, *step_ids: str) -> None:
    """روتین روزانه را در پس‌زمینه ثبت کن — مسیر ورود/OTP مسدود نشود."""
    app = current_app._get_current_object()
    ph = (phone or "").strip()
    steps = tuple(step_ids)

    def _worker() -> None:
        with app.app_context():
            try:
                _routine_auto_tick(ph, *steps)
            except Exception:
                app.logger.exception("deferred routine auto tick failed phone=%s", ph)

    threading.Thread(target=_worker, daemon=True).start()


def _defer_online_partner_ping(phone: str, name: str | None, ip: str) -> None:
    app = current_app._get_current_object()
    ph = (phone or '').strip()
    nm = (name or '').strip() or None
    addr = (ip or 'نامشخص').strip()

    def _worker() -> None:
        with app.app_context():
            try:
                import admin.routes as admin_routes_module
                if hasattr(admin_routes_module, '_update_online_partner'):
                    admin_routes_module._update_online_partner(ph, nm, addr)
            except Exception:
                app.logger.exception('online partner ping failed phone=%s', ph)

    threading.Thread(target=_worker, daemon=True).start()


def _mark_routine_today(phone: str) -> bool:
    """ثبت روز جاری برای روتین همکار (بازگشت True در صورت تغییر)."""
    if not phone:
        return False
    today = datetime.now().strftime('%Y-%m-%d')
    records = load_partner_routines()
    rec = next((r for r in records if str(r.get('phone')) == phone), None)
    if not rec:
        rec = {"phone": phone, "days": [], "updated_at": None}
        records.append(rec)
    if today in rec.get('days', []):
        return False
    rec.setdefault('days', []).append(today)
    rec['days'] = sorted(set(rec['days']))
    rec['updated_at'] = datetime.utcnow().isoformat() + "Z"
    save_partner_routines(records)
    return True


def _lands_for_favorite_codes(codes: List[str], me_phone: str) -> List[Dict[str, Any]]:
    """ساخت لیست کارت‌های علاقه‌مندی بر اساس کدهای ذخیره‌شده در مرورگر."""
    ordered = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not ordered:
        return []
    code_set = set(ordered)
    try:
        display_lands = load_express_lands_cached() or []
    except Exception:
        display_lands = []
    code_to_land = {
        str(l.get('code')): l
        for l in display_lands
        if str(l.get('code') or '') in code_set
    }
    try:
        assignments = load_express_assignments() or []
        _maybe_auto_release_expired_transactions(assignments)
    except Exception:
        assignments = []
    code_to_global_status: Dict[str, str] = {}
    status_priority = {
        'sold': 5,
        'in_transaction': 4,
        'closed': 3,
        'pending': 2,
        'approved': 1,
        'active': 0,
        '': 0,
    }
    for a in assignments:
        code_key = str(a.get('land_code') or '')
        if not code_key:
            continue
        status = _assignment_display_status(a)
        current = code_to_global_status.get(code_key, 'active')
        if status_priority.get(status, 0) > status_priority.get(current, 0):
            code_to_global_status[code_key] = status
    my_by_code = {
        str(a.get('land_code')): a
        for a in assignments
        if str(a.get('partner_phone')) == me_phone
    }
    try:
        my_reposts = [r for r in (load_express_reposts() or []) if str(r.get('partner_phone')) == me_phone]
        my_reposted_codes = {str(r.get('code')) for r in my_reposts}
    except Exception:
        my_reposted_codes = set()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    from ..utils.dates import is_ad_expired
    result: List[Dict[str, Any]] = []
    for code in ordered:
        land = code_to_land.get(code)
        if not land:
            continue
        item = dict(land)
        global_status = _effective_land_status(code_to_global_status.get(code, 'active'), item)
        a = my_by_code.get(code)
        if a and is_approved:
            item['_assignment_id'] = a.get('id')
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_is_expired'] = is_ad_expired(land)
            from .new_land_sms import attach_express_land_commission
            attach_express_land_commission(item)
            item['_share_url'] = ''
            item['_share_token'] = ''
            item['_reposted_by_me'] = code in my_reposted_codes
        else:
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_is_expired'] = is_ad_expired(land)
            if is_approved:
                from .new_land_sms import attach_express_land_commission
                attach_express_land_commission(item)
        item.setdefault('created_at', land.get('created_at') or '1970-01-01')
        item['_detail_url'] = url_for('express_partner.land_detail', code=code)
        result.append(item)
    return _sort_dashboard_lands_sold_last(result)


def _assignment_display_status(assignment: Dict[str, Any] | None) -> str:
    """وضعیت نمایشی اختصاص — transaction_holder همیشه به in_transaction نگاشت می‌شود."""
    if not assignment or not isinstance(assignment, dict):
        return 'active'
    if assignment.get('transaction_holder'):
        return 'in_transaction'
    try:
        st = str(assignment.get('status') or 'active').strip().lower()
    except Exception:
        st = 'active'
    if st in ('in_transaction', 'in-transaction', 'in transaction'):
        return 'in_transaction'
    return st or 'active'


def _auto_release_expired_transactions(assignments: List[Dict[str, Any]]) -> None:
    """رفع خودکار معاملات بعد از ۵ روز بدون تأیید پشتیبان"""
    from datetime import datetime, timedelta
    now = datetime.now()
    updated = False
    
    for a in assignments:
        if _assignment_display_status(a) != 'in_transaction':
            continue
        
        started_at_str = a.get('transaction_started_at')
        if not started_at_str:
            continue
        
        try:
            started_at = datetime.strptime(started_at_str, '%Y-%m-%d %H:%M:%S')
            if now - started_at > timedelta(days=5):
                a['status'] = 'active'
                a['updated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                a['auto_released'] = True
                a['auto_released_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                a.pop('transaction_holder', None)
                a.pop('transaction_started_at', None)
                updated = True
        except Exception:
            continue
    
    if updated:
        save_express_assignments(assignments)


_AUTO_RELEASE_LAST_MONO = 0.0
_AUTO_RELEASE_MIN_INTERVAL_S = 120.0


def _maybe_auto_release_expired_transactions(assignments: List[Dict[str, Any]]) -> None:
    """همان رفع خودکار معاملات منقضی، حداکثر یک‌بار در چند ثانیه (سبک‌تر برای داشبورد پرتکرار)."""
    global _AUTO_RELEASE_LAST_MONO
    now = time.monotonic()
    if now - _AUTO_RELEASE_LAST_MONO < _AUTO_RELEASE_MIN_INTERVAL_S:
        return
    _AUTO_RELEASE_LAST_MONO = now
    _auto_release_expired_transactions(assignments)


def _get_my_last_application(phone: str) -> Dict[str, Any] | None:
    """Return latest Express Partner application for a phone, if any."""
    try:
        from .referrals import _phones_match

        apps = load_express_partner_apps() or []
        mine = [a for a in apps if isinstance(a, dict) and _phones_match(a.get('phone'), phone)]
        if not mine:
            return None
        try:
            mine.sort(key=lambda x: x.get('created_at',''), reverse=True)
        except Exception:
            pass
        return mine[0]
    except Exception:
        return None


def _has_active_application(phone: str) -> bool:
    """Return True if the user already has an in-progress application (not approved/rejected/cancelled)."""
    try:
        from .referrals import _phones_match

        apps = load_express_partner_apps() or []
        for a in apps:
            if not isinstance(a, dict):
                continue
            if not _phones_match(a.get('phone'), phone):
                continue
            status = str(a.get('status') or '').strip().lower()
            if status in ('approved', 'rejected', 'cancelled'):
                continue
            return True
    except Exception:
        pass
    return False


APPROVED_PARTNER_STATUSES = {"approved", "active", "enabled", "ok", "true", "1"}


def _is_partner_approved(profile: Dict[str, Any] | None) -> bool:
    if not profile:
        return False
    status = str(profile.get("status") or "").strip().lower()
    return profile.get("status") is True or status in APPROVED_PARTNER_STATUSES


def require_partner_access(json_response: bool = False, allow_pending: bool = False, allow_guest: bool = False):
    """Decorator to ensure the user is an approved Express partner before accessing a route."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_phone"):
                if allow_guest:
                    # اجازه دسترسی مهمان (فقط نمایش) - بدون پروفایل
                    g.express_partner_profile = None
                    return fn(*args, **kwargs)
                if json_response:
                    return jsonify({"success": False, "error": "unauthorized"}), 401
                nxt = request.full_path.rstrip("?") if request.full_path else request.path
                return redirect(url_for("express_partner.login", next=nxt))

            me_phone = (session.get("user_phone") or "").strip()
            _ensure_session_partner_on_g()
            profile = getattr(g, 'express_partner_profile', None)

            approved = _is_partner_approved(profile)
            if not approved:
                if allow_pending:
                    g.express_partner_profile = profile
                    return fn(*args, **kwargs)
                if json_response:
                    return jsonify({"success": False, "error": "not_approved"}), 403
                last_app = _get_my_last_application(me_phone)
                if last_app:
                    return redirect(_post_apply_landing_url(me_phone))
                flash('برای ورود به پنل، لطفاً ابتدا درخواست همکاری خود را ثبت و تکمیل کنید.', 'warning')
                return redirect(url_for('express_partner.apply'))

            g.express_partner_profile = profile
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@express_partner_bp.after_request
def _express_partner_no_store_html(resp):
    """جلوگیری از کش HTML در مرورگر/PWA؛ بعد از خروج صفحهٔ کهنه «همچنان لاگین» دیده نشود."""
    try:
        ct = (resp.headers.get('Content-Type') or '').lower()
        if 'text/html' in ct:
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            resp.headers['Pragma'] = 'no-cache'
    except Exception:
        pass
    return resp


# به‌روزرسانی خودکار timestamp همکاران آنلاین + آمار روتین در تمام route‌های express_partner
@express_partner_bp.before_request
def track_online_partner():
    """فعالیت آنلاین و تیک بازاریابی روزانه — بدون نیاز به باز کردن صفحه روتین."""
    if not session.get("user_phone"):
        return
    session.permanent = True
    try:
        phone = (session.get("user_phone") or "").strip()
        if not phone:
            return

        today = datetime.now().strftime('%Y-%m-%d')
        if session.get('_routine_auto_mkt_day') != today:
            session['_routine_auto_mkt_day'] = today
            _defer_routine_auto_tick(phone, ROUTINE_STEP_MARKETING)

        now_ts = time.time()
        last_ping = session.get('_express_online_ping_ts') or 0
        if now_ts - float(last_ping) >= 120:
            session['_express_online_ping_ts'] = now_ts
            display_name = None
            try:
                prof = _partner_profile_for_phone(phone)
                if prof:
                    display_name = (prof.get('name') or prof.get('full_name') or '').strip() or None
            except Exception:
                pass
            _defer_online_partner_ping(phone, display_name, request.remote_addr or 'نامشخص')
    except Exception:
        pass

@express_partner_bp.app_context_processor
def inject_role_flags():
    try:
        me = str(session.get("user_phone") or "").strip()
    except Exception:
        me = ""
    is_express_partner = False
    if me:
        if 'VINOR_IS_EXPRESS_PARTNER' in session:
            is_express_partner = bool(session.get('VINOR_IS_EXPRESS_PARTNER'))
        else:
            _ensure_session_partner_on_g()
            is_express_partner = _is_partner_approved(getattr(g, 'express_partner_profile', None))
            session['VINOR_IS_EXPRESS_PARTNER'] = is_express_partner
    
    # دریافت VAPID_PUBLIC_KEY از config
    try:
        from flask import current_app
        vapid_public = current_app.config.get("VAPID_PUBLIC_KEY", "")
    except Exception:
        vapid_public = ""
    
    from ..utils.apk_version import is_vinor_apk_request

    is_vinor_apk = False
    if has_request_context():
        try:
            is_vinor_apk = is_vinor_apk_request(request)
        except Exception:
            is_vinor_apk = False

    android_apk_url = ''
    android_apk_version = ''
    show_apk_download_banner = False
    show_apk_strip = False
    apk_strip_mode = ''
    show_app_update_nav = False
    _raw_apk_url = ''
    if not is_vinor_apk:
        try:
            _apk_settings = _express_settings_cached()
            _raw_apk_url = (_apk_settings.get('android_apk_url') or '').strip()
            android_apk_version = (_apk_settings.get('android_apk_version') or '').strip()
            if _raw_apk_url:
                from ..utils.short_urls import public_apk_download_url
                android_apk_url = public_apk_download_url(_apk_settings, external=False)
                show_apk_strip = True
                apk_strip_mode = 'install'
                show_apk_download_banner = True
        except Exception:
            pass
    else:
        try:
            _apk_settings = _express_settings_cached()
            _raw_apk_url = (_apk_settings.get('android_apk_url') or '').strip()
            android_apk_version = (_apk_settings.get('android_apk_version') or '').strip()
            from ..utils.apk_version import should_show_apk_update
            from ..utils.short_urls import public_apk_download_url
            if _raw_apk_url:
                android_apk_url = public_apk_download_url(_apk_settings, external=False)
            show_app_update_nav = should_show_apk_update(
                android_apk_version,
                apk_url=_raw_apk_url,
                req=request,
            )
            if show_app_update_nav and _raw_apk_url:
                show_apk_strip = True
                apk_strip_mode = 'update'
                show_apk_download_banner = True
        except Exception:
            pass

    from ..utils.flash_messages import AUTH_FLASH_CATEGORY_FILTER
    from ..utils.seo import robots_meta_content

    vinor_robots_meta = "noindex, nofollow"
    if has_request_context():
        try:
            vinor_robots_meta = robots_meta_content(
                request.path or "",
                logged_in=bool(me),
            )
        except Exception:
            pass

    if not me:
        vinor_express_auth_segment = "guest"
    elif is_express_partner:
        vinor_express_auth_segment = "partner"
    else:
        vinor_express_auth_segment = "user"

    return {
        "VINOR_IS_EXPRESS_PARTNER": is_express_partner,
        "vinor_express_auth_segment": vinor_express_auth_segment,
        "VAPID_PUBLIC_KEY": vapid_public,
        "is_vinor_apk": is_vinor_apk,
        "android_apk_url": android_apk_url,
        "android_apk_version": android_apk_version,
        "show_apk_download_banner": show_apk_download_banner,
        "show_apk_strip": show_apk_strip,
        "apk_strip_mode": apk_strip_mode,
        "show_app_update_nav": show_app_update_nav,
        "auth_flash_categories": AUTH_FLASH_CATEGORY_FILTER,
        "vinor_robots_meta": vinor_robots_meta,
    }


# -------------------------
# PWA Routes (Separate from main VINOR PWA)
# -------------------------
@express_partner_bp.route('/', methods=['GET'], endpoint='partner_root')
def partner_root():
    """Legacy /express/partner → داشبورد یا پورسانت بر اساس نقش."""
    if session.get('user_phone'):
        return redirect(_redirect_after_login(), code=302)
    return redirect(url_for('express_partner.dashboard'), code=302)


@express_partner_bp.route('/manifest.webmanifest', methods=['GET'], endpoint='manifest')
def serve_manifest():
    """Serve Express Partner manifest separately"""
    from flask import Response, send_from_directory
    import os
    static_dir = os.path.join(current_app.root_path, "static")
    file_path = os.path.join(static_dir, "express-partner.webmanifest")
    mimetype = "application/manifest+json"
    
    if os.path.exists(file_path):
        return send_from_directory(static_dir, "express-partner.webmanifest", mimetype=mimetype)
    
    # Fallback JSON
    fallback_json = '''{
      "id": "/express/partner/",
      "name": "وینور اکسپرس - پنل همکاران",
      "short_name": "وینور اکسپرس",
      "description": "پنل مدیریت همکاران وینور - دسترسی به آگهی‌های تخصیص یافته، کمیسیون‌ها و ابزارهای مدیریت",
      "dir": "rtl",
      "lang": "fa",
      "start_url": "/express/partner/?source=pwa",
      "scope": "/express/partner/",
      "display": "standalone",
      "display_override": ["window-controls-overlay", "standalone", "minimal-ui"],
      "orientation": "portrait",
      "background_color": "#030712",
      "theme_color": "#030712",
      "categories": ["business", "productivity"],
      "capture_links": "existing-client-navigate",
      "launch_handler": { "client_mode": "auto" },
      "icons": [
        { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
        { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
      ]
    }'''
    return Response(fallback_json, status=200, mimetype=mimetype)


@express_partner_bp.route('/sw.js', methods=['GET'], endpoint='service_worker')
def serve_service_worker():
    """Serve Express Partner service worker separately"""
    from flask import send_from_directory, Response
    import os
    static_dir = os.path.join(current_app.root_path, "static")
    sw_file = "express-partner-sw.js"
    sw_path = os.path.join(static_dir, sw_file)
    
    if os.path.exists(sw_path):
        response = send_from_directory(static_dir, sw_file, mimetype="application/javascript")
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    
    # Fallback: return empty service worker if file not found
    current_app.logger.warning(f"Service worker file not found: {sw_path}")
    return Response("// Express Partner Service Worker not found", 
                   mimetype="application/javascript", 
                   status=404)


@express_partner_bp.route('/offline', methods=['GET'], endpoint='offline')
def offline_page():
    """Express Partner offline page"""
    return render_template('express_partner/offline.html')


APPLY_NAME_MAX_LEN = 40
APPLY_CITY_MAX_LEN = 30
APPLY_EXPERIENCE_MAX_LEN = 80
APPLY_NOTE_MAX_LEN = 300


def _apply_limits_context() -> dict:
    return {
        'apply_name_max': APPLY_NAME_MAX_LEN,
        'apply_city_max': APPLY_CITY_MAX_LEN,
        'apply_experience_max': APPLY_EXPERIENCE_MAX_LEN,
        'apply_note_max': APPLY_NOTE_MAX_LEN,
    }


def _clip_apply_fields(name: str, city: str, experience: str, note: str) -> tuple[str, str, str, str]:
    return (
        (name or '').strip()[:APPLY_NAME_MAX_LEN],
        (city or '').strip()[:APPLY_CITY_MAX_LEN],
        (experience or '').strip()[:APPLY_EXPERIENCE_MAX_LEN],
        (note or '').strip()[:APPLY_NOTE_MAX_LEN],
    )


def _parse_apply_national_id(raw: str) -> str:
    from ..utils.iran_ids import normalize_digits
    return normalize_digits(raw)[:10]


def _apply_form_context(
    me_phone: str,
    *,
    name: str = '',
    city: str = '',
    national_id: str = '',
    experience: str = '',
    note: str = '',
    cities=None,
) -> dict:
    profile = _partner_profile_for_phone(me_phone) or {}
    avatar = (profile.get('avatar') or '').strip()
    from ..utils.images import display_avatar_url
    avatar_updated_at = int(profile.get('avatar_updated_at') or 0)
    display_name = (name or profile.get('name') or me_phone or '').strip()
    return {
        'me_phone': me_phone,
        'name': name,
        'city': city,
        'national_id': national_id,
        'experience': experience,
        'note': note,
        'cities': cities if cities is not None else _active_cities_cached(),
        'has_avatar': bool(avatar),
        'avatar_url': display_avatar_url(avatar, avatar_updated_at) if avatar else '',
        'avatar_initials_name': display_name,
        **_apply_limits_context(),
    }


def _partner_has_avatar(me_phone: str) -> bool:
    profile = _partner_profile_for_phone(me_phone) or {}
    return bool((profile.get('avatar') or '').strip())


def _apply_login_redirect():
    """ریدایرکت به ورود با حفظ ref دعوت در next."""
    from flask import make_response
    from .referrals import capture_ref_on_login, store_referral_ref_token, set_ref_cookie_on_response

    ref = (request.args.get('ref') or '').strip()
    next_apply = url_for('express_partner.apply', ref=ref) if ref else url_for('express_partner.apply')
    try:
        if ref:
            store_referral_ref_token(ref)
        else:
            capture_ref_on_login()
    except Exception:
        pass
    resp = make_response(redirect(url_for('express_partner.login', next=next_apply)))
    if ref:
        set_ref_cookie_on_response(resp, ref)
    return resp


def _apply_invite_ref_value() -> str:
    try:
        from .referrals import referral_ref_token_for_session
        return (request.args.get('ref') or '').strip() or referral_ref_token_for_session()
    except Exception:
        return (request.args.get('ref') or '').strip()


def _apply_render_with_ref(**ctx):
    from flask import make_response
    from .referrals import set_ref_cookie_on_response

    invite_ref = ctx.pop('invite_ref', None)
    if invite_ref is None:
        invite_ref = _apply_invite_ref_value()
    ctx['invite_ref'] = invite_ref
    resp = make_response(render_template('express_partner/apply.html', **ctx))
    if invite_ref:
        set_ref_cookie_on_response(resp, invite_ref)
    return resp


@express_partner_bp.route('/apply', methods=['GET', 'POST'], endpoint='apply')
def apply():
    """درخواست همکاری — تک‌صفحه، کم‌اصطکاک."""
    if not session.get("user_phone"):
        return _apply_login_redirect()
    me_phone = (session.get("user_phone") or "").strip()
    try:
        from .referrals import stash_referrer_from_request, attach_referrer_to_pending_application
        stash_referrer_from_request(me_phone)
        attach_referrer_to_pending_application(
            me_phone,
            query_ref=request.args.get('ref') or '',
            form_ref=request.form.get('ref') or '',
        )
    except Exception:
        pass

    blocked = _apply_page_guard(me_phone)
    if blocked is not None:
        return blocked

    defaults = _apply_form_defaults(me_phone)
    cities = _active_cities_cached()

    if request.method == 'POST':
        if _has_active_application(me_phone):
            return redirect(_post_apply_landing_url(me_phone))
        name, city, experience, note = _clip_apply_fields(
            request.form.get('name') or '',
            request.form.get('city') or '',
            request.form.get('experience') or '',
            request.form.get('note') or '',
        )
        national_id = _parse_apply_national_id(request.form.get('national_id') or '')
        if not name or not city or not national_id:
            flash('نام، کد ملی و شهر فعالیت الزامی است.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, name=name, city=city, national_id=national_id,
                experience=experience, note=note, cities=cities,
            ))
        from ..utils.iran_ids import is_valid_iran_national_id
        if not is_valid_iran_national_id(national_id):
            flash('کد ملی واردشده معتبر نیست.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, name=name, city=city, national_id=national_id,
                experience=experience, note=note, cities=cities,
            ))
        if cities and city not in cities:
            flash('شهر انتخاب‌شده معتبر نیست.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, name=name, city=city, national_id=national_id,
                experience=experience, note=note, cities=cities,
            ))
        avatar_file = request.files.get('avatar')
        has_avatar = _partner_has_avatar(me_phone)
        if avatar_file and avatar_file.filename:
            saved_avatar = _save_partner_avatar_upload(me_phone, avatar_file)
            if not saved_avatar:
                flash('ذخیرهٔ تصویر پروفایل ناموفق بود. دوباره تلاش کنید.', 'error')
                return _apply_render_with_ref(**_apply_form_context(
                    me_phone, name=name, city=city, national_id=national_id,
                    experience=experience, note=note, cities=cities,
                ))
            has_avatar = True
        if not has_avatar:
            flash('انتخاب تصویر پروفایل الزامی است.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, name=name, city=city, national_id=national_id,
                experience=experience, note=note, cities=cities,
            ))
        return _submit_partner_application(me_phone, {
            'name': name,
            'city': city,
            'national_id': national_id,
            'experience': experience,
            'note': note,
        })

    clipped = _clip_apply_fields(
        defaults['name'], defaults['city'], defaults['experience'], defaults['note'],
    )
    return _apply_render_with_ref(**_apply_form_context(
        me_phone,
        name=clipped[0],
        city=clipped[1],
        national_id=defaults.get('national_id', ''),
        experience=clipped[2],
        note=clipped[3],
        cities=cities,
    ))


@express_partner_bp.route('/apply/step1', methods=['GET', 'POST'], endpoint='apply_step1')
@express_partner_bp.route('/apply/step2', methods=['GET', 'POST'], endpoint='apply_step2')
@express_partner_bp.route('/apply/step3', methods=['GET', 'POST'], endpoint='apply_step3')
def apply_steps_legacy():
    """سازگاری با لینک‌های قدیمی — همه به فرم تک‌صفحه."""
    return redirect(url_for('express_partner.apply'))


@express_partner_bp.post('/apply/cancel', endpoint='apply_cancel')
def apply_cancel():
    if not session.get("user_phone"):
        return redirect(url_for("express_partner.login", next=url_for("express_partner.apply")))
    me_phone = (session.get("user_phone") or "").strip()
    apps = load_express_partner_apps() or []
    updated = False
    for app in apps:
        try:
            if str(app.get('phone')) == me_phone and str(app.get('status') or '').strip().lower() in ('', 'new', 'pending', 'under_review'):
                app['status'] = 'cancelled'
                app['cancelled_at'] = datetime.utcnow().isoformat() + "Z"
                updated = True
                break
        except Exception:
            continue
    if updated:
        save_express_partner_apps(apps)
        flash('درخواست شما لغو شد. هر زمان می‌توانید دوباره درخواست ثبت کنید.', 'info')
    session.pop('apply_data', None)
    return redirect(url_for('express_partner.apply'))


def _active_application_referred_by(me_phone: str) -> str:
    """شماره معرف درخواست فعال کاربر، اگر از مسیر دعوت آمده باشد."""
    try:
        from .referrals import _phones_match

        apps = load_express_partner_apps() or []
        for a in apps:
            if not isinstance(a, dict):
                continue
            if not _phones_match(a.get('phone'), me_phone):
                continue
            status = str(a.get('status') or '').strip().lower()
            if status in ('approved', 'rejected', 'cancelled'):
                continue
            return (a.get('referred_by_phone') or '').strip()
    except Exception:
        pass
    return ''


def _post_apply_landing_url(me_phone: str, *, referrer_phone: str = '') -> str:
    """پس از ثبت درخواست → صفحه تشکر (شامل دانلود اپ در مرورگر)."""
    return url_for('express_partner.thanks')


def _apply_page_guard(me_phone: str):
    """همکار تأییدشده → داشبورد؛ درخواست فعال → تشکر/دانلود؛ در غیر این صورت فرم."""
    profile = _partner_profile_for_phone(me_phone)
    if _is_partner_approved(profile):
        return redirect(url_for('express_partner.dashboard'))
    if _has_active_application(me_phone):
        return redirect(_post_apply_landing_url(me_phone))
    return None


def _apply_form_defaults(me_phone: str) -> dict:
    data = session.get('apply_data') or {}
    profile = _partner_profile_for_phone(me_phone) or {}
    last_app = _get_my_last_application(me_phone)
    use_last = last_app and not _has_active_application(me_phone)
    name, city, experience, note = _clip_apply_fields(
        data.get('name') or profile.get('name') or (last_app.get('name') if use_last else '') or '',
        data.get('city') or profile.get('city') or (last_app.get('city') if use_last else '') or '',
        data.get('experience') or (last_app.get('experience') if use_last else '') or '',
        data.get('note') or (last_app.get('note') if use_last else '') or '',
    )
    national_id = _parse_apply_national_id(
        data.get('national_id')
        or profile.get('national_id')
        or (last_app.get('national_id') if use_last else '')
        or ''
    )
    return {
        'name': name,
        'city': city,
        'national_id': national_id,
        'experience': experience,
        'note': note,
    }


def _sync_unapproved_partner_profile(me_phone: str, data: dict) -> None:
    """اگر رکورد همکار (غیرتأیید) وجود دارد، نام/شهر را هم‌زمان با درخواست به‌روز کن."""
    partners = load_express_partners() or []
    profile = next((p for p in partners if str(p.get('phone') or '').strip() == me_phone), None)
    if not profile or _is_partner_approved(profile):
        return
    profile['name'] = data.get('name', '')
    profile['city'] = data.get('city', '')
    if data.get('national_id'):
        profile['national_id'] = data.get('national_id')
    try:
        save_express_partners(partners)
        _invalidate_partner_session_cache()
    except Exception:
        current_app.logger.error('Failed to sync partner profile from apply', exc_info=True)


def _append_sms_history(entry: dict) -> None:
    try:
        history = load_sms_history(current_app) or []
        entry = dict(entry)
        entry['id'] = len(history) + 1
        history.append(entry)
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception as hist_err:
        current_app.logger.error('Failed to save SMS history: %s', hist_err)


def _send_partner_application_sms(me_phone: str, recipient_name: str) -> dict:
    """پیامک تأیید ثبت درخواست همکاری برای کاربر (+ اطلاع ادمین)."""
    mobile = normalize_iran_mobile(me_phone)
    if not is_valid_iran_mobile(mobile):
        current_app.logger.warning(
            'Partner application SMS skipped: invalid mobile raw=%r normalized=%r',
            me_phone,
            mobile,
        )
        return {'ok': False, 'skipped': True, 'error': 'invalid_mobile', 'mobile': mobile}

    settings = load_settings(current_app) or {}
    sms_message = (settings.get('partner_application_sms_message') or '').strip()
    if not sms_message:
        sms_message = 'درخواست همکاری شما ثبت شد و در حال بررسی است. وینور'
    sms_line_number = (settings.get('sms_line_number') or get_sms_line_number() or '09981801922').strip()

    sms_result = send_sms_direct(mobile=mobile, message=sms_message, line_number=sms_line_number)
    ok = bool(sms_result.get('ok'))
    err = None
    if not ok:
        body = sms_result.get('body') or {}
        err = str(body.get('message') or body.get('error') or 'sms_send_failed')
        if sms_is_infrastructure_error(err):
            time.sleep(0.6)
            sms_result = send_sms_direct(mobile=mobile, message=sms_message, line_number=sms_line_number)
            ok = bool(sms_result.get('ok'))
            if ok:
                err = None
            else:
                body = sms_result.get('body') or {}
                err = str(body.get('message') or body.get('error') or err)
        if not ok:
            current_app.logger.error(
                'Partner application SMS failed mobile=%s status=%s body=%s',
                mobile,
                sms_result.get('status'),
                body,
            )

    _append_sms_history({
        'mobile': mobile,
        'recipient_name': recipient_name or '',
        'template_id': None,
        'message': sms_message,
        'parameters': {},
        'success': ok,
        'status_code': sms_result.get('status', 0),
        'response': sms_result.get('body', {}),
        'source': 'express_partner_application',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'error': None if ok else err,
    })

    try:
        from .admin_action_sms import notify_admin_pending_action
        notify_admin_pending_action(
            'application',
            partner_name=recipient_name,
            partner_phone=mobile,
        )
    except Exception as admin_err:
        current_app.logger.error('Admin SMS error: %s', admin_err, exc_info=True)

    return {
        'ok': ok,
        'skipped': False,
        'error': err,
        'mobile': mobile,
        'infra_error': (not ok) and sms_is_infrastructure_error(err),
    }


def _send_withdrawal_admin_sms(
    *,
    partner_phone: str,
    partner_name: str,
    amount: int,
    bank_summary: str,
) -> dict:
    """اطلاع‌رسانی پیامکی درخواست برداشت جدید به ادمین."""
    from .admin_action_sms import notify_admin_pending_action
    return notify_admin_pending_action(
        'withdrawal',
        partner_phone=partner_phone,
        partner_name=partner_name,
        amount=amount,
        bank_summary=bank_summary,
    )


def _format_visit_date_sms(iso_date: str) -> str:
    jalali = format_iso_date_jalali(iso_date)
    return jalali or (iso_date or '')[:10] or '—'


def _send_visit_admin_sms(
    *,
    partner_phone: str,
    partner_name: str,
    land_code: str,
    land_title: str,
    visit_date: str,
) -> dict:
    """اطلاع‌رسانی پیامکی درخواست بازدید جدید به ادمین."""
    from .admin_action_sms import notify_admin_pending_action
    return notify_admin_pending_action(
        'visit',
        partner_phone=partner_phone,
        partner_name=partner_name,
        land_code=land_code,
        land_title=land_title,
        visit_date=_format_visit_date_sms(visit_date),
    )


def _apply_post_submit_context(
    name: str,
    *,
    fresh_submit: bool,
    sms_sent: bool | None = None,
    sms_skipped: bool = False,
    sms_error: str | None = None,
    sms_infra_error: bool = False,
) -> dict:
    return {
        'name': name or '',
        'fresh_submit': bool(fresh_submit),
        'sms_sent': sms_sent,
        'sms_skipped': bool(sms_skipped),
        'sms_error': sms_error,
        'sms_infra_error': bool(sms_infra_error),
    }


def _redirect_apply_thanks(name: str, *, fresh_submit: bool, sms_sent: bool | None = None, sms_skipped: bool = False, sms_error: str | None = None, sms_infra_error: bool = False):
    from .referrals import clear_ref_cookie_on_response

    session['apply_thanks_context'] = _apply_post_submit_context(
        name,
        fresh_submit=fresh_submit,
        sms_sent=sms_sent,
        sms_skipped=sms_skipped,
        sms_error=sms_error,
        sms_infra_error=sms_infra_error,
    )
    resp = redirect(url_for('express_partner.thanks'))
    return clear_ref_cookie_on_response(resp)


@express_partner_bp.route('/thanks', methods=['GET'], endpoint='thanks')
def apply_thanks():
    """صفحهٔ تشکر پس از ثبت درخواست همکاری."""
    if not session.get('user_phone'):
        return redirect(url_for('express_partner.login', next=url_for('express_partner.apply')))
    me_phone = (session.get('user_phone') or '').strip()
    ctx = session.pop('apply_thanks_context', None) or {}

    if ctx.get('fresh_submit'):
        sms_sent = ctx.get('sms_sent')
        sms_skipped = ctx.get('sms_skipped', False)
        sms_infra = ctx.get('sms_infra_error', False)
        # خطای زیرساخت (شبکه/DNS) — پیام خنثی؛ فقط در لاگ ثبت شده
        if sms_sent is False and sms_infra:
            sms_sent = None
        elif sms_sent is False and sms_skipped:
            flash(
                'درخواست ثبت شد. به‌دلیل مشکل در شماره موبایل، پیامک تأیید ارسال نشد.',
                'warning',
            )
        elif sms_sent is False:
            flash(
                'درخواست ثبت شد اما ارسال پیامک تأیید ناموفق بود. درخواست شما در صف بررسی است.',
                'warning',
            )
        return render_template(
            'express_partner/thanks.html',
            **_thanks_page_kwargs(me_phone, ctx, pending_review=False),
        )

    if _is_partner_approved(_partner_profile_for_phone(me_phone)):
        return redirect(url_for('express_partner.dashboard'))

    if _has_active_application(me_phone):
        last_app = _get_my_last_application(me_phone) or {}
        ctx = {**ctx, 'name': (last_app.get('name') or ctx.get('name') or '')}
        return render_template(
            'express_partner/thanks.html',
            **_thanks_page_kwargs(me_phone, ctx, pending_review=True),
        )

    return redirect(url_for('express_partner.apply'))


def _thanks_page_kwargs(me_phone: str, ctx: dict | None = None, *, pending_review: bool = False) -> dict:
    """Context for thanks page including optional app download block."""
    from ..utils.apk_version import is_vinor_apk_request

    ctx = ctx or {}
    _settings = _express_settings_cached()
    _raw_apk_url = (_settings.get('android_apk_url') or '').strip()
    android_apk_version = (_settings.get('android_apk_version') or '').strip()
    from ..utils.short_urls import public_apk_download_url
    android_apk_url = public_apk_download_url(_settings, external=False) if _raw_apk_url else ''
    size_label = ''
    try:
        n = int(_settings.get('android_apk_size_bytes') or 0)
        if n >= 1_048_576:
            size_label = f'حدود {max(1, round(n / 1_048_576))} مگابایت'
        elif n >= 1024:
            size_label = f'حدود {max(1, round(n / 1024))} کیلوبایت'
    except Exception:
        size_label = ''
    last_app = _get_my_last_application(me_phone) or {}
    is_vinor_apk = bool(has_request_context() and is_vinor_apk_request(request))
    show_app_download = not is_vinor_apk and (
        ctx.get('fresh_submit') or pending_review or _has_active_application(me_phone)
    )
    sms_sent = ctx.get('sms_sent')
    sms_skipped = ctx.get('sms_skipped', False)
    sms_infra = ctx.get('sms_infra_error', False)
    if sms_sent is False and sms_infra:
        sms_sent = None
    return {
        'name': (ctx.get('name') or last_app.get('name') or '').strip(),
        'pending_review': pending_review,
        'sms_sent': sms_sent if (ctx.get('fresh_submit') or not pending_review) else None,
        'sms_skipped': sms_skipped,
        'sms_infra': sms_infra,
        'show_app_download': show_app_download,
        'android_apk_url': android_apk_url if show_app_download else '',
        'android_apk_version': android_apk_version if show_app_download else '',
        'android_apk_size_label': size_label if show_app_download else '',
    }


@express_partner_bp.route('/download-app', methods=['GET'], endpoint='download_app')
def download_app():
    """سازگاری با لینک قدیمی — هدایت به صفحه تشکر."""
    return redirect(url_for('express_partner.thanks'))


def _submit_partner_application(me_phone: str, data: dict):
    """ثبت نهایی درخواست همکاری."""
    if _has_active_application(me_phone):
        session.pop('apply_data', None)
        return redirect(_post_apply_landing_url(me_phone))

    if _is_partner_approved(_partner_profile_for_phone(me_phone)):
        session.pop('apply_data', None)
        return redirect(url_for("express_partner.dashboard"))

    apps = load_express_partner_apps() or []
    new_id = (max([int(x.get("id", 0) or 0) for x in apps if isinstance(x, dict)], default=0) or 0) + 1
    referrer_phone = ''
    try:
        from .referrals import (
            clear_referrer_session,
            register_referral_on_application,
            resolve_referrer_for_apply,
        )
        referrer_phone = resolve_referrer_for_apply(
            me_phone,
            form_ref=request.form.get('ref') or '',
            query_ref=request.args.get('ref') or '',
        )
    except Exception:
        referrer_phone = ''
    record = {
        "id": new_id,
        "name": data.get('name', ''),
        "phone": _canonical_partner_phone(me_phone),
        "national_id": data.get('national_id', ''),
        "city": data.get('city', ''),
        "experience": data.get('experience', ''),
        "note": data.get('note', ''),
        "status": "new",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if referrer_phone:
        record["referred_by_phone"] = referrer_phone
    apps.append(record)
    save_express_partner_apps(apps)
    _sync_unapproved_partner_profile(me_phone, data)
    if referrer_phone:
        try:
            register_referral_on_application(
                inviter_phone=referrer_phone,
                invitee_phone=record.get('phone', me_phone),
                invitee_name=record.get('name', ''),
                application_id=new_id,
            )
            clear_referrer_session()
        except Exception:
            pass

    sms_out = {'ok': False, 'skipped': True, 'error': 'sms_error'}
    try:
        sms_out = _send_partner_application_sms(me_phone, data.get('name', ''))
    except Exception as e:
        current_app.logger.error('Application SMS flow error: %s', e, exc_info=True)
        err_msg = str(e)
        sms_out = {
            'ok': False,
            'skipped': False,
            'error': err_msg,
            'infra_error': sms_is_infrastructure_error(err_msg),
        }

    session.pop('apply_data', None)
    return _redirect_apply_thanks(
        record.get('name', ''),
        fresh_submit=True,
        sms_sent=bool(sms_out.get('ok')),
        sms_skipped=bool(sms_out.get('skipped')),
        sms_error=sms_out.get('error'),
        sms_infra_error=bool(sms_out.get('infra_error')),
    )


def _dashboard_selected_cities():
    """
    شهرهای فیلتر داشبورد (چندتایی، جدا شده با ویرگول در query).
    پیش‌فرض: همه شهرها. city= خالی → همه؛ city=تهران,کرج → فقط آن شهرها.
    """
    if 'city' not in request.args:
        return []
    raw = (request.args.get('city') or '').strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(',') if p.strip()]


@express_partner_bp.route('/dashboard', methods=['GET'], endpoint='dashboard')
@require_partner_access(allow_pending=True, allow_guest=True)
def dashboard():
    me_phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, 'express_partner_profile', None)

    # فیلتر جستجو و شهر برای نمایش نتایج در همان داشبورد
    search_query = (request.args.get('q', '') or '').strip().lower()
    selected_cities = _dashboard_selected_cities()
    selected_city = ','.join(selected_cities)
    # برای لینک‌ها: حالت «همه شهرها» باید city= خالی در URL بماند، نه حذف پارامتر
    city_url = selected_city if ('city' in request.args or selected_cities) else None
    filter_tag = (request.args.get('tag') or '').strip().lower()
    filter_cat = (request.args.get('cat') or '').strip()
    has_filters = _dashboard_request_has_filters(search_query, selected_cities, filter_tag, filter_cat)

    if (
        me_phone
        and _is_partner_approved(profile)
        and not has_filters
        and request.args.get('all') != '1'
        and _should_redirect_partner_default_to_commissions()
    ):
        return redirect(url_for('express_partner.commissions'))

    apps = load_express_partner_apps() or []
    my_apps = [a for a in apps if str(a.get("phone")) == me_phone]
    # آیا کاربر درخواست همکاری ثبت کرده و در وضعیت بررسی است؟
    def _norm_status(v):
        try:
            s = str(v or '').strip().lower()
        except Exception:
            s = ''
        return s
    has_pending_app = any(_norm_status(a.get('status')) in ('pending','under_review','waiting','review') for a in my_apps)

    is_approved = _is_partner_approved(profile)
    assigned_lands, expired_count = _build_partner_dashboard_lands(
        me_phone,
        is_approved,
        search_query=search_query,
        selected_cities=selected_cities,
        filter_tag=filter_tag,
        filter_cat=filter_cat,
    )

    my_comms = _commissions_for_phone(me_phone)
    # کل درآمد: فقط پورسانت‌های تایید شده و پرداخت شده (نه pending و rejected)
    total_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
    
    # در انتظار: فقط پورسانت‌هایی که status='pending' یا None/خالی است (default به pending)
    pending_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or 'pending').strip() == 'pending')
    
    # فروش‌های تایید شده: تعداد پورسانت‌هایی که status='approved' یا 'paid' دارند
    sold_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))

    # URL ویدئو آموزش - می‌تواند از تنظیمات یا متغیر محیطی گرفته شود
    training_video_url = os.environ.get("TRAINING_VIDEO_URL", "")  # مثال: "https://www.youtube.com/watch?v=VIDEO_ID"
    # شهرهای فعال برای فیلتر جستجو (قابل مدیریت در پنل ادمین)
    cities = _active_cities_cached()
    # سئو: عنوان و توضیح برای موتورهای جستجو (صفحه فایل‌ها برای همه در دسترس است)
    count = len(assigned_lands)
    dashboard_mobile_only = _is_mobile_partner_client()
    show_all_cards = request.args.get("all") == "1" or has_filters
    dashboard_lands_truncated = False
    if not show_all_cards and count > DASHBOARD_INITIAL_CARD_LIMIT:
        assigned_lands, dashboard_lands_truncated = _truncate_dashboard_lands(
            assigned_lands, DASHBOARD_INITIAL_CARD_LIMIT
        )
    seo_title = "فایل‌های اکسپرس وینور | خرید و فروش ملک و زمین"
    seo_description = f"لیست فایل‌های اکسپرس وینور. {count} فایل معتبر برای خرید و فروش ملک، زمین، ویلا و آپارتمان. مشاهده قیمت و جزئیات."
    try:
        canonical_url = url_for('express_partner.dashboard', _external=True)
        if request.args.get('q') or request.args.get('city'):
            canonical_url = url_for('express_partner.dashboard', q=request.args.get('q') or None, city=request.args.get('city') or None, _external=True)
    except Exception:
        canonical_url = ''
    from flask import make_response
    resp = make_response(render_template(
        "express_partner/dashboard.html",
        profile=profile,
        selected_city=selected_city,
        selected_cities=selected_cities,
        city_url=city_url,
        is_approved=is_approved,
        has_pending_app=has_pending_app,
        my_apps=my_apps,
        training_video_url=training_video_url,
        cities=cities,
        assigned_lands=assigned_lands,
        lands_total_count=count,
        dashboard_lands_truncated=dashboard_lands_truncated,
        dashboard_mobile_only=dashboard_mobile_only,
        total_commission=total_commission,
        pending_commission=pending_commission,
        sold_count=sold_count,
        expired_count=expired_count,
        hide_header=True,
        SHOW_SUBMIT_BUTTON=False,
        brand="وینور",
        domain="vinor.ir",
        seo_title=seo_title,
        seo_description=seo_description,
        canonical_url=canonical_url,
    ))
    # برای کاربران مهمان: کش عمومی کوتاه برای سئو و سرعت
    if not me_phone and not profile:
        resp.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
        resp.headers["Vary"] = "Accept-Encoding"
    else:
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["Vary"] = "Cookie"
        _append_partner_tab_prefetch(resp)
    return resp


def _dashboard_data_payload(me_phone, profile, has_pending_app, assigned_lands, total_commission, pending_commission, sold_count, expired_count, is_approved):
    """ساخت خروجی JSON داشبورد برای اپ اندروید."""
    from ..utils.images import partner_card_image_url

    def _text_field(val, default=''):
        if val is None:
            return default
        return str(val).strip() or default

    lands_json = []
    for land in assigned_lands:
        code = land.get('code') or ''
        try:
            detail_url = url_for('express_partner.land_detail', code=code, _external=True)
        except Exception:
            detail_url = ''
        lands_json.append({
            'code': code,
            'title': _text_field(land.get('title'), '—'),
            'price_total': int(land.get('price_total') or land.get('price') or 0),
            'commission_amount': int(land.get('_commission_amount') or 0),
            'commission_pct': land.get('_commission_pct'),
            'assignment_status': _text_field(land.get('_assignment_status'), 'active'),
            'is_expired': bool(land.get('_is_expired')),
            'size': _text_field(land.get('size')),
            'location': _text_field(land.get('location')),
            'city': _text_field(land.get('city')),
            'category': _text_field(land.get('category')),
            'created_at': _text_field(land.get('created_at')),
            'image_url': partner_card_image_url(land) or None,
            'detail_url': detail_url,
        })
    out = {
        'success': True,
        'profile': profile is not None,
        'is_approved': is_approved,
        'has_pending_app': has_pending_app,
        'total_commission': total_commission,
        'pending_commission': pending_commission,
        'sold_count': sold_count,
        'expired_count': expired_count or 0,
        'assigned_lands': lands_json,
    }
    return out


def _public_lands_payload(limit=50):
    """لیست فایل‌های عمومی اکسپرس برای نمایش به مهمان در اپ (بدون لاگین)."""
    from ..utils.images import partner_card_image_url

    def _img_url(land):
        url = partner_card_image_url(land if isinstance(land, dict) else {})
        return url or None

    try:
        express_lands = load_express_lands_cached() or []
    except Exception:
        express_lands = []
    express_lands = _sort_by_created_at_desc(express_lands)
    lands_json = []
    for land in express_lands[:limit]:
        code = (land.get('code') or '').strip()
        if not code:
            continue
        try:
            detail_url = url_for('express_partner.land_detail', code=code, _external=True)
        except Exception:
            detail_url = ''
        lands_json.append({
            'code': code,
            'title': (land.get('title') or '—').strip(),
            'price_total': int(land.get('price_total') or land.get('price') or 0),
            'commission_amount': 0,
            'commission_pct': None,
            'assignment_status': 'active',
            'is_expired': False,
            'size': (land.get('size') or '').strip(),
            'location': (land.get('location') or '').strip(),
            'city': (land.get('city') or '').strip(),
            'category': (land.get('category') or '').strip(),
            'created_at': (land.get('created_at') or '').strip(),
            'image_url': _img_url(land),
            'detail_url': detail_url,
        })
    return lands_json


@express_partner_bp.get('/dashboard/data', endpoint='dashboard_data')
@require_partner_access(allow_pending=True, allow_guest=True)
def dashboard_data():
    """API JSON برای اپ اندروید: داده داشبورد (فایل‌های ارسالی، آمار، وضعیت)."""
    me_phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, 'express_partner_profile', None)
    apps = load_express_partner_apps() or []
    my_apps = [a for a in apps if str(a.get("phone")) == me_phone]
    def _norm_status(v):
        try:
            return str(v or '').strip().lower()
        except Exception:
            return ''
    has_pending_app = any(_norm_status(a.get('status')) in ('pending', 'under_review', 'waiting', 'review') for a in my_apps)

    is_approved = bool(profile and (profile.get("status") in ("approved", True)))
    assigned_lands, expired_count = _build_partner_dashboard_lands(me_phone, is_approved)
    if len(assigned_lands) > DASHBOARD_INITIAL_CARD_LIMIT:
        assigned_lands, _ = _truncate_dashboard_lands(assigned_lands, DASHBOARD_INITIAL_CARD_LIMIT)
    my_comms = _commissions_for_phone(me_phone)
    total_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
    pending_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or 'pending').strip() == 'pending')
    sold_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
    payload = _dashboard_data_payload(me_phone, profile, has_pending_app, assigned_lands, total_commission, pending_commission, sold_count, expired_count, is_approved)
    # همیشه لیست عمومی را بفرست تا اپ در صورت خالی بودن assigned_lands هم کارت‌ها را نشان دهد
    try:
        payload['public_lands'] = _public_lands_payload(limit=50)
    except Exception:
        payload['public_lands'] = []
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Vary'] = 'Cookie'
    return resp


@express_partner_bp.get('/api/public-lands')
def api_public_lands():
    """لیست فایل‌های عمومی اکسپرس برای اپ - بدون نیاز به لاگین یا کوکی."""
    try:
        payload = _public_lands_payload(limit=50)
    except Exception:
        payload = []
    return jsonify({'success': True, 'public_lands': payload})


@express_partner_bp.post('/api/repost')
@require_partner_access(allow_pending=True)
def api_repost():
    """
    ثبت بازنشر یک فایل توسط همکار.
    - ورودی: code (کد فایل)
    - رفتار: دو رکورد بازنشر برای تقویت نمایش در اکسپلور
    """
    try:
        data = request.get_json(silent=True) or request.form
        code = (data.get('code') or '').strip()
    except Exception:
        code = ''
    if not code:
        return jsonify({'ok': False, 'error': 'missing_code'}), 400
    me_phone = (session.get("user_phone") or '').strip()
    lands = load_ads_cached() or []
    land = next((l for l in lands if str(l.get('code')) == code), None)
    if not land:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    # ثبت دو رکورد بازنشر
    try:
        from ..utils.storage import load_express_reposts, save_express_reposts
    except Exception:
        return jsonify({'ok': False, 'error': 'storage_missing'}), 500
    items = load_express_reposts() or []
    now = datetime.utcnow().isoformat() + "Z"
    items.append({'code': code, 'partner_phone': me_phone, 'timestamp': now})
    # محدود کردن طول فایل به 2000 رکورد برای جلوگیری از رشد
    if len(items) > 2000:
        items = items[-2000:]
    save_express_reposts(items)
    return jsonify({'ok': True})


@express_partner_bp.post('/api/repost/remove')
@require_partner_access(allow_pending=True)
def api_repost_remove():
    """
    حذف بازنشر یک فایل توسط همکار (برداشت بازنشر).
    - ورودی: code
    """
    try:
        data = request.get_json(silent=True) or request.form
        code = (data.get('code') or '').strip()
    except Exception:
        code = ''
    if not code:
        return jsonify({'ok': False, 'error': 'missing_code'}), 400
    me_phone = (session.get("user_phone") or '').strip()
    try:
        items = load_express_reposts() or []
        # حذف تمام رکوردهای مربوط به این همکار و این فایل
        items = [r for r in items if not (str(r.get('partner_phone')) == me_phone and str(r.get('code')) == code)]
        save_express_reposts(items)
        return jsonify({'ok': True})
    except Exception:
        return jsonify({'ok': False, 'error': 'persist_failed'}), 500

@express_partner_bp.get('/favorites', endpoint='favorites')
@require_partner_access(allow_pending=True)
def favorites_page():
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    resp = make_response(render_template(
        'express_partner/favorites.html',
        me_phone=me_phone,
        is_approved=is_approved,
        hide_header=True,
    ))
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.post('/api/favorites/cards')
@require_partner_access(allow_pending=True, json_response=True)
def api_favorites_cards():
    """HTML کارت‌های علاقه‌مندی برای کدهای ارسالی از localStorage."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    data = request.get_json(silent=True) or {}
    codes = data.get('codes') if isinstance(data, dict) else []
    if not isinstance(codes, list):
        codes = []
    codes = [str(c).strip() for c in codes if str(c).strip()][:200]
    lands = _lands_for_favorite_codes(codes, me_phone)
    valid_codes = [str(item.get('code') or '').strip() for item in lands if str(item.get('code') or '').strip()]
    html = render_template(
        'express_partner/partials/favorites_cards_inner.html',
        assigned_lands=lands,
        is_approved=is_approved,
    )
    return jsonify({
        'ok': True,
        'html': html,
        'count': len(lands),
        'requested': len(codes),
        'valid_codes': valid_codes,
    })


@express_partner_bp.get('/requests', endpoint='requests')
@require_partner_access(allow_pending=True)
def requests_page():
    """صفحهٔ وضعیت همهٔ درخواست‌های بازدید همکار جاری."""
    me_phone = (session.get('user_phone') or '').strip()
    current_filter = (request.args.get('filter') or 'all').strip().lower()
    if current_filter not in ('all', PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS):
        current_filter = 'all'
    rows = load_express_visit_requests() or []
    if not isinstance(rows, list):
        rows = []
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []

    status_meta = {
        PENDING_STATUS: {
            'label': 'در انتظار تأیید',
            'hint': 'درخواست شما ثبت شده و منتظر بررسی تیم وینور است.',
            'bucket': 'pending',
        },
        APPROVED_STATUS: {
            'label': 'تأیید شده',
            'hint': 'بازدید تأیید شده؛ پس از انجام بازدید، آن را روی فایل ثبت کنید.',
            'bucket': 'approved',
        },
        DONE_PENDING_STATUS: {
            'label': 'در انتظار تأیید انجام بازدید',
            'hint': 'انجام بازدید ثبت شده و منتظر تأیید ادمین است. پس از تأیید، پورسانت بازدید در صف تأیید قرار می‌گیرد.',
            'bucket': 'done_pending',
        },
        COMPLETED_STATUS: {
            'label': 'بازدید انجام شد',
            'hint': 'بازدید ثبت شده؛ پس از تأیید پورسانت بازدید، درخواست معامله فعال می‌شود.',
            'bucket': 'completed',
        },
        CANCELLED_STATUS: {
            'label': 'تأیید نشده',
            'hint': 'این درخواست توسط تیم وینور تأیید نشده یا بسته شده است.',
            'bucket': 'cancelled',
        },
    }

    items: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('partner_phone') or '').strip() != me_phone:
            continue
        st = str(row.get('status') or PENDING_STATUS).strip() or PENDING_STATUS
        meta = status_meta.get(st, {'label': st, 'hint': '', 'bucket': 'other'})
        visit_date = str(row.get('visit_date') or '').strip()
        progress_row = dict(row)
        progress_row['visit_commission_required'] = _visit_commission_required_for(
            commissions,
            me_phone,
            str(row.get('land_code') or ''),
        )
        progress_steps = visit_progress_steps(progress_row, commissions, partner_phone=me_phone)
        items.append({
            'id': row.get('id') or '',
            'land_code': row.get('land_code') or '',
            'land_title': row.get('land_title') or row.get('land_code') or 'فایل اکسپرس',
            'visit_date': visit_date,
            'visit_date_jalali': format_iso_date_jalali(visit_date) if visit_date else '',
            'status': st,
            'status_label': meta['label'],
            'status_hint': meta['hint'],
            'bucket': meta['bucket'],
            'created_at': row.get('created_at') or '',
            'updated_at': row.get('updated_at') or '',
            'approved_at': row.get('approved_at') or '',
            'completed_at': row.get('completed_at') or '',
            'admin_note': row.get('admin_note') or '',
            'progress_steps': progress_steps,
        })

    items.sort(key=lambda item: str(item.get('updated_at') or item.get('created_at') or ''), reverse=True)
    counts = {
        'all': len(items),
        'pending': sum(1 for i in items if i.get('status') == PENDING_STATUS),
        'approved': sum(1 for i in items if i.get('status') == APPROVED_STATUS),
        'done_pending': sum(1 for i in items if i.get('status') == DONE_PENDING_STATUS),
        'completed': sum(1 for i in items if i.get('status') == COMPLETED_STATUS),
        'cancelled': sum(1 for i in items if i.get('status') == CANCELLED_STATUS),
    }
    filter_options = [
        {'key': 'all', 'label': 'همه', 'count': counts['all']},
        {'key': PENDING_STATUS, 'label': 'در انتظار', 'count': counts['pending']},
        {'key': APPROVED_STATUS, 'label': 'تأیید شده', 'count': counts['approved']},
        {'key': DONE_PENDING_STATUS, 'label': 'انتظار تأیید بازدید', 'count': counts['done_pending']},
        {'key': COMPLETED_STATUS, 'label': 'انجام شده', 'count': counts['completed']},
        {'key': CANCELLED_STATUS, 'label': 'تأیید نشده', 'count': counts['cancelled']},
    ]
    if current_filter != 'all':
        items = [item for item in items if item.get('status') == current_filter]
    current_filter_label = next(
        (opt['label'] for opt in filter_options if opt['key'] == current_filter),
        'همه',
    )
    current_filter_count = len(items)
    return render_template(
        'express_partner/requests.html',
        items=items,
        counts=counts,
        filter_options=filter_options,
        current_filter=current_filter,
        current_filter_label=current_filter_label,
        current_filter_count=current_filter_count,
        hide_header=True,
    )


@express_partner_bp.get('/commissions', endpoint='commissions')
@require_partner_access(allow_pending=True)
def commissions_page():
    me_phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    my_comms = _commissions_for_phone(me_phone)

    comm_stats = _partner_commission_stats(me_phone, my_comms)
    withdrawable_balance = comm_stats["withdrawable_balance"]
    pending_withdrawal_total = comm_stats["in_withdrawal_amount"]
    financial_snapshot = _commission_financial_snapshot(
        comm_stats,
        min_withdrawal_amount=MIN_WITHDRAWAL_AMOUNT,
    )

    _attach_commission_txn_labels(my_comms)
    txn_items = _partner_txn_items(me_phone, my_comms)

    try:
        my_comms.sort(key=lambda x: x.get('created_at',''), reverse=True)
    except Exception:
        pass

    partner_name = ""
    try:
        if profile and isinstance(profile, dict):
            partner_name = (str(profile.get("name") or "")).strip()
    except Exception:
        partner_name = ""

    resp = make_response(render_template(
        "express_partner/commissions.html",
        items=txn_items,
        comm_stats=comm_stats,
        total_commission=comm_stats["total_confirmed_amount"],
        pending_commission=comm_stats["pending_amount"],
        paid_commission=comm_stats["received_amount"],
        sold_count=comm_stats["total_confirmed_count"],
        pending_count=comm_stats["pending_count"],
        approved_count=comm_stats["approved_count"],
        paid_count=comm_stats["received_count"],
        approved_commission=comm_stats["approved_amount"],
        withdrawable_balance=withdrawable_balance,
        requestable_balance=withdrawable_balance,
        min_withdrawal_amount=MIN_WITHDRAWAL_AMOUNT,
        pending_withdrawal_total=pending_withdrawal_total,
        commission_financial_snapshot=financial_snapshot,
        partner_name=partner_name,
        hide_header=True,
        SHOW_SUBMIT_BUTTON=False,
        brand="وینور",
        domain="vinor.ir",
        is_approved=is_approved,
    ))
    if is_approved:
        _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/commissions/transactions', endpoint='commissions_transactions')
@require_partner_access(allow_pending=True)
def commissions_transactions_page():
    me_phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    if not is_approved:
        return redirect(url_for('express_partner.commissions'))

    my_comms = _commissions_for_phone(me_phone)
    _attach_commission_txn_labels(my_comms)
    txn_items = _partner_txn_items(me_phone, my_comms)
    txn_summary = partner_txn_feed_summary(txn_items)
    comm_stats = _partner_commission_stats(me_phone, my_comms)

    resp = make_response(render_template(
        "express_partner/commissions_txn_list.html",
        items=txn_items,
        txn_summary=txn_summary,
        comm_stats=comm_stats,
        total_commission=comm_stats["total_confirmed_amount"],
        paid_commission=comm_stats.get("paid_withdrawal_amount", comm_stats.get("received_amount", 0)),
        sold_count=comm_stats["total_confirmed_count"],
        paid_count=comm_stats.get("paid_withdrawal_count", comm_stats.get("received_count", 0)),
        hide_header=True,
        SHOW_SUBMIT_BUTTON=False,
        brand="وینور",
        domain="vinor.ir",
        is_approved=is_approved,
    ))
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/commissions/data', endpoint='commissions_data')
@require_partner_access(allow_pending=True, json_response=True)
def commissions_data():
    """API JSON برای اپ اندروید: خلاصه و لیست پورسانت‌های همکار جاری."""
    me_phone = (session.get("user_phone") or "").strip()
    my_comms = _commissions_for_phone(me_phone)
    comm_stats = _partner_commission_stats(me_phone, my_comms)

    def _i(v):
        try:
            return int(str(v).replace(',', '').strip() or '0')
        except Exception:
            return 0

    try:
        my_comms = sorted(my_comms, key=lambda x: x.get('created_at', ''), reverse=True)
    except Exception:
        pass

    items = []
    for c in my_comms:
        items.append({
            'land_code': c.get('land_code') or '—',
            'created_at': c.get('created_at') or '',
            'sale_amount': _i(c.get('sale_amount')),
            'commission_pct': c.get('commission_pct'),
            'commission_amount': _i(c.get('commission_amount')),
            'status': (c.get('status') or 'pending').strip(),
        })
    return jsonify({
        'success': True,
        'total_commission': comm_stats['total_confirmed_amount'],
        'pending_commission': comm_stats['pending_amount'],
        'paid_commission': comm_stats['received_amount'],
        'sold_count': comm_stats['total_confirmed_count'],
        'withdrawable_balance': comm_stats['withdrawable_balance'],
        'requestable_balance': comm_stats['withdrawable_balance'],
        'min_withdrawal_amount': MIN_WITHDRAWAL_AMOUNT,
        'pending_withdrawal_total': comm_stats['in_withdrawal_amount'],
        'in_withdrawal_amount': comm_stats['in_withdrawal_amount'],
        'approved_commission': comm_stats['approved_amount'],
        'items': items,
    })


def _commission_financial_snapshot(
    comm_stats: Dict[str, Any],
    *,
    min_withdrawal_amount: int = MIN_WITHDRAWAL_AMOUNT,
) -> Dict[str, Any]:
    """خلاصه مالی یکپارچه برای UI وب — منبع حقیقت همان partner_commission_dashboard است."""
    s = comm_stats if isinstance(comm_stats, dict) else {}
    wd = int(s.get('withdrawable_balance') or 0)
    min_wd = int(min_withdrawal_amount or MIN_WITHDRAWAL_AMOUNT)
    req = int(s.get('requestable_balance') or wd)
    return {
        'version': 1,
        'withdrawable_balance': wd,
        'requestable_balance': req,
        'in_withdrawal_amount': int(s.get('in_withdrawal_amount') or 0),
        'in_withdrawal_count': int(s.get('in_withdrawal_count') or 0),
        'pending_amount': int(s.get('pending_amount') or 0),
        'pending_count': int(s.get('pending_count') or 0),
        'total_confirmed_amount': int(s.get('total_confirmed_amount') or 0),
        'total_confirmed_count': int(s.get('total_confirmed_count') or 0),
        'paid_withdrawal_amount': int(
            s.get('paid_withdrawal_amount') or s.get('received_amount') or 0
        ),
        'paid_withdrawal_count': int(
            s.get('paid_withdrawal_count') or s.get('received_count') or 0
        ),
        'min_withdrawal_amount': min_wd,
        'can_withdraw': wd >= min_wd,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    }


@express_partner_bp.get('/commissions/summary', endpoint='commissions_summary')
@require_partner_access(allow_pending=True, json_response=True)
def commissions_summary():
    """API سبک: فقط اعداد مالی پورسانت — برای sync امن UI بدون جایگزینی DOM."""
    me_phone = (session.get("user_phone") or "").strip()
    comm_stats = _partner_commission_stats(me_phone, _commissions_for_phone(me_phone))
    snapshot = _commission_financial_snapshot(
        comm_stats,
        min_withdrawal_amount=MIN_WITHDRAWAL_AMOUNT,
    )
    return jsonify({'success': True, 'snapshot': snapshot})


def _sort_bank_accounts_by_created(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..utils.dates import parse_datetime_safe
    try:
        return sorted(rows, key=lambda x: parse_datetime_safe(x.get('created_at', '1970-01-01')), reverse=True)
    except Exception:
        return list(rows)


def _rebalance_partner_bank_defaults(all_rows: List[Dict[str, Any]], phone: str) -> None:
    from ..utils.dates import parse_datetime_safe
    ph = (phone or "").strip()
    mine = [r for r in all_rows if isinstance(r, dict) and str(r.get('phone') or '').strip() == ph]
    if not mine:
        return
    defs = [r for r in mine if r.get('is_default')]
    if len(defs) == 0:
        oldest_first = sorted(
            mine,
            key=lambda x: parse_datetime_safe(x.get('created_at', '9999-12-31')),
        )
        pick = oldest_first[0].get('id')
        for r in mine:
            r['is_default'] = (r.get('id') == pick)
    elif len(defs) > 1:
        oldest_first = sorted(
            defs,
            key=lambda x: parse_datetime_safe(x.get('created_at', '9999-12-31')),
        )
        pick = oldest_first[0].get('id')
        for r in mine:
            r['is_default'] = (r.get('id') == pick)


@express_partner_bp.get('/bank-accounts/data', endpoint='bank_accounts_data')
@require_partner_access(json_response=True)
def bank_accounts_data():
    """فهرست حساب‌های ذخیره‌شدهٔ همکار + کاتالوگ بانک برای فرم."""
    me_phone = (session.get("user_phone") or "").strip()
    all_rows = load_partner_bank_accounts() or []
    if not isinstance(all_rows, list):
        all_rows = []
    mine = accounts_for_phone(all_rows, me_phone)
    mine = _sort_bank_accounts_by_created(mine)
    comm_stats = _partner_commission_stats(me_phone, _commissions_for_phone(me_phone))
    w_balance = comm_stats['withdrawable_balance']
    default_acc = next((a for a in mine if a.get('is_default')), mine[0] if mine else None)
    return jsonify({
        'success': True,
        'accounts': [public_account_dict(r) for r in mine],
        'banks': catalog_public(),
        'withdrawable_balance': w_balance,
        'requestable_balance': w_balance,
        'min_withdrawal_amount': MIN_WITHDRAWAL_AMOUNT,
        'default_account_id': (default_acc or {}).get('id') or '',
    })


@express_partner_bp.post('/bank-accounts/add', endpoint='bank_accounts_add')
@require_partner_access(json_response=True)
def bank_accounts_add():
    """افزودن حساب؛ شماره کامل کارت در سرور ذخیره می‌شود (فقط پنل ادمین)؛ در UI همکار ماسک می‌ماند."""
    me_phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    bank_key = (data.get('bank_key') or '').strip().lower()
    pan = (data.get('pan') or data.get('card_number') or '').strip()
    holder = (data.get('holder_name') or data.get('holder') or '').strip()
    sheba_raw = (data.get('sheba') or '').strip()

    rec, err = validate_new_account(bank_key, pan, holder, sheba_raw)
    if err or not rec:
        return jsonify({'success': False, 'error': err or 'invalid'}), 400

    all_rows = load_partner_bank_accounts() or []
    if not isinstance(all_rows, list):
        all_rows = []
    mine = accounts_for_phone(all_rows, me_phone)
    rec['phone'] = me_phone
    rec['created_at'] = datetime.utcnow().isoformat() + 'Z'
    rec['is_default'] = len(mine) == 0
    all_rows.append(rec)
    _rebalance_partner_bank_defaults(all_rows, me_phone)
    try:
        save_partner_bank_accounts(all_rows)
    except Exception:
        current_app.logger.exception('save_partner_bank_accounts failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    return jsonify({'success': True, 'account': public_account_dict(rec)})


def _bank_account_has_active_withdrawal(acc_id: str, phone: str) -> bool:
    from .partner_withdrawals import ACTIVE_WITHDRAWAL_STATUSES, partner_phones_match

    acc_id = (acc_id or '').strip()
    if not acc_id:
        return False
    for w in load_partner_withdrawals() or []:
        if not isinstance(w, dict):
            continue
        if not partner_phones_match(w.get('phone'), phone):
            continue
        if str(w.get('bank_account_id') or '').strip() != acc_id:
            continue
        if str(w.get('status') or 'pending').strip().lower() in ACTIVE_WITHDRAWAL_STATUSES:
            return True
    return False


@express_partner_bp.post('/bank-accounts/update', endpoint='bank_accounts_update')
@require_partner_access(json_response=True)
def bank_accounts_update():
    """ویرایش حساب بانکی ثبت‌شده."""
    me_phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    acc_id = (data.get('id') or '').strip()
    if not acc_id:
        return jsonify({'success': False, 'error': 'missing_id'}), 400

    bank_key = (data.get('bank_key') or '').strip().lower()
    pan = (data.get('pan') or data.get('card_number') or '').strip()
    holder = (data.get('holder_name') or data.get('holder') or '').strip()
    sheba_raw = (data.get('sheba') or '').strip()

    all_rows = load_partner_bank_accounts() or []
    if not isinstance(all_rows, list):
        all_rows = []

    target = None
    target_idx = None
    for i, r in enumerate(all_rows):
        if not isinstance(r, dict):
            continue
        if str(r.get('id') or '').strip() != acc_id:
            continue
        if not accounts_for_phone([r], me_phone):
            return jsonify({'success': False, 'error': 'not_found'}), 404
        target_idx = i
        target = r
        break
    if target is None or target_idx is None:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    updated, err = apply_account_fields(target, bank_key, pan, holder, sheba_raw)
    if err or not updated:
        return jsonify({'success': False, 'error': err or 'invalid'}), 400

    all_rows[target_idx] = updated
    try:
        save_partner_bank_accounts(all_rows)
    except Exception:
        current_app.logger.exception('save_partner_bank_accounts update failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    return jsonify({'success': True, 'account': public_account_dict(updated)})


@express_partner_bp.post('/bank-accounts/delete', endpoint='bank_accounts_delete')
@require_partner_access(json_response=True)
def bank_accounts_delete():
    """حذف حساب بانکی همکار."""
    me_phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    acc_id = (data.get('id') or '').strip()
    if not acc_id:
        return jsonify({'success': False, 'error': 'missing_id'}), 400

    if _bank_account_has_active_withdrawal(acc_id, me_phone):
        return jsonify({'success': False, 'error': 'active_withdrawal'}), 409

    all_rows = load_partner_bank_accounts() or []
    if not isinstance(all_rows, list):
        all_rows = []

    mine = accounts_for_phone(all_rows, me_phone)
    if not any(str(r.get('id') or '').strip() == acc_id for r in mine):
        return jsonify({'success': False, 'error': 'not_found'}), 404

    from .partner_withdrawals import partner_phones_match

    all_rows = [
        r for r in all_rows
        if not (
            isinstance(r, dict)
            and str(r.get('id') or '').strip() == acc_id
            and partner_phones_match(r.get('phone'), me_phone)
        )
    ]
    _rebalance_partner_bank_defaults(all_rows, me_phone)
    try:
        save_partner_bank_accounts(all_rows)
    except Exception:
        current_app.logger.exception('save_partner_bank_accounts delete failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    return jsonify({'success': True})


@express_partner_bp.post('/bank-accounts/default', endpoint='bank_accounts_set_default')
@require_partner_access(json_response=True)
def bank_accounts_set_default():
    """تنظیم/لغو حساب پیش‌فرض برای برداشت."""
    me_phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    acc_id = (data.get('id') or '').strip()
    want = bool(data.get('is_default'))
    if not acc_id:
        return jsonify({'success': False, 'error': 'missing_id'}), 400

    all_rows = load_partner_bank_accounts() or []
    if not isinstance(all_rows, list):
        all_rows = []
    mine_ids = {str(r.get('id') or '') for r in accounts_for_phone(all_rows, me_phone)}
    if acc_id not in mine_ids:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    from .partner_withdrawals import partner_phones_match
    for r in all_rows:
        if not isinstance(r, dict) or not partner_phones_match(r.get('phone'), me_phone):
            continue
        if want:
            r['is_default'] = (str(r.get('id') or '') == acc_id)
        else:
            if str(r.get('id') or '') == acc_id:
                r['is_default'] = False
    _rebalance_partner_bank_defaults(all_rows, me_phone)
    try:
        save_partner_bank_accounts(all_rows)
    except Exception:
        current_app.logger.exception('save_partner_bank_accounts default failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    return jsonify({'success': True})


@express_partner_bp.post('/withdrawals/request', endpoint='withdrawals_request')
@require_partner_access(json_response=True)
def withdrawals_request():
    """ثبت درخواست برداشت پورسانت توسط همکار."""
    me_phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    bank_account_id = (data.get('bank_account_id') or data.get('account_id') or '').strip()

    all_banks = load_partner_bank_accounts() or []
    if not isinstance(all_banks, list):
        all_banks = []
    mine_banks = accounts_for_phone(all_banks, me_phone)

    all_wd = load_partner_withdrawals() or []
    if not isinstance(all_wd, list):
        all_wd = []
    _reconcile_partner_commissions(me_phone)
    comms = _commissions_for_phone(me_phone)

    rec, err = validate_new_request(
        amount,
        bank_account_id,
        me_phone,
        mine_banks,
        comms,
        all_wd,
    )
    if err or not rec:
        return jsonify({'success': False, 'error': err or 'invalid'}), 400

    partner_name = _partner_display_name(me_phone)
    rec['partner_name'] = partner_name
    rec['created_at'] = datetime.utcnow().isoformat() + 'Z'
    rec['updated_at'] = rec['created_at']
    all_wd.append(rec)
    try:
        save_partner_withdrawals(all_wd)
    except Exception:
        current_app.logger.exception('save_partner_withdrawals failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500

    try:
        _send_withdrawal_admin_sms(
            partner_phone=me_phone,
            partner_name=partner_name,
            amount=int(rec.get('amount') or 0),
            bank_summary=str(rec.get('bank_summary') or ''),
        )
    except Exception:
        current_app.logger.exception('withdrawal admin SMS failed')

    try:
        from .commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=me_phone,
            event='withdrawal_requested',
            amount=int(rec.get('amount') or 0),
            bank_summary=str(rec.get('bank_summary') or ''),
            reference_id=str(rec.get('id') or ''),
        )
    except Exception:
        current_app.logger.exception('withdrawal_requested partner SMS failed')

    return jsonify({
        'success': True,
        'request': {
            'id': rec.get('id'),
            'amount': rec.get('amount'),
            'status': rec.get('status'),
            'bank_summary': rec.get('bank_summary'),
            'withdrawable_balance': _partner_withdrawable_balance(me_phone),
            'requestable_balance': _partner_requestable_balance(me_phone),
        },
    })


@express_partner_bp.post('/withdrawals/<wid>/cancel', endpoint='withdrawals_cancel')
@require_partner_access(json_response=True)
def withdrawals_cancel(wid: str):
    """لغو درخواست برداشت در وضعیت «در انتظار بررسی» توسط همکار."""
    me_phone = (session.get("user_phone") or "").strip()
    all_wd = load_partner_withdrawals() or []
    if not isinstance(all_wd, list):
        all_wd = []
    commissions = _express_commissions_cached() or []
    now_iso = datetime.utcnow().isoformat() + 'Z'
    ok, err = cancel_partner_withdrawal(all_wd, me_phone, wid, commissions, now_iso)
    if not ok:
        code = err or 'cancel_failed'
        status = 404 if code == 'not_found' else 400
        return jsonify({'success': False, 'error': code}), status
    cancelled_row = next(
        (
            w for w in all_wd
            if isinstance(w, dict) and str(w.get('id') or '') == str(wid).strip()
        ),
        None,
    )
    try:
        save_partner_withdrawals(all_wd)
        save_express_commissions(commissions)
    except Exception:
        current_app.logger.exception('withdrawals_cancel save failed')
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    if cancelled_row:
        try:
            from .commission_sms import notify_partner_commission_txn
            notify_partner_commission_txn(
                partner_phone=me_phone,
                event='withdrawal_cancelled',
                amount=int(cancelled_row.get('amount') or 0),
                bank_summary=str(cancelled_row.get('bank_summary') or ''),
                reference_id=str(wid),
            )
        except Exception:
            current_app.logger.exception('withdrawal_cancelled partner SMS failed')
    return jsonify({
        'success': True,
        'withdrawable_balance': _partner_withdrawable_balance(me_phone),
        'requestable_balance': _partner_requestable_balance(me_phone),
    })


@express_partner_bp.get('/api/notes')
@require_partner_access(json_response=True, allow_pending=True)
def api_notes_list():
    """JSON API: فهرست یادداشت‌های همکار جاری برای اپ اندروید."""
    me_phone = (session.get("user_phone") or "").strip()
    items = [n for n in (load_partner_notes() or []) if str(n.get('phone')) == me_phone]
    items = _sort_by_created_at_desc(items)
    payload = []
    for n in items:
        try:
            payload.append({
                'id': int(n.get('id') or 0),
                'content': (n.get('content') or '').strip(),
                'created_at': (n.get('created_at') or '').strip(),
            })
        except Exception:
            continue
    return jsonify({'success': True, 'items': payload})


@express_partner_bp.post('/api/notes')
@require_partner_access(json_response=True, allow_pending=True)
def api_add_note():
    """JSON API: افزودن یک یادداشت جدید برای همکار جاری."""
    me_phone = (session.get("user_phone") or "").strip()
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({'success': False, 'error': 'empty'}), 400
    items = load_partner_notes() or []
    new_id = (max([int(x.get('id', 0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
    rec = {
        "id": new_id,
        "phone": me_phone,
        "content": content,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    items.append(rec)
    save_partner_notes(items)
    return jsonify({
        'success': True,
        'item': {
            'id': rec["id"],
            'content': rec["content"],
            'created_at': rec["created_at"],
        },
    })


@express_partner_bp.post('/api/notes/<int:nid>/delete')
@require_partner_access(json_response=True, allow_pending=True)
def api_delete_note(nid: int):
    """JSON API: حذف یک یادداشت کاربر جاری بر اساس id."""
    me_phone = (session.get("user_phone") or "").strip()
    items = load_partner_notes() or []
    before = len(items)
    items = [n for n in items if not (int(n.get('id', 0) or 0) == int(nid) and str(n.get('phone')) == me_phone)]
    save_partner_notes(items)
    deleted = len(items) != before
    return jsonify({'success': deleted})


@express_partner_bp.post('/sales/add')
@require_partner_access(allow_pending=True)
def add_sale():
    me_phone = (session.get("user_phone") or "").strip()
    title = (request.form.get("title") or "").strip()
    amount = (request.form.get("amount") or "").strip()
    note = (request.form.get("note") or "").strip()
    if not title:
        return redirect(url_for("express_partner.dashboard"))
    items = load_partner_sales() or []
    new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
    try:
        amount_num = int(str(amount).replace(',', '').strip() or '0')
    except Exception:
        amount_num = 0
    items.append({
        "id": new_id,
        "phone": me_phone,
        "title": title,
        "amount": amount_num,
        "note": note,
        "created_at": datetime.utcnow().isoformat()+"Z"
    })
    save_partner_sales(items)
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.post('/files/upload')
@require_partner_access(allow_pending=True)
def upload_file():
    me_phone = (session.get("user_phone") or "").strip()
    f = request.files.get('file')
    if not f or not f.filename:
        return redirect(url_for("express_partner.dashboard"))
    base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', me_phone)
    os.makedirs(base, exist_ok=True)
    tsname = datetime.utcnow().strftime('%Y%m%d%H%M%S%f') + "__" + f.filename
    safe_name = tsname.replace('..','_').replace('/','_').replace('\\','_')
    path = os.path.join(base, safe_name)
    f.save(path)
    metas = load_partner_files_meta() or []
    new_id = (max([int(x.get('id',0) or 0) for x in metas if isinstance(x, dict)], default=0) or 0) + 1
    metas.append({"id": new_id, "phone": me_phone, "filename": safe_name, "stored_at": datetime.utcnow().isoformat()+"Z"})
    save_partner_files_meta(metas)
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.get('/files/<int:fid>/download')
@require_partner_access(allow_pending=True)
def download_file(fid: int):
    me_phone = (session.get("user_phone") or "").strip()
    metas = load_partner_files_meta() or []
    meta = next((m for m in metas if int(m.get('id',0) or 0) == int(fid) and str(m.get('phone')) == me_phone), None)
    if not meta:
        abort(404)
    base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', me_phone)
    fp = os.path.join(base, meta.get('filename') or '')
    if not os.path.isfile(fp):
        abort(404)
    return send_from_directory(base, os.path.basename(fp), as_attachment=True)


# -------------------------
# Auth (Express Partner themed)
# -------------------------
def _clear_express_partner_auth_session() -> None:
    """فقط خروج از حساب همکار؛ سشن ادمین یا پیش‌نویس apply_data حذف نمی‌شود."""
    for k in (
        'user_id', 'user_phone', 'otp_code', 'otp_phone', 'otp_created_at', 'next',
        'VINOR_IS_EXPRESS_PARTNER',
        '_routine_auto_mkt_day', '_express_online_ping_ts',
    ):
        session.pop(k, None)
    if not session.get('logged_in'):
        session.permanent = False
    try:
        session.modified = True
    except Exception:
        pass


def _logout_dest_url() -> str:
    return url_for('express_partner.login', change=1)


@express_partner_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    from ..utils.flash_messages import purge_non_auth_flashes

    purge_non_auth_flashes()
    if request.method == 'GET':
        if request.args.get('change') and _login_change_clears_otp():
            _clear_otp_session()
        elif session.get('otp_code') and session.get('otp_phone'):
            if _otp_session_expired():
                _clear_otp_session()
            else:
                return redirect(_login_otp_redirect_url())
        try:
            from .referrals import capture_ref_on_login
            capture_ref_on_login()
        except Exception:
            pass
    # اگر از قبل لاگین است، مستقیم به داشبورد (یا مسیر هدف) برود
    if session.get("user_phone"):
        session.permanent = True
        try:
            from .referrals import stash_referrer_from_request
            stash_referrer_from_request((session.get('user_phone') or '').strip())
        except Exception:
            pass
        nxt = _redirect_after_login()
        return redirect(nxt)

    if request.method == 'POST':
        from ..utils.flash_messages import FLASH_AUTH_ERROR, FLASH_AUTH_INFO, FLASH_AUTH_WARNING

        wants_json = _auth_wants_json()

        if not _legal_accepted(request):
            msg = 'برای ادامه باید حریم خصوصی و قوانین استفاده را بپذیرید.'
            if wants_json:
                return jsonify({'ok': False, 'error': msg}), 400
            flash('برای ادامه باید <a href="{privacy}" class="underline">حریم خصوصی</a> و <a href="{terms}" class="underline">قوانین استفاده</a> را بپذیرید.'.format(
                privacy=url_for('main.privacy', next=_login_next_preserve() or ''),
                terms=url_for('express_partner.legal_terms', next=_login_next_preserve() or ''),
            ), FLASH_AUTH_ERROR)
            return redirect(url_for('express_partner.login', next=_login_next_preserve() or None))

        phone_raw = request.form.get('phone', '')
        phone = _otp_canonical_phone(phone_raw)
        from ..services.sms import is_valid_iran_mobile

        if not is_valid_iran_mobile(phone):
            msg = 'لطفاً یک شماره موبایل ۱۱ رقمی معتبر (۰۹…) وارد کنید.'
            if wants_json:
                return jsonify({'ok': False, 'error': msg}), 400
            flash(msg, FLASH_AUTH_ERROR)
            return redirect(url_for('express_partner.login', next=_login_next_preserve() or None))

        code = f"{random.randint(10000, 99999)}"
        _store_otp_session(phone, code)
        _dispatch_otp_sms(phone, code)

        nxt = _login_next_preserve()
        if nxt:
            session['next'] = nxt

        otp_url = _login_otp_redirect_url()
        if wants_json:
            r = jsonify({'ok': True, 'redirect': otp_url})
            r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            return r
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            r = redirect(otp_url)
            r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            return r
        flash('کد تأیید ارسال شد.', FLASH_AUTH_INFO)
        return redirect(otp_url)
    return render_template('express_partner/auth/login_step1.html')


@express_partner_bp.route('/login/otp', methods=['GET'], endpoint='login_otp')
def login_otp():
    """مرحله تأیید OTP — فقط GET (بعد از POST شماره، الگوی PRG)."""
    from ..utils.flash_messages import FLASH_AUTH_ERROR, purge_non_auth_flashes

    purge_non_auth_flashes()
    try:
        from .referrals import capture_ref_on_login
        capture_ref_on_login()
    except Exception:
        pass
    if session.get('user_phone'):
        return redirect(_redirect_after_login())

    phone = _otp_session_phone()
    if not phone or not session.get('otp_code'):
        # prefetch قبل از POST شماره نباید flash بگذارد — روی صفحه OTP باقی می‌ماند
        if not _is_prefetch_request():
            flash('ابتدا شماره موبایل خود را وارد کنید.', FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login'))
    if _otp_session_expired():
        _clear_otp_session()
        flash('کد تأیید منقضی شده است. لطفاً دوباره شماره موبایل را وارد کنید.', FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))

    login_next = _login_next_preserve() or _session_next_safe()
    is_likely_partner = _is_phone_approved_partner(phone)
    return render_template(
        'express_partner/auth/login_step2.html',
        phone=phone,
        login_next=login_next,
        is_likely_partner=is_likely_partner,
    )


@express_partner_bp.route('/verify', methods=['POST'], endpoint='verify')
def verify():
    from ..utils.flash_messages import (
        FLASH_AUTH_ERROR,
        FLASH_AUTH_SUCCESS,
        purge_non_auth_flashes,
    )

    wants_json = _auth_wants_json()
    if not wants_json:
        purge_non_auth_flashes()
    from ..services.sms import normalize_otp_code

    code = normalize_otp_code(request.form.get('otp_code') or '')
    form_phone = _otp_canonical_phone((request.form.get('phone') or '').strip())
    sess_phone = _otp_session_phone()
    if not sess_phone or not session.get('otp_code'):
        msg = 'جلسهٔ تأیید منقضی شده. لطفاً دوباره شماره موبایل را وارد کنید.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login')}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login'))
    if _otp_session_expired():
        _clear_otp_session()
        msg = 'کد تأیید منقضی شده است. لطفاً دوباره شماره موبایل را وارد کنید.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login')}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))
    if not form_phone:
        msg = 'شماره موبایل یافت نشد. لطفاً از ابتدا وارد شوید.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login')}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))
    if form_phone != sess_phone:
        msg = 'شماره موبایل با درخواست ورود همخوانی ندارد.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login', change=1)}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))

    if len(code) != 5:
        msg = 'لطفاً کد ۵ رقمی را به‌درستی وارد کنید.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login_otp'))

    verified_phone = _verify_otp_for_phone(code, form_phone)
    if verified_phone:
        form_next = (request.form.get('next') or '').strip()
        if form_next and form_next.startswith('/') and not form_next.startswith('//'):
            session['next'] = form_next
        try:
            from .referrals import capture_ref_on_login
            capture_ref_on_login()
        except Exception:
            pass
        dest = _finalize_partner_login(verified_phone)
        if wants_json:
            r = jsonify({'ok': True, 'redirect': dest})
            r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            try:
                r.headers['Link'] = f'<{dest}>; rel=preload; as=document'
            except Exception:
                pass
            return r
        flash('ورود شما با موفقیت انجام شد.', FLASH_AUTH_SUCCESS)
        return redirect(dest)

    msg = 'کد تأیید نادرست است. لطفاً دوباره تلاش کنید.'
    if wants_json:
        return jsonify({'ok': False, 'error': msg}), 400
    flash(msg, FLASH_AUTH_ERROR)
    if _otp_session_phone():
        return redirect(url_for('express_partner.login_otp'))
    return redirect(url_for('express_partner.login'))


@express_partner_bp.route('/support', methods=['GET', 'POST'], endpoint='support')
@require_partner_access(allow_pending=True, allow_guest=True)
def support():
    """صفحه پشتیبانی — ارسال و پیگیری تیکت."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    me_name = (profile.get('name') or '').strip() if profile else ''

    if request.method == 'POST':
        if not me_phone:
            flash('برای ارسال تیکت ابتدا وارد حساب خود شوید.', 'warning')
            return redirect(url_for('express_partner.login', next=url_for('express_partner.support')))

        category = (request.form.get('category') or 'other').strip()
        subject = (request.form.get('subject') or '').strip()
        message = (request.form.get('message') or '').strip()

        tickets = load_support_tickets() or []
        if not isinstance(tickets, list):
            tickets = []
        rec, err = create_support_ticket(
            tickets,
            user_phone=me_phone,
            user_name=me_name or me_phone,
            category=category,
            subject=subject,
            message=message,
        )
        if err:
            flash(partner_ticket_error_message(err, tickets, me_phone), 'profile')
            return redirect(url_for('express_partner.support', tab='new'))
        if not rec:
            flash('ارسال تیکت ناموفق بود. دوباره تلاش کنید.', 'profile')
            return redirect(url_for('express_partner.support', tab='new'))

        try:
            save_support_tickets(tickets)
        except Exception:
            current_app.logger.error('Failed to save support ticket', exc_info=True)
            flash('خطا در ثبت تیکت.', 'profile')
            return redirect(url_for('express_partner.support', tab='new'))

        try:
            notify_admin_pending_action(
                'ticket',
                partner_phone=me_phone,
                partner_name=me_name or me_phone,
                subject=rec.get('subject') or '',
                detail=(rec.get('message') or '')[:120],
            )
        except Exception:
            current_app.logger.exception('support ticket admin SMS failed')

        flash('تیکت شما ثبت شد. پاسخ از طریق همین صفحه نمایش داده می‌شود.', 'profile')
        return redirect(url_for('express_partner.support', tab='list'))

    user_tickets: List[Dict[str, Any]] = []
    ticket_stats: Dict[str, Any] = {
        'open_count': 0,
        'total_count': 0,
        'daily_remaining': 0,
        'open_remaining': 0,
        'cooldown_seconds': 0,
        'can_submit': False,
        'block_reason': '',
    }
    tab = (request.args.get('tab') or '').strip().lower()
    quick = (request.args.get('quick') or '').strip().lower()
    support_prefill: Dict[str, str] = {'category': '', 'subject': '', 'message': ''}
    support_submit_label = 'ارسال تیکت'
    support_message_label = 'متن'
    support_message_placeholder = 'مشکل یا سوال را با جزئیات بنویسید…'
    if quick == 'visit_without_details':
        tab = 'new'
        support_prefill = {
            'category': 'cooperation',
            'subject': 'درخواست بازدید بدون مشخصات',
            'message': 'درخواست بازدید',
        }
        support_submit_label = 'درخواست بازدید'
        support_message_label = 'متن'
        support_message_placeholder = 'متن درخواست بازدید را بنویسید…'
    elif quick == 'deal_without_details':
        tab = 'new'
        support_prefill = {
            'category': 'cooperation',
            'subject': 'درخواست معامله بدون مشخصات',
            'message': 'درخواست معامله',
        }
        support_submit_label = 'درخواست معامله'
        support_message_label = 'متن'
        support_message_placeholder = 'متن درخواست معامله را بنویسید…'
    if me_phone:
        all_tickets = load_support_tickets() or []
        if isinstance(all_tickets, list):
            user_tickets = tickets_for_phone(all_tickets, me_phone, limit=50)
            ticket_stats = partner_ticket_stats(all_tickets, me_phone)
    if tab not in ('new', 'list'):
        tab = 'list' if user_tickets else 'new'

    return render_template(
        'express_partner/support.html',
        hide_header=True,
        me_phone=me_phone,
        me_name=me_name,
        tickets=user_tickets,
        ticket_stats=ticket_stats,
        ticket_tab=tab,
        ticket_categories=TICKET_CATEGORIES,
        support_prefill=support_prefill,
        support_submit_label=support_submit_label,
        support_message_label=support_message_label,
        support_message_placeholder=support_message_placeholder,
        message_min_len=MESSAGE_MIN_LEN,
        message_max_len=MESSAGE_MAX_LEN,
    )


@express_partner_bp.route('/help', methods=['GET'], endpoint='help')
@require_partner_access(allow_pending=True, allow_guest=True)
def help():
    """صفحه راهنمای داخلی برای Express Partner"""
    return render_template('express_partner/help.html')


@express_partner_bp.route('/training', methods=['GET'], endpoint='training')
@require_partner_access()
def training():
    """صفحه آموزش مینیمال برای همکاران"""
    # URL ویدئو آموزش - می‌تواند از تنظیمات یا متغیر محیطی خوانده شود
    training_video_url = os.environ.get("TRAINING_VIDEO_URL", "")
    # اگر URL خالی است، از یک placeholder استفاده می‌کنیم
    # می‌توانید URL ویدئو YouTube یا هر سرویس دیگری را اینجا قرار دهید
    # مثال: "https://www.youtube.com/embed/VIDEO_ID" یا URL مستقیم ویدئو
    
    return render_template('express_partner/training.html', 
                         hide_header=True,
                         training_video_url=training_video_url)


@express_partner_bp.route('/legal/privacy', methods=['GET'], endpoint='legal_privacy')
def legal_privacy():
    """حریم خصوصی — هدایت به آدرس canonical /privacy"""
    return redirect(url_for('main.privacy', **request.args.to_dict()))


@express_partner_bp.route('/legal/terms', methods=['GET'], endpoint='legal_terms')
def legal_terms():
    """قوانین استفاده پنل همکار — عمومی، موبایل‌محور."""
    return render_template('express_partner/legal/terms.html', hide_header=True)


def _redirect_login_next(fallback_endpoint: str = 'express_partner.dashboard'):
    """هدایت امن بعد از ورود؛ فقط مسیر نسبی داخلی."""
    nxt = session.pop('next', None)
    if isinstance(nxt, str):
        nxt = nxt.strip()
        if nxt.startswith('/') and not nxt.startswith('//'):
            return redirect(nxt)
    return redirect(url_for(fallback_endpoint))


def _legal_accepted(request_obj) -> bool:
    if request_obj.form.get('accept_legal') in ('1', 'on', 'true', 'yes'):
        return True
    data = request_obj.get_json(silent=True) if request_obj.is_json else None
    if isinstance(data, dict):
        val = data.get('accept_legal')
        if val in (True, 1, '1', 'true', 'yes', 'on'):
            return True
    return False


@express_partner_bp.route('/cooperation-terms', methods=['GET'], endpoint='cooperation_terms')
@require_partner_access(allow_pending=True, allow_guest=True)
def cooperation_terms():
    """شرایط همکاری برای کاربران عادی و متقاضیان همکاری."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile) if me_phone else False
    next_url = (request.args.get('next') or '').strip()
    back_url = url_for('express_partner.dashboard')
    if next_url.startswith('/express/partner'):
        back_url = next_url
    return render_template(
        'express_partner/cooperation_terms.html',
        hide_header=True,
        is_approved=is_approved,
        back_url=back_url,
    )


@express_partner_bp.route('/invite', methods=['GET'], endpoint='invite_colleagues')
@require_partner_access(allow_pending=True)
def invite_colleagues():
    """صفحهٔ اشتراک لینک دعوت — همکاران تأییدشده: دعوت همکار؛ کاربران عادی: دعوت دوستان."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    me_name = (profile.get('name') or '').strip()
    is_approved = _is_partner_approved(profile)
    from ..utils.share_tokens import encode_partner_ref
    from ..utils.short_urls import public_referral_url
    canonical_phone = _canonical_partner_phone(me_phone)
    ref_token = encode_partner_ref(canonical_phone)
    invite_url = public_referral_url(ref_token)
    inviter = me_name or 'همکار وینور'
    if is_approved:
        share_text = f'{inviter} شما را به همکاری در وینور اکسپرس دعوت می‌کند.'
    else:
        share_text = f'{inviter} شما را به وینور دعوت می‌کند.'
    try:
        from .referrals import referral_stats_for_inviter, REFERRAL_BONUS_AMOUNT
        ref_stats = referral_stats_for_inviter(me_phone)
        bonus_per_invite = REFERRAL_BONUS_AMOUNT
    except Exception:
        ref_stats = {
            'invite_count': 0,
            'waiting_invites': 0,
            'successful_invites': 0,
            'approved_count': 0,
            'pending_invites': 0,
            'pending_commission': 0,
            'approved_commission': 0,
            'paid_commission': 0,
            'total_earned': 0,
        }
        bonus_per_invite = 500_000
    return render_template(
        'express_partner/invite_colleagues.html',
        invite_url=invite_url,
        share_text=share_text,
        me_name=me_name,
        is_approved=is_approved,
        ref_stats=ref_stats,
        bonus_per_invite=bonus_per_invite,
    )


@express_partner_bp.route('/routine', methods=['GET'], endpoint='routine')
@require_partner_access(allow_pending=True, allow_guest=True)
def routine():
    """روتین روزانه/هفتگی برای ثبت پیشرفت (جدا از آموزش)"""
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    resp = make_response(render_template(
        'express_partner/routine.html',
        hide_header=True,
        is_approved=is_approved,
    ))
    if is_approved:
        _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.route('/routine/data', methods=['GET'], endpoint='routine_data')
@require_partner_access(allow_pending=True)
def routine_data():
    """
    برگرداندن روزهای انجام‌شده روتین در ماه خواسته‌شده برای کاربر جاری.
    پارامتر month به شکل YYYY-MM. اگر خالی باشد، ماه جاری.
    """
    phone = (session.get("user_phone") or "").strip()
    month = (request.args.get('month') or '').strip()
    if not month or len(month) != 7:
        month = datetime.now().strftime('%Y-%m')

    records = load_partner_routines_cached()
    rec = next((r for r in records if str(r.get('phone')) == phone), None)
    days = []
    steps = {}
    if rec and isinstance(rec.get('days'), list):
        days = [d for d in rec.get('days') if isinstance(d, str) and d.startswith(month + '-')]
    if rec and isinstance(rec.get('steps'), dict):
        steps = {k: int(v) for k, v in rec.get('steps', {}).items() if isinstance(k, str) and k.startswith(month + '-') and isinstance(v, (int, float))}

    resp = make_response(jsonify({"success": True, "month": month, "days": days, "steps": steps}))
    # Short microcache for faster back-to-back calendar fetches
    resp.headers["Cache-Control"] = "public, max-age=20, stale-while-revalidate=40"
    return resp


@express_partner_bp.route('/routine/complete', methods=['POST'], endpoint='routine_complete')
@require_partner_access(allow_pending=True)
def routine_complete():
    """
    ثبت انجام روتین برای امروز (با ذخیره در فایل سمت سرور).
    """
    phone = (session.get("user_phone") or "").strip()
    today = datetime.now().strftime('%Y-%m-%d')

    records = load_partner_routines_cached()
    rec = next((r for r in records if str(r.get('phone')) == phone), None)
    if not rec:
        rec = {"phone": phone, "days": [], "steps": {}, "updated_at": None}
        records.append(rec)

    if today not in rec.get('days', []):
        rec.setdefault('days', []).append(today)
        rec['days'] = sorted(set(rec['days']))
    rec.setdefault('steps', {})
    rec['updated_at'] = datetime.utcnow().isoformat() + "Z"

    save_partner_routines(records)
    # No-store for mutation responses
    resp = make_response(jsonify({"success": True, "date": today, "days": rec.get('days', []), "steps": rec.get('steps', {})}))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# -------------------------
# Vinor AI (صفحه داخلی پرتال — چت جدا برای هر کاربر)
# -------------------------
@express_partner_bp.get('/ai', endpoint='ai')
@require_partner_access(allow_pending=True)
def ai_page():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import (
        ensure_active_thread,
        messages_for_ui,
        threads_for_ui,
    )
    phone = (session.get('user_phone') or '').strip()
    ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
    threads = threads_for_ui(phone, audience=AUDIENCE_PARTNER)
    active_thread_id = next((t['id'] for t in threads if t.get('is_active')), '')
    resp = make_response(
        render_template(
            'express_partner/ai.html',
            hide_header=True,
            chat_messages=messages_for_ui(phone, audience=AUDIENCE_PARTNER),
            chat_threads=threads,
            active_thread_id=active_thread_id,
            ai_audience='partner',
            chat_api_url=url_for('express_partner.ai_chat'),
            clear_api_url=url_for('express_partner.ai_clear'),
            history_api_url=url_for('express_partner.ai_history'),
            switch_thread_url=url_for('express_partner.ai_switch_thread'),
            delete_thread_url=url_for('express_partner.ai_delete_thread'),
            sync_api_url=url_for('express_partner.ai_sync'),
        )
    )
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/ai/sync', endpoint='ai_sync')
@require_partner_access(allow_pending=True, json_response=True)
def ai_sync():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import messages_since

    phone = (session.get('user_phone') or '').strip()
    thread_id = (request.args.get('thread_id') or '').strip() or None
    after = (request.args.get('after') or '').strip()
    after_count = request.args.get('count', type=int) or 0
    exclude_esc = [
        x.strip()
        for x in (request.args.get('exclude_esc') or '').split(',')
        if x.strip()
    ]
    msgs = messages_since(
        phone,
        thread_id,
        after,
        audience=AUDIENCE_PARTNER,
        after_count=max(0, after_count),
        exclude_escalation_ids=exclude_esc,
    )
    return jsonify({
        'ok': True,
        'messages': msgs,
        'thread_id': thread_id,
        'total': len(msgs),
    })


@express_partner_bp.get('/ai/history', endpoint='ai_history')
@require_partner_access(allow_pending=True, json_response=True)
def ai_history():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import messages_for_ui, threads_for_ui

    phone = (session.get('user_phone') or '').strip()
    thread_id = (request.args.get('thread_id') or '').strip() or None
    threads_only = request.args.get('threads_only', '').lower() in ('1', 'true', 'yes')
    payload = {
        'ok': True,
        'threads': threads_for_ui(phone, audience=AUDIENCE_PARTNER),
        'thread_id': thread_id,
    }
    if not threads_only:
        payload['messages'] = messages_for_ui(phone, thread_id, audience=AUDIENCE_PARTNER)
    return jsonify(payload)


@express_partner_bp.post('/ai/chat', endpoint='ai_chat')
@require_partner_access(allow_pending=True, json_response=True)
def ai_chat():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import (
        append_exchange,
        ensure_active_thread,
        history_for_api,
        threads_for_ui,
    )
    from app.ai.http_errors import ai_chat_http_status
    from app.ai.services import generate_reply

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or request.form.get('message') or '').strip()
    thread_id = (data.get('thread_id') or '').strip() or None
    if not message:
        return jsonify({'ok': False, 'error': 'پیام خالی است.'}), 400

    if not thread_id:
        thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)

    history = history_for_api(phone, thread_id, audience=AUDIENCE_PARTNER)
    result = generate_reply(
        message,
        history=history,
        user_key=phone,
        audience=AUDIENCE_PARTNER,
        thread_id=thread_id,
    )
    if not result.get('ok'):
        return jsonify(result), ai_chat_http_status(result)

    land_codes = result.get('land_codes') or []
    msgs, tid = append_exchange(
        phone,
        message,
        result.get('reply') or '',
        thread_id=thread_id,
        assistant_land_codes=land_codes,
        audience=AUDIENCE_PARTNER,
    )
    result['messages'] = msgs
    result['audience'] = AUDIENCE_PARTNER
    result['thread_id'] = tid
    result['threads'] = threads_for_ui(phone, audience=AUDIENCE_PARTNER)
    return jsonify(result)


@express_partner_bp.post('/ai/clear', endpoint='ai_clear')
@require_partner_access(allow_pending=True, json_response=True)
def ai_clear():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import clear_chat

    phone = (session.get('user_phone') or '').strip()
    tid = clear_chat(phone, audience=AUDIENCE_PARTNER)
    return jsonify({'ok': True, 'thread_id': tid})


@express_partner_bp.post('/ai/thread/switch', endpoint='ai_switch_thread')
@require_partner_access(allow_pending=True, json_response=True)
def ai_switch_thread():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import messages_for_ui, set_active_thread, threads_for_ui

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get('thread_id') or '').strip()
    if not thread_id or not set_active_thread(phone, thread_id, audience=AUDIENCE_PARTNER):
        return jsonify({'ok': False, 'error': 'گفتگو یافت نشد.'}), 404
    return jsonify({
        'ok': True,
        'thread_id': thread_id,
        'messages': messages_for_ui(phone, thread_id, audience=AUDIENCE_PARTNER),
        'threads': threads_for_ui(phone, audience=AUDIENCE_PARTNER),
    })


@express_partner_bp.post('/ai/thread/delete', endpoint='ai_delete_thread')
@require_partner_access(allow_pending=True, json_response=True)
def ai_delete_thread():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import delete_thread, load_user_record, messages_for_ui, threads_for_ui

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get('thread_id') or '').strip()
    if not thread_id or not delete_thread(phone, thread_id, audience=AUDIENCE_PARTNER):
        return jsonify({'ok': False, 'error': 'حذف ممکن نیست.'}), 400
    record = load_user_record(phone, audience=AUDIENCE_PARTNER)
    active = record.get('active_id')
    return jsonify({
        'ok': True,
        'thread_id': active,
        'messages': messages_for_ui(phone, active, audience=AUDIENCE_PARTNER),
        'threads': threads_for_ui(phone, audience=AUDIENCE_PARTNER),
    })


@express_partner_bp.route('/routine/steps', methods=['POST'], endpoint='routine_steps')
@require_partner_access(allow_pending=True)
def routine_steps():
    """وضعیت تیک‌های امروز — فقط خواندنی؛ ثبت خودکار از فعالیت همکار انجام می‌شود."""
    phone = (session.get("user_phone") or "").strip()
    target_day = datetime.now().strftime('%Y-%m-%d')
    payload = request.get_json(silent=True) or {}
    req_date = (payload.get('date') or '').strip()
    if req_date:
        try:
            datetime.strptime(req_date, "%Y-%m-%d")
            target_day = req_date
        except Exception:
            pass

    detail = routine_detail_for_phone(phone, target_day)
    count = len(detail)
    records = load_partner_routines_cached() or []
    rec = next((r for r in records if str(r.get('phone')) == phone), None) or {}
    resp = make_response(jsonify({
        "success": True,
        "date": target_day,
        "count": count,
        "days": rec.get('days', []),
        "steps": rec.get('steps', {}),
        "detail": detail,
        "auto": True,
    }))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@express_partner_bp.get('/routine/steps/detail')
@require_partner_access(allow_pending=True)
def routine_steps_detail():
    """برگرداندن لیست تیک‌های روز مشخص شده (detail) — ثبت خودکار."""
    phone = (session.get("user_phone") or "").strip()
    date = (request.args.get('date') or '').strip()
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    detail = routine_detail_for_phone(phone, date)
    resp = make_response(jsonify({"success": True, "date": date, "detail": detail, "auto": True}))
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _mark_in_transaction_finish(
    code: str,
    *,
    success: bool,
    message: str,
    category: str = 'success',
    new_status: str | None = None,
    tx_mode: str | None = None,
    visit_date: str | None = None,
    redirect_url: str | None = None,
):
    """پاسخ HTML (redirect) یا JSON برای درخواست AJAX جزئیات فایل."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        payload = {
            'success': success,
            'message': message,
            'new_status': new_status,
            'category': category,
        }
        if tx_mode:
            payload['tx_mode'] = tx_mode
        if visit_date:
            payload['visit_date'] = visit_date
            jalali = format_iso_date_jalali(visit_date)
            if jalali:
                payload['visit_date_jalali'] = jalali
        if success and redirect_url:
            payload['redirect_url'] = redirect_url
        return jsonify(payload), (200 if success else 400)
    if message:
        flash(message, 'land')
    if success:
        if redirect_url:
            return redirect(redirect_url)
        return redirect(url_for('express_partner.land_detail', code=code))
    return redirect(url_for('express_partner.dashboard'))


def _express_land_in_catalog(code: str) -> bool:
    """فایل در لیست اکسپرس (یا آگهی‌ها) وجود دارد."""
    key = str(code or '').strip()
    if not key:
        return False
    try:
        express_lands = load_express_lands_cached() or []
    except Exception:
        express_lands = []
    if any(str(l.get('code') or '').strip() == key for l in express_lands):
        return True
    try:
        lands_all = load_ads_cached() or []
    except Exception:
        lands_all = []
    return any(str(l.get('code') or '').strip() == key for l in lands_all)


def _express_land_partner_ctx(code: str, me_phone: str) -> Dict[str, Any] | None:
    """
    زمینه دسترسی همکار به یک فایل اکسپرس.
    برای بازدید/وضعیت دکمه، داشتن assignment اختصاصی لازم نیست؛ فایل باید در کاتالوگ باشد.
    """
    key = str(code or '').strip()
    ph = (me_phone or '').strip()
    if not key or not ph or not _express_land_in_catalog(key):
        return None
    assignments = load_express_assignments() or []
    global_status = 'active'
    status_priority = {
        'sold': 5, 'in_transaction': 4, 'closed': 3, 'pending': 2, 'approved': 1, 'active': 0, '': 0,
    }
    holder_phone = None
    for a in assignments:
        if str(a.get('land_code') or '').strip() != key:
            continue
        status = _assignment_display_status(a)
        if status_priority.get(status, 0) > status_priority.get(global_status, 0):
            global_status = status
        th = str(a.get('transaction_holder') or '').strip()
        if th:
            holder_phone = th
    my_assignment = next(
        (
            a for a in assignments
            if str(a.get('land_code') or '').strip() == key
            and str(a.get('partner_phone') or '').strip() == ph
        ),
        None,
    )
    return {
        'global_status': global_status,
        'holder_phone': holder_phone,
        'my_assignment': my_assignment,
    }


def _partner_land_tx_payload(
    code: str,
    me_phone: str,
    *,
    is_partner_approved: bool,
    global_assignment_status: str | None = None,
) -> dict:
    assignments = load_express_assignments() or []
    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []
    visit_commission_required = _visit_commission_required_for(commissions, me_phone, code)
    gs = global_assignment_status
    if gs is None:
        gs = 'active'
        status_priority = {
            'sold': 5, 'in_transaction': 4, 'closed': 3, 'pending': 2, 'approved': 1, 'active': 0, '': 0,
        }
        for a in assignments:
            if str(a.get('land_code')) != str(code):
                continue
            status = _assignment_display_status(a)
            if status_priority.get(status, 0) > status_priority.get(gs, 0):
                gs = status
    state = resolve_partner_land_tx_state(
        me_phone=me_phone,
        land_code=str(code),
        assignments=assignments,
        visit_requests=visit_requests,
        is_partner_approved=is_partner_approved,
        global_assignment_status=str(gs or 'active'),
        commissions=commissions,
        visit_commission_required=visit_commission_required,
    )
    return state


def _visit_commission_amount_toman() -> int:
    try:
        settings = load_settings(current_app) or {}
        return max(0, int(settings.get('visit_commission_amount_toman') or 0))
    except Exception:
        return 0


def _has_visit_commission_record(commissions: List[Dict[str, Any]], phone: str, code: str) -> bool:
    ph = (phone or '').strip()
    ck = str(code or '').strip()
    if not ph or not ck:
        return False
    for c in commissions or []:
        if not isinstance(c, dict):
            continue
        if str(c.get('partner_phone') or '').strip() != ph:
            continue
        if str(c.get('land_code') or '').strip() != ck:
            continue
        if commission_is_visit(c) and str(c.get('status') or '').strip().lower() in ('pending', 'approved', 'paid'):
            return True
    return False


def _visit_commission_required_for(commissions: List[Dict[str, Any]], phone: str, code: str) -> bool:
    return _visit_commission_amount_toman() > 0 or _has_visit_commission_record(commissions, phone, code)


@express_partner_bp.route('/visit-requests/<code>', methods=['POST'], endpoint='create_visit_request')
@require_partner_access()
def create_visit_request(code: str):
    """ثبت درخواست بازدید با تاریخ انتخاب‌شده."""
    me_phone = (session.get('user_phone') or '').strip()
    visit_date = (request.form.get('visit_date') or '').strip()
    if not visit_date and request.is_json:
        try:
            visit_date = ((request.get_json(silent=True) or {}).get('visit_date') or '').strip()
        except Exception:
            visit_date = ''

    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get('phone')) == me_phone), None)
    try:
        is_pa = _is_partner_approved(partner_profile)
    except Exception:
        is_pa = False
    if not is_pa:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='برای ثبت درخواست بازدید باید حساب همکاری شما تأیید شده باشد.',
            category='error',
        )

    ctx = _express_land_partner_ctx(code, me_phone)
    if ctx is None:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='فایل موردنظر پیدا نشد یا در لیست اکسپرس موجود نیست.',
            category='error',
        )

    if not ctx.get('my_assignment'):
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='برای این فایل انتساب فعالی برای شما ثبت نشده است. با پشتیبانی تماس بگیرید.',
            category='error',
        )

    current_status = ctx['global_status']
    holder_phone = ctx.get('holder_phone')
    if current_status == 'sold':
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='این فایل قبلاً فروخته شده است.',
            category='error',
        )

    if holder_phone and holder_phone != me_phone:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='این فایل در حال حاضر توسط همکار دیگری در حال معامله است.',
            category='error',
        )
    if current_status == 'in_transaction' or holder_phone == me_phone:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='این فایل در حال معامله است؛ ابتدا معامله را رفع کنید.',
            category='error',
        )

    lands_all = load_ads_cached() or []
    land = next((l for l in lands_all if str(l.get('code')) == str(code)), None)
    land_title = (land.get('title') if land else None) or code

    partner_name = (partner_profile.get('name') if partner_profile else None) or me_phone

    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    rec, err = record_visit_request(
        visit_requests,
        partner_phone=me_phone,
        partner_name=partner_name,
        land_code=str(code),
        land_title=str(land_title),
        visit_date=visit_date,
    )
    if err == 'already_pending':
        open_rec = partner_open_visit(visit_requests, me_phone, str(code))
        vdate = (open_rec or {}).get('visit_date') or visit_date
        try:
            is_pa = _is_partner_approved(partner_profile)
        except Exception:
            is_pa = False
        tx_state = _partner_land_tx_payload(
            code,
            me_phone,
            is_partner_approved=is_pa,
            global_assignment_status=current_status,
        )
        return _mark_in_transaction_finish(
            code,
            success=True,
            message='درخواست بازدید شما قبلاً ثبت شده است. از صفحه درخواست‌ها وضعیت را پیگیری کنید.',
            category='success',
            new_status='active',
            tx_mode=tx_state.get('tx_mode') or 'visit_pending',
            visit_date=vdate,
            redirect_url=url_for('express_partner.requests', submitted=1),
        )
    if err == 'past_date':
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='تاریخ بازدید نمی‌تواند در گذشته باشد.',
            category='error',
        )
    if err == 'date_too_far':
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='تاریخ بازدید حداکثر تا ۹۰ روز آینده قابل انتخاب است.',
            category='error',
        )
    if err == 'weekday_not_allowed':
        from .visit_requests import visit_allowed_weekdays_summary
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='تاریخ انتخاب‌شده در روزهای مجاز بازدید نیست. روزهای مجاز: ' + visit_allowed_weekdays_summary(),
            category='error',
        )
    if err or not rec:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='تاریخ بازدید نامعتبر است.',
            category='error',
        )

    save_express_visit_requests(visit_requests)
    sms_result = _send_visit_admin_sms(
        partner_phone=me_phone,
        partner_name=partner_name,
        land_code=str(code),
        land_title=str(land_title),
        visit_date=rec.get('visit_date') or visit_date,
    )
    try:
        from .visit_sms import notify_partner_land_tx_sms
        notify_partner_land_tx_sms(
            partner_phone=me_phone,
            event='visit_submitted',
            land_code=str(code),
            land_title=str(land_title),
            visit_date=str(rec.get('visit_date') or visit_date),
            reference_id=str(rec.get('id') or ''),
        )
    except Exception:
        current_app.logger.exception(
            'visit_submitted partner SMS failed phone=%s code=%s', me_phone, code
        )
    msg = 'درخواست بازدید ارسال شد. از صفحه درخواست‌ها وضعیت را پیگیری کنید.'
    if not sms_result.get('ok') and not sms_result.get('skipped'):
        msg = 'درخواست بازدید ارسال شد. از صفحه درخواست‌ها وضعیت را پیگیری کنید. (ارسال پیامک به ادمین ناموفق بود.)'

    try:
        is_pa = _is_partner_approved(partner_profile)
    except Exception:
        is_pa = False
    tx_state = _partner_land_tx_payload(
        code,
        me_phone,
        is_partner_approved=is_pa,
        global_assignment_status=current_status,
    )
    _routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)
    return _mark_in_transaction_finish(
        code,
        success=True,
        message=msg,
        category='success',
        new_status='active',
        tx_mode=tx_state.get('tx_mode') or 'visit_pending',
        visit_date=tx_state.get('visit_date') or rec.get('visit_date') or visit_date,
        redirect_url=url_for('express_partner.requests', submitted=1),
    )


@express_partner_bp.route('/visit-requests/<code>/complete', methods=['POST'], endpoint='complete_visit_request')
@require_partner_access()
def complete_visit_request(code: str):
    """ثبت اعلام «بازدید انجام شد» توسط همکار؛ تأیید نهایی با ادمین است."""
    me_phone = (session.get('user_phone') or '').strip()
    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get('phone')) == me_phone), None)
    is_pa = _is_partner_approved(partner_profile)
    if not is_pa:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='برای ثبت انجام بازدید باید حساب همکاری شما تأیید شده باشد.',
            category='error',
        )

    ctx = _express_land_partner_ctx(code, me_phone)
    if ctx is None:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='فایل موردنظر پیدا نشد یا در لیست اکسپرس موجود نیست.',
            category='error',
        )

    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []
    rec, err = request_visit_done_confirmation(visit_requests, me_phone, str(code))
    if err == 'not_approved':
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='ابتدا درخواست بازدید شما باید توسط ادمین تأیید شود.',
            category='error',
        )
    if not rec:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='در ثبت انجام بازدید خطایی رخ داد.',
            category='error',
        )
    save_express_visit_requests(visit_requests)

    tx_state = _partner_land_tx_payload(
        code,
        me_phone,
        is_partner_approved=True,
        global_assignment_status=ctx.get('global_status') or 'active',
    )
    msg = 'بازدید انجام شد ثبت شد و منتظر تأیید ادمین است.'
    if err == 'already_pending':
        msg = 'بازدید انجام شد قبلاً ثبت شده و منتظر تأیید ادمین است.'
    elif err == 'already_completed':
        msg = 'بازدید قبلاً توسط ادمین تأیید شده است.'
    return _mark_in_transaction_finish(
        code,
        success=True,
        message=msg,
        category='success',
        new_status=ctx.get('global_status') or 'active',
        tx_mode=tx_state.get('tx_mode') or 'visit_done_pending',
        visit_date=tx_state.get('visit_date') or None,
    )


@express_partner_bp.get('/lands/<string:code>/tx-status', endpoint='land_tx_status')
@require_partner_access()
def land_tx_status(code: str):
    """وضعیت دکمه بازدید/معامله — برای به‌روزرسانی خودکار پس از تأیید ادمین."""
    me_phone = (session.get('user_phone') or '').strip()
    ctx = _express_land_partner_ctx(code, me_phone)
    if ctx is None:
        return jsonify(success=False, message='فایل یافت نشد.'), 404

    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get('phone')) == me_phone), None)
    try:
        is_partner_approved = _is_partner_approved(partner_profile)
    except Exception:
        is_partner_approved = False

    state = _partner_land_tx_payload(
        code,
        me_phone,
        is_partner_approved=is_partner_approved,
        global_assignment_status=ctx['global_status'],
    )
    if is_partner_approved:
        _routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)
    resp = jsonify(success=True, **state)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@express_partner_bp.route('/mark-in-transaction/<code>', methods=['POST'], endpoint='mark_in_transaction')
@require_partner_access()
def mark_in_transaction(code: str):
    """Toggle وضعیت ملک بین در حال معامله و فعال - فقط یک همکار می‌تواند معامله کند"""
    me_phone = (session.get("user_phone") or "").strip()
    success_message = ''
    success_category = 'success'
    
    try:
        assignments = load_express_assignments() or []
        updated = False
        new_status = None
        
        # ابتدا بررسی می‌کنیم که همکار فعلی دسترسی به این فایل دارد یا نه
        my_assignment = None
        for a in assignments:
            if (str(a.get('land_code')) == str(code) and 
                str(a.get('partner_phone')) == me_phone):
                my_assignment = a
                break
        
        if my_assignment is None:
            return _mark_in_transaction_finish(
                code,
                success=False,
                message='فایل موردنظر پیدا نشد یا دسترسی شما به آن محدود است.',
                category='error',
            )
        
        current_status = my_assignment.get('status', 'active')
        
        # اگر فایل فروخته شده، امکان تغییر وضعیت نیست
        if current_status == 'sold':
            return _mark_in_transaction_finish(
                code,
                success=False,
                message='این فایل قبلاً فروخته شده و امکان تغییر وضعیت آن وجود ندارد.',
                category='error',
            )
        
        # بررسی آیا فایل توسط همکاری در حال معامله است (چک کردن transaction_holder)
        holder_phone = None
        for a in assignments:
            if str(a.get('land_code')) == str(code) and a.get('transaction_holder'):
                holder_phone = str(a.get('transaction_holder', ''))
                break
        
        # اگر در حال معامله توسط کسی هست
        if holder_phone:
            # فقط همان همکار می‌تواند رفع معامله کند
            if holder_phone != me_phone:
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='این فایل در حال حاضر توسط همکار دیگری در حال معامله است و فقط همان همکار می‌تواند وضعیت را تغییر دهد.',
                    category='error',
                )
            # همکار صاحب معامله می‌خواهد رفع معامله کند
            new_status = 'active'
        else:
            # بررسی تعداد فایل‌های در حال معامله این همکار (حداکثر ۲ فایل)
            my_transaction_count = sum(
                1 for a in assignments 
                if a.get('transaction_holder') == me_phone
            )
            if my_transaction_count >= 2:
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='شما هم‌زمان فقط می‌توانید روی ۲ فایل در حال معامله باشید.',
                    category='error',
                )
            visit_requests = load_express_visit_requests() or []
            if not isinstance(visit_requests, list):
                visit_requests = []
            completed_visit = partner_visit_completed(visit_requests, me_phone, code)
            commissions_for_visit = load_express_commissions() or []
            if not isinstance(commissions_for_visit, list):
                commissions_for_visit = []
            visit_commission_required = _visit_commission_required_for(commissions_for_visit, me_phone, code)
            if not completed_visit:
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='برای ثبت درخواست معامله، ابتدا بازدید را انجام‌شده ثبت کنید.',
                    category='error',
                )
            if visit_commission_required and not visit_commission_ready_for_deal(commissions_for_visit, me_phone, code):
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='برای ثبت درخواست معامله، ابتدا پورسانت بازدید باید توسط ادمین تأیید و به کیف پول شما اضافه شود.',
                    category='error',
                )
            # هیچ‌کس معامله نکرده، این همکار می‌تواند معامله کند
            new_status = 'in_transaction'
        
        # اعمال تغییرات
        for a in assignments:
            if str(a.get('land_code')) == str(code):
                current_a_status = a.get('status', 'active')
                if current_a_status in ('active', 'pending', 'in_transaction'):
                    a['status'] = new_status
                    a['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # ذخیره همکار صاحب معامله و زمان شروع
                    if new_status == 'in_transaction':
                        a['transaction_holder'] = me_phone
                        a['transaction_started_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        a.pop('transaction_holder', None)
                        a.pop('transaction_started_at', None)
                    updated = True
                    current_app.logger.info(f"Updated assignment {a.get('id')} for partner {a.get('partner_phone')} to status {new_status}")
        
        if updated:
            save_express_assignments(assignments)

            # اگر وضعیت به "در حال معامله" تغییر کرد، رکورد پورسانت ایجاد کن
            if new_status == 'in_transaction':
                try:
                    # بارگذاری اطلاعات فایل برای محاسبه پورسانت
                    lands_all = load_ads_cached() or []
                    land = next((l for l in lands_all if str(l.get('code')) == str(code)), None)
                    
                    if not land:
                        current_app.logger.warning(f"Land {code} not found in cache")
                        success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد. (اطلاعات کامل فایل در دسترس نیست)'
                    else:
                        # بارگذاری کمیسیون‌های موجود
                        commissions = load_express_commissions() or []
                        created_count = 0
                        skipped_count = 0
                        
                        # فقط برای همکاری که معامله را شروع کرده پورسانت ایجاد کن
                        my_assignment_for_commission = next(
                            (a for a in assignments 
                             if str(a.get('land_code')) == str(code) and 
                                str(a.get('partner_phone')) == me_phone),
                            None
                        )
                        
                        if my_assignment_for_commission:
                            partner_phone = me_phone
                            from .new_land_sms import (
                                resolve_express_land_commission_amount,
                                resolve_express_land_commission_pct,
                            )
                            commission_pct = resolve_express_land_commission_pct(land)
                            commission_amount = resolve_express_land_commission_amount(land)
                            try:
                                price_total = int(
                                    str(land.get('price_total') or land.get('price') or '0')
                                    .replace(',', '').replace(' ', '').strip() or '0'
                                )
                            except Exception:
                                price_total = 0
                            
                            # بررسی پورسانت فعال قبلی (ردشده مجدداً قابل ثبت است)
                            if commission_blocks_new_deal_record(commissions, partner_phone, str(code)):
                                current_app.logger.info(
                                    "Active commission already exists for partner %s land %s",
                                    partner_phone,
                                    code,
                                )
                                skipped_count += 1
                            elif commission_pct > 0:
                                if commission_amount <= 0:
                                    current_app.logger.warning(
                                        "Commission amount is 0 for partner %s, land %s: price=%s, pct=%s",
                                        partner_phone, code, price_total, commission_pct,
                                    )
                                elif commission_amount > 0:
                                    # ایجاد ID جدید
                                    new_id = (max([int(x.get('id', 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
                                    
                                    # ایجاد رکورد پورسانت
                                    new_commission = {
                                        'id': new_id,
                                        'commission_type': 'deal',
                                        'partner_phone': partner_phone,
                                        'land_code': str(code),
                                        'sale_amount': price_total,
                                        'commission_pct': commission_pct,
                                        'commission_amount': commission_amount,
                                        'status': 'pending',
                                        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    }
                                    
                                    commissions.append(new_commission)
                                    created_count += 1
                                    try:
                                        from .admin_action_sms import notify_admin_pending_action
                                        notify_admin_pending_action(
                                            'commission',
                                            partner_phone=partner_phone,
                                            partner_name=_partner_display_name(partner_phone),
                                            land_code=str(code),
                                            amount=commission_amount,
                                        )
                                    except Exception:
                                        current_app.logger.exception(
                                            'commission pending admin SMS failed partner=%s land=%s',
                                            partner_phone,
                                            code,
                                        )
                                    try:
                                        from .commission_sms import notify_partner_commission_txn
                                        notify_partner_commission_txn(
                                            partner_phone=partner_phone,
                                            event='commission_pending',
                                            amount=commission_amount,
                                            land_code=str(code),
                                            reference_id=str(new_id),
                                        )
                                    except Exception:
                                        current_app.logger.exception(
                                            'commission_pending SMS failed partner=%s land=%s',
                                            partner_phone,
                                            code,
                                        )
                                    current_app.logger.info(f"Created commission record {new_id} for partner {partner_phone} and land {code}: amount={commission_amount}, pct={commission_pct}, price={price_total}")
                            else:
                                current_app.logger.warning(f"Commission percentage is 0 or missing for partner {partner_phone}, land {code}")
                        
                        if created_count > 0:
                            save_express_commissions(commissions)
                            success_message = 'درخواست معامله ثبت شد. پس از تأیید ادمین، مبلغ به موجودی پورسانت شما اضافه می‌شود.'
                        else:
                            if skipped_count > 0:
                                success_message = 'درخواست معامله ثبت شد. (پورسانت فعال قبلی برای این فایل وجود دارد.)'
                            else:
                                success_message = 'درخواست معامله ثبت شد. پس از تأیید ادمین، مبلغ به موجودی پورسانت شما اضافه می‌شود.'
                        if not success_message:
                            success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد.'
                except Exception as e:
                    current_app.logger.error(f"Error creating commission records: {e}", exc_info=True)
                    success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد، اما در ثبت پورسانت خطایی رخ داد.'
                    success_category = 'warning'
            else:
                # رفع معامله: بازگرداندن بازدید تأییدشده + حذف پورسانت pending
                visit_requests = load_express_visit_requests() or []
                if not isinstance(visit_requests, list):
                    visit_requests = []
                if restore_visit_approved_after_deal_release(visit_requests, me_phone, code):
                    save_express_visit_requests(visit_requests)

                try:
                    commissions = load_express_commissions() or []
                    removed_count = 0
                    
                    # پیدا کردن و حذف پورسانت‌های pending مربوط به این فایل
                    commissions_to_keep = []
                    for c in commissions:
                        if (
                            str(c.get('land_code')) == str(code)
                            and str(c.get('partner_phone') or '').strip() == me_phone
                            and c.get('status') == 'pending'
                            and commission_is_deal(c)
                        ):
                            # این پورسانت را حذف می‌کنیم
                            removed_count += 1
                            current_app.logger.info(f"Removed pending commission {c.get('id')} for land {code}")
                        else:
                            commissions_to_keep.append(c)
                    
                    if removed_count > 0:
                        save_express_commissions(commissions_to_keep)
                        success_message = f'وضعیت ملک به «فعال» تغییر کرد و {removed_count} پورسانت در انتظار حذف شد.'
                    else:
                        success_message = 'وضعیت ملک به «فعال» تغییر کرد.'
                except Exception as e:
                    current_app.logger.error(f"Error removing commission records: {e}")
                    success_message = 'وضعیت ملک به «فعال» تغییر کرد.'
            if not success_message:
                success_message = (
                    'ملک به عنوان «در حال معامله» علامت‌گذاری شد.'
                    if new_status == 'in_transaction'
                    else 'وضعیت ملک به «فعال» تغییر کرد.'
                )
            tx_state = _partner_land_tx_payload(
                code,
                me_phone,
                is_partner_approved=True,
                global_assignment_status=new_status or 'active',
            )
            try:
                from .visit_sms import notify_partner_land_tx_sms
                lands_all = load_ads_cached() or []
                land_row = next(
                    (l for l in lands_all if str(l.get('code')) == str(code)),
                    None,
                )
                land_title_sms = (land_row.get('title') if land_row else None) or str(code)
                if new_status == 'in_transaction':
                    notify_partner_land_tx_sms(
                        partner_phone=me_phone,
                        event='deal_started',
                        land_code=str(code),
                        land_title=str(land_title_sms),
                        visit_date=str(tx_state.get('visit_date') or ''),
                    )
                elif new_status == 'active':
                    notify_partner_land_tx_sms(
                        partner_phone=me_phone,
                        event='deal_released',
                        land_code=str(code),
                        land_title=str(land_title_sms),
                    )
            except Exception:
                current_app.logger.exception(
                    'deal tx partner SMS failed phone=%s code=%s status=%s',
                    me_phone,
                    code,
                    new_status,
                )
            if new_status == 'in_transaction':
                _routine_auto_tick(me_phone, ROUTINE_STEP_DEAL)
            return _mark_in_transaction_finish(
                code,
                success=True,
                message=success_message,
                category=success_category,
                new_status=new_status,
                tx_mode=tx_state.get('tx_mode'),
                visit_date=tx_state.get('visit_date') or None,
            )
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='در بروزرسانی وضعیت فایل خطایی رخ داد. لطفاً چند لحظه دیگر دوباره تلاش کنید.',
            category='error',
        )
    except Exception as e:
        current_app.logger.error(f"Error toggling land transaction status: {e}")
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='در بروزرسانی وضعیت فایل خطایی رخ داد. لطفاً چند لحظه دیگر دوباره تلاش کنید.',
            category='error',
        )


@express_partner_bp.route('/logout', methods=['POST'], endpoint='logout')
def logout():
    """خروج با POST؛ اعتبار از کوکی سشن (در اپ CSRF معاف است تا توکن کهنه خروج را نشکند)."""
    from ..utils.flash_messages import FLASH_AUTH_INFO

    _clear_express_partner_auth_session()
    flash('از حساب خارج شدید.', FLASH_AUTH_INFO)
    dest = _logout_dest_url()
    r = redirect(dest)
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    r.headers['Pragma'] = 'no-cache'
    return r


@express_partner_bp.post('/api/logout')
def api_logout():
    """خروج برای اپ اندروید / WebView (بدون CSRF؛ با کوکی سشن)."""
    _clear_express_partner_auth_session()
    dest = _logout_dest_url()
    resp = jsonify({'success': True, 'redirect': dest})
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@express_partner_bp.post('/api/login-request')
def api_login_request():
    """درخواست ارسال کد OTP برای اپ اندروید (ورود نیتیو). ورودی JSON: {"phone": "09..."}."""
    data = request.get_json(silent=True) or {}
    phone_raw = (data.get('phone') or '').strip()
    phone = _otp_canonical_phone(phone_raw)
    if not _legal_accepted(request):
        return jsonify({
            'success': False,
            'error': 'پذیرش حریم خصوصی و قوانین استفاده الزامی است.',
            'legal_required': True,
        }), 400
    from ..services.sms import is_valid_iran_mobile

    if not is_valid_iran_mobile(phone):
        return jsonify({'success': False, 'error': 'شماره موبایل معتبر نیست.'}), 400

    code = f"{random.randint(10000, 99999)}"
    _store_otp_session(phone, code)
    _dispatch_otp_sms(phone, code)
    return jsonify({'success': True, 'message': 'کد تأیید ارسال شد.'})


@express_partner_bp.post('/api/verify')
def api_verify():
    """تأیید کد OTP برای اپ اندروید. ورودی JSON: {"code": "12345", "phone": "09..."}."""
    from ..services.sms import normalize_otp_code, is_valid_iran_mobile

    data = request.get_json(silent=True) or {}
    code = normalize_otp_code(data.get('code') or '')
    req_phone = _otp_canonical_phone((data.get('phone') or '').strip())
    if not code:
        return jsonify({'success': False, 'error': 'کد تأیید را وارد کنید.'}), 400
    if not is_valid_iran_mobile(req_phone):
        return jsonify({'success': False, 'error': 'شماره موبایل معتبر نیست.'}), 400
    sess_phone = _otp_session_phone()
    if not sess_phone or not session.get('otp_code'):
        return jsonify({'success': False, 'error': 'جلسهٔ تأیید منقضی شده. دوباره درخواست کد دهید.'}), 400
    if _otp_session_expired():
        _clear_otp_session()
        return jsonify({'success': False, 'error': 'کد تأیید منقضی شده است. دوباره درخواست کد دهید.'}), 400
    if req_phone != sess_phone:
        return jsonify({'success': False, 'error': 'شماره با درخواست ورود همخوانی ندارد.'}), 400
    verified_phone = _verify_otp_for_phone(code, req_phone)
    if not verified_phone:
        return jsonify({'success': False, 'error': 'کد تأیید نادرست است.'}), 400
    try:
        from .referrals import capture_ref_on_login
        capture_ref_on_login()
    except Exception:
        pass
    dest = _finalize_partner_login(verified_phone)
    return jsonify({'success': True, 'message': 'ورود با موفقیت انجام شد.', 'redirect': dest})


@express_partner_bp.route('/otp/resend', methods=['POST'], endpoint='otp_resend')
def otp_resend():
    # پشتیبانی از JSON (اپ) و form (وب)
    data = request.get_json(silent=True) or {}
    from ..services.sms import is_valid_iran_mobile

    sess_phone = _otp_session_phone()
    if not sess_phone or not session.get('otp_code'):
        if request.is_json:
            return jsonify({'ok': False, 'error': 'ابتدا شماره را وارد کنید.'}), 400
        return jsonify({'ok': False, 'error': 'ابتدا شماره را وارد کنید.'}), 400
    if _otp_session_expired():
        _clear_otp_session()
        if request.is_json:
            return jsonify({'ok': False, 'error': 'کد منقضی شده. دوباره وارد شوید.'}), 400
        return jsonify({'ok': False, 'error': 'کد منقضی شده. دوباره وارد شوید.'}), 400
    req_phone = _otp_canonical_phone(
        (data.get('phone') or request.form.get('phone') or '').strip()
    )
    phone = sess_phone
    if req_phone and req_phone != sess_phone:
        if request.is_json:
            return jsonify({'ok': False, 'error': 'شماره با درخواست ورود همخوانی ندارد.'}), 400
        return jsonify({'ok': False, 'error': 'شماره با درخواست ورود همخوانی ندارد.'}), 400
    if not is_valid_iran_mobile(phone):
        if request.is_json:
            return jsonify({'ok': False, 'error': 'شماره معتبر نیست.'}), 400
        return jsonify({'ok': False, 'error': 'شماره معتبر نیست.'}), 400
    try:
        code = f"{random.randint(10000, 99999)}"
        _store_otp_session(phone, code)
        _dispatch_otp_sms(phone, code)
        if request.is_json:
            return jsonify({'ok': True, 'message': 'کد تأیید مجدد ارسال شد.'})
        return jsonify({'ok': True})
    except Exception:
        if request.is_json:
            return jsonify({'ok': False, 'error': 'خطا در ارسال مجدد کد.'}), 502
        return jsonify({'ok': False, 'error': 'خطا در ارسال مجدد کد.'}), 502


@express_partner_bp.route('/profile', methods=['GET'], endpoint='profile')
@require_partner_access(allow_pending=True, allow_guest=True)
def profile_page():
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    # تعیین وضعیت تایید همکاری
    try:
        is_approved = bool(profile and ((str(profile.get('status') or '').lower() == 'approved') or (profile.get('status') is True)))
    except Exception:
        is_approved = False
    me_name = (profile.get('name') or '').strip()
    # Inject latest APK info from settings for direct rendering
    _settings = _express_settings_cached()
    _raw_apk_url = (_settings.get('android_apk_url') or '').strip()
    android_apk_version = (_settings.get('android_apk_version') or '').strip()
    from ..utils.short_urls import public_apk_download_url
    android_apk_url = public_apk_download_url(_settings, external=False) if _raw_apk_url else ''
    android_apk_updated_at = _settings.get('android_apk_updated_at') or ''
    android_apk_size_bytes = _settings.get('android_apk_size_bytes') or ''
    from ..utils.apk_version import is_vinor_apk_request, should_show_apk_update
    is_vinor_apk = is_vinor_apk_request(request)
    show_app_update_card = should_show_apk_update(
        android_apk_version,
        apk_url=_raw_apk_url,
        req=request,
    )
    from .referrals import REFERRAL_BONUS_AMOUNT
    resp = make_response(render_template(
        'express_partner/profile.html',
        me_phone=me_phone,
        me_name=me_name,
        profile=profile,
        is_approved=is_approved,
        referral_bonus_per_invite=REFERRAL_BONUS_AMOUNT,
        android_apk_url=android_apk_url,
        android_apk_version=android_apk_version,
        android_apk_updated_at=android_apk_updated_at,
        android_apk_size_bytes=android_apk_size_bytes,
        is_vinor_apk=is_vinor_apk,
        show_app_update_card=show_app_update_card,
    ))
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/profile/data', endpoint='profile_data')
@require_partner_access(allow_pending=True, allow_guest=True)
def profile_data():
    """API JSON برای اپ اندروید: داده پروفایل همکار (برای صفحه من نیتیو)."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    try:
        is_approved = bool(profile and ((str(profile.get('status') or '').lower() == 'approved') or (profile.get('status') is True)))
    except Exception:
        is_approved = False
    me_name = (profile.get('name') or '').strip()
    avatar = (profile.get('avatar') or '').strip()
    from ..utils.images import display_avatar_url
    avatar_url = display_avatar_url(avatar, profile.get('avatar_updated_at')) if avatar else None
    _settings = _express_settings_cached()
    _raw_apk_url = (_settings.get('android_apk_url') or '').strip()
    android_apk_version = (_settings.get('android_apk_version') or '').strip()
    from ..utils.short_urls import public_apk_download_url
    android_apk_url = public_apk_download_url(_settings, external=False) if _raw_apk_url else ''
    from ..utils.apk_version import should_show_apk_update
    show_app_update = should_show_apk_update(
        android_apk_version,
        apk_url=_raw_apk_url,
        req=request,
    )
    try:
        from flask_wtf.csrf import generate_csrf
        csrf_token = generate_csrf()
    except Exception:
        csrf_token = ''
    return jsonify({
        'success': True,
        'me_phone': me_phone,
        'me_name': me_name or 'همکار وینور',
        'avatar_url': avatar_url,
        'is_approved': is_approved,
        'android_apk_url': android_apk_url if show_app_update else '',
        'android_apk_version': android_apk_version if show_app_update else '',
        'show_app_update': show_app_update,
        'csrf_token': csrf_token,
    })


def _normalize_profile_birth_date(birth_date: str, prev_birth: str = '') -> str:
    """سال-only از UI را با تاریخ کامل قبلی ادغام می‌کند."""
    birth_date = (birth_date or '').strip()[:32]
    prev_birth = (prev_birth or '').strip()
    if not birth_date:
        return ''
    if prev_birth and '/' in prev_birth:
        parts = [p.strip() for p in prev_birth.split('/') if p.strip()]
        head = parts[0] if parts else ''
        if head and birth_date.isdigit() and len(birth_date) <= 4:
            if birth_date == head:
                return prev_birth
            if len(parts) >= 2:
                return birth_date + '/' + '/'.join(parts[1:])
    return birth_date


def _apply_partner_profile_fields(
    profile: Dict[str, Any],
    *,
    name: str,
    city: str,
    bio: str,
    birth_date: str,
    cities_allowed: List[str] | None,
    landline: str | None = None,
    email: str | None = None,
) -> Dict[str, Any]:
    """به‌روزرسانی فیلدهای قابل ویرایش پروفایل همکار روی همان dict."""
    prev_birth = (profile.get('birth_date') or '').strip()
    birth_date = _normalize_profile_birth_date(birth_date, prev_birth)
    name = (name or '').strip()[:60]
    city = (city or '').strip()[:60]
    bio = (bio or '').strip()[:200]

    if name:
        profile['name'] = name
    else:
        profile.pop('name', None)
    if city:
        if cities_allowed and city not in cities_allowed:
            city = ''
        if city:
            profile['city'] = city
        else:
            profile.pop('city', None)
    else:
        profile.pop('city', None)
    if bio:
        profile['bio'] = bio
    else:
        profile.pop('bio', None)
    if landline is not None:
        landline = (landline or '').strip()[:20]
        if landline:
            profile['landline'] = landline
        else:
            profile.pop('landline', None)
    if email is not None:
        email = (email or '').strip()[:120]
        if email:
            profile['email'] = email
        else:
            profile.pop('email', None)
    if birth_date:
        profile['birth_date'] = birth_date
    else:
        profile.pop('birth_date', None)
    return profile


def _profile_edit_json(profile: Dict[str, Any], me_phone: str) -> Dict[str, Any]:
    avatar = (profile.get('avatar') or '').strip()
    from ..utils.images import display_avatar_url
    return {
        'success': True,
        'me_phone': me_phone,
        'me_name': (profile.get('name') or '').strip(),
        'me_city': (profile.get('city') or '').strip(),
        'me_bio': (profile.get('bio') or '').strip(),
        'me_landline': (profile.get('landline') or '').strip(),
        'me_email': (profile.get('email') or '').strip(),
        'me_birth_date': (profile.get('birth_date') or '').strip(),
        'avatar_url': display_avatar_url(avatar, profile.get('avatar_updated_at')) if avatar else None,
        'avatar_updated_at': int(profile.get('avatar_updated_at') or 0) if avatar else 0,
    }


@express_partner_bp.route('/profile/edit', methods=['GET', 'POST'], endpoint='profile_edit')
@require_partner_access(allow_pending=True)
def profile_edit_page():
    """
    ویرایش مشخصات همکار: نام، شهر، بیو، تاریخ تولد؛ موبایل فقط نمایش.
    هر همکار با شمارهٔ session (user_phone) در لیست express_partners شناسایی می‌شود؛
    تمام فیلدها فقط روی همان دیکشنری پروفایل همان شماره ذخیره می‌شوند (مجزا از بقیهٔ کاربران).
    """
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    from ..utils.flash_messages import purge_stale_auth_flashes, purge_stale_land_flashes
    purge_stale_land_flashes()
    purge_stale_auth_flashes()
    partners = load_express_partners() or []
    profile = _find_partner_record(partners, me_phone)
    if not profile:
        profile = {'phone': me_phone}

    cities_allowed = _active_cities_cached()

    if request.method == 'POST':
        profile = _get_or_create_partner_record(partners, me_phone)
        _apply_partner_profile_fields(
            profile,
            name=request.form.get('name') or '',
            city=request.form.get('city') or '',
            bio=request.form.get('bio') or '',
            birth_date=request.form.get('birth_date') or '',
            cities_allowed=cities_allowed,
        )
        try:
            save_express_partners(partners)
            _invalidate_partner_session_cache()
            flash('مشخصات با موفقیت به‌روزرسانی شد.', 'profile')
        except Exception:
            current_app.logger.error("Failed to save partner profile edits", exc_info=True)
            flash('خطا در ذخیره مشخصات.', 'profile')
        return redirect(url_for('express_partner.profile_edit'))

    me_name = (profile.get('name') or '').strip()
    me_city = (profile.get('city') or '').strip()
    me_bio = (profile.get('bio') or '').strip()
    me_birth_date = (profile.get('birth_date') or '').strip()
    cities = cities_allowed
    return render_template('express_partner/profile_edit.html',
                           me_phone=me_phone,
                           me_phone_tail=phone_last4(me_phone),
                           me_name=me_name,
                           me_city=me_city,
                           me_bio=me_bio,
                           me_birth_date=me_birth_date,
                           profile=profile,
                           cities=cities)


@express_partner_bp.get('/profile/edit/data', endpoint='profile_edit_data')
@require_partner_access(allow_pending=True)
def profile_edit_data():
    """API JSON برای اپ اندروید: داده فرم ویرایش پروفایل."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    partners = load_express_partners() or []
    profile = _find_partner_record(partners, me_phone) or {'phone': me_phone}
    cities = _active_cities_cached()
    payload = _profile_edit_json(profile, me_phone)
    payload['cities'] = cities if isinstance(cities, list) else []
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@express_partner_bp.post('/api/profile/update')
@require_partner_access(allow_pending=True, json_response=True)
def api_profile_update():
    """به‌روزرسانی نام، شهر، درباره من برای وب و اپ (JSON)."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    data = request.get_json(silent=True)
    if not data and request.data:
        try:
            data = json.loads(request.data.decode('utf-8') if isinstance(request.data, bytes) else request.data)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    name = (data.get('name') or '').strip()[:60]
    if not name:
        return jsonify({'success': False, 'error': 'name_required'}), 400
    partners = load_express_partners() or []
    profile = _get_or_create_partner_record(partners, me_phone)
    cities_allowed = _active_cities_cached()
    _apply_partner_profile_fields(
        profile,
        name=name,
        city=data.get('city') or '',
        bio=data.get('bio') or '',
        birth_date=data.get('birth_date') or '',
        cities_allowed=cities_allowed,
    )
    try:
        save_express_partners(partners)
        _invalidate_partner_session_cache()
        return jsonify(_profile_edit_json(profile, me_phone))
    except Exception:
        current_app.logger.error("Failed to save partner profile edits", exc_info=True)
        return jsonify({'success': False, 'error': 'save_failed'}), 500


@express_partner_bp.post('/profile/delete-account', endpoint='profile_delete_account')
@require_partner_access(allow_pending=True)
def profile_delete_account():
    """حذف داده‌های همکار و خروج از سشن (غیرقابل بازگشت)."""
    me_phone = (session.get('user_phone') or '').strip()
    if not me_phone:
        return redirect(url_for('express_partner.login'))

    if (request.form.get('confirm_delete') or '').strip() != '1':
        flash('برای حذف حساب، گزینهٔ تأیید را علامت بزنید.', 'profile')
        return redirect(url_for('express_partner.profile_edit'))

    confirm_tail = phone_last4(request.form.get('confirm_phone_tail') or '')
    expected_tail = phone_last4(me_phone)
    if confirm_tail != expected_tail:
        flash('۴ رقم آخر شماره موبایل با شمارهٔ حساب شما مطابقت ندارد.', 'profile')
        return redirect(url_for('express_partner.profile_edit'))

    from ..utils.partner_account import admin_purge_person_account
    result = admin_purge_person_account(me_phone)
    if not result.get('ok'):
        current_app.logger.error(
            'Partner account purge incomplete for %s: %s',
            me_phone,
            result.get('errors'),
        )
        flash('حذف کامل حساب انجام نشد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.', 'profile')
        return redirect(url_for('express_partner.profile_edit'))

    _invalidate_partner_session_cache()
    _clear_express_partner_auth_session()
    from ..utils.flash_messages import FLASH_AUTH_INFO

    flash('حساب کاربری شما حذف شد.', FLASH_AUTH_INFO)
    r = redirect(url_for('express_partner.login'))
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    r.headers['Pragma'] = 'no-cache'
    return r


def _save_partner_avatar_upload(me_phone: str, f) -> str | None:
  """ذخیره فایل آواتار بدون پردازش. مسیر نسبی partner/avatars/... یا None."""
  if not me_phone or not f or not f.filename:
      return None
  base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', 'avatars', me_phone)
  os.makedirs(base, exist_ok=True)
  try:
      for fn in os.listdir(base):
          try:
              if fn.startswith('avatar.'):
                  os.remove(os.path.join(base, fn))
          except Exception:
              continue
  except Exception:
      pass
  orig_lower = (f.filename or '').lower()
  ext = '.jpg'
  for e in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
      if orig_lower.endswith(e):
          ext = e
          break
  final_name = 'avatar' + ext
  final_path = os.path.join(base, final_name)
  try:
      f.stream.seek(0)
      f.save(final_path)
  except Exception:
      current_app.logger.error("Failed to save partner avatar file", exc_info=True)
      return None
  partners = load_express_partners() or []
  prof = _get_or_create_partner_record(partners, me_phone)
  rel_path = f'partner/avatars/{_canonical_partner_phone(me_phone) or me_phone}/{os.path.basename(final_path)}'
  prof['avatar'] = rel_path
  try:
      from time import time as _now
      prof['avatar_updated_at'] = int(_now())
  except Exception:
      prof['avatar_updated_at'] = 0
  try:
      save_express_partners(partners)
      _invalidate_partner_session_cache()
  except Exception:
      current_app.logger.error("Failed to save partner avatar path", exc_info=True)
      return None
  return rel_path


@express_partner_bp.post('/api/profile/avatar')
def api_profile_avatar():
    """آپلود آواتار برای اپ اندروید (multipart، بدون CSRF)."""
    if not session.get('user_phone'):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    f = request.files.get('avatar')
    if not f or not f.filename:
        return jsonify({'success': False, 'error': 'no_file'}), 400
    rel_path = _save_partner_avatar_upload(me_phone, f)
    if not rel_path:
        return jsonify({'success': False, 'error': 'save_failed'}), 500
    partners = load_express_partners() or []
    prof = _find_partner_record(partners, me_phone) or {}
    updated_at = int((prof or {}).get('avatar_updated_at') or 0)
    from ..utils.images import display_avatar_url
    return jsonify({
        'success': True,
        'avatar_url': display_avatar_url(rel_path, updated_at),
        'avatar_updated_at': updated_at,
    })


@express_partner_bp.post('/profile/avatar')
@require_partner_access(allow_pending=True)
def profile_avatar_upload():
    """
    آپلود و تنظیم آواتار پروفایل همکار
    """
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    f = request.files.get('avatar')
    if not f or not f.filename:
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))
    rel_path = _save_partner_avatar_upload(me_phone, f)
    if not rel_path:
        flash('خطا در ذخیره تصویر پروفایل.', 'profile')
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))
    flash('عکس پروفایل به‌روز شد.', 'profile')
    return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))


@express_partner_bp.route('/top-sellers', methods=['GET'], endpoint='top_sellers')
@require_partner_access(allow_pending=True, allow_guest=True)
def top_sellers_page():
    """صفحه فروشنده‌های برتر"""
    try:
        partners = load_express_partners() or []
        
        # محاسبه آمار برای هر همکار
        def _i(v):
            try:
                return int(str(v).replace(',', '').strip() or '0')
            except Exception:
                return 0
        
        # محاسبه مجموع پورسانت‌های تایید شده برای هر همکار
        comms = load_express_commissions() or []
        partner_stats = {}
        
        for partner in partners:
            partner_phone = str(partner.get('phone', '')).strip()
            if not partner_phone:
                continue
            
            # پورسانت‌های تایید شده و پرداخت شده
            my_comms = [c for c in comms if str(c.get('partner_phone', '')).strip() == partner_phone]
            total_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
            sales_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
            
            partner_stats[partner_phone] = {
                'partner': partner,
                'total_commission': total_commission,
                'sales_count': sales_count,
                'total_income': _i(partner.get('total_income', 0)),
                'approved_sales_count': _i(partner.get('approved_sales_count', 0))
            }
        
        # مرتب‌سازی بر اساس مجموع درآمد (total_income یا total_commission)
        top_sellers = sorted(
            partner_stats.values(),
            key=lambda x: max(x['total_income'], x['total_commission']),
            reverse=True
        )
        
        # فقط همکارانی که حداقل یک فروش داشته‌اند
        top_sellers = [s for s in top_sellers if s['sales_count'] > 0 or s['approved_sales_count'] > 0]
        
    except Exception as e:
        current_app.logger.error(f"Error loading top sellers: {e}", exc_info=True)
        top_sellers = []
    
    return render_template(
        'express_partner/top_sellers.html',
        top_sellers=top_sellers
    )


@express_partner_bp.post('/files/<int:fid>/delete')
@require_partner_access(allow_pending=True)
def delete_file(fid: int):
    me_phone = (session.get("user_phone") or "").strip()
    metas = load_partner_files_meta() or []
    kept = []
    removed = None
    for m in metas:
        try:
            if int(m.get('id',0) or 0) == int(fid) and str(m.get('phone')) == me_phone:
                removed = m
            else:
                kept.append(m)
        except Exception:
            kept.append(m)
    save_partner_files_meta(kept)
    if removed:
        try:
            base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', me_phone)
            fp = os.path.join(base, removed.get('filename') or '')
            if os.path.isfile(fp):
                os.remove(fp)
        except Exception:
            pass
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.post('/sales/<int:sid>/update')
@require_partner_access(allow_pending=True)
def update_sale(sid: int):
    me_phone = (session.get("user_phone") or "").strip()
    items = load_partner_sales() or []
    for s in items:
        try:
            if int(s.get('id',0) or 0) == int(sid) and str(s.get('phone')) == me_phone:
                title = (request.form.get("title") or "").strip() or s.get('title')
                amount = (request.form.get("amount") or "").strip()
                note = (request.form.get("note") or "").strip()
                try:
                    amount_num = int(str(amount).replace(',', '').strip()) if amount else s.get('amount') or 0
                except Exception:
                    amount_num = s.get('amount') or 0
                s.update({ 'title': title, 'amount': amount_num, 'note': note })
                break
        except Exception:
            continue
    save_partner_sales(items)
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.post('/sales/<int:sid>/delete')
@require_partner_access(allow_pending=True)
def delete_sale(sid: int):
    me_phone = (session.get("user_phone") or "").strip()
    items = load_partner_sales() or []
    items = [s for s in items if not (int(s.get('id',0) or 0) == int(sid) and str(s.get('phone')) == me_phone)]
    save_partner_sales(items)
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.get('/notifications', endpoint='notifications')
@require_partner_access(allow_pending=True)
def notifications_page():
    from app.services.postchi import postchi_preview

    me_phone = _normalize_phone((session.get('user_phone') or '').strip())
    notifications = get_user_notifications(me_phone, limit=50) if me_phone else []
    unread = unread_count(me_phone) if me_phone else 0
    postchi = postchi_preview(me_phone) if me_phone else {
        'preview': 'پیام‌های رسمی وینور',
        'unread': 0,
        'subtitle': 'پستچی وینور',
    }
    resp = make_response(render_template(
        'express_partner/notifications.html',
        notifications=notifications,
        unread_count=unread,
        postchi=postchi,
        postchi_url=url_for('express_partner.postchi'),
    ))
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/postchi', endpoint='postchi')
@require_partner_access(allow_pending=True)
def postchi_page():
    from app.services.postchi import build_thread

    me_phone = _normalize_phone((session.get('user_phone') or '').strip())
    messages = build_thread(me_phone) if me_phone else []
    resp = make_response(render_template(
        'express_partner/postchi.html',
        messages=messages,
        back_url=url_for('express_partner.notifications'),
        hide_header=True,
    ))
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.route('/api/postchi/messages', methods=['GET'], endpoint='api_postchi_messages')
@require_partner_access(json_response=True, allow_pending=True)
def api_postchi_messages():
    from app.services.postchi import build_thread
    from app.services.notifications import _normalize_user_id

    me_phone = _normalize_user_id((session.get('user_phone') or '').strip())
    messages = build_thread(me_phone) if me_phone else []
    return jsonify({'success': True, 'messages': messages})


@express_partner_bp.route('/api/postchi/send', methods=['POST'], endpoint='api_postchi_send')
@require_partner_access(json_response=True, allow_pending=True)
def api_postchi_send():
    from app.services.postchi import send_user_message
    from app.services.notifications import _normalize_user_id

    me_phone = _normalize_user_id((session.get('user_phone') or '').strip())
    if not me_phone:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    payload = request.get_json(silent=True) or {}
    text = (payload.get('message') or payload.get('body') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'empty'}), 400
    msg = send_user_message(me_phone, text)
    if not msg:
        return jsonify({'success': False, 'error': 'failed'}), 400
    return jsonify({'success': True, 'message': msg})


@express_partner_bp.route('/api/postchi/open', methods=['POST'], endpoint='api_postchi_open')
@require_partner_access(json_response=True, allow_pending=True)
def api_postchi_open():
    from app.services.postchi import open_postchi
    from app.services.notifications import unread_count, _normalize_user_id

    me_phone = _normalize_user_id((session.get('user_phone') or '').strip())
    if not me_phone:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    open_postchi(me_phone)
    return jsonify({
        'success': True,
        'unread_count': unread_count(me_phone),
    })


# -------------------------
# Notifications API
# -------------------------
@express_partner_bp.route('/api/notifications', methods=['GET'])
@require_partner_access(json_response=True, allow_pending=True)
def get_notifications():
    """Get user notifications"""
    from app.services.notifications import get_user_notifications, unread_count, _normalize_user_id

    me_phone_raw = (session.get("user_phone") or "").strip()
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    notifications = get_user_notifications(me_phone, limit=50)
    unread = unread_count(me_phone)

    return jsonify({
        "success": True,
        "notifications": notifications,
        "unread_count": unread,
    })


@express_partner_bp.route('/api/notifications/unread-count', methods=['GET'])
@require_partner_access(json_response=True, allow_pending=True)
def get_unread_count():
    """Get unread notifications count"""
    from app.services.notifications import unread_count, _normalize_user_id
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    # استفاده از همان تابع normalize که در notifications.py استفاده می‌شود
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    resp = jsonify({
        "success": True,
        "unread_count": unread_count(me_phone)
    })
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@express_partner_bp.route('/api/notifications/<string:notif_id>/read', methods=['POST'])
@require_partner_access(json_response=True, allow_pending=True)
def mark_notification_read(notif_id: str):
    """Mark a notification as read"""
    from app.services.notifications import mark_read, unread_count, _normalize_user_id
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    # استفاده از همان تابع normalize که در notifications.py استفاده می‌شود
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    
    if not me_phone:
        return jsonify({
            "success": False,
            "error": "Invalid user phone",
            "unread_count": 0
        }), 400
    
    success = mark_read(me_phone, notif_id)
    unread = unread_count(me_phone)
    
    try:
        from flask import current_app
        current_app.logger.info(f"API: Mark notification read: user={me_phone}, notif_id={notif_id}, success={success}, unread={unread}")
    except Exception:
        pass
    
    return jsonify({
        "success": success,
        "unread_count": unread
    })


@express_partner_bp.route('/api/notifications/read-all', methods=['POST'])
@require_partner_access(json_response=True, allow_pending=True)
def mark_all_notifications_read():
    """Mark all notifications as read"""
    from app.services.notifications import mark_all_read, unread_count, _normalize_user_id
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    # استفاده از همان تابع normalize که در notifications.py استفاده می‌شود
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    count = mark_all_read(me_phone)
    # دریافت unread_count بعد از mark_all_read
    remaining_unread = unread_count(me_phone)
    return jsonify({
        "success": True,
        "marked_count": count,
        "unread_count": remaining_unread
    })


# -----------------------------------------------------------------------------
# Debug endpoint برای بررسی اعلان‌ها
# -----------------------------------------------------------------------------
@express_partner_bp.route('/api/notifications/debug', methods=['GET'])
@require_partner_access(json_response=True, allow_pending=True)
def notifications_debug():
    """Debug endpoint برای بررسی مشکل اعلان‌ها"""
    from app.services.notifications import _load_all, _normalize_user_id, get_user_notifications, merge_duplicate_keys
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    me_phone_normalized = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    
    # اجرای merge خودکار کلیدهای تکراری
    merge_result = merge_duplicate_keys()
    
    # بارگذاری همه داده‌ها (بعد از merge)
    all_data = _load_all()
    all_keys = list(all_data.keys())
    
    # بررسی اعلان‌های کاربر
    user_notifications = get_user_notifications(me_phone_normalized, limit=50)
    
    # بررسی تطابق کلیدها
    matching_keys = []
    for key in all_keys:
        if _normalize_user_id(key) == me_phone_normalized:
            matching_keys.append({
                "original_key": key,
                "normalized": _normalize_user_id(key),
                "notifications_count": len(all_data.get(key, []))
            })
    
    return jsonify({
        "success": True,
        "merge_result": merge_result,
        "debug_info": {
            "session_phone_raw": me_phone_raw,
            "session_phone_normalized": me_phone_normalized,
            "all_keys_in_storage": all_keys,
            "matching_keys": matching_keys,
            "user_notifications_count": len(user_notifications),
            "user_notifications": user_notifications[:5],  # فقط 5 تا اول
            "direct_key_exists": me_phone_normalized in all_data,
            "direct_key_notifications": len(all_data.get(me_phone_normalized, [])) if me_phone_normalized in all_data else 0
        }
    })


@express_partner_bp.route('/api/check-status', methods=['GET'], endpoint='check_status')
def check_status():
    """بررسی وضعیت تایید همکار - برای pull-to-refresh"""
    try:
        if not session.get("user_phone"):
            current_app.logger.warning("check_status: No user_phone in session")
            return jsonify({"success": False, "error": "unauthorized"}), 401
        
        me_phone = (session.get("user_phone") or "").strip()
        if not me_phone:
            current_app.logger.warning("check_status: Empty user_phone")
            return jsonify({"success": False, "error": "empty_phone"}), 400
        
        current_app.logger.info(f"check_status: Checking status for phone: {me_phone}")
        
        try:
            partners = load_express_partners() or []
            current_app.logger.debug(f"check_status: Loaded {len(partners)} partners")
        except Exception as load_err:
            current_app.logger.error(f"check_status: Error loading partners: {load_err}")
            return jsonify({"success": False, "error": "failed_to_load_partners"}), 500
        
        profile = _find_partner_record(partners, me_phone)
        
        if profile:
            current_app.logger.info(f"check_status: Profile found for {me_phone}, status: {profile.get('status')}")
            is_approved = _is_partner_approved(profile)
            current_app.logger.info(f"check_status: Is approved: {is_approved}")
            
            if is_approved:
                redirect_url = _default_post_login_url(me_phone)
                current_app.logger.info(f"check_status: Partner approved, redirecting to: {redirect_url}")
                return jsonify({
                    "success": True,
                    "approved": True,
                    "redirect_url": redirect_url
                })
        
        current_app.logger.info(f"check_status: Partner not approved yet for {me_phone}")
        return jsonify({
            "success": True,
            "approved": False
        })
        
    except Exception as e:
        current_app.logger.error(f"check_status: Unexpected error: {e}", exc_info=True)
        return jsonify({
            "success": False, 
            "error": "internal_error",
            "message": str(e)
        }), 500


@express_partner_bp.get('/lands/<string:code>', endpoint='land_detail')
@require_partner_access(allow_pending=True, allow_guest=True)
def land_detail(code: str):
    """Express land detail page within partner panel."""
    from ..utils.flash_messages import purge_stale_auth_flashes, purge_stale_land_flashes
    purge_stale_land_flashes()
    purge_stale_auth_flashes()
    lands = load_ads_cached() or []
    land = next((l for l in lands if l.get('code') == code and l.get('is_express')), None)

    if not land:
        flash('این آگهی اکسپرس پیدا نشد یا دیگر در دسترس نیست.', 'warning')
        return redirect(url_for('express_partner.dashboard'))

    # ثبت بازدید فایل اکسپرس از سمت همکار (هر IP در هر روز فقط یک بازدید)
    try:
        views = load_express_partner_views() or []
        if not isinstance(views, list):
            views = []
        
        visitor_ip = request.remote_addr or ''
        now = datetime.utcnow()
        today_str = now.strftime('%Y-%m-%d')
        
        # بررسی اینکه آیا این IP در امروز برای این فایل قبلاً بازدید داشته یا نه
        already_viewed_today = False
        for v in views:
            try:
                v_ip = v.get('ip', '')
                v_code = v.get('code', '')
                v_ts_str = v.get('timestamp', '')
                if v_ip == visitor_ip and v_code == code and v_ts_str:
                    v_dt = datetime.fromisoformat(v_ts_str.replace('Z', '+00:00'))
                    if v_dt.tzinfo:
                        v_dt = v_dt.replace(tzinfo=None)
                    v_date_str = v_dt.strftime('%Y-%m-%d')
                    if v_date_str == today_str:
                        already_viewed_today = True
                        break
            except Exception:
                continue
        
        # اگر این IP امروز برای این فایل بازدید نداشته، ثبت کن
        if not already_viewed_today and visitor_ip and code:
            views.append({
                'timestamp': now.isoformat(),
                'code': code,
                'ip': visitor_ip,
                'user_agent': request.headers.get('User-Agent', '')[:200]
            })
            # نگه داشتن فقط 50000 بازدید اخیر
            if len(views) > 50000:
                views = views[-50000:]
            save_express_partner_views(views)
    except Exception as e:
        current_app.logger.error(f"Error tracking express partner listing view: {e}", exc_info=True)

    partners = load_express_partners() or []
    me_phone = (session.get("user_phone") or "").strip()
    partner_profile = next((p for p in partners if str(p.get("phone")) == me_phone), None)
    if me_phone and _is_partner_approved(partner_profile) and not _is_prefetch_request():
        _routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)

    # محاسبه پورسانت از assignments
    assignments = load_express_assignments() or []
    assignment = next((a for a in assignments if a.get('land_code') == code and a.get('partner_phone') == me_phone), None)
    global_assignment_status = 'active'
    status_priority = {
        'sold': 5,
        'in_transaction': 4,
        'closed': 3,
        'pending': 2,
        'approved': 1,
        'active': 0,
        '': 0,
    }
    for a in assignments:
        if str(a.get('land_code')) != str(code):
            continue
        status = _assignment_display_status(a)
        if status_priority.get(status, 0) > status_priority.get(global_assignment_status, 0):
            global_assignment_status = status
    if _express_land_marked_sold(land):
        global_assignment_status = 'sold'
    try:
        is_approved = _is_partner_approved(partner_profile)
    except Exception:
        is_approved = False
    
    if assignment:
        land['_assignment_id'] = assignment.get('id')
    land['_assignment_status'] = global_assignment_status
    if is_approved:
        from .new_land_sms import attach_express_land_commission
        attach_express_land_commission(land)

    visit_requests_list = load_express_visit_requests() or []
    if not isinstance(visit_requests_list, list):
        visit_requests_list = []
    commissions_for_tx = load_express_commissions() or []
    if not isinstance(commissions_for_tx, list):
        commissions_for_tx = []
    tx_state = resolve_partner_land_tx_state(
        me_phone=me_phone,
        land_code=str(code),
        assignments=assignments,
        visit_requests=visit_requests_list,
        is_partner_approved=is_approved,
        global_assignment_status=global_assignment_status,
        commissions=commissions_for_tx,
        visit_commission_required=_visit_commission_required_for(commissions_for_tx, me_phone, code),
    )
    land['_visit_date'] = tx_state.get('visit_date') or ''
    land['_visit_date_jalali'] = tx_state.get('visit_date_jalali') or ''
    land['_visit_status'] = tx_state.get('visit_status') or ''
    land['_tx_button_mode'] = tx_state.get('tx_mode') or 'visit'
    land['_visit_progress_steps'] = []
    land['_visit_progress_summary'] = {}
    if is_approved and me_phone:
        progress_row = next(
            (
                r for r in visit_requests_list
                if isinstance(r, dict)
                and str(r.get('partner_phone') or '').strip() == me_phone
                and str(r.get('land_code') or '').strip() == str(code)
                and str(r.get('status') or '').strip() != CANCELLED_STATUS
            ),
            None,
        )
        if progress_row is None:
            progress_row = {
                'partner_phone': me_phone,
                'land_code': str(code),
                'status': PENDING_STATUS,
                'visit_requested': False,
            }
        progress_row = dict(progress_row)
        progress_row['visit_commission_required'] = _visit_commission_required_for(
            commissions_for_tx,
            me_phone,
            str(code),
        )
        progress_steps = visit_progress_steps(
            progress_row,
            commissions_for_tx,
            partner_phone=me_phone,
        )
        land['_visit_progress_steps'] = progress_steps
        land['_visit_progress_summary'] = visit_progress_summary(progress_steps)

    share_token = ''
    share_url = ''

    # تصاویر — URL خام بدون واریانت
    from ..utils.images import sanitize_land_media
    land = sanitize_land_media(dict(land) if isinstance(land, dict) else land)

    is_logged_in = bool(me_phone)

    try:
        canonical_url = url_for('express_partner.land_detail', code=code, _external=True)
    except Exception:
        canonical_url = f"https://vinor.ir/express/partner/lands/{code}"

    from ..utils.seo import build_land_seo, similar_lands
    express_lands = load_express_lands_cached() or []
    seo = build_land_seo(land, canonical_url=canonical_url)
    related_raw = similar_lands(land, express_lands, limit=15)
    related_lands: List[Dict[str, Any]] = []
    if related_raw:
        rel_code_status: Dict[str, str] = {}
        for a in assignments:
            ck = str(a.get('land_code') or '')
            if not ck:
                continue
            st = _assignment_display_status(a)
            cur = rel_code_status.get(ck, 'active')
            if status_priority.get(st, 0) > status_priority.get(cur, 0):
                rel_code_status[ck] = st
        my_assign_by_code: Dict[str, Dict[str, Any]] = {}
        if me_phone:
            for a in assignments:
                if str(a.get('partner_phone')) == me_phone:
                    ck = str(a.get('land_code') or '')
                    if ck:
                        my_assign_by_code[ck] = a
        for item in related_raw:
            if not isinstance(item, dict):
                continue
            ck = str(item.get('code') or '')
            gs = rel_code_status.get(ck, 'active')
            if gs == 'sold' or str(item.get('express_status') or '').strip().lower() == 'sold':
                continue
            ritem = dict(item)
            ritem['_assignment_status'] = gs
            ritem['_in_transaction'] = gs == 'in_transaction'
            ritem['_detail_url'] = url_for('express_partner.land_detail', code=ck)
            ass = my_assign_by_code.get(ck)
            if ass and is_approved and gs not in ('sold', 'closed'):
                ritem['_assignment_id'] = ass.get('id')
                from .new_land_sms import attach_express_land_commission
                attach_express_land_commission(ritem)
            elif is_approved and gs not in ('sold', 'closed'):
                from .new_land_sms import attach_express_land_commission
                attach_express_land_commission(ritem)
            related_lands.append(sanitize_land_media(ritem))
            if len(related_lands) >= 6:
                break

    sold_count = 0
    if me_phone:
        my_comms = _commissions_for_phone(me_phone)
        sold_count = sum(
            1 for c in my_comms
            if (c.get('status') or '').strip() in ('approved', 'paid')
        )

    from flask import get_flashed_messages
    from .land_detail_config import build_land_detail_config

    try:
        from flask_wtf.csrf import generate_csrf
        csrf_val = generate_csrf()
    except Exception:
        csrf_val = ""

    images_list = land.get("images") or []
    video_val = land.get("video")
    has_video_flag = bool(video_val and str(video_val).strip())
    total_items_count = (1 if has_video_flag else 0) + len(images_list)
    land_flash_messages = [
        {"text": str(msg), "category": str(cat)}
        for cat, msg in get_flashed_messages(with_categories=True, category_filter=["land"])
    ]

    land_detail_config = build_land_detail_config(
        land,
        images=images_list,
        has_video=has_video_flag,
        total_items=total_items_count,
        share_url=share_url or "",
        is_approved=is_approved,
        visit_date_min=visit_date_min_iso(),
        visit_allowed_weekdays_js=visit_allowed_weekdays_for_js(),
        flash_messages=land_flash_messages,
        tx_status_url=url_for("express_partner.land_tx_status", code=code),
        csrf_token=csrf_val,
    )

    return render_template(
        'express_partner/land_detail.html',
        land=land,
        seo=seo,
        related_lands=related_lands,
        sold_count=sold_count,
        share_url=share_url,
        share_token=share_token,
        partner_profile=partner_profile,
        is_approved=is_approved,
        is_logged_in=is_logged_in,
        is_partner_context=True,
        ref_partner=None,
        brand="وینور",
        domain="vinor.ir",
        visit_date_min=visit_date_min_iso(),
        land_detail_config=land_detail_config,
    )


