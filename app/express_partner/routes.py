from __future__ import annotations

import os
import json
import threading
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from flask import (
    render_template, request, redirect, url_for, session,
    send_from_directory, current_app, abort, flash, g,
    has_request_context,
)
from functools import wraps
import re, time

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
    load_ads_cached, load_active_cities, load_express_lands_cached, save_ads,
    load_sms_history, save_sms_history,
    load_settings,
    load_express_partner_views, save_express_partner_views,
    load_partner_routines, load_partner_routines_cached, save_partner_routines,
    load_partner_bank_accounts, save_partner_bank_accounts,
    load_partner_withdrawals, save_partner_withdrawals,
    load_express_visit_requests, save_express_visit_requests,
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
    active_withdrawals_for_phone,
    reserved_withdrawal_total,
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
    partner_active_visit_record,
    partner_can_request_new_visit,
    partner_visit_completed,
    partner_visit_customer_phone,
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
from .commissions_flow import (
    APPROVED_STATUS,
    PAID_STATUS,
    commission_blocks_new_deal_record,
    commission_is_deal,
    commission_is_visit,
    has_finalized_deal_commission,
    sync_sold_if_deal_already_approved,
)
from .admin_action_sms import notify_admin_pending_action
from ..utils.dates import format_iso_date_jalali, parse_datetime_safe
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


def _mark_express_land_sold(code: str) -> bool:
    """express_status فایل را sold می‌کند تا لیست/SEO با انتساب هم‌خوان باشد."""
    ck = str(code or '').strip()
    if not ck:
        return False
    lands = load_ads_cached() or []
    if not isinstance(lands, list):
        return False
    changed = False
    for land in lands:
        if not isinstance(land, dict):
            continue
        if str(land.get('code') or '').strip() != ck:
            continue
        if str(land.get('express_status') or '').strip().lower() != 'sold':
            land['express_status'] = 'sold'
            changed = True
        break
    if changed:
        save_ads(lands)
    return changed


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
    from .partner_session_sync import canonical_partner_phone

    phone = (phone or '').strip()
    if not phone:
        return None
    norm = canonical_partner_phone(phone)
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
            p_norm = canonical_partner_phone(p_phone)
            by_phone[p_phone] = p
            if p_norm:
                by_phone.setdefault(p_norm, p)
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
    from .partner_session_sync import canonical_partner_phone

    me_phone = canonical_partner_phone(str(session.get('user_phone') or ''))
    if not me_phone:
        g.express_partner_profile = None
        return
    from .plus_subscription import persist_plus_expiry_backfill_for_phone

    if persist_plus_expiry_backfill_for_phone(me_phone):
        for key in ('_express_partners_list_cached', '_express_partner_by_phone'):
            if hasattr(g, key):
                try:
                    delattr(g, key)
                except Exception:
                    pass
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
                try:
                    c['_txn_meta'] = f'از {int(float(prev)):,} به {int(float(tgt)):,} تومان'
                except (TypeError, ValueError):
                    c['_txn_meta'] = 'توسط ادمین'
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


OTP_TTL_SECONDS = 120  # fallback if config unavailable


def _otp_ttl() -> int:
    try:
        from app.auth.otp.config import otp_ttl_seconds

        return otp_ttl_seconds()
    except Exception:
        return OTP_TTL_SECONDS


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
        return (time.time() - float(ts)) > _otp_ttl()
    except (TypeError, ValueError):
        return True


OTP_SESSION_PENDING = "pending"


def _verify_otp_for_phone(code: str, phone: str) -> str | None:
    """تأیید با OTPService. سشن فقط شمارهٔ درحال‌ورود را محدود می‌کند، منبع حقیقت نیست."""
    if not code or not phone:
        return None
    norm_phone = _otp_canonical_phone(phone)
    if not norm_phone:
        return None
    if _otp_session_expired():
        _clear_otp_session()
    sess_phone = _otp_session_phone()
    if sess_phone and sess_phone != norm_phone:
        return None
    from app.auth.otp.service import PURPOSE_PARTNER, partner_login_digits, verify_otp

    result = verify_otp(
        phone=norm_phone,
        purpose=PURPOSE_PARTNER,
        code=code,
        digits=partner_login_digits(),
    )
    if not result.ok:
        return None
    return _canonical_partner_phone(result.phone)


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


def _store_otp_session(phone: str, code: str | None = None) -> None:
    """سشن فقط وضعیت pending را نگه می‌دارد — کد plaintext ذخیره نمی‌شود."""
    _clear_otp_session()
    canonical = _otp_canonical_phone(phone)
    session.permanent = True
    session.update({
        'otp_code': OTP_SESSION_PENDING,
        'otp_phone': canonical,
        'otp_created_at': time.time(),
    })
    try:
        session.modified = True
    except Exception:
        pass


def _partner_otp_fail_payload(issued_err: str) -> tuple[str, int]:
    from app.auth.otp.errors import (
        OTP_COOLDOWN,
        OTP_INVALID_PHONE,
        OTP_RATE_LIMITED,
    )

    if issued_err == OTP_INVALID_PHONE:
        return "شماره موبایل معتبر نیست.", 400
    if issued_err in (OTP_RATE_LIMITED, OTP_COOLDOWN):
        return "لطفاً کمی صبر کنید و دوباره تلاش کنید.", 429
    return "ارسال کد ممکن نشد. کمی بعد دوباره تلاش کنید.", 502


def _issue_partner_login_otp(phone: str) -> tuple[bool, str]:
    """Generate + hash-store + SMS dispatch. Returns (ok, error_code)."""
    from app.auth.otp.errors import OTP_RATE_LIMITED
    from app.auth.otp.request_meta import client_ip, client_user_agent
    from app.auth.otp.service import PURPOSE_PARTNER, partner_login_digits, request_otp

    issued = request_otp(
        phone=phone,
        purpose=PURPOSE_PARTNER,
        digits=partner_login_digits(),
        ip=client_ip(),
        user_agent=client_user_agent(),
    )
    # حتی اگر sms.ir timeout بدهد، ممکن است پیامک رفته باشد — سشن را نگه دار.
    if issued.accepted or issued.challenge_id:
        _store_otp_session(phone)
    if not issued.accepted:
        return False, issued.error or OTP_RATE_LIMITED
    return True, ""


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


_APPLY_LOGIN_NEXT_ALIASES = frozenset({'apply', 'coop', 'cooperation'})


def _resolve_login_next_url(raw: str) -> str | None:
    """alias مثل apply → مسیر واقعی فرم همکاری؛ فقط مسیر داخلی همکار."""
    nxt = (raw or '').strip()
    if not nxt:
        return None
    if nxt.lower() in _APPLY_LOGIN_NEXT_ALIASES:
        return url_for('express_partner.apply')
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return None


def _login_next_preserve():
    return _resolve_login_next_url(
        request.args.get('next') or request.form.get('next') or ''
    )


def _session_next_safe():
    raw = session.get('next')
    if isinstance(raw, str):
        return _resolve_login_next_url(raw)
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
    if path in (
        _post_login_path_only(url_for('express_partner.home')),
        _post_login_path_only(url_for('express_partner.home')),
        _post_login_path_only(url_for('express_partner.home')),
    ):
        return True
    if path.startswith('/express/partner/login'):
        return True
    return False


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
    """پیش‌فرض بعد از ورود: داشبورد."""
    is_partner = _is_phone_approved_partner(phone)
    _cache_session_partner_role(is_partner)
    return url_for('express_partner.home')


def _redirect_after_login(phone: str | None = None) -> str:
    """deep link صریح اولویت دارد؛ مسیرهای عمومی → داشبورد."""
    nxt = _login_next_preserve() or _session_next_safe()
    ph = _canonical_partner_phone(phone or session.get('user_phone') or '')
    is_partner = _is_phone_approved_partner(ph)
    _cache_session_partner_role(is_partner)
    apply_path = _post_login_path_only(url_for('express_partner.apply'))
    if nxt and _post_login_path_only(nxt) == apply_path:
        try:
            session.pop('next', None)
        except Exception:
            pass
        if is_partner:
            return _default_post_login_url(ph)
        try:
            if _has_active_application(ph):
                return url_for('express_partner.thanks')
        except Exception:
            pass
        return nxt
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
    # قبل از پاک شدن session: ادغام حافظه/اهداف مهمان → شماره
    try:
        from app.memory.merge import merge_guest_goals, merge_guest_session_memory

        merge_guest_session_memory(canonical)
        gid = str(session.get("ai_guest_id") or "").strip()
        if gid:
            merge_guest_goals(f"guest_{gid}", canonical)
    except Exception:
        pass
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
        session.pop('VINOR_PLUS_ACTIVE', None)
        session.pop('_plus_lifecycle_sms_ts', None)
        session.modified = True
    except Exception:
        pass
    # Phase 5 Roles: cache portal roles after login (does not change OTP keys).
    try:
        from app.roles.service import refresh_session_portal_roles
        refresh_session_portal_roles(session)
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


_ASSIGNMENT_STATUS_PRIORITY = {
    'sold': 5,
    'in_transaction': 4,
    'closed': 3,
    'pending': 2,
    'approved': 1,
    'active': 0,
    '': 0,
}


def _express_assignment_indexes(
    assignments: List[Dict[str, Any]],
    me_phone: str,
) -> tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """یک پاس روی assignments: وضعیت هر فایل + تخصیص‌های من بر اساس کد."""
    me = (me_phone or '').strip()
    by_land_status: Dict[str, str] = {}
    my_by_code: Dict[str, Dict[str, Any]] = {}
    priority = _ASSIGNMENT_STATUS_PRIORITY
    for a in assignments:
        if not isinstance(a, dict):
            continue
        lc = str(a.get('land_code') or '').strip()
        if not lc:
            continue
        st = _assignment_display_status(a)
        cur = by_land_status.get(lc, 'active')
        if priority.get(st, 0) > priority.get(cur, 0):
            by_land_status[lc] = st
        if me and str(a.get('partner_phone') or '').strip() == me:
            my_by_code[lc] = a
    return by_land_status, my_by_code


def _auto_release_expired_transactions(assignments: List[Dict[str, Any]]) -> None:
    """رفع خودکار معاملات بعد از ۵ روز بدون تأیید پشتیبان"""
    from datetime import datetime, timedelta

    from .commissions_flow import remove_pending_deal_commissions_for

    now = datetime.now()
    updated = False
    released: List[tuple[str, str]] = []

    for a in assignments:
        if _assignment_display_status(a) != 'in_transaction':
            continue

        started_at_str = a.get('transaction_started_at')
        if not started_at_str:
            continue

        try:
            started_at = datetime.strptime(started_at_str, '%Y-%m-%d %H:%M:%S')
            if now - started_at > timedelta(days=5):
                code = str(a.get('land_code') or '').strip()
                holder = str(a.get('transaction_holder') or '').strip()
                a['status'] = 'active'
                a['updated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                a['auto_released'] = True
                a['auto_released_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                a.pop('transaction_holder', None)
                a.pop('transaction_started_at', None)
                updated = True
                if code and holder:
                    released.append((code, holder))
        except Exception:
            continue

    if updated:
        save_express_assignments(assignments)
        if released:
            try:
                commissions = load_express_commissions() or []
                if not isinstance(commissions, list):
                    commissions = []
                total_removed = 0
                for code, holder in released:
                    commissions, removed = remove_pending_deal_commissions_for(
                        commissions, partner_phone=holder, land_code=code
                    )
                    total_removed += removed
                if total_removed > 0:
                    save_express_commissions(commissions)
                    current_app.logger.info(
                        'auto-release removed %s pending deal commission(s) for %s land(s)',
                        total_removed,
                        len(released),
                    )
            except Exception:
                current_app.logger.exception(
                    'auto-release pending deal commission cleanup failed'
                )
            # پیام در چت — همکار بداند می‌تواند دوباره معامله ثبت کند
            try:
                from .sales_coach import deliver_partner_progress_update
                from app.utils.storage import load_ads_cached

                lands = load_ads_cached() or []
                title_by_code = {
                    str(l.get('code') or '').strip(): str(l.get('title') or '').strip()
                    for l in lands
                    if isinstance(l, dict)
                }
                for code, holder in released:
                    deliver_partner_progress_update(
                        partner_phone=holder,
                        event='deal_auto_released',
                        land_code=code,
                        land_title=title_by_code.get(code, ''),
                    )
            except Exception:
                current_app.logger.exception('auto-release chat progress failed')


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
    from .partner_roles import partner_is_approved
    return partner_is_approved(profile)


def _is_partner_special(profile: Dict[str, Any] | None) -> bool:
    from .partner_roles import partner_is_special
    return partner_is_special(profile)


def _partner_tier_label(profile: Dict[str, Any] | None, *, is_approved: bool | None = None) -> str:
    from .partner_roles import (
        COOP_LEVEL_MARKETER,
        COOP_LEVEL_PLUS,
        COOP_LEVEL_REGULAR,
        COOP_LEVEL_VISITOR,
        partner_coop_level,
    )

    del is_approved
    level = partner_coop_level(profile)
    if level == COOP_LEVEL_PLUS:
        return "پلاس"
    if level == COOP_LEVEL_VISITOR:
        return "ویزیتور"
    if level == COOP_LEVEL_MARKETER:
        return "بازاریاب"
    if level == COOP_LEVEL_REGULAR:
        return "کاربر عادی"
    return "کاربر عادی"


def require_special_partner(json_response: bool = False):
    """فقط همکار ویژه — باید اول همکار تأییدشده باشد."""
    def decorator(fn):
        @wraps(fn)
        @require_partner_access(json_response=json_response)
        def wrapper(*args, **kwargs):
            profile = getattr(g, 'express_partner_profile', None)
            if not _is_partner_special(profile):
                if json_response:
                    return jsonify({"success": False, "error": "not_special"}), 403
                flash("این بخش فقط برای همکاران ویژه فعال است.", "warning")
                return redirect(url_for("express_partner.home", menu=1))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


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

        plus_ping_ts = session.get('_plus_lifecycle_sms_ts') or 0
        if now_ts - float(plus_ping_ts) >= 21600:
            session['_plus_lifecycle_sms_ts'] = now_ts
            try:
                from .partner_roles import PARTNER_TIER_SPECIAL, partner_tier
                from .plus_sms import defer_plus_lifecycle_sms_check

                prof = _partner_profile_for_phone(phone)
                if isinstance(prof, dict) and partner_tier(prof) == PARTNER_TIER_SPECIAL:
                    defer_plus_lifecycle_sms_check(
                        current_app._get_current_object(),
                        phone,
                        prof,
                    )
            except Exception:
                pass
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
            from ..utils.apk_version import resolve_android_apk_version_code, should_show_apk_update
            from ..utils.short_urls import public_apk_download_url
            if _raw_apk_url:
                android_apk_url = public_apk_download_url(_apk_settings, external=False)
            show_app_update_nav = should_show_apk_update(
                android_apk_version,
                apk_url=_raw_apk_url,
                req=request,
                server_version_code=resolve_android_apk_version_code(_apk_settings),
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

    plus_system_on = False
    try:
        from .zarinpal_config import plus_system_enabled as _plus_system_enabled

        plus_system_on = bool(_plus_system_enabled())
    except Exception:
        plus_system_on = False

    lawyer_system_on = False
    try:
        from app.lawyer.config import lawyer_system_enabled as _lawyer_system_enabled

        lawyer_system_on = bool(_lawyer_system_enabled())
    except Exception:
        lawyer_system_on = False

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
        "plus_system_enabled": plus_system_on,
        "lawyer_system_enabled": lawyer_system_on,
    }


# -------------------------
# PWA Routes (Separate from main VINOR PWA)
# -------------------------
@express_partner_bp.route('/', methods=['GET'], endpoint='partner_root')
def partner_root():
    """Legacy /express/partner → داشبورد."""
    if session.get('user_phone'):
        return redirect(_redirect_after_login(), code=302)
    return redirect(url_for('express_partner.home'), code=302)


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
      "name": "وینور اکسپرس - پنل بازاریاب فروش",
      "short_name": "وینور اکسپرس",
      "description": "پنل مدیریت همکاران وینور - دسترسی به آگهی‌های تخصیص یافته، کمیسیون‌ها و ابزارهای مدیریت",
      "dir": "rtl",
      "lang": "fa",
      "start_url": "/express/partner/home?source=pwa",
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


def _default_apply_city(raw: str = '') -> str:
    """شهر فعالیت — در فرم ساده‌شده پیش‌فرض گرمابسرد."""
    city = (raw or '').strip()[:APPLY_CITY_MAX_LEN]
    if city:
        return city
    try:
        from ..utils.iran_cities import FOCUS_SERVICE_CITY
        return str(FOCUS_SERVICE_CITY or '').strip()[:APPLY_CITY_MAX_LEN] or 'گرمابسرد'
    except Exception:
        return 'گرمابسرد'


def _compose_apply_name(data: dict) -> tuple[str, str, str]:
    """نام + نام‌خانوادگی → (first, last, full). سازگار با فیلد قدیمی name."""
    first = (data.get('first_name') or '').strip()[:APPLY_NAME_MAX_LEN]
    last = (data.get('last_name') or '').strip()[:APPLY_NAME_MAX_LEN]
    full = (data.get('name') or '').strip()
    if first or last:
        full = f'{first} {last}'.strip()
    elif full:
        parts = full.split(None, 1)
        first = (parts[0] if parts else '')[:APPLY_NAME_MAX_LEN]
        last = (parts[1] if len(parts) > 1 else '')[:APPLY_NAME_MAX_LEN]
    full = full[: (APPLY_NAME_MAX_LEN * 2 + 1)]
    return first, last, full


def _apply_back_url() -> str:
    """صفحهٔ قبل در مسیر همکار؛ در غیر این صورت خانه."""
    home = url_for('express_partner.home')
    ref = (request.referrer or '').strip()
    if not ref:
        return home
    try:
        from urllib.parse import urlparse

        parsed = urlparse(ref)
        if parsed.netloc and parsed.netloc != request.host:
            return home
        path = (parsed.path or '').strip() or '/'
        if not path.startswith('/express/partner/'):
            return home
        low = path.lower()
        if any(x in low for x in ('/apply', '/login', '/otp')):
            return home
        qs = ('?' + parsed.query) if parsed.query else ''
        return path + qs
    except Exception:
        return home


def _apply_form_context(
    me_phone: str,
    *,
    first_name: str = '',
    last_name: str = '',
    name: str = '',
    national_id: str = '',
) -> dict:
    profile = _partner_profile_for_phone(me_phone) or {}
    if not first_name and not last_name and name:
        first_name, last_name, name = _compose_apply_name({'name': name})
    elif first_name or last_name:
        _, _, name = _compose_apply_name({'first_name': first_name, 'last_name': last_name})
    display_name = (name or profile.get('name') or me_phone or '').strip()
    return {
        'me_phone': me_phone,
        'first_name': first_name,
        'last_name': last_name,
        'name': name,
        'national_id': national_id,
        'avatar_initials_name': display_name,
        'back_url': _apply_back_url(),
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
    resp = make_response(redirect(url_for('express_partner.home', menu=1, login_next=next_apply)))
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
    """درخواست همکاری — نام، نام‌خانوادگی، کد ملی؛ پس از ارسال تأیید خودکار."""
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

    if request.method == 'POST':
        if _has_active_application(me_phone):
            return redirect(_post_apply_landing_url(me_phone))
        first_name, last_name, name = _compose_apply_name({
            'first_name': request.form.get('first_name') or '',
            'last_name': request.form.get('last_name') or '',
            'name': request.form.get('name') or '',
        })
        national_id = _parse_apply_national_id(request.form.get('national_id') or '')
        if not first_name or not last_name or not national_id:
            flash('نام، نام خانوادگی و کد ملی الزامی است.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, first_name=first_name, last_name=last_name, national_id=national_id,
            ))
        from ..utils.iran_ids import is_valid_iran_national_id
        if not is_valid_iran_national_id(national_id):
            flash('کد ملی واردشده معتبر نیست.', 'error')
            return _apply_render_with_ref(**_apply_form_context(
                me_phone, first_name=first_name, last_name=last_name, national_id=national_id,
            ))
        return _submit_partner_application(me_phone, {
            'first_name': first_name,
            'last_name': last_name,
            'name': name,
            'national_id': national_id,
        })

    return _apply_render_with_ref(**_apply_form_context(
        me_phone,
        first_name=defaults.get('first_name', ''),
        last_name=defaults.get('last_name', ''),
        national_id=defaults.get('national_id', ''),
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
        return redirect(url_for('express_partner.home'))
    if _has_active_application(me_phone):
        return redirect(_post_apply_landing_url(me_phone))
    return None


def _apply_form_defaults(me_phone: str) -> dict:
    data = session.get('apply_data') or {}
    profile = _partner_profile_for_phone(me_phone) or {}
    last_app = _get_my_last_application(me_phone)
    use_last = last_app and not _has_active_application(me_phone)
    src = last_app if use_last else {}
    first_name, last_name, name = _compose_apply_name({
        'first_name': data.get('first_name') or src.get('first_name') or '',
        'last_name': data.get('last_name') or src.get('last_name') or '',
        'name': data.get('name') or profile.get('name') or (src.get('name') if use_last else '') or '',
    })
    national_id = _parse_apply_national_id(
        data.get('national_id')
        or profile.get('national_id')
        or (src.get('national_id') if use_last else '')
        or ''
    )
    return {
        'first_name': first_name,
        'last_name': last_name,
        'name': name,
        'national_id': national_id,
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

    from app.services.system_sms_templates import get_template_body

    settings = load_settings(current_app) or {}
    sms_message = get_template_body('partner_application').strip()
    if not sms_message:
        sms_message = 'وینور\nدرخواست همکاری‌ت ثبت شد؛ منتظر بررسی.'
    sms_line_number = (settings.get('sms_line_number') or get_sms_line_number() or '09981801922').strip()

    sms_result = send_sms_direct(mobile=mobile, message=sms_message, line_number=sms_line_number, record_history=False)
    ok = bool(sms_result.get('ok'))
    err = None
    if not ok:
        body = sms_result.get('body') or {}
        err = str(body.get('message') or body.get('error') or 'sms_send_failed')
        if sms_is_infrastructure_error(err):
            time.sleep(0.6)
            sms_result = send_sms_direct(mobile=mobile, message=sms_message, line_number=sms_line_number, record_history=False)
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


def _send_visit_schedule_admin_sms(
    *,
    partner_phone: str,
    partner_name: str,
    notes: str = '',
    presence_address: str = '',
) -> dict:
    """پیامک پشتیبان برای درخواست تعیین وقت بازدید از مدال خانه."""
    from .admin_action_sms import notify_admin_pending_action
    from ..utils.dates import format_display_jalali_datetime

    return notify_admin_pending_action(
        'visit_schedule',
        partner_phone=partner_phone,
        partner_name=partner_name,
        notes=(notes or '').strip(),
        presence_address=(presence_address or '').strip(),
        system_date=format_display_jalali_datetime(None),
    )


def _visit_schedule_support_phone() -> str:
    """شماره پشتیبان برای هماهنگی وقت بازدید."""
    from ..services.sms import normalize_iran_mobile, is_valid_iran_mobile
    from ..utils.storage import load_settings

    settings = load_settings(current_app) or {}
    raw = str(settings.get('partner_application_admin_phone') or '').strip()
    phone = normalize_iran_mobile(raw)
    if is_valid_iran_mobile(phone):
        return phone
    try:
        from app.crm.config import VISIT_CALL_TARGET
        fallback = normalize_iran_mobile(str(VISIT_CALL_TARGET or '').strip())
        if is_valid_iran_mobile(fallback):
            return fallback
    except Exception:
        pass
    return '09121471301'


def _visit_schedule_party_lines(label: str, name: str, phone: str) -> list:
    """مشخصات طرف مقابل — نام و شماره؛ اگر خالی باشد خطی اضافه نمی‌شود."""
    label_s = (label or '').strip()
    name_s = (name or '').strip()
    phone_s = (phone or '').strip()
    if not label_s or (not name_s and not phone_s):
        return []
    shown = name_s or phone_s
    lines = [f'{label_s}: {shown}']
    if phone_s and phone_s != shown:
        lines.append(phone_s)
    return lines


def _build_visit_schedule_sms(
    *,
    weekday: str = '',
    jalali_date: str = '',
    visit_time: str = '',
    presence_address: str = '',
    support_phone: str = '',
    counterpart_label: str = '',
    counterpart_name: str = '',
    counterpart_phone: str = '',
) -> str:
    """قالب تعیین وقت — از رجیstry پیامک سیستمی."""
    from app.services.system_sms_templates import visit_schedule_body

    msg = visit_schedule_body(
        weekday=weekday,
        jalali_date=jalali_date,
        visit_time=visit_time,
        presence_address=presence_address,
        support_phone=support_phone,
        counterpart_label=counterpart_label,
        counterpart_name=counterpart_name,
        counterpart_phone=counterpart_phone,
    )
    if msg:
        return msg
    # fallback
    day = (weekday or '').strip()
    date_s = (jalali_date or '').strip()
    time_s = (visit_time or '').strip()
    when_parts = [p for p in (day, date_s) if p]
    when_line = ' '.join(when_parts) if when_parts else '—'
    lines = [
        'وینور',
        'وقت بازدید تعیین شد',
        when_line,
    ]
    if time_s:
        lines.append(f'ساعت {time_s}')
    addr = (presence_address or '').strip()
    if addr:
        lines.append(f'آدرس حضور: {addr}')
    lines.extend(_visit_schedule_party_lines(
        counterpart_label, counterpart_name, counterpart_phone,
    ))
    support = (support_phone or '').strip()
    if support:
        lines.append(f'هماهنگی با پشتیبانی: {support}')
    return '\n'.join(lines)


def _send_visit_schedule_sms_to(
    *,
    to_phone: str,
    message: str,
    history_type: str,
    partner_phone: str = '',
) -> dict:
    from datetime import datetime

    from ..services.sms import send_sms_direct, normalize_iran_mobile, is_valid_iran_mobile
    from ..utils.storage import load_settings, load_sms_history, save_sms_history
    from app.services.sms_config import get_sms_line_number

    mobile = normalize_iran_mobile(to_phone)
    if not is_valid_iran_mobile(mobile):
        return {'ok': False, 'skipped': True, 'error': 'invalid_phone'}

    settings = load_settings(current_app) or {}
    line = (settings.get('sms_line_number') or get_sms_line_number() or '09981801922').strip()
    sms_result = send_sms_direct(mobile=mobile, message=message, line_number=line, record_history=False)
    ok = bool(sms_result.get('ok'))
    err = None
    body = sms_result.get('body') or {}
    if not ok:
        err = str(body.get('message') or body.get('error') or 'sms_send_failed')
        try:
            current_app.logger.error(
                'Visit schedule SMS failed type=%s mobile=%s status=%s body=%s',
                history_type,
                mobile,
                sms_result.get('status'),
                body,
            )
        except Exception:
            pass

    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        history.append({
            'type': history_type,
            'mobile': mobile,
            'partner_phone': partner_phone or to_phone,
            'message': message,
            'ok': ok,
            'error': err,
            'status_code': sms_result.get('status', 0),
            'response': body,
            'created_at': datetime.utcnow().isoformat() + 'Z',
        })
        if len(history) > 5000:
            history = history[-5000:]
        save_sms_history(history, current_app)
    except Exception:
        try:
            current_app.logger.exception('Visit schedule SMS history failed type=%s', history_type)
        except Exception:
            pass

    return {'ok': ok, 'skipped': False, 'error': err}


def _send_visit_schedule_partner_sms(
    *,
    partner_phone: str,
    partner_name: str = '',
    weekday: str = '',
    jalali_date: str = '',
    visit_time: str = '',
    support_phone: str = '',
    presence_address: str = '',
    plus_user_phone: str = '',
    plus_user_name: str = '',
    land_code: str = '',
) -> dict:
    """پیامک تعیین وقت یکسان برای بازاریاب و کاربر پلاس؛ فقط مشخصات طرفین فرق دارد."""
    from ..services.sms import normalize_iran_mobile

    support = normalize_iran_mobile(support_phone) or _visit_schedule_support_phone()
    addr = (presence_address or '').strip()
    if not addr:
        try:
            from .visit_requests import resolve_visit_presence_address
            addr = resolve_visit_presence_address(
                plus_user_phone=plus_user_phone,
                land_code=land_code,
            )
        except Exception:
            addr = ''

    common = {
        'weekday': weekday,
        'jalali_date': jalali_date,
        'visit_time': visit_time,
        'presence_address': addr,
        'support_phone': support,
    }
    partner_n = normalize_iran_mobile(partner_phone)
    plus_n = normalize_iran_mobile(plus_user_phone)
    same_person = bool(partner_n and plus_n and partner_n == plus_n)

    partner_msg = _build_visit_schedule_sms(
        **common,
        counterpart_label='' if (not plus_n or same_person) else 'کاربر پلاس',
        counterpart_name=plus_user_name,
        counterpart_phone=plus_user_phone,
    )
    partner_res = _send_visit_schedule_sms_to(
        to_phone=partner_phone,
        message=partner_msg,
        history_type='partner_visit_schedule',
        partner_phone=partner_phone,
    )

    plus_res = {'ok': True, 'skipped': True, 'error': None}
    if plus_n and not same_person:
        plus_msg = _build_visit_schedule_sms(
            **common,
            counterpart_label='بازاریاب',
            counterpart_name=partner_name or partner_phone,
            counterpart_phone=partner_phone,
        )
        plus_res = _send_visit_schedule_sms_to(
            to_phone=plus_user_phone,
            message=plus_msg,
            history_type='plus_visit_schedule',
            partner_phone=partner_phone,
        )

    plus_failed = (not plus_res.get('ok')) and (not plus_res.get('skipped'))
    partner_failed = (not partner_res.get('ok')) and (not partner_res.get('skipped'))
    return {
        'ok': bool(partner_res.get('ok')) and not plus_failed,
        'skipped': bool(partner_res.get('skipped')) and bool(plus_res.get('skipped')),
        'error': partner_res.get('error') or plus_res.get('error'),
        'plus': plus_res,
        'partner_failed': partner_failed,
        'plus_failed': plus_failed,
    }


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
        return redirect(url_for('express_partner.home'))

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
    """سازگاری با لینک قدیمی — هدایت به دانلود APK (نه صفحه تشکر)."""
    from ..utils.short_urls import (
        apk_file_url_from_settings,
        canonical_public_apk_download_url,
        public_apk_download_url,
    )

    _settings = _express_settings_cached()
    if not apk_file_url_from_settings(_settings):
        return redirect(url_for('express_partner.home'))
    # نسبی برای مرورگر همین origin؛ مطلق برای کلاینت‌های خارجی
    target = public_apk_download_url(_settings, external=False) or canonical_public_apk_download_url(
        _settings
    )
    return redirect(target or url_for('main.short_apk_download'))


def _auto_approve_partner_application(record: dict, *, source: str = 'partner_apply_auto') -> dict:
    """تأیید فوری درخواست — همان مسیر ادمین."""
    try:
        from admin.routes import _approve_express_partner
    except Exception as exc:
        current_app.logger.error('auto-approve import failed: %s', exc, exc_info=True)
        return {'ok': False, 'error': str(exc)}
    phone = str(record.get('phone') or '').strip()
    return _approve_express_partner(
        phone=phone,
        name=(record.get('name') or '').strip(),
        city=(record.get('city') or '').strip(),
        national_id=(record.get('national_id') or '').strip(),
        referred_by_phone=(record.get('referred_by_phone') or '').strip(),
        application=record,
        remove_application=True,
        send_sms=True,
        source=source,
    )


def create_partner_application_core(
    me_phone: str,
    data: dict,
    *,
    form_ref: str = '',
    query_ref: str = '',
    auto_approve: bool = True,
) -> dict:
    """ثبت درخواست همکاری بدون redirect — برای فرم وب و اجنت چت؛ پیش‌فرض تأیید خودکار."""
    phone = (me_phone or '').strip()
    if not phone:
        return {'ok': False, 'error': 'برای ثبت درخواست باید وارد شوید.'}
    if _is_partner_approved(_partner_profile_for_phone(phone)):
        return {'ok': False, 'error': 'حساب شما هم‌اکنون همکار تأییدشده است.', 'already_partner': True}
    if _has_active_application(phone):
        return {'ok': False, 'error': 'درخواست فعال دارید؛ منتظر بررسی بمانید.', 'already_pending': True}

    first_name, last_name, name = _compose_apply_name(data)
    experience = (data.get('experience') or '').strip()[:APPLY_EXPERIENCE_MAX_LEN]
    note = (data.get('note') or '').strip()[:APPLY_NOTE_MAX_LEN]
    city = _default_apply_city(data.get('city') or '')
    national_id = _parse_apply_national_id(data.get('national_id') or '')
    if not first_name or not last_name or not national_id:
        return {'ok': False, 'error': 'نام، نام خانوادگی و کد ملی الزامی است.'}
    if not name:
        return {'ok': False, 'error': 'نام، نام خانوادگی و کد ملی الزامی است.'}
    from ..utils.iran_ids import is_valid_iran_national_id
    if not is_valid_iran_national_id(national_id):
        return {'ok': False, 'error': 'کد ملی واردشده معتبر نیست.'}

    apps = load_express_partner_apps() or []
    new_id = (max([int(x.get('id', 0) or 0) for x in apps if isinstance(x, dict)], default=0) or 0) + 1
    referrer_phone = ''
    try:
        from .referrals import (
            clear_referrer_session,
            register_referral_on_application,
            resolve_referrer_for_apply,
        )
        referrer_phone = resolve_referrer_for_apply(
            phone,
            form_ref=form_ref or '',
            query_ref=query_ref or '',
        )
    except Exception:
        referrer_phone = ''
    payload = {
        'first_name': first_name,
        'last_name': last_name,
        'name': name,
        'city': city,
        'national_id': national_id,
        'experience': experience,
        'note': note,
    }
    record = {
        'id': new_id,
        'first_name': first_name,
        'last_name': last_name,
        'name': name,
        'phone': _canonical_partner_phone(phone),
        'national_id': national_id,
        'city': city,
        'experience': experience,
        'note': note,
        'status': 'new',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'source': (data.get('source') or 'web').strip() or 'web',
    }
    if referrer_phone:
        record['referred_by_phone'] = referrer_phone
    apps.append(record)
    save_express_partner_apps(apps)
    _sync_unapproved_partner_profile(phone, payload)
    if referrer_phone:
        try:
            register_referral_on_application(
                inviter_phone=referrer_phone,
                invitee_phone=record.get('phone', phone),
                invitee_name=record.get('name', ''),
                application_id=new_id,
            )
            clear_referrer_session()
        except Exception:
            pass

    try:
        session.pop('apply_data', None)
    except Exception:
        pass

    if auto_approve:
        approve_out = _auto_approve_partner_application(
            record,
            source=f"partner_apply_auto:{(data.get('source') or 'web')}",
        )
        if approve_out.get('ok'):
            return {
                'ok': True,
                'application_id': new_id,
                'name': name,
                'first_name': first_name,
                'last_name': last_name,
                'city': city,
                'auto_approved': True,
                'already_approved': bool(approve_out.get('already_approved')),
                'sms_sent': True,
                'sms_skipped': False,
                'sms_error': None,
                'sms_infra_error': False,
                'message': 'همکاری شما تأیید شد. پنل بازاریاب فعال است.',
            }
        current_app.logger.error(
            'Partner auto-approve failed phone=%s app=%s err=%s',
            phone,
            new_id,
            approve_out.get('error'),
        )

    sms_out = {'ok': False, 'skipped': True, 'error': 'sms_error'}
    try:
        sms_out = _send_partner_application_sms(phone, name)
    except Exception as e:
        current_app.logger.error('Application SMS flow error: %s', e, exc_info=True)
        err_msg = str(e)
        sms_out = {
            'ok': False,
            'skipped': False,
            'error': err_msg,
            'infra_error': sms_is_infrastructure_error(err_msg),
        }

    return {
        'ok': True,
        'application_id': new_id,
        'name': name,
        'first_name': first_name,
        'last_name': last_name,
        'city': city,
        'auto_approved': False,
        'sms_sent': bool(sms_out.get('ok')),
        'sms_skipped': bool(sms_out.get('skipped')),
        'sms_error': sms_out.get('error'),
        'sms_infra_error': bool(sms_out.get('infra_error')),
        'message': 'درخواست همکاری ثبت شد و در صف بررسی است.',
    }


def _submit_partner_application(me_phone: str, data: dict):
    """ثبت نهایی درخواست همکاری (فرم وب → redirect)."""
    out = create_partner_application_core(
        me_phone,
        data,
        form_ref=request.form.get('ref') or '',
        query_ref=request.args.get('ref') or '',
    )
    if not out.get('ok'):
        if out.get('already_partner'):
            return redirect(url_for('express_partner.home'))
        if out.get('already_pending'):
            return redirect(_post_apply_landing_url(me_phone))
        flash(str(out.get('error') or 'ثبت درخواست ناموفق بود.'), 'error')
        return redirect(url_for('express_partner.apply'))
    if out.get('auto_approved'):
        flash(str(out.get('message') or 'همکاری شما تأیید شد.'), 'success')
        return redirect(url_for('express_partner.home'))
    return _redirect_apply_thanks(
        out.get('name', ''),
        fresh_submit=True,
        sms_sent=bool(out.get('sms_sent')),
        sms_skipped=bool(out.get('sms_skipped')),
        sms_error=out.get('sms_error'),
        sms_infra_error=bool(out.get('sms_infra_error')),
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


HOME_SUGGESTED_FILES_LIMIT = 1


def _home_urgent_actions(
    phone: str,
    *,
    assigned_lands: List[Dict[str, Any]],
    visit_rows: List[Dict[str, Any]],
    withdrawable_balance: int,
    follow_up_count: int,
) -> List[Dict[str, Any]]:
    ph = (phone or '').strip()
    if not ph:
        return []
    today_iso = date.today().isoformat()
    actions: List[Dict[str, Any]] = []

    for land in assigned_lands or []:
        if str(land.get('_assignment_status') or '').strip().lower() == 'in_transaction':
            code = str(land.get('code') or '').strip()
            if not code:
                continue
            land_label = (land.get('title') or code).strip()
            actions.append({
                'key': 'deal_pending_chat',
                'icon': 'fa-handshake',
                'tone': 'red',
                'title': 'معامله منتظر تأیید است',
                'subtitle': land_label,
                'cta': 'وضعیت در چت',
                'url': url_for('express_partner.home'),
                'chat_prompt': (
                    f'فایل {code}'
                    + (f' ({land_label})' if land_label and land_label != code else '')
                    + ': فروشم ثبت شده و منتظر تأیید ادمین است؛ وضعیت کوتاه بگو. '
                    'اگر انصراف می‌خوام بگو کارت بستن معامله بده.'
                ),
                'chat_intent': 'status',
                'land_code': code,
                'priority': 100,
            })
            break

    for row in visit_rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('partner_phone') or '').strip() != ph:
            continue
        st = str(row.get('status') or '').strip()
        vd = str(row.get('visit_date') or '').strip()
        code = str(row.get('land_code') or '').strip()
        if st == APPROVED_STATUS and vd == today_iso and code:
            land_label = (row.get('land_title') or code).strip()
            actions.append({
                'key': 'visit_today',
                'icon': 'fa-map-marker-alt',
                'tone': 'amber',
                'title': 'امروز بازدید داری',
                'subtitle': land_label,
                'cta': 'ثبت در چت',
                'url': url_for('express_partner.home'),
                'chat_prompt': (
                    f'فایل {code}'
                    + (f' ({land_label})' if land_label and land_label != code else '')
                    + ': بازدید انجام شد — کارت تأییدش رو بده.'
                ),
                'chat_intent': 'complete_visit',
                'land_code': code,
                'priority': 90,
            })
            break

    if follow_up_count > 0:
        n = int(follow_up_count)
        actions.append({
            'key': 'follow_up',
            'icon': 'fa-clipboard-list',
            'tone': 'blue',
            'title': f'{n} اقدام رو همین الان باید انجام بدی' if n > 1 else 'یک اقدام رو همین الان باید انجام بدی',
            'subtitle': 'از چت خانه قدم بعدی را بزن',
            'cta': 'برو به چت',
            'url': url_for('express_partner.home'),
            'chat_prompt': 'قدم بعدی فروش من چیست؟ از همین چت جلو ببر.',
            'chat_intent': 'next_action',
            'priority': 80,
        })

    if int(withdrawable_balance or 0) >= int(MIN_WITHDRAWAL_AMOUNT):
        actions.append({
            'key': 'withdraw',
            'icon': 'fa-wallet',
            'tone': 'green',
            'title': 'پولت آماده برداشت است',
            'subtitle': 'از کیف پول درخواست برداشت بزن؛ قدم بعدی فروش را از چت بپرس',
            'cta': 'برداشت',
            'url': url_for('express_partner.commissions'),
            'priority': 70,
        })

    actions.sort(key=lambda a: int(a.get('priority') or 0), reverse=True)
    return actions[:1]


def _home_score_suggested_land(land: Dict[str, Any], *, now: datetime | None = None) -> float:
    now = now or datetime.utcnow()
    score = 0.0
    comm = int(land.get('_commission_amount') or 0)
    if comm > 0:
        score += min(comm / 500_000.0, 60.0)
    st = str(land.get('_assignment_status') or '').strip().lower()
    if st == 'in_transaction':
        score += 45.0
    created = parse_datetime_safe(land.get('created_at') or '')
    try:
        age_days = max(0, (now - created).days)
    except Exception:
        age_days = 999
    if age_days <= 14:
        score += max(0.0, 35.0 - age_days * 2.0)
    if st in ('active', 'approved', 'pending') and not land.get('_is_expired'):
        score += 8.0
    return score


# قیف فروش روی کارت خانه (۴ مرحله مأموریت)
_HOME_FUNNEL_STEPS = (
    ('assigned', 'اختصاص فایل', 'fa-bullseye'),
    ('marketing', 'بازاریابی', 'fa-bullhorn'),
    ('visit_request', 'درخواست بازدید', 'fa-calendar-days'),
    ('deal_or_revisit', 'معامله / بازدید مجدد', 'fa-handshake'),
)


def _home_funnel_for_land(
    phone: str,
    land: Dict[str, Any],
    visit_rows: List[Dict[str, Any]] | None = None,
    *,
    commissions: List[Dict[str, Any]] | None = None,
    visit_commission_required: bool = False,
) -> Dict[str, Any]:
    """مرحله و مسیر ۴تایی مأموریت برای کارت سفر خانه.

    منبع حقیقت برای CTA: current_key (با tx_mode ریزتنظیم می‌شود).
    """
    from app.express_partner.visit_requests import (
        partner_active_visit_record,
        visit_commission_ready_for_deal,
    )

    ph = (phone or '').strip()
    code = str(land.get('code') or '').strip()
    assign_st = str(land.get('_assignment_status') or '').strip().lower()
    latest = partner_active_visit_record(visit_rows or [], ph, code) if ph and code else None
    status = str((latest or {}).get('status') or '').strip()

    has_visit = bool(latest)
    visit_pending = status == PENDING_STATUS
    visit_approved_only = status == APPROVED_STATUS
    visit_done_pending = status == DONE_PENDING_STATUS
    visit_done = status == COMPLETED_STATUS
    visit_cancelled = status == CANCELLED_STATUS
    in_tx = assign_st == 'in_transaction' or bool(land.get('_in_transaction'))
    sold = assign_st == 'sold'
    visit_ready = bool(visit_done)
    wait_visit_commission = False
    _ = (visit_commission_required, commissions)

    # مسیر رسمی مأموریت:
    # ۱) اختصاص — با بودن روی کارت همیشه done
    # ۲) بازاریابی — تا قبل از ثبت بازدید (کلیک/CTA می‌تواند مستقیم به بازدید بپرد)
    # ۳) درخواست بازدید — از ثبت بازدید تا completed (با ساب‌لیبل وضعیت)
    # ۴) معامله/بازدید مجدد — بعد از completed تا sold
    assigned_done = True
    marketing_done = (has_visit and not visit_cancelled) or in_tx or sold
    visit_step_done = visit_done or in_tx or sold
    deal_done = sold

    done_flags = [
        assigned_done,
        marketing_done,
        visit_step_done,
        deal_done,
    ]
    current_idx = next((i for i, d in enumerate(done_flags) if not d), None)

    steps = []
    for i, (key, label, icon) in enumerate(_HOME_FUNNEL_STEPS):
        state = 'done' if done_flags[i] else 'todo'
        if current_idx is not None and i == current_idx:
            state = 'current'
        # برچسب مرحله ۳ را با وضعیت بازدید زنده نگه دار
        step_label = label
        if key == 'visit_request' and state == 'current':
            if visit_pending:
                step_label = 'منتظر تأیید بازدید'
            elif visit_approved_only:
                step_label = 'بازدید را انجام بده'
            elif visit_done_pending:
                step_label = 'تأیید انجام بازدید'
        if key == 'deal_or_revisit' and state == 'current':
            if in_tx:
                step_label = 'در حال معامله'
        steps.append({'key': key, 'label': step_label, 'icon': icon, 'state': state})

    current_key = ''
    if current_idx is not None and 0 <= current_idx < len(_HOME_FUNNEL_STEPS):
        current_key = _HOME_FUNNEL_STEPS[current_idx][0]
    elif sold:
        current_key = 'done'

    if sold:
        stage_label = 'تکمیل شد'
    elif in_tx:
        stage_label = 'در حال معامله'
    elif visit_cancelled and not visit_done:
        stage_label = 'بازاریابی مجدد'
    elif visit_done:
        stage_label = 'معامله یا بازدید مجدد'
    elif visit_done_pending:
        stage_label = 'در انتظار تأیید انجام'
    elif visit_approved_only:
        stage_label = 'بازدید تأییدشد'
    elif visit_pending or (has_visit and not visit_cancelled):
        stage_label = 'در انتظار بازدید'
    else:
        stage_label = 'بازاریابی'

    return {
        'stage_label': stage_label,
        'funnel_steps': steps,
        'current_key': current_key,
        'current_idx': current_idx,
    }


def _home_suggested_files(
    phone: str,
    is_approved: bool,
    *,
    assigned_lands: List[Dict[str, Any]] | None = None,
    visit_rows: List[Dict[str, Any]] | None = None,
    urgent_actions: List[Dict[str, Any]] | None = None,
    limit: int = HOME_SUGGESTED_FILES_LIMIT,
) -> List[Dict[str, Any]]:
    from ..utils.images import partner_card_image_url
    from app.express_partner.sales_coach import (
        build_journey_chat_cta,
        coach_tip_for_stage,
        enrich_funnel_steps_for_nav,
    )
    from app.express_partner.visit_requests import resolve_partner_land_tx_state

    if assigned_lands is None:
        assigned_lands, _ = _build_partner_dashboard_lands(phone, is_approved)
    candidates: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    assignments = load_express_assignments() or []
    commissions = load_express_commissions_cached() or []
    visits = visit_rows if isinstance(visit_rows, list) else (load_express_visit_requests() or [])
    for land in assigned_lands or []:
        if not isinstance(land, dict):
            continue
        # کارت مأموریت/پیشنهاد خانه فقط فایلِ اختصاص‌یافته به همکار
        if not land.get('_assignment_id'):
            continue
        st = str(land.get('_assignment_status') or '').strip().lower()
        if st == 'sold' or land.get('_is_expired'):
            continue
        code = str(land.get('code') or '').strip()
        if not code:
            continue
        try:
            price_total = int(land.get('price_total') or land.get('price') or 0)
        except Exception:
            price_total = 0
        visit_req = _visit_commission_required_for(
            commissions if isinstance(commissions, list) else [], phone, code
        )
        funnel = _home_funnel_for_land(
            phone,
            land,
            visit_rows=visits,
            commissions=commissions if isinstance(commissions, list) else [],
            visit_commission_required=visit_req,
        )
        stage_label = funnel.get("stage_label") or "علاقه‌مند"
        tip = coach_tip_for_stage(
            stage_label=str(stage_label),
            in_transaction=st == "in_transaction",
            sold=False,
            commission_amount=int(land.get("_commission_amount") or 0),
        )
        try:
            tx_state = resolve_partner_land_tx_state(
                me_phone=phone,
                land_code=code,
                assignments=assignments,
                visit_requests=visits,
                is_partner_approved=bool(is_approved),
                global_assignment_status=st or "active",
                commissions=commissions if isinstance(commissions, list) else [],
                visit_commission_required=visit_req,
            )
            tx_mode = str(tx_state.get("tx_mode") or "")
            can_revisit = bool(tx_state.get("can_revisit"))
        except Exception:
            tx_mode = ""
            can_revisit = False
        funnel_key = str(funnel.get("current_key") or "")
        cta = build_journey_chat_cta(
            code=code,
            title=(land.get("title") or "").strip(),
            tx_mode=tx_mode,
            stage_label=str(stage_label),
            funnel_key=funnel_key,
            can_revisit=can_revisit,
        )
        funnel_steps = enrich_funnel_steps_for_nav(
            funnel.get('funnel_steps') or [],
            code=code,
            title=(land.get("title") or "").strip(),
            tx_mode=tx_mode,
            can_revisit=can_revisit,
        )
        candidates.append({
            'code': code,
            'title': (land.get('title') or '—').strip(),
            'city': (land.get('city') or '').strip(),
            'location': (land.get('location') or '').strip(),
            'price_total': price_total,
            'commission_amount': int(land.get('_commission_amount') or 0),
            'commission_pct': land.get('_commission_pct'),
            'image_url': partner_card_image_url(land) or None,
            'detail_url': url_for('express_partner.land_detail', code=code),
            'more_url': url_for('express_partner.home'),
            'stage_label': stage_label,
            'funnel_steps': funnel_steps,
            'funnel_key': funnel_key,
            'tx_mode': tx_mode,
            'can_revisit': can_revisit,
            'cta_label': cta.get('label') or 'ادامه در چت',
            'cta_url': '',
            'cta_icon': cta.get('icon') or 'fa-comments',
            'cta_action': cta.get('action') or '',
            'cta_chat_prompt': cta.get('prompt') or '',
            'cta_secondary_label': cta.get('secondary_label') or '',
            'cta_secondary_icon': cta.get('secondary_icon') or '',
            'cta_secondary_action': cta.get('secondary_action') or '',
            'cta_secondary_prompt': cta.get('secondary_prompt') or '',
            'show_fav': True,
            'coach_tip': tip,
            '_score': _home_score_suggested_land(land, now=now),
        })
    candidates.sort(key=lambda x: float(x.get('_score') or 0), reverse=True)
    out = []
    for item in candidates[:limit]:
        row = dict(item)
        row.pop('_score', None)
        code = str(row.get('code') or '')
        for act in (urgent_actions or []):
            if not isinstance(act, dict):
                continue
            act_code = str(act.get('land_code') or '').strip()
            if act_code and act_code == code:
                row['cta_label'] = act.get('cta') or row.get('cta_label')
                row['cta_icon'] = act.get('icon') or row.get('cta_icon') or 'fa-comments'
                chat_p = str(act.get('chat_prompt') or '').strip()
                if act.get('key') in ('deal_pending_chat', 'visit_today') or chat_p:
                    row['cta_url'] = ''
                    if chat_p:
                        row['cta_chat_prompt'] = chat_p
                    row['cta_action'] = str(act.get('chat_intent') or row.get('cta_action') or '')
                    if act.get('key') == 'deal_pending_chat':
                        row['stage_label'] = 'منتظر تأیید معامله'
                    elif act.get('key') == 'visit_today':
                        row['stage_label'] = 'بازدید امروز'
                break
        out.append(row)
    return out


def _home_follow_up_count(phone: str, visit_rows: List[Dict[str, Any]]) -> int:
    ph = (phone or '').strip()
    if not ph:
        return 0
    follow_statuses = frozenset({APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS})
    return sum(
        1 for row in (visit_rows or [])
        if isinstance(row, dict)
        and str(row.get('partner_phone') or '').strip() == ph
        and str(row.get('status') or '').strip() in follow_statuses
    )


def _partner_has_pending_app(me_phone: str) -> bool:
    ph = (me_phone or '').strip()
    if not ph:
        return False
    apps = load_express_partner_apps() or []
    pending = frozenset({'pending', 'under_review', 'waiting', 'review'})
    for a in apps:
        if not isinstance(a, dict):
            continue
        if str(a.get('phone') or '').strip() != ph:
            continue
        if str(a.get('status') or '').strip().lower() in pending:
            return True
    return False


def _partner_has_completed_deal(
    me_phone: str,
    commissions: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """True اگر حداقل یک پورسانت فروش (معامله) با وضعیت approved/paid داشته باشد."""
    ph = (me_phone or '').strip()
    if not ph:
        return False
    rows = commissions if commissions is not None else _commissions_for_phone(ph)
    finalized = frozenset({APPROVED_STATUS, PAID_STATUS})
    for c in rows or []:
        if not isinstance(c, dict):
            continue
        try:
            if not commission_is_deal(c):
                continue
        except Exception:
            continue
        if (str(c.get('status') or '')).strip().lower() in finalized:
            return True
    return False


def _home_ai_empty_title(
    *,
    is_approved: bool,
    has_pending_app: bool,
    has_completed_deal: bool,
) -> str:
    """تیتر حالت خالی خانه — بر اساس مرحلهٔ کاربر."""
    if is_approved:
        if has_completed_deal:
            return 'امروز دنبال فروشی یا جذب فایل؟'
        return 'آماده‌ای اولین پورسانتت را بگیری؟'
    if has_pending_app:
        return 'تا تأیید، از همین‌جا بپرس'
    # مهمان / واردنشده / لاگین‌شدهٔ غیرتأیید
    return 'دنبال خرید ملکی یا همکاری با وینور؟'


_HOME_NEWS_FALLBACK: List[str] = [
    'زمین جابان فروش رفت و پورسانت رسید',
    'فایل گرمابسرد بسته شد و پورسانت نشست',
    'ویلای آبسرد بسته شد — پورسانت در کیف پول است',
    'همکار دماوند با یک معامله پورسانت گرفت',
    'باغ کیلان فروخته شد؛ پورسانت قابل برداشت شد',
    'زمین رودهن امروز فروش رفت و پورسانت نشست',
    'فایل بومهن فروخته شد؛ پورسانت تسویه شد',
    'ویلای گیلاوند بسته شد و پورسانت رسید',
    'زمین مشا فروخته شد؛ پورسانت همکار واریز شد',
    'باغ سربندان فروخته شد — پورسانت در حساب است',
    'فایل دماوند بسته شد؛ پورسانت ثبت شد',
    'زمین هویر فروش رفت؛ پورسانت تسویه شد',
]

_HOME_NEWS_TEMPLATES: tuple[str, ...] = (
    '{label} فروش رفت و پورسانت رسید',
    '{label} بسته شد — پورسانت در کیف پول است',
    'فایل {label} فروخته شد؛ پورسانت واریز شد',
    'معامله {label} بسته شد و پورسانت نشست',
    '{label} امروز فروش رفت؛ پورسانت قابل برداشت شد',
)


def _home_news_short_label(comm: Dict[str, Any], lands_by_code: Dict[str, Dict[str, Any]]) -> str:
    code = str(comm.get('land_code') or '').strip()
    if not code or code == 'referral':
        return ''
    land = lands_by_code.get(code)
    if isinstance(land, dict):
        loc = str(land.get('location') or '').strip()
        if loc:
            return loc
        city = str(land.get('city') or '').strip()
        if city:
            return city
    title = str(comm.get('land_title') or '').strip()
    if title:
        parts = [p.strip() for p in re.split(r'[\s،,]+', title) if p.strip()]
        if parts:
            tail = parts[-1]
            if len(tail) >= 2 and not tail.isdigit():
                return tail
        return title[:32].strip()
    return 'فایل وینور'


def _home_news_headlines(*, limit: int = 40) -> List[str]:
    """تیترهای چرخشی خبر خانه — از معاملات تأییدشده + fallback."""
    headlines: List[str] = []
    seen: set[str] = set()
    try:
        comms = _express_commissions_cached() or []
        lands = load_express_lands_cached() or []
        lands_by_code = {
            str(L.get('code') or '').strip(): L
            for L in lands
            if isinstance(L, dict) and str(L.get('code') or '').strip()
        }
        eligible: List[tuple[str, Dict[str, Any]]] = []
        for c in comms:
            if not isinstance(c, dict):
                continue
            ct = str(c.get('commission_type') or 'deal').strip().lower()
            if ct in ('referral', 'manual_adjustment', 'visit'):
                continue
            st = str(c.get('status') or '').strip().lower()
            if st not in ('approved', 'paid'):
                continue
            code = str(c.get('land_code') or '').strip()
            if not code or code == 'referral':
                continue
            ts = str(
                c.get('approved_at') or c.get('paid_at') or c.get('created_at') or ''
            ).strip()
            eligible.append((ts, c))
        eligible.sort(key=lambda row: row[0], reverse=True)
        for i, (_, comm) in enumerate(eligible[: max(limit, 1)]):
            label = _home_news_short_label(comm, lands_by_code)
            if not label:
                continue
            tpl = _HOME_NEWS_TEMPLATES[i % len(_HOME_NEWS_TEMPLATES)]
            line = tpl.format(label=label)
            if line in seen:
                continue
            seen.add(line)
            headlines.append(line)
    except Exception:
        try:
            current_app.logger.exception('home news headlines failed')
        except Exception:
            pass
    for fb in _HOME_NEWS_FALLBACK:
        if len(headlines) >= limit:
            break
        if fb not in seen:
            seen.add(fb)
            headlines.append(fb)
    if headlines:
        return headlines[:limit]
    return list(_HOME_NEWS_FALLBACK[:12])


def _land_status_from_assigned_lands(assigned_lands: List[Dict[str, Any]]) -> Dict[str, str]:
    land_status: Dict[str, str] = {}
    for land in assigned_lands or []:
        if not isinstance(land, dict):
            continue
        code = str(land.get('code') or '').strip()
        if code:
            land_status[code] = str(land.get('_assignment_status') or 'active').strip().lower()
    return land_status


def _build_partner_sales_pipeline(
    me_phone: str,
    profile,
    visit_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    land_status: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """آیتم‌ها و شمارش تب‌های پیگیری — مشترک بین /requests و badge خانه."""
    from .partner_roles import partner_can_manage_deal, partner_can_record_visit_attendance
    from .visit_requests import (
        OPEN_VISIT_STATUSES,
        PIPELINE_DEALS,
        PIPELINE_REQUESTS,
        PIPELINE_VISITS,
        partner_request_feed_item,
        partner_requests_can_revisit,
        partner_visits_for_phone,
    )

    ph = (me_phone or '').strip()
    is_approved = _is_partner_approved(profile)
    is_special = _is_partner_special(profile) if is_approved else False

    rows = visit_rows if visit_rows is not None else (load_express_visit_requests() or [])
    if not isinstance(rows, list):
        rows = []
    mine = partner_visits_for_phone(rows, ph)

    if land_status is None:
        land_status = {}
        if ph and is_approved:
            try:
                lands, _ = _build_partner_dashboard_lands(ph, True)
                land_status = _land_status_from_assigned_lands(lands)
            except Exception:
                land_status = {}
    else:
        land_status = dict(land_status)

    support_phone = '09121471301'
    try:
        from app.crm.config import VISIT_CALL_TARGET
        raw = str(VISIT_CALL_TARGET or '').strip()
        phone = normalize_iran_mobile(raw)
        if is_valid_iran_mobile(phone):
            support_phone = phone
        elif raw:
            support_phone = raw
    except Exception:
        support_phone = '09121471301'

    items: List[Dict[str, Any]] = []
    allow_attendance = partner_can_record_visit_attendance(profile)
    allow_deal = partner_can_manage_deal(profile)
    for r in mine:
        code = str(r.get('land_code') or '').strip()
        gs = land_status.get(code, 'active')
        can_revisit = partner_requests_can_revisit(
            r,
            assignment_status=gs,
            visit_requests=rows,
            phone=ph,
        )
        items.append(partner_request_feed_item(
            r,
            can_revisit=can_revisit,
            support_phone=support_phone,
            assignment_status=gs,
            allow_attendance=allow_attendance,
            allow_deal=allow_deal,
            allow_revisit=is_approved,
            me_phone=ph,
        ))

    open_count = sum(
        1
        for r in mine
        if str(r.get('status') or '').strip() in OPEN_VISIT_STATUSES
    )

    inbox_items: list = []
    offers: list = []
    visit_weekday_labels = {}
    visit_weekday_order = []
    visit_allowed_weekdays = []
    visit_hour_rows_data = []
    visit_allowed_weekdays_summary = ''
    visit_allowed_hours_summary = ''
    visit_presence_address = ''
    if is_special:
        try:
            from .special_visit_inbox import visits_for_special_owner
            from .visit_requests import (
                VISIT_WEEKDAY_LABELS,
                VISIT_WEEKDAY_ORDER,
                get_plus_visit_presence_address,
                get_visit_allowed_weekdays,
                visit_allowed_hours_summary as _hours_summary,
                visit_allowed_weekdays_summary as _days_summary,
                visit_hour_rows,
            )

            inbox_items = visits_for_special_owner(ph) or []
            visit_weekday_labels = VISIT_WEEKDAY_LABELS
            visit_weekday_order = VISIT_WEEKDAY_ORDER
            visit_allowed_weekdays = get_visit_allowed_weekdays(plus_user_phone=ph)
            visit_allowed_weekdays_summary = _days_summary(plus_user_phone=ph)
            visit_hour_rows_data = visit_hour_rows(plus_user_phone=ph)
            visit_allowed_hours_summary = _hours_summary(plus_user_phone=ph)
            visit_presence_address = get_plus_visit_presence_address(ph)
        except Exception:
            current_app.logger.exception('sales pipeline inbox load failed')
            inbox_items = []
        try:
            from app.commercial.config import commercial_ui_enabled
            if commercial_ui_enabled():
                from .special_offer_inbox import offers_for_special_owner
                offers = offers_for_special_owner(ph) or []
        except Exception:
            offers = []

    if is_special and inbox_items:
        inbox_ids = {
            str(i.get('id') or '').strip()
            for i in inbox_items
            if str(i.get('id') or '').strip()
        }
        if inbox_ids:
            items = [
                it for it in items
                if str(it.get('id') or '').strip() not in inbox_ids
            ]

    tab_counts = {
        PIPELINE_REQUESTS: 0,
        PIPELINE_VISITS: 0,
        PIPELINE_DEALS: 0,
    }
    for it in items:
        key = str(it.get('pipeline_tab') or PIPELINE_REQUESTS)
        if key in tab_counts:
            tab_counts[key] += 1
    for it in inbox_items:
        key = str(it.get('pipeline_tab') or PIPELINE_VISITS)
        if key in tab_counts:
            tab_counts[key] += 1
    if offers:
        tab_counts[PIPELINE_DEALS] += len(offers)

    return {
        'items': items,
        'inbox_items': inbox_items,
        'offers': offers,
        'tab_counts': tab_counts,
        'open_count': open_count,
        'is_approved': is_approved,
        'is_special': is_special,
        'support_phone': support_phone,
        'allow_attendance': allow_attendance,
        'visit_weekday_labels': visit_weekday_labels,
        'visit_weekday_order': visit_weekday_order,
        'visit_allowed_weekdays': visit_allowed_weekdays,
        'visit_hour_rows_data': visit_hour_rows_data,
        'visit_allowed_weekdays_summary': visit_allowed_weekdays_summary,
        'visit_allowed_hours_summary': visit_allowed_hours_summary,
        'visit_presence_address': visit_presence_address,
    }


def _home_requests_pipeline_count(
    me_phone: str,
    profile,
    visit_rows: List[Dict[str, Any]],
    *,
    land_status: Optional[Dict[str, str]] = None,
) -> int:
    """مجموع آیتم‌های صندوق پیگیری — برای badge کاشی خانه."""
    ph = (me_phone or '').strip()
    if not ph or not _is_partner_approved(profile):
        return 0
    try:
        pipe = _build_partner_sales_pipeline(
            ph, profile, visit_rows, land_status=land_status
        )
        tab_counts = pipe.get('tab_counts') or {}
        return sum(int(tab_counts.get(k) or 0) for k in tab_counts)
    except Exception:
        current_app.logger.exception('home requests pipeline count failed')
        return 0


def _build_home_dashboard_payload(me_phone: str, profile) -> Dict[str, Any]:
    ph = (me_phone or '').strip()
    is_approved = _is_partner_approved(profile)
    has_pending_app = _partner_has_pending_app(ph) if ph and not is_approved else False
    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []

    my_comms = _commissions_for_phone(ph) if ph else []
    comm_stats = _partner_commission_stats(ph, my_comms) if ph else {}
    withdrawable = int(comm_stats.get('withdrawable_balance') or 0) if ph else 0
    follow_up_count = _home_follow_up_count(ph, visit_rows) if ph else 0
    has_completed_deal = _partner_has_completed_deal(ph, my_comms) if ph and is_approved else False

    # مأموریت/کارت فایل اجباری حذف شد — خانه = چت بازاریاب فروش
    assigned_lands: List[Dict[str, Any]] = []
    if ph:
        assigned_lands, _ = _build_partner_dashboard_lands(ph, is_approved)

    personal_lands = [
        L for L in (assigned_lands or [])
        if isinstance(L, dict) and L.get('_assignment_id')
    ]

    urgent_actions = _home_urgent_actions(
        ph,
        assigned_lands=personal_lands,
        visit_rows=visit_rows,
        withdrawable_balance=withdrawable,
        follow_up_count=follow_up_count,
    ) if ph else []

    suggested_files = _home_suggested_files(
        ph,
        is_approved,
        assigned_lands=personal_lands,
        visit_rows=visit_rows,
        urgent_actions=urgent_actions,
        limit=1,
    ) if ph else []

    home_requests_pipeline_count = (
        _home_requests_pipeline_count(
            ph,
            profile,
            visit_rows,
            land_status=_land_status_from_assigned_lands(personal_lands),
        )
        if ph and is_approved else 0
    )

    out: Dict[str, Any] = {
        'success': True,
        'is_logged_in': bool(ph),
        'is_approved': is_approved,
        'has_pending_app': has_pending_app,
        'has_completed_deal': has_completed_deal,
        'urgent_actions': urgent_actions,
        'suggested_files': suggested_files,
        'journey_card': None,
        'mission': None,
        'withdrawable_balance': withdrawable,
        'home_requests_pipeline_count': home_requests_pipeline_count,
        'customer_modal_lands': [],
        'is_special': _is_partner_special(profile) if ph and is_approved else False,
        'lawyer_feature_on': False,
        'plus_system_enabled': False,
        'customer_modal_plus_users': [],
        'visit_slots_by_plus': {},
        'crm_ui_enabled': False,
    }
    try:
        ctx = _home_customer_modal_context(ph, is_approved)
        out['customer_modal_lands'] = ctx.get('customer_modal_lands') or []
        out['customer_modal_plus_users'] = ctx.get('customer_modal_plus_users') or []
        out['visit_slots_by_plus'] = ctx.get('visit_slots_by_plus') or {}
    except Exception:
        pass
    try:
        from app.crm.config import crm_ui_enabled

        out['crm_ui_enabled'] = bool(crm_ui_enabled() and is_approved)
    except Exception:
        out['crm_ui_enabled'] = False
    try:
        from app.lawyer.config import lawyer_enabled

        out['lawyer_feature_on'] = bool(lawyer_enabled())
    except Exception:
        out['lawyer_feature_on'] = False
    try:
        from .zarinpal_config import plus_system_enabled as _plus_system_enabled

        out['plus_system_enabled'] = bool(_plus_system_enabled())
    except Exception:
        out['plus_system_enabled'] = False
    return out


def _partner_ai_welcome(*, is_approved: bool, has_pending_app: bool, me_phone: str) -> str:
    """پیام شروع‌کنندهٔ وینور در چت خانه — خریدار | استخدام/فروش."""
    from app.ai.welcome import opening_text

    _ = me_phone
    return opening_text(is_approved=is_approved, has_pending_app=bool(has_pending_app))


def _partner_ai_layer_context(
    me_phone: str,
    *,
    profile: Optional[Dict[str, Any]] = None,
    has_pending_app: bool = False,
) -> Dict[str, Any]:
    """زمینهٔ چت خانه — بازاریاب تأییدشده: کامل؛ مهمان/کاربر عادی: جستجو+ورود به بازاریابی."""
    phone = (me_phone or '').strip()
    is_approved = _is_partner_approved(profile) if phone else False
    limited = not is_approved
    open_tid = (request.args.get('thread') or '').strip()
    want_ai = str(request.args.get('ai') or '').strip() in ('1', 'true', 'yes')

    ctx: Dict[str, Any] = {
        'home_ai_enabled': True,
        'home_ai_limited': limited,
        'ai_chat_welcome': _partner_ai_welcome(
            is_approved=is_approved,
            has_pending_app=bool(has_pending_app),
            me_phone=phone,
        ),
        'chat_messages': [],
        'chat_threads': [],
        'active_thread_id': '',
        'postchi_thread_id': '__postchi__',
        'lawyer_thread_id': '__lawyer__',
        'lawyer_enabled': False,
        'lawyer_feature_on': False,
        'home_ai_open': False,
        'home_ai_open_thread': '',
        'chat_api_url': '',
        'clear_api_url': '',
        'history_api_url': '',
        'switch_thread_url': '',
        'delete_thread_url': '',
        'sync_api_url': '',
        'agent_confirm_url': '',
        'agent_cancel_url': '',
        'postchi_messages_url': '',
        'postchi_send_url': '',
        'postchi_open_url': '',
        'ai_upload_url': '',
        'guest_replies_remaining': None,
        'guest_replies_limit': None,
    }

    chat_messages: List[Dict[str, Any]] = []
    chat_threads: List[Dict[str, Any]] = []
    active_thread_id = ''
    postchi_thread_id = '__postchi__'
    home_ai_open = False
    home_ai_open_thread = ''

    if limited:
        # مهمان / کاربر عادی / متقاضی: چت عمومی محدود — بدون پستچی و ابزار فروش
        # وکیل ملکی فقط برای کاربر واردشده (دارای شماره)
        lawyer_thread_id = '__lawyer__'
        lawyer_on = False
        lawyer_feature_on = False
        try:
            from app.ai.audience import AUDIENCE_PUBLIC
            from app.ai.chat_store import (
                ensure_active_thread,
                messages_for_ui,
                threads_for_ui,
            )
            from app.ai.user_key import ai_user_key
            from app.ai.welcome import ensure_vinor_opens_chat
            from app.lawyer.config import lawyer_enabled as _lawyer_enabled
            from app.lawyer.service import (
                LAWYER_THREAD_ID,
                ensure_lawyer_thread,
                is_lawyer_thread,
                threads_with_lawyer,
            )

            user_key = ai_user_key()
            lawyer_feature_on = bool(_lawyer_enabled())
            lawyer_on = lawyer_feature_on and bool(phone)
            lawyer_thread_id = LAWYER_THREAD_ID
            if (is_lawyer_thread(open_tid) or open_tid in ('lawyer', 'vakil')) and lawyer_on:
                active_thread_id = ensure_lawyer_thread(
                    user_key, audience=AUDIENCE_PUBLIC
                )
                chat_messages = messages_for_ui(
                    user_key,
                    thread_id=active_thread_id,
                    audience=AUDIENCE_PUBLIC,
                ) or []
                home_ai_open = True
                home_ai_open_thread = LAWYER_THREAD_ID
            elif open_tid and not (
                is_lawyer_thread(open_tid) or open_tid in ('lawyer', 'vakil')
            ):
                # لینک مستقیم هم به همان چت واحد وینور
                active_thread_id = ensure_active_thread(user_key, audience=AUDIENCE_PUBLIC)
                home_ai_open = True
                home_ai_open_thread = active_thread_id
                chat_messages, active_thread_id = ensure_vinor_opens_chat(
                    user_key,
                    audience=AUDIENCE_PUBLIC,
                    thread_id=active_thread_id or None,
                    text=ctx['ai_chat_welcome'],
                    has_pending_app=bool(has_pending_app),
                )
                if not chat_messages:
                    chat_messages = messages_for_ui(
                        user_key,
                        thread_id=active_thread_id or None,
                        audience=AUDIENCE_PUBLIC,
                    ) or []
            else:
                # بدو ورود: صفحه خالی GPT — تاریخچه پاک نمی‌شود؛ چت قبلی در کشو می‌ماند
                active_thread_id = ensure_active_thread(
                    user_key, audience=AUDIENCE_PUBLIC
                )
                chat_messages = []
                if want_ai:
                    home_ai_open = True
            if lawyer_on:
                chat_threads = threads_with_lawyer(
                    user_key,
                    audience=AUDIENCE_PUBLIC,
                    active_thread_id=active_thread_id,
                )
            else:
                chat_threads = threads_for_ui(user_key, audience=AUDIENCE_PUBLIC) or []
        except Exception:
            chat_messages = []
            chat_threads = []
            active_thread_id = ''
            home_ai_open = False
            home_ai_open_thread = ''
            lawyer_on = False
            lawyer_feature_on = False

        guest_remaining = None
        guest_limit = None
        try:
            from app.ai.credits import (
                guest_free_assistant_replies,
                guest_replies_remaining,
                is_guest_user_key,
            )
            from app.ai.user_key import ai_user_key

            uk = ai_user_key()
            if is_guest_user_key(uk):
                guest_remaining = guest_replies_remaining(uk)
                guest_limit = guest_free_assistant_replies()
        except Exception:
            guest_remaining = None
            guest_limit = None

        ctx.update({
            'chat_messages': chat_messages,
            'chat_threads': chat_threads,
            'active_thread_id': active_thread_id,
            'postchi_thread_id': '',
            'lawyer_thread_id': lawyer_thread_id,
            'lawyer_enabled': lawyer_on,
            'lawyer_feature_on': lawyer_feature_on,
            'home_ai_open': home_ai_open,
            'home_ai_open_thread': home_ai_open_thread,
            'chat_api_url': url_for('ai.chat'),
            'clear_api_url': url_for('ai.clear'),
            'history_api_url': url_for('ai.history'),
            'switch_thread_url': url_for('ai.switch_thread'),
            'delete_thread_url': url_for('ai.delete_thread'),
            'sync_api_url': url_for('ai.sync'),
            'agent_confirm_url': url_for('ai.agent_confirm'),
            'agent_cancel_url': url_for('ai.agent_cancel'),
            'postchi_messages_url': '',
            'postchi_send_url': '',
            'postchi_open_url': '',
            'ai_upload_url': url_for('express_partner.ai_upload'),
            'guest_replies_remaining': guest_remaining,
            'guest_replies_limit': guest_limit,
        })
        return ctx

    try:
        from app.ai.audience import AUDIENCE_PARTNER
        from app.ai.chat_store import ensure_active_thread, messages_for_ui
        from app.services.postchi import (
            POSTCHI_THREAD_ID,
            is_postchi_thread,
            open_postchi,
            postchi_messages_for_ui,
        )
        from app.lawyer.config import lawyer_enabled as _lawyer_enabled
        from app.lawyer.service import (
            LAWYER_THREAD_ID,
            ensure_lawyer_thread,
            is_lawyer_thread,
            threads_with_lawyer_and_postchi,
        )

        postchi_thread_id = POSTCHI_THREAD_ID
        lawyer_thread_id = LAWYER_THREAD_ID

        if is_postchi_thread(open_tid):
            active_thread_id = POSTCHI_THREAD_ID
            chat_messages = postchi_messages_for_ui(phone) or []
            open_postchi(phone)
            home_ai_open = True
            home_ai_open_thread = POSTCHI_THREAD_ID
        elif is_lawyer_thread(open_tid) or open_tid in ('lawyer', 'vakil'):
            if _lawyer_enabled():
                active_thread_id = ensure_lawyer_thread(phone, audience=AUDIENCE_PARTNER)
                chat_messages = messages_for_ui(
                    phone,
                    thread_id=active_thread_id,
                    audience=AUDIENCE_PARTNER,
                ) or []
                home_ai_open = True
                home_ai_open_thread = LAWYER_THREAD_ID
            else:
                active_thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
                chat_messages = messages_for_ui(phone, active_thread_id, audience=AUDIENCE_PARTNER) or []
        elif open_tid:
            # لینک قدیمی مأموریت/فایل هم به همان چت واحد وینور می‌رود
            from app.ai.welcome import ensure_vinor_opens_chat

            active_thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
            home_ai_open = True
            home_ai_open_thread = active_thread_id
            chat_messages, active_thread_id = ensure_vinor_opens_chat(
                phone,
                audience=AUDIENCE_PARTNER,
                thread_id=active_thread_id or None,
                text=ctx['ai_chat_welcome'],
                is_approved=True,
            )
            if not chat_messages:
                chat_messages = messages_for_ui(
                    phone,
                    thread_id=active_thread_id or None,
                    audience=AUDIENCE_PARTNER,
                ) or []
        else:
            # بدو ورود: صفحه خالی GPT — تاریخچه پاک نمی‌شود؛ چت قبلی در کشو می‌ماند
            active_thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
            chat_messages = []
            if want_ai:
                home_ai_open = True
        chat_threads = threads_with_lawyer_and_postchi(
            phone,
            audience=AUDIENCE_PARTNER,
            active_thread_id=active_thread_id,
        )
    except Exception:
        chat_messages = []
        chat_threads = []
        active_thread_id = ''
        home_ai_open = False
        home_ai_open_thread = ''
        lawyer_thread_id = '__lawyer__'

    ctx.update({
        'chat_messages': chat_messages,
        'chat_threads': chat_threads,
        'active_thread_id': active_thread_id,
        'postchi_thread_id': postchi_thread_id,
        'lawyer_thread_id': lawyer_thread_id,
        'lawyer_enabled': True,
        'lawyer_feature_on': True,
        'home_ai_open': home_ai_open,
        'home_ai_open_thread': home_ai_open_thread,
        'chat_api_url': url_for('express_partner.ai_chat'),
        'clear_api_url': url_for('express_partner.ai_clear'),
        'history_api_url': url_for('express_partner.ai_history'),
        'switch_thread_url': url_for('express_partner.ai_switch_thread'),
        'delete_thread_url': url_for('express_partner.ai_delete_thread'),
        'sync_api_url': url_for('express_partner.ai_sync'),
        'agent_confirm_url': url_for('express_partner.ai_agent_confirm'),
        'agent_cancel_url': url_for('express_partner.ai_agent_cancel'),
        'postchi_messages_url': url_for('express_partner.api_postchi_messages'),
        'postchi_send_url': url_for('express_partner.api_postchi_send'),
        'postchi_open_url': url_for('express_partner.api_postchi_open'),
        'ai_upload_url': url_for('express_partner.ai_upload'),
    })
    try:
        from app.lawyer.config import lawyer_enabled as _le

        _on = bool(_le())
        ctx['lawyer_enabled'] = _on
        ctx['lawyer_feature_on'] = _on
    except Exception:
        ctx['lawyer_enabled'] = False
        ctx['lawyer_feature_on'] = False
    return ctx


@express_partner_bp.route('/home', methods=['GET'], endpoint='home')
@require_partner_access(allow_pending=True, allow_guest=True)
def home_page():
    """داشبورد روزانه — مرکز اقدامات فوری و فایل‌های پیشنهادی."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    payload = _build_home_dashboard_payload(me_phone, profile)
    partner_name = _partner_display_name(me_phone) if me_phone else ''
    ai_ctx = _partner_ai_layer_context(
        me_phone,
        profile=profile if isinstance(profile, dict) else None,
        has_pending_app=bool(payload.get('has_pending_app')),
    )
    ai_ctx['home_ai_empty_title'] = _home_ai_empty_title(
        is_approved=bool(payload.get('is_approved')),
        has_pending_app=bool(payload.get('has_pending_app')),
        has_completed_deal=bool(payload.get('has_completed_deal')),
    )
    ai_ctx['home_news_items'] = _home_news_headlines()

    # دادهٔ کشوی پروفایل (منوی GPT روی داشبورد)
    drawer_profile = profile if isinstance(profile, dict) else {}
    me_name = ''
    is_special = False
    referral_bonus_per_invite = 0
    is_vinor_apk = False
    show_app_update_card = False
    android_apk_url = ''
    android_apk_version = ''
    try:
        me_name = (drawer_profile.get('name') or partner_name or '').strip()
        is_approved_flag = bool(payload.get('is_approved'))
        is_special = _is_partner_special(drawer_profile) if is_approved_flag else False
        from .referrals import REFERRAL_BONUS_AMOUNT
        referral_bonus_per_invite = REFERRAL_BONUS_AMOUNT
        _settings = _express_settings_cached()
        _raw_apk_url = (_settings.get('android_apk_url') or '').strip()
        android_apk_version = (_settings.get('android_apk_version') or '').strip()
        from ..utils.short_urls import public_apk_download_url
        android_apk_url = public_apk_download_url(_settings, external=False) if _raw_apk_url else ''
        from ..utils.apk_version import (
            is_vinor_apk_request,
            resolve_android_apk_version_code,
            should_show_apk_update,
        )
        is_vinor_apk = is_vinor_apk_request(request)
        show_app_update_card = should_show_apk_update(
            android_apk_version,
            apk_url=_raw_apk_url,
            req=request,
            server_version_code=resolve_android_apk_version_code(_settings),
        )
        # اگر آپدیت لازم نیست، URL را برای کارت منو خالی بگذار (بنر نصب از context می‌آید)
        if is_vinor_apk and not show_app_update_card:
            android_apk_url = ''
    except Exception:
        pass

    # پیشنهادهای سریع خانه — هم‌راستا با تیتر خالی (مرحلهٔ کاربر)
    ai_quick_prompts: List[Dict[str, str]] = []
    try:
        from .sales_coach import build_home_ai_quick_prompts

        ai_quick_prompts = build_home_ai_quick_prompts(
            me_phone=me_phone,
            is_approved=bool(payload.get('is_approved')),
            has_pending_app=bool(payload.get('has_pending_app')),
            has_completed_deal=bool(payload.get('has_completed_deal')),
        )
        _icon_by_intent = {
            'coop_levels': 'users',
            'coop_status': 'clipboard',
            'coop_apply': 'handshake',
            'find_land': 'search',
            'marketing': 'pen',
            'next_action': 'bolt',
        }
        for _item in ai_quick_prompts:
            if not _item.get('icon'):
                _item['icon'] = _icon_by_intent.get(
                    str(_item.get('intent') or '').strip(),
                    'spark',
                )
    except Exception:
        ai_quick_prompts = []

    customer_modal_ctx: Dict[str, Any] = {
        'customer_modal_lands': [],
        'customer_modal_plus_users': [],
        'next_auto_visit': None,
    }
    try:
        customer_modal_ctx = _home_customer_modal_context(
            me_phone,
            bool(payload.get('is_approved')),
        )
    except Exception:
        pass

    public_home_lands: List[Dict[str, Any]] = []
    divar_ads_ctx: Dict[str, Any] = {}
    try:
        from .divar_pro_ads import home_divar_ads_context
        from .home_ads_config import (
            get_home_ads_settings,
            home_ads_show_divar,
            home_ads_show_vinor,
            home_ads_system_enabled,
        )

        if home_ads_system_enabled():
            cfg = get_home_ads_settings()
            divar_ads_ctx = home_divar_ads_context() or {}
            vinor_lands: List[Dict[str, Any]] = []
            if home_ads_show_vinor():
                try:
                    vinor_lands = _home_public_carousel_lands(
                        limit=int(cfg.get('vinor_limit') or 40)
                    )
                except Exception:
                    vinor_lands = []
            divar_list: List[Dict[str, Any]] = []
            if home_ads_show_divar():
                raw_divar = divar_ads_ctx.get('divar_pro_ads')
                divar_list = raw_divar if isinstance(raw_divar, list) else []
            merged_ads = _merge_home_ads_carousel(divar_list, vinor_lands)
            if merged_ads:
                vinor_n = sum(1 for a in merged_ads if str(a.get('source') or '') == 'vinor')
                divar_n = len(merged_ads) - vinor_n
                divar_ads_ctx = dict(divar_ads_ctx or {})
                divar_ads_ctx['divar_pro_ads_enabled'] = True
                divar_ads_ctx['divar_pro_ads'] = merged_ads
                divar_ads_ctx['divar_pro_ads_title'] = str(cfg.get('title') or 'آگهی‌ها')
                divar_ads_ctx['home_ads_vinor_count'] = vinor_n
                divar_ads_ctx['home_ads_divar_count'] = divar_n
            else:
                divar_ads_ctx = {
                    'divar_pro_ads_enabled': False,
                    'divar_pro_ads': [],
                    'divar_pro_ads_title': str(cfg.get('title') or 'آگهی‌ها'),
                    'divar_pro_profile_url': str(cfg.get('divar_profile_url') or ''),
                }
        else:
            divar_ads_ctx = {
                'divar_pro_ads_enabled': False,
                'divar_pro_ads': [],
                'divar_pro_ads_title': '',
                'divar_pro_profile_url': '',
            }
    except Exception:
        divar_ads_ctx = {}
    # ai_quick_prompts بعد از **ai_ctx تا با کلید هم‌نام در context بازنویسی نشود
    resp = make_response(render_template(
        'express_partner/home.html',
        profile=drawer_profile or profile,
        me_phone=me_phone,
        me_name=me_name,
        partner_name=partner_name,
        is_approved=payload.get('is_approved'),
        is_special=is_special,
        referral_bonus_per_invite=referral_bonus_per_invite,
        is_vinor_apk=is_vinor_apk,
        show_app_update_card=show_app_update_card,
        show_app_update_nav=show_app_update_card,
        android_apk_url=android_apk_url if (show_app_update_card or not is_vinor_apk) else '',
        android_apk_version=android_apk_version,
        has_pending_app=payload.get('has_pending_app'),
        urgent_actions=payload.get('urgent_actions') or [],
        suggested_files=payload.get('suggested_files') or [],
        journey_card=payload.get('journey_card'),
        withdrawable_balance=int(payload.get('withdrawable_balance') or 0),
        home_requests_pipeline_count=int(payload.get('home_requests_pipeline_count') or 0),
        hide_header=True,
        bottom_nav_active='home',
        brand='وینور',
        domain='vinor.ir',
        seo_title='داشبورد | وینور اکسپرس',
        seo_description='پنل بازاریاب فروش — از چت مشتری یا نوع فایل بفرست تا فایل مناسب معرفی شود.',
        **ai_ctx,
        ai_quick_prompts=ai_quick_prompts,
        public_home_lands=public_home_lands,
        customer_modal_lands=customer_modal_ctx.get('customer_modal_lands') or [],
        customer_modal_plus_users=customer_modal_ctx.get('customer_modal_plus_users') or [],
        next_auto_visit=customer_modal_ctx.get('next_auto_visit'),
        next_auto_visit_by_plus=customer_modal_ctx.get('next_auto_visit_by_plus') or {},
        visit_slots_by_plus=customer_modal_ctx.get('visit_slots_by_plus') or {},
        **divar_ads_ctx,
    ))
    if not me_phone:
        # مهمان هم چت محدود دارد — کش عمومی ممنوع
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
        resp.headers['Vary'] = 'Cookie'
    else:
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    _append_partner_tab_prefetch(resp)
    return resp


@express_partner_bp.get('/home/data', endpoint='home_data')
@require_partner_access(allow_pending=True, allow_guest=True)
def home_data():
    """API JSON داشبورد روزانه."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    payload = _build_home_dashboard_payload(me_phone, profile)
    payload['home_news_items'] = _home_news_headlines()
    try:
        from .sales_coach import build_home_ai_quick_prompts

        payload['ai_quick_prompts'] = build_home_ai_quick_prompts(
            me_phone=me_phone,
            is_approved=bool(payload.get('is_approved')),
            has_pending_app=bool(payload.get('has_pending_app')),
            has_completed_deal=bool(payload.get('has_completed_deal')),
        )
    except Exception:
        payload['ai_quick_prompts'] = []
    ads_out, ads_count = _home_ads_for_api()
    payload['divar_pro_ads'] = ads_out
    payload['divar_pro_ads_count'] = ads_count
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Vary'] = 'Cookie'
    return resp


def _apk_json(payload: dict, status: int = 200):
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Vary'] = 'Cookie'
    return resp, status


@express_partner_bp.get('/api/training/data', endpoint='apk_training_data')
@require_partner_access(allow_pending=True, allow_guest=True, json_response=True)
def apk_training_data():
    from .apk_native import training_payload
    return _apk_json(training_payload())


@express_partner_bp.get('/api/levels/data', endpoint='apk_levels_data')
@require_partner_access(allow_pending=True, allow_guest=True, json_response=True)
def apk_levels_data():
    from .apk_native import levels_payload, session_phone, session_profile
    return _apk_json(levels_payload(session_phone(), session_profile()))


@express_partner_bp.get('/api/invite/data', endpoint='apk_invite_data')
@require_partner_access(allow_pending=True, json_response=True)
def apk_invite_data():
    from .apk_native import invite_payload, session_phone, session_profile
    return _apk_json(invite_payload(session_phone(), session_profile()))


@express_partner_bp.get('/api/apply/data', endpoint='apk_apply_data')
@require_partner_access(allow_pending=True, json_response=True)
def apk_apply_data():
    from .apk_native import apply_payload, session_phone
    return _apk_json(apply_payload(session_phone()))


@express_partner_bp.post('/api/apply/submit', endpoint='apk_apply_submit')
@require_partner_access(allow_pending=True, json_response=True)
def apk_apply_submit():
    from .apk_native import apply_payload, session_phone
    me_phone = session_phone()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    out = create_partner_application_core(
        me_phone,
        data,
        form_ref=str(data.get('ref') or ''),
        query_ref=str(request.args.get('ref') or ''),
    )
    if out.get('already_partner'):
        return _apk_json({'ok': True, 'status': 'approved', 'message': out.get('error') or 'حساب همکاری فعال است.'})
    if out.get('already_pending'):
        payload = apply_payload(me_phone)
        payload['message'] = out.get('error') or payload.get('message') or 'درخواست فعال دارید.'
        return _apk_json(payload)
    if not out.get('ok'):
        return _apk_json({'ok': False, 'status': 'form', 'error': out.get('error') or 'ثبت ناموفق بود.'}, 400)
    if out.get('auto_approved'):
        return _apk_json({
            'ok': True,
            'status': 'approved',
            'message': out.get('message') or 'همکاری شما تأیید شد.',
        })
    payload = apply_payload(me_phone)
    payload['message'] = out.get('message') or 'درخواست ثبت شد.'
    return _apk_json(payload)


@express_partner_bp.get('/api/requests/data', endpoint='apk_requests_data')
@require_partner_access(allow_pending=True, json_response=True)
def apk_requests_data():
    from .apk_native import requests_payload, session_phone, session_profile
    tab = (request.args.get('tab') or '').strip()
    return _apk_json(requests_payload(session_phone(), session_profile(), tab))


@express_partner_bp.get('/api/listings/data', endpoint='apk_listings_data')
@require_special_partner(json_response=True)
def apk_listings_data():
    from .apk_native import listings_payload, session_phone
    return _apk_json(listings_payload(session_phone()))


@express_partner_bp.get('/api/legal/data', endpoint='apk_legal_data')
@require_partner_access(allow_pending=True, allow_guest=True, json_response=True)
def apk_legal_data():
    from .apk_native import legal_payload
    return _apk_json(legal_payload(request.args.get('doc') or 'terms'))


@express_partner_bp.route('/dashboard', methods=['GET'], endpoint='dashboard')
@require_partner_access(allow_pending=True, allow_guest=True)
def dashboard_redirect():
    """سازگاری با URL قدیمی — داشبورد جدید در /home"""
    return redirect(url_for('express_partner.home'), code=302)


@express_partner_bp.route('/files', methods=['GET'], endpoint='files')
@require_partner_access(allow_pending=True, allow_guest=True)
def files_page():
    """صفحه «فایل‌ها» حذف شد — ریدایرکت دائمی به خانه."""
    return redirect(url_for('express_partner.home'), code=301)


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


def _home_public_carousel_lands(limit: int = 50) -> List[Dict[str, Any]]:
    """فایل‌های عمومی کامل برای نوار کشویی خانه (مهمان / کاربر عادی)."""
    sanitize_land_media = None
    try:
        from ..utils.images import sanitize_land_media as _sanitize_land_media

        sanitize_land_media = _sanitize_land_media
    except Exception:
        sanitize_land_media = None

    try:
        express_lands = load_express_lands_cached() or []
    except Exception:
        express_lands = []
    express_lands = _sort_by_created_at_desc(express_lands)
    out: List[Dict[str, Any]] = []
    for land in express_lands:
        if not isinstance(land, dict):
            continue
        try:
            from .special_listings import is_admin_created_express_listing

            if is_admin_created_express_listing(land):
                continue
        except Exception:
            pass
        code = str(land.get('code') or '').strip()
        if not code:
            continue
        if _express_land_marked_sold(land):
            continue
        if str(land.get('express_status') or '').strip().lower() in ('closed', 'archived', 'hidden'):
            continue
        try:
            from app.utils.iran_cities import land_in_service_focus

            if not land_in_service_focus(land):
                continue
        except Exception:
            pass
        item = dict(land)
        item['_assignment_status'] = 'public'
        item['_in_transaction'] = False
        item['_is_public'] = True
        try:
            from .new_land_sms import attach_express_land_commission

            attach_express_land_commission(item)
        except Exception:
            item.setdefault('_commission_pct', 0)
            item.setdefault('_commission_amount', 0)
        try:
            item['_detail_url'] = url_for('express_partner.land_detail', code=code)
        except Exception:
            item['_detail_url'] = f'/express/partner/lands/{code}'
        if sanitize_land_media is not None:
            try:
                out.append(sanitize_land_media(item))
            except Exception:
                out.append(item)
        else:
            out.append(item)
        if len(out) >= max(1, int(limit or 50)):
            break
    return out


def _format_home_ad_price_toman(amount: Any) -> str:
    try:
        num = int(float(amount or 0))
    except Exception:
        return ''
    if num <= 0:
        return ''
    try:
        grouped = f'{num:,}'.replace(',', '،').translate(
            str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
        )
        return f'{grouped} تومان'
    except Exception:
        return f'{num} تومان'


def _vinor_land_to_home_ad(land: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """نرمال‌سازی فایل داخلی وینور به شکل کارت نوار آگهی‌ها."""
    if not isinstance(land, dict):
        return None
    code = str(land.get('code') or '').strip()
    if not code:
        return None
    title = str(land.get('title') or '').strip() or 'فایل وینور'
    try:
        price_n = int(land.get('price_total') or land.get('price') or 0)
    except Exception:
        price_n = 0
    city = str(land.get('city') or '').strip()
    location = str(land.get('location') or '').strip()
    loc_parts = [p for p in (city, location) if p]
    images = land.get('images') if isinstance(land.get('images'), list) else []
    image_url = ''
    try:
        from ..utils.images import partner_card_image_url

        image_url = str(partner_card_image_url(land) or '').strip()
    except Exception:
        image_url = ''
    if not image_url and images:
        raw0 = str(images[0] or '').strip()
        if raw0.startswith('http://') or raw0.startswith('https://') or raw0.startswith('/'):
            image_url = raw0
        elif raw0:
            image_url = '/uploads/' + raw0.lstrip('/')
    detail = str(land.get('_detail_url') or '').strip()
    if not detail:
        try:
            detail = url_for('express_partner.land_detail', code=code)
        except Exception:
            detail = f'/express/partner/lands/{code}'
    try:
        from .new_land_sms import attach_express_land_commission

        attach_express_land_commission(land)
    except Exception:
        pass
    try:
        commission_amount = int(land.get('_commission_amount') or 0)
    except Exception:
        commission_amount = 0
    return {
        'token': code,
        'title': title,
        'price': _format_home_ad_price_toman(price_n),
        'location': '، '.join(loc_parts),
        'image_url': image_url,
        'badge': 'وینور',
        'image_count': len(images),
        'url': detail,
        'source': 'vinor',
        'external': False,
        'commission_amount': max(0, commission_amount),
        'commission_pct': land.get('_commission_pct') or 0,
    }


def _home_ads_for_api() -> tuple:
    """همان ادغام آگهی خانهٔ وب — برای JSON اپ."""
    ads: List[Dict[str, Any]] = []
    try:
        from .divar_pro_ads import home_divar_ads_context
        from .home_ads_config import (
            get_home_ads_settings,
            home_ads_show_divar,
            home_ads_show_vinor,
            home_ads_system_enabled,
        )

        if not home_ads_system_enabled():
            return [], 0
        cfg = get_home_ads_settings() or {}
        divar_ads_ctx = home_divar_ads_context() or {}
        vinor_lands: List[Dict[str, Any]] = []
        if home_ads_show_vinor():
            try:
                vinor_lands = _home_public_carousel_lands(
                    limit=int(cfg.get('vinor_limit') or 40)
                )
            except Exception:
                vinor_lands = []
        divar_list: List[Dict[str, Any]] = []
        if home_ads_show_divar():
            raw = divar_ads_ctx.get('divar_pro_ads')
            divar_list = raw if isinstance(raw, list) else []
        ads = _merge_home_ads_carousel(divar_list, vinor_lands)
    except Exception:
        ads = []
    out: List[Dict[str, Any]] = []
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        try:
            image_count = int(ad.get('image_count') or 0)
        except Exception:
            image_count = 0
        try:
            commission_amount = int(ad.get('commission_amount') or 0)
        except Exception:
            commission_amount = 0
        out.append({
            'title': str(ad.get('title') or '').strip(),
            'price': str(ad.get('price') or '').strip(),
            'location': str(ad.get('location') or '').strip(),
            'image_url': str(ad.get('image_url') or '').strip(),
            'image_count': image_count,
            'token': str(ad.get('token') or '').strip(),
            'source': str(ad.get('source') or '').strip(),
            'url': str(ad.get('url') or '').strip(),
            'commission_amount': max(0, commission_amount),
        })
    return out, len(out)


def _merge_home_ads_carousel(
    divar_ads: List[Dict[str, Any]],
    vinor_lands: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """وینور اول، سپس دیوار — بدون تکرار توکن/کد."""
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from .home_ads_config import (
            attach_divar_ad_commission,
            divar_commission_pct_by_profile_url,
        )

        _divar_pct_map = divar_commission_pct_by_profile_url()
    except Exception:
        attach_divar_ad_commission = None  # type: ignore[assignment]
        _divar_pct_map = {}
    for land in vinor_lands or []:
        ad = _vinor_land_to_home_ad(land)
        if not ad:
            continue
        key = f"vinor:{ad['token']}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(ad)
    for raw in divar_ads or []:
        if not isinstance(raw, dict):
            continue
        ad = dict(raw)
        tok = str(ad.get('token') or '').strip()
        key = f"divar:{tok}" if tok else f"divar:{ad.get('url') or id(ad)}"
        if key in seen:
            continue
        seen.add(key)
        ad.setdefault('source', 'divar')
        if not str(ad.get('badge') or '').strip():
            ad['badge'] = 'دیوار'
        public_url = str(ad.get('divar_url') or ad.get('url') or '').strip()
        if tok and (not public_url or 'divar.ir' not in public_url):
            public_url = f'https://divar.ir/v/{tok}'
        ad['divar_url'] = public_url
        if tok:
            try:
                ad['url'] = url_for('express_partner.divar_ad_detail', token=tok)
            except Exception:
                ad['url'] = f'/express/partner/divar/{tok}'
            ad['external'] = False
        else:
            ad.setdefault('external', True)
        if attach_divar_ad_commission is not None:
            try:
                attach_divar_ad_commission(ad, _divar_pct_map)
            except Exception:
                ad.setdefault('commission_amount', 0)
                ad.setdefault('commission_pct', 0)
        else:
            ad.setdefault('commission_amount', 0)
            ad.setdefault('commission_pct', 0)
        merged.append(ad)
    return merged


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


def _crm_ui_or_404():
    """Gate CRM partner UI behind feature flags (default ON)."""
    try:
        from app.crm.config import crm_ui_enabled
        if crm_ui_enabled():
            return None
    except Exception:
        pass
    from flask import abort
    abort(404)


@express_partner_bp.get('/customers', endpoint='customers')
@require_partner_access()
def customers_page():
    """Phase 1 CRM — مشتریان من (فلگ VINOR_CRM_* پیش‌فرض ON)."""
    _crm_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.crm.config import VISIT_CALL_TARGET
    from .customers import partner_customers_view

    flash_msg = (request.args.get('msg') or '').strip()
    flash_ok = (request.args.get('ok') or '1').strip() != '0'
    return render_template(
        'express_partner/customers.html',
        me_phone=me_phone,
        customers=partner_customers_view(me_phone),
        visit_call_target=VISIT_CALL_TARGET,
        flash_msg=flash_msg,
        flash_ok=flash_ok,
        hide_header=True,
        bottom_nav_active='profile',
    )


@express_partner_bp.post('/customers', endpoint='customers_create')
@require_partner_access()
def customers_create():
    _crm_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.crm.service import upsert_contact
    from app.services.sms import normalize_iran_mobile

    first = (request.form.get('first_name') or '').strip()
    last = (request.form.get('last_name') or '').strip()
    phone_raw = (request.form.get('customer_phone') or '').strip()
    phone = normalize_iran_mobile(phone_raw) or phone_raw
    if not first or not last or not phone:
        return redirect(url_for('express_partner.customers', ok=0, msg='نام و شماره الزامی است.'))
    rec = upsert_contact(
        partner_phone=me_phone,
        customer_phone=phone,
        first_name=first,
        last_name=last,
        source='manual',
    )
    if not rec:
        return redirect(url_for('express_partner.customers', ok=0, msg='ثبت مشتری ممکن نشد.'))
    return redirect(url_for('express_partner.customers', ok=1, msg='مشتری ذخیره شد.'))


@express_partner_bp.post('/customers/<contact_id>/calls', endpoint='customers_log_call')
@require_partner_access()
def customers_log_call(contact_id: str):
    _crm_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.crm.config import VISIT_CALL_TARGET
    from app.crm.service import get_contact, log_call

    contact = get_contact(contact_id)
    me_n = normalize_iran_mobile(me_phone) or me_phone
    owner = normalize_iran_mobile(contact.partner_phone) if contact else ""
    if not contact or owner != me_n:
        return redirect(url_for('express_partner.customers', ok=0, msg='مشتری یافت نشد.'))
    outcome = (request.form.get('outcome') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    to_number = (request.form.get('to_number') or '').strip() or VISIT_CALL_TARGET
    call = log_call(
        partner_phone=me_phone,
        contact_id=contact_id,
        outcome=outcome,
        notes=notes,
        to_number=to_number,
    )
    if not call:
        return redirect(url_for('express_partner.customers', ok=0, msg='ثبت تماس ممکن نشد.'))
    return redirect(url_for('express_partner.customers', ok=1, msg='تماس ثبت شد.'))


@express_partner_bp.post('/customers/<contact_id>/followups', endpoint='customers_followup')
@require_partner_access()
def customers_followup(contact_id: str):
    _crm_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.crm.service import get_contact, schedule_followup

    contact = get_contact(contact_id)
    me_n = normalize_iran_mobile(me_phone) or me_phone
    owner = normalize_iran_mobile(contact.partner_phone) if contact else ""
    if not contact or owner != me_n:
        return redirect(url_for('express_partner.customers', ok=0, msg='مشتری یافت نشد.'))
    due_at = (request.form.get('due_at') or '').strip()
    notes = (request.form.get('notes') or '').strip()
    fu = schedule_followup(
        partner_phone=me_phone,
        contact_id=contact_id,
        due_at=due_at,
        notes=notes,
    )
    if not fu:
        return redirect(url_for('express_partner.customers', ok=0, msg='ثبت پیگیری ممکن نشد.'))
    return redirect(url_for('express_partner.customers', ok=1, msg='پیگیری ثبت شد.'))


def _commercial_ui_or_404():
    try:
        from app.commercial.config import commercial_ui_enabled
        if commercial_ui_enabled():
            return None
    except Exception:
        pass
    from flask import abort
    abort(404)


@express_partner_bp.get('/negotiations', endpoint='negotiations')
@require_partner_access()
def negotiations_page():
    """صفحهٔ قدیمی مذاکرات — گزارش زنده جایگزین شده."""
    return redirect(url_for('express_partner.home'))


@express_partner_bp.post('/negotiations', endpoint='negotiations_create')
@require_partner_access()
def negotiations_create():
    _commercial_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.commercial.service import propose_offer

    land_code = (request.form.get('land_code') or '').strip()
    buyer_phone = (request.form.get('buyer_phone') or '').strip()
    terms = (request.form.get('terms') or '').strip()
    try:
        amount = int(request.form.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    offer = propose_offer(
        land_code=land_code,
        partner_phone=me_phone,
        buyer_phone=buyer_phone,
        amount=amount,
        terms=terms,
        proposed_by='partner',
    )
    if not offer:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='ثبت پیشنهاد ممکن نشد.'))
    return redirect(url_for('express_partner.negotiations', ok=1, msg='پیشنهاد ثبت شد.'))


@express_partner_bp.post('/offers/<offer_id>/respond', endpoint='offer_respond')
@require_partner_access()
def offer_respond(offer_id: str):
    _commercial_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.commercial.service import get_offer, respond_offer
    from app.services.sms import normalize_iran_mobile as _norm

    offer = get_offer(offer_id)
    if not offer or _norm(offer.partner_phone) != (_norm(me_phone) or me_phone):
        return redirect(url_for('express_partner.negotiations', ok=0, msg='پیشنهاد یافت نشد.'))
    action = (request.form.get('action') or '').strip().lower()
    out = respond_offer(offer_id, action=action, actor_key=me_phone)
    if not out:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='پاسخ نامعتبر بود.'))
    return redirect(url_for('express_partner.negotiations', ok=1, msg='وضعیت پیشنهاد به‌روز شد.'))


@express_partner_bp.post('/offers/<offer_id>/counter', endpoint='offer_counter')
@require_partner_access()
def offer_counter(offer_id: str):
    _commercial_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.commercial.service import get_offer, propose_counter

    offer = get_offer(offer_id)
    if not offer:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='پیشنهاد یافت نشد.'))
    try:
        amount = int(request.form.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    terms = (request.form.get('terms') or '').strip()
    counter = propose_counter(
        offer_id=offer_id,
        amount=amount,
        terms=terms,
        proposed_by='partner',
        actor_key=me_phone,
    )
    if not counter:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='ثبت پیشنهاد متقابل ممکن نشد.'))
    return redirect(url_for('express_partner.negotiations', ok=1, msg='پیشنهاد متقابل ثبت شد.'))


@express_partner_bp.post('/offers/<offer_id>/reserve', endpoint='offer_reserve')
@require_partner_access()
def offer_reserve(offer_id: str):
    _commercial_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.commercial.service import hold_reservation

    res = hold_reservation(offer_id=offer_id, actor_key=me_phone)
    if not res:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='رزرو نرم ممکن نشد.'))
    return redirect(url_for('express_partner.negotiations', ok=1, msg='رزرو نرم ثبت شد (بدون قفل assignment).'))


@express_partner_bp.post('/reservations/<reservation_id>/release', endpoint='reservation_release')
@require_partner_access()
def reservation_release(reservation_id: str):
    _commercial_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.commercial.service import release_reservation

    out = release_reservation(reservation_id, actor_key=me_phone)
    if not out:
        return redirect(url_for('express_partner.negotiations', ok=0, msg='آزادسازی ممکن نشد.'))
    return redirect(url_for('express_partner.negotiations', ok=1, msg='رزرو آزاد شد.'))


def _closing_ui_or_404():
    try:
        from app.closing.config import closing_ui_enabled
        if closing_ui_enabled():
            return None
    except Exception:
        pass
    from flask import abort
    abort(404)


@express_partner_bp.get('/deals', endpoint='deals')
@require_partner_access()
def deals_page():
    """صفحهٔ قدیمی معاملات — ادغام در پیگیری."""
    return redirect(_sales_pipeline_url('deals'))


@express_partner_bp.post('/deals/<deal_id>/contracts', endpoint='deal_contract_create')
@require_partner_access()
def deal_contract_create(deal_id: str):
    _closing_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.closing.service import create_contract, get_deal

    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != me_phone:
        return redirect(url_for('express_partner.deals', ok=0, msg='معامله یافت نشد.'))
    title = (request.form.get('title') or '').strip()
    document_ref = (request.form.get('document_ref') or '').strip()
    contract = create_contract(
        deal_id=deal.id,
        title=title,
        document_ref=document_ref,
        actor_key=me_phone,
    )
    if contract is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='ثبت قرارداد ممکن نشد.'))
    return redirect(url_for('express_partner.deals', ok=1, msg='قرارداد ثبت شد.'))


@express_partner_bp.post('/contracts/<contract_id>/document', endpoint='contract_document_update')
@require_partner_access()
def contract_document_update(contract_id: str):
    _closing_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.closing.service import get_contract, get_deal, update_contract_document

    contract = get_contract(contract_id)
    if contract is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='قرارداد یافت نشد.'))
    deal = get_deal(contract.deal_id)
    if deal is None or deal.partner_phone != me_phone:
        return redirect(url_for('express_partner.deals', ok=0, msg='دسترسی غیرمجاز.'))
    document_status = (request.form.get('document_status') or '').strip()
    document_ref = (request.form.get('document_ref') or '').strip()
    updated = update_contract_document(
        contract_id,
        document_status=document_status,
        document_ref=document_ref,
        actor_key=me_phone,
    )
    if updated is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='به‌روزرسانی قرارداد ممکن نشد.'))
    return redirect(url_for('express_partner.deals', ok=1, msg='وضعیت سند به‌روز شد.'))


@express_partner_bp.post('/deals/<deal_id>/payments', endpoint='deal_payment_create')
@require_partner_access()
def deal_payment_create(deal_id: str):
    _closing_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.closing.service import add_payment, get_deal

    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != me_phone:
        return redirect(url_for('express_partner.deals', ok=0, msg='معامله یافت نشد.'))
    try:
        amount = int(str(request.form.get('amount') or '0').replace(',', '').strip() or '0')
    except Exception:
        amount = 0
    milestone_label = (request.form.get('milestone_label') or '').strip()
    due_at = (request.form.get('due_at') or '').strip()
    contract_id = (request.form.get('contract_id') or '').strip()
    pay = add_payment(
        deal_id=deal.id,
        amount=amount,
        contract_id=contract_id,
        due_at=due_at,
        milestone_label=milestone_label,
        actor_key=me_phone,
    )
    if pay is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='ثبت قسط ممکن نشد.'))
    return redirect(url_for('express_partner.deals', ok=1, msg='قسط ثبت شد.'))


@express_partner_bp.post('/payments/<payment_id>/mark-paid', endpoint='payment_mark_paid')
@require_partner_access()
def payment_mark_paid(payment_id: str):
    _closing_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.closing.service import get_deal, get_payment, mark_payment_paid

    pay = get_payment(payment_id)
    if pay is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='قسط یافت نشد.'))
    deal = get_deal(pay.deal_id)
    if deal is None or deal.partner_phone != me_phone:
        return redirect(url_for('express_partner.deals', ok=0, msg='دسترسی غیرمجاز.'))
    updated = mark_payment_paid(payment_id, actor_key=me_phone)
    if updated is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='ثبت پرداخت ممکن نشد.'))
    return redirect(url_for('express_partner.deals', ok=1, msg='قسط پرداخت‌شده علامت خورد.'))


@express_partner_bp.post('/deals/<deal_id>/settlements', endpoint='deal_settlement_create')
@require_partner_access()
def deal_settlement_create(deal_id: str):
    _closing_ui_or_404()
    me_phone = (session.get('user_phone') or '').strip()
    from app.closing.service import get_deal, open_settlement

    deal = get_deal(deal_id)
    if deal is None or deal.partner_phone != me_phone:
        return redirect(url_for('express_partner.deals', ok=0, msg='معامله یافت نشد.'))
    try:
        partner_amount = int(str(request.form.get('partner_amount') or '0').replace(',', '').strip() or '0')
    except Exception:
        partner_amount = 0
    withdrawal_id = (request.form.get('withdrawal_id') or '').strip()
    parties = []
    if partner_amount > 0:
        parties.append({'role': 'partner', 'amount': partner_amount, 'phone': me_phone, 'label': 'پورسانت همکار'})
    settlement = open_settlement(
        deal_id=deal.id,
        parties=parties,
        withdrawal_id=withdrawal_id,
        total_amount=partner_amount,
        actor_key=me_phone,
    )
    if settlement is None:
        return redirect(url_for('express_partner.deals', ok=0, msg='ثبت تسویه ممکن نشد.'))
    return redirect(url_for('express_partner.deals', ok=1, msg='تسویه باز شد (لینک اختیاری به برداشت موجود).'))


def _integration_ui_or_404():
    try:
        from app.integration.config import integration_ui_enabled
        if integration_ui_enabled():
            return None
    except Exception:
        pass
    from flask import abort
    abort(404)


@express_partner_bp.get('/journey', endpoint='journey')
@require_partner_access()
def journey_page():
    """صفحهٔ قدیمی مسیر معامله — گزارش زنده جایگزین شده."""
    return redirect(url_for('express_partner.home'))


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
    from .apk_native import land_card
    items = [land_card(item) for item in lands]
    return jsonify({
        'ok': True,
        'html': html,
        'count': len(lands),
        'requested': len(codes),
        'valid_codes': valid_codes,
        'items': items,
        'is_approved': is_approved,
    })


def _sales_pipeline_url(tab: str = 'requests', **extra):
    """صفحهٔ یکپارچهٔ پیگیری: درخواست / بازدید / معامله."""
    from .visit_requests import PIPELINE_TABS

    kwargs = dict(extra)
    t = str(tab or '').strip().lower()
    if t in PIPELINE_TABS:
        kwargs['tab'] = t
    return url_for('express_partner.requests', **kwargs)


@express_partner_bp.get('/requests', endpoint='requests')
@require_partner_access(allow_pending=True)
def requests_page():
    """پیگیری فروش — درخواست، بازدید و معامله در یک صفحه."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    from .partner_roles import partner_coop_level
    from .visit_requests import (
        PIPELINE_DEALS,
        PIPELINE_REQUESTS,
        PIPELINE_TABS,
        PIPELINE_VISITS,
    )

    pipe = _build_partner_sales_pipeline(me_phone, profile)
    items = pipe['items']
    inbox_items = pipe['inbox_items']
    offers = pipe['offers']
    tab_counts = pipe['tab_counts']
    open_count = pipe['open_count']
    is_approved = pipe['is_approved']
    is_special = pipe['is_special']
    support_phone = pipe['support_phone']
    allow_attendance = pipe['allow_attendance']
    visit_weekday_labels = pipe['visit_weekday_labels']
    visit_weekday_order = pipe['visit_weekday_order']
    visit_allowed_weekdays = pipe['visit_allowed_weekdays']
    visit_hour_rows_data = pipe['visit_hour_rows_data']
    visit_allowed_weekdays_summary = pipe['visit_allowed_weekdays_summary']
    visit_allowed_hours_summary = pipe['visit_allowed_hours_summary']
    visit_presence_address = pipe['visit_presence_address']

    inbox_needs = sum(1 for i in inbox_items if i.get('needs_action')) + len(offers)
    inbox_visit_count = sum(
        1
        for i in inbox_items
        if str(i.get('pipeline_tab') or PIPELINE_VISITS) == PIPELINE_VISITS
    )
    requested_tab = str(request.args.get('tab') or '').strip().lower()
    if requested_tab not in PIPELINE_TABS:
        deal_needs = any(
            i.get('can_approve_deal') or i.get('can_start_deal') or i.get('can_confirm_deal')
            for i in inbox_items
        )
        inbox_action = any(
            i.get('needs_action') and str(i.get('pipeline_tab') or PIPELINE_VISITS) == PIPELINE_VISITS
            for i in inbox_items
        )
        if is_special and deal_needs:
            requested_tab = PIPELINE_DEALS
        elif is_special and (inbox_action or inbox_visit_count):
            requested_tab = PIPELINE_VISITS
        else:
            requested_tab = PIPELINE_REQUESTS

    resp = make_response(render_template(
        'express_partner/requests.html',
        items=items,
        inbox_items=inbox_items,
        offers=offers,
        tab_counts=tab_counts,
        active_tab=requested_tab,
        open_count=open_count,
        inbox_needs=inbox_needs,
        support_phone=support_phone,
        me_phone=me_phone,
        is_approved=is_approved,
        is_special=is_special,
        coop_level=partner_coop_level(profile),
        can_record_attendance=allow_attendance,
        hide_header=True,
        brand='وینور',
        domain='vinor.ir',
        visit_weekday_labels=visit_weekday_labels,
        visit_weekday_order=visit_weekday_order,
        visit_allowed_weekdays=visit_allowed_weekdays,
        visit_hour_rows=visit_hour_rows_data,
        visit_allowed_weekdays_summary=visit_allowed_weekdays_summary,
        visit_allowed_hours_summary=visit_allowed_hours_summary,
        visit_presence_address=visit_presence_address,
        schedule_open=(request.args.get('schedule') or '').strip() == '1',
    ))
    if is_approved:
        _append_partner_tab_prefetch(resp)
    return resp


def _requests_action_json(ok: bool, *, message: str = '', error: str = '', **extra):
    payload = {'ok': bool(ok), 'message': message, 'error': error}
    payload.update(extra)
    return jsonify(payload), (200 if ok else 400)


@express_partner_bp.post('/requests/<vid>/remove', endpoint='requests_remove')
@require_partner_access()
def requests_remove(vid: str):
    """لغو درخواست باز یا حذف قطعی درخواست لغو/عدم‌حضور/انجام‌شده."""
    me_phone = (session.get('user_phone') or '').strip()
    from .visit_requests import partner_cancel_own_visit, partner_delete_own_visit

    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []

    updated, err = partner_cancel_own_visit(
        visit_rows, request_id=str(vid or ''), partner_phone=me_phone
    )
    if updated and not err:
        try:
            save_express_visit_requests(visit_rows)
        except Exception:
            current_app.logger.exception('requests_remove cancel save failed id=%s', vid)
            return _requests_action_json(False, error='ذخیره نشد.')
        try:
            from .visit_sms import notify_partner_land_tx_sms
            notify_partner_land_tx_sms(
                partner_phone=me_phone,
                event='visit_rejected',
                land_code=str(updated.get('land_code') or ''),
                land_title=str(updated.get('land_title') or ''),
                visit_date=str(updated.get('visit_date') or ''),
                reference_id=str(updated.get('id') or ''),
            )
        except Exception:
            pass
        return _requests_action_json(True, message='درخواست حذف شد.', action='cancelled')

    if err in (None, 'not_cancellable'):
        ok, derr = partner_delete_own_visit(
            visit_rows, request_id=str(vid or ''), partner_phone=me_phone
        )
        if ok:
            try:
                save_express_visit_requests(visit_rows)
            except Exception:
                current_app.logger.exception('requests_remove delete save failed id=%s', vid)
                return _requests_action_json(False, error='ذخیره نشد.')
            return _requests_action_json(True, message='از لیست حذف شد.', action='deleted')
        err = derr or err

    msg = {
        'not_cancellable': 'این درخواست قابل حذف نیست.',
        'not_deletable': 'این درخواست قابل حذف نیست.',
        'forbidden': 'دسترسی ندارید.',
        'not_found': 'درخواست پیدا نشد.',
        'invalid': 'درخواست نامعتبر است.',
    }.get(err or '', 'حذف انجام نشد.')
    return _requests_action_json(False, error=msg)


@express_partner_bp.post('/requests/<vid>/revisit', endpoint='requests_revisit')
@require_partner_access()
def requests_revisit(vid: str):
    """ثبت بازدید مجدد با زمان‌بندی خودکار روی همان فایل."""
    me_phone = (session.get('user_phone') or '').strip()
    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get('phone')) == me_phone), None)
    try:
        is_pa = _is_partner_approved(partner_profile)
    except Exception:
        is_pa = False
    if not is_pa:
        return _requests_action_json(False, error='حساب همکاری تأیید نشده است.')

    from .visit_requests import (
        COMPLETED_STATUS,
        CANCELLED_STATUS,
        NO_SHOW_STATUS,
        create_visit_request as record_visit_request,
        next_auto_visit_date,
        partner_can_request_new_visit,
        partner_cancel_own_visit,
        partner_requests_can_revisit,
    )

    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []

    prev = None
    rid = str(vid or '').strip()
    for r in visit_rows:
        if isinstance(r, dict) and str(r.get('id') or '').strip() == rid:
            prev = r
            break
    if not prev or str(prev.get('partner_phone') or '').strip() != me_phone:
        return _requests_action_json(False, error='درخواست پیدا نشد.')

    land_code = str(prev.get('land_code') or '').strip()
    if not land_code:
        return _requests_action_json(False, error='فایل مرتبط پیدا نشد.')

    lands, _ = _build_partner_dashboard_lands(me_phone, True)
    land = next((L for L in (lands or []) if str(L.get('code') or '') == land_code), None)
    if land is None:
        return _requests_action_json(False, error='فایل در دسترس نیست.')
    gs = str(land.get('_assignment_status') or '').strip().lower()
    if not partner_requests_can_revisit(
        prev,
        assignment_status=gs,
        visit_requests=visit_rows,
        phone=me_phone,
    ):
        return _requests_action_json(False, error='برای این مورد بازدید مجدد ممکن نیست.')

    st = str(prev.get('status') or '').strip()
    past_open = st not in (COMPLETED_STATUS, CANCELLED_STATUS, NO_SHOW_STATUS)
    if past_open:
        closed, cerr = partner_cancel_own_visit(
            visit_rows, request_id=rid, partner_phone=me_phone
        )
        if not closed:
            return _requests_action_json(
                False,
                error={
                    'not_cancellable': 'این درخواست قابل بستن نیست.',
                    'forbidden': 'دسترسی ندارید.',
                    'not_found': 'درخواست پیدا نشد.',
                }.get(cerr or '', 'بازدید قبلی بسته نشد.'),
            )

    if not partner_can_request_new_visit(gs, visit_rows, me_phone, land_code):
        return _requests_action_json(False, error='الان امکان بازدید مجدد نیست.')

    next_slot = next_auto_visit_date(
        plus_user_phone=str(prev.get('plus_user_phone') or ''),
    )
    if not next_slot or not next_slot.get('iso'):
        return _requests_action_json(False, error='روز مجاز بازدید پیدا نشد.')

    land_title = str(land.get('title') or prev.get('land_title') or land_code)
    partner_name = (partner_profile.get('name') if partner_profile else None) or me_phone
    rec, err = record_visit_request(
        visit_rows,
        partner_phone=me_phone,
        partner_name=partner_name,
        land_code=land_code,
        land_title=land_title,
        visit_date=str(next_slot.get('iso') or ''),
        visit_time=str(next_slot.get('time_en') or next_slot.get('time') or ''),
        customer_first_name=str(prev.get('customer_first_name') or ''),
        customer_last_name=str(prev.get('customer_last_name') or ''),
        customer_phone=str(prev.get('customer_phone') or ''),
        notes=str(prev.get('notes') or ''),
        require_customer=False,
        plus_user_phone=str(prev.get('plus_user_phone') or ''),
        plus_user_name=str(prev.get('plus_user_name') or ''),
    )
    if err == 'already_pending':
        return _requests_action_json(False, error='برای این فایل بازدید باز دارید.')
    if err in ('no_hours', 'hour_not_allowed', 'weekday_not_allowed'):
        return _requests_action_json(False, error='وقت مجاز بازدید برای ثبت مجدد پیدا نشد.')
    if err or not rec:
        return _requests_action_json(False, error='ثبت بازدید مجدد ممکن نشد.')

    try:
        save_express_visit_requests(visit_rows)
    except Exception:
        current_app.logger.exception('requests_revisit save failed id=%s', vid)
        return _requests_action_json(False, error='ذخیره نشد.')

    try:
        _send_visit_schedule_admin_sms(
            partner_phone=me_phone,
            partner_name=partner_name,
            notes=str(prev.get('notes') or ''),
            presence_address=str(rec.get('visit_presence_address') or prev.get('visit_presence_address') or ''),
        )
    except Exception:
        pass
    try:
        _send_visit_schedule_partner_sms(
            partner_phone=me_phone,
            partner_name=partner_name,
            weekday=str(next_slot.get('weekday') or ''),
            jalali_date=str(next_slot.get('jalali_fa') or next_slot.get('jalali') or ''),
            visit_time=str(next_slot.get('time') or next_slot.get('time_en') or '').strip(),
            presence_address=str(rec.get('visit_presence_address') or ''),
            plus_user_phone=str(rec.get('plus_user_phone') or prev.get('plus_user_phone') or ''),
            plus_user_name=str(rec.get('plus_user_name') or prev.get('plus_user_name') or ''),
            land_code=str(rec.get('land_code') or prev.get('land_code') or ''),
        )
    except Exception:
        pass

    label = f"{next_slot.get('weekday') or ''} {next_slot.get('jalali_fa') or ''}".strip()
    time_bit = str(next_slot.get('time') or rec.get('visit_time') or '').strip()
    if time_bit:
        label = f"{label} ساعت {time_bit}".strip()
    return _requests_action_json(
        True,
        message=f'بازدید مجدد ثبت شد{(" — " + label) if label else ""}.',
        visit_id=rec.get('id'),
    )


@express_partner_bp.post('/requests/<vid>/complete', endpoint='requests_complete_visit')
@require_partner_access()
def requests_complete_visit(vid: str):
    """ویزیتور: ثبت «بازدید انجام شد» از کارت پیگیری."""
    return _partner_visit_attendance_action(vid, outcome='done')


@express_partner_bp.post('/requests/<vid>/no-show', endpoint='requests_no_show_visit')
@require_partner_access()
def requests_no_show_visit(vid: str):
    """ویزیتور: ثبت عدم حضور از کارت پیگیری."""
    return _partner_visit_attendance_action(vid, outcome='no_show')


@express_partner_bp.post('/requests/<vid>/visit-result', endpoint='requests_visit_result')
@require_partner_access()
def requests_visit_result(vid: str):
    """ثبت نتیجه بازدید: علاقه‌مند / پیگیری دوباره / بی‌علاقه."""
    me_phone = (session.get('user_phone') or '').strip()
    from .partner_roles import partner_can_manage_deal
    from .visit_requests import record_visit_outcome, visit_outcome_hint, visit_outcome_label

    profile = getattr(g, 'express_partner_profile', None)
    if not partner_can_manage_deal(profile):
        return _requests_action_json(
            False,
            error='ثبت نتیجه بازدید فقط برای ویزیتور و پلاس فعال است.',
        )
    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []
    rec = next(
        (r for r in visit_rows if isinstance(r, dict) and str(r.get('id') or '') == str(vid or '')),
        None,
    )
    if not rec:
        return _requests_action_json(False, error='درخواست پیدا نشد.')
    if str(rec.get('partner_phone') or '').strip() != me_phone:
        return _requests_action_json(False, error='دسترسی ندارید.')
    body = request.get_json(silent=True) if request.is_json else None
    if not isinstance(body, dict):
        body = {}
    outcome = str(request.form.get('outcome') or body.get('outcome') or '').strip()
    notes = str(request.form.get('notes') or body.get('notes') or '').strip()
    updated, err = record_visit_outcome(
        visit_rows, str(vid), outcome=outcome, notes=notes, actor_phone=me_phone
    )
    if err == 'invalid_status':
        return _requests_action_json(False, error='اول «بازدید انجام شد» را ثبت کنید.')
    if err == 'invalid_outcome':
        return _requests_action_json(False, error='یکی از سه نتیجه را انتخاب کنید.')
    if err or not updated:
        return _requests_action_json(False, error='ثبت نتیجه ممکن نشد.')
    try:
        save_express_visit_requests(visit_rows)
    except Exception:
        current_app.logger.exception('visit outcome save failed id=%s', vid)
        return _requests_action_json(False, error='ذخیره نشد.')
    try:
        from .special_visit_inbox import inject_visit_outcome_chat

        inject_visit_outcome_chat(updated, outcome=outcome)
    except Exception:
        current_app.logger.exception('visit outcome chat failed id=%s', vid)
    label = visit_outcome_label(outcome) or 'ثبت شد'
    hint = visit_outcome_hint(outcome)
    msg = f'{label} ثبت شد.' + (f' {hint}' if hint else '')
    wants_html = (request.headers.get('X-Requested-With') or '') != 'XMLHttpRequest' and not request.is_json
    if wants_html:
        flash(msg, 'success')
        return redirect(_sales_pipeline_url('deals' if outcome == 'interested' else 'requests'))
    return _requests_action_json(True, message=msg, visit_id=updated.get('id'), status=updated.get('status'))


@express_partner_bp.post('/requests/<vid>/deal-confirm', endpoint='requests_confirm_deal')
@require_partner_access()
def requests_confirm_deal(vid: str):
    return _partner_deal_decision_action(vid, decision='approved')


@express_partner_bp.post('/requests/<vid>/deal-reject', endpoint='requests_reject_deal')
@require_partner_access()
def requests_reject_deal(vid: str):
    return _partner_deal_decision_action(vid, decision='rejected')


@express_partner_bp.post('/requests/<vid>/deal-close', endpoint='requests_close_deal')
@require_partner_access()
def requests_close_deal(vid: str):
    return _partner_deal_decision_action(vid, decision='closed')


def _partner_deal_decision_action(vid: str, *, decision: str):
    me_phone = (session.get('user_phone') or '').strip()
    from .partner_roles import partner_can_manage_deal
    from .visit_requests import record_visit_deal_decision

    profile = getattr(g, 'express_partner_profile', None)
    if not partner_can_manage_deal(profile):
        return _requests_action_json(
            False,
            error='تأیید و بستن معامله فقط برای ویزیتور و پلاس فعال است.',
        )
    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []
    rec = next(
        (r for r in visit_rows if isinstance(r, dict) and str(r.get('id') or '') == str(vid or '')),
        None,
    )
    if not rec:
        return _requests_action_json(False, error='درخواست پیدا نشد.')
    if str(rec.get('partner_phone') or '').strip() != me_phone:
        return _requests_action_json(False, error='دسترسی ندارید.')
    updated, err = record_visit_deal_decision(
        visit_rows, str(vid), decision=decision, actor_phone=me_phone
    )
    if err == 'already_decided':
        return _requests_action_json(False, error='برای این پرونده قبلاً تصمیم ثبت شده است.')
    if err == 'invalid_status':
        return _requests_action_json(False, error='این پرونده الان در مرحله معامله نیست.')
    if err or not updated:
        return _requests_action_json(False, error='ثبت تصمیم ممکن نشد.')
    try:
        save_express_visit_requests(visit_rows)
    except Exception:
        current_app.logger.exception('deal decision save failed id=%s', vid)
        return _requests_action_json(False, error='ذخیره نشد.')
    try:
        from .special_visit_inbox import inject_visit_deal_chat

        inject_visit_deal_chat(updated, decision=decision)
    except Exception:
        current_app.logger.exception('deal decision chat failed id=%s', vid)
    if str(rec.get('land_code') or '').strip():
        try:
            from .special_visit_inbox import _apply_special_deal_action

            listing_act = {
                'approved': 'start_deal',
                'rejected': 'reject_deal',
                'closed': 'approve_deal',
            }.get(decision)
            if listing_act:
                _apply_special_deal_action(
                    rec, owner_phone=me_phone, action=listing_act
                )
        except Exception:
            pass
    msg = {
        'approved': 'معامله تأیید شد.',
        'rejected': 'معامله رد شد.',
        'closed': 'پرونده بسته شد.',
    }.get(decision, 'ثبت شد.')
    wants_html = (request.headers.get('X-Requested-With') or '') != 'XMLHttpRequest' and not request.is_json
    if wants_html:
        flash(msg, 'success')
        return redirect(_sales_pipeline_url('deals'))
    return _requests_action_json(True, message=msg, visit_id=updated.get('id'), status=updated.get('status'))


def _partner_visit_attendance_action(vid: str, *, outcome: str):
    me_phone = (session.get('user_phone') or '').strip()
    from .partner_roles import partner_can_record_visit_attendance
    from .visit_requests import record_visit_attendance

    profile = getattr(g, 'express_partner_profile', None)
    if not partner_can_record_visit_attendance(profile):
        return _requests_action_json(
            False,
            error='ثبت نتیجه بازدید فقط برای ویزیتور و پلاس فعال است.',
        )

    visit_rows = load_express_visit_requests() or []
    if not isinstance(visit_rows, list):
        visit_rows = []
    rec = next(
        (r for r in visit_rows if isinstance(r, dict) and str(r.get('id') or '') == str(vid or '')),
        None,
    )
    if not rec:
        return _requests_action_json(False, error='درخواست پیدا نشد.')
    if str(rec.get('partner_phone') or '').strip() != me_phone:
        return _requests_action_json(False, error='دسترسی ندارید.')
    updated, err = record_visit_attendance(visit_rows, str(vid), outcome=outcome)
    if err == 'already_completed':
        updated = updated or rec
        err = None
    if err == 'invalid_status':
        return _requests_action_json(False, error='این بازدید الان قابل ثبت نتیجه نیست.')
    if err or not updated:
        return _requests_action_json(False, error='ثبت نتیجه ممکن نشد.')
    try:
        save_express_visit_requests(visit_rows)
    except Exception:
        current_app.logger.exception('visit attendance save failed id=%s', vid)
        return _requests_action_json(False, error='ذخیره نشد.')
    try:
        from .special_visit_inbox import inject_visit_attendance_chat

        inject_visit_attendance_chat(updated, outcome=outcome)
    except Exception:
        current_app.logger.exception('visit attendance chat failed id=%s', vid)
    if outcome == 'no_show':
        msg = 'عدم حضور ثبت شد.'
    else:
        msg = 'بازدید انجام شد. حالا نتیجه را ثبت کنید.'
    wants_html = (request.headers.get('X-Requested-With') or '') != 'XMLHttpRequest' and not request.is_json
    if wants_html:
        flash(msg, 'success')
        return redirect(_sales_pipeline_url('requests'))
    return _requests_action_json(True, message=msg, visit_id=updated.get('id'), status=updated.get('status'))


def _inject_visit_registered_into_chat(
    partner_phone: str,
    *,
    land_code: str = '',
    land_title: str = '',
    visit_id: str = '',
    date_label: str = '',
    already: bool = False,
    fallback_message: str = '',
) -> List[Dict[str, Any]]:
    """پیام تأیید بازدید را در همان ترد وینور بنویس تا در چت دیده شود."""
    phone = str(partner_phone or '').strip()
    if not phone:
        return []
    try:
        from app.ai.audience import AUDIENCE_PARTNER
        from app.ai.chat_store import append_exchange, ensure_active_thread
        from app.ai.agent_tools import support_call_phone

        call_phone = support_call_phone()
        code = str(land_code or '').strip()
        title = str(land_title or '').strip() or code
        file_bit = f' فایل {title}' if title else ''
        when = str(date_label or '').strip()
        date_bit = f' برای {when}' if when else ''

        if already:
            body = str(fallback_message or '').strip() or (
                f'برای این فایل بازدید باز از قبل دارید.'
            )
            body = (
                f'{body} برای هماهنگی با {call_phone} تماس بگیر. '
                'اگر بازدید انجام شده، کارت زیر را تأیید کن.'
            )
        else:
            body = (
                f'بازدید{file_bit}{date_bit} ثبت شد. '
                f'برای هماهنگی همین حالا با {call_phone} تماس بگیر. '
                'اگر بازدید انجام شده، کارت زیر را تأیید کن.'
            )

        actions: List[Dict[str, Any]] = []
        if code:
            try:
                from app.ai.agent_tools import _offer_complete_visit_for_open

                follow = _offer_complete_visit_for_open(
                    phone=phone,
                    land_code=code,
                    existing_visit_id=str(visit_id or ''),
                )
                ui = follow.get('ui_action') if isinstance(follow, dict) else None
                if isinstance(ui, dict):
                    ui = dict(ui)
                    ui['show_visit_call'] = True
                    ui['call_phone'] = call_phone
                    actions.append(ui)
            except Exception:
                pass

        tid = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
        msgs, _tid = append_exchange(
            phone,
            '',
            body,
            thread_id=tid,
            audience=AUDIENCE_PARTNER,
            assistant_agent_actions=actions or None,
        )
        try:
            from app.ai.agent_tools import _remember_sales

            if not already:
                _remember_sales(
                    phone,
                    'visit',
                    land_code=code,
                    detail=when,
                    audience='partner',
                )
        except Exception:
            pass
        if msgs:
            last = msgs[-1]
            return [last] if isinstance(last, dict) else []
    except Exception as exc:
        try:
            current_app.logger.warning('inject visit chat reply failed: %s', exc)
        except Exception:
            pass
    return []


@express_partner_bp.post('/home/register-customer', endpoint='home_register_customer')
@require_partner_access()
def home_register_customer():
    """درخواست تعیین وقت بازدید از مدال خانه (فایل و کاربر پلاس اختیاری)."""
    me_phone = (session.get('user_phone') or '').strip()
    payload = {}
    if request.is_json:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
    if not payload:
        payload = request.form.to_dict(flat=True) or {}

    notes = str(
        payload.get('notes')
        or payload.get('description')
        or payload.get('توضیحات')
        or ''
    ).strip()
    land_code = str(payload.get('land_code') or '').strip()
    plus_user_phone = str(
        payload.get('plus_user_phone')
        or payload.get('plus_phone')
        or ''
    ).strip()
    visit_slot_raw = str(payload.get('visit_slot') or '').strip()
    visit_date_in = str(payload.get('visit_date') or '').strip()
    visit_time_in = str(payload.get('visit_time') or '').strip()
    customer_first_name = str(payload.get('customer_first_name') or '').strip()
    customer_last_name = str(payload.get('customer_last_name') or '').strip()
    customer_phone_raw = str(payload.get('customer_phone') or '').strip()

    def _fail(msg: str, code: int = 400):
        return jsonify({'ok': False, 'error': msg}), code

    partners = load_express_partners() or []
    partner_profile = next((p for p in partners if str(p.get('phone')) == me_phone), None)
    try:
        is_pa = _is_partner_approved(partner_profile)
    except Exception:
        is_pa = False
    if not is_pa:
        return _fail('برای ثبت درخواست باید حساب همکاری شما تأیید شده باشد.', 403)

    from .visit_requests import (
        list_plus_users_for_visit,
        list_upcoming_visit_slots,
        next_auto_visit_date,
        parse_visit_hour,
        partner_cancel_own_visit,
        plus_phone_for_land_code,
        visit_slot_has_passed,
    )

    plus_user_name = ''
    land_owner_phone = plus_phone_for_land_code(land_code) if land_code else ''
    if land_owner_phone:
        plus_user_phone = land_owner_phone
    if plus_user_phone:
        from .partner_session_sync import canonical_partner_phone

        plus_users = list_plus_users_for_visit()
        want = canonical_partner_phone(plus_user_phone) or plus_user_phone
        plus_hit = next(
            (
                u for u in plus_users
                if (canonical_partner_phone(str(u.get('phone') or '')) or str(u.get('phone') or '').strip()) == want
                or str(u.get('phone') or '').strip() == plus_user_phone
            ),
            None,
        )
        if plus_hit is None and not land_owner_phone:
            return _fail('کاربر پلاس انتخاب‌شده پیدا نشد.')
        if plus_hit is not None:
            plus_user_name = str(plus_hit.get('name') or plus_user_phone)
            plus_user_phone = str(plus_hit.get('phone') or want)
        else:
            plus_user_name = plus_user_phone

    customer_phone = ''
    if customer_phone_raw:
        customer_phone = normalize_iran_mobile(customer_phone_raw) or customer_phone_raw
        if not is_valid_iran_mobile(customer_phone):
            return _fail('شماره مشتری معتبر نیست.')

    if '|' in visit_slot_raw:
        visit_date_in, _, visit_time_in = visit_slot_raw.partition('|')
        visit_date_in = visit_date_in.strip()
        visit_time_in = visit_time_in.strip()

    slots = list_upcoming_visit_slots(plus_user_phone=plus_user_phone)
    next_slot = None
    want_hour = parse_visit_hour(visit_time_in) if visit_time_in else None
    if visit_date_in:
        for item in slots:
            if str(item.get('iso') or '') != visit_date_in:
                continue
            if want_hour is None or int(item.get('hour') or -1) == want_hour:
                next_slot = item
                break
        if next_slot is None:
            return _fail('وقت انتخاب‌شده دیگر آزاد نیست. وقت دیگری انتخاب کنید.')
    if next_slot is None:
        next_slot = next_auto_visit_date(plus_user_phone=plus_user_phone) or (slots[0] if slots else None)
    if not next_slot or not next_slot.get('iso'):
        return _fail('روز مجاز بازدید پیدا نشد. با پشتیبانی هماهنگ کنید.')

    visit_date = str(next_slot.get('iso') or '')
    lands, _ = _build_partner_dashboard_lands(me_phone, True)
    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    land = None
    land_title = ''
    if land_code:
        land = next((L for L in (lands or []) if str(L.get('code') or '') == land_code), None)
        if land is None:
            return _fail('فایل انتخاب‌شده پیدا نشد.')
        st = str(land.get('_assignment_status') or '').strip().lower()
        if st == 'sold':
            return _fail('این فایل قبلاً فروخته شده است.')
        if st == 'in_transaction' or land.get('_in_transaction'):
            return _fail('این فایل در حال معامله است.')
        land_title = str(land.get('title') or land_code)
        open_rec = partner_open_visit(visit_requests, me_phone, land_code)
        if open_rec:
            open_st = str(open_rec.get('status') or '').strip()
            if (
                open_st in (PENDING_STATUS, APPROVED_STATUS)
                and visit_slot_has_passed(open_rec)
            ):
                closed, _cerr = partner_cancel_own_visit(
                    visit_requests,
                    request_id=str(open_rec.get('id') or ''),
                    partner_phone=me_phone,
                )
                if not closed:
                    return _fail('بازدید قبلی این فایل بسته نشد.')
            elif not partner_can_request_new_visit(st, visit_requests, me_phone, land_code):
                already_msg = 'برای این فایل بازدید باز از قبل دارید.'
                chat_msgs = _inject_visit_registered_into_chat(
                    me_phone,
                    land_code=land_code,
                    land_title=land_title,
                    visit_id=str((open_rec or {}).get('id') or ''),
                    already=True,
                    fallback_message=already_msg,
                )
                return jsonify({
                    'ok': True,
                    'already_pending': True,
                    'message': already_msg,
                    'messages': chat_msgs,
                    'land_code': land_code,
                    'redirect_url': url_for('express_partner.requests', tab='requests'),
                })

    partner_name = (partner_profile.get('name') if partner_profile else None) or me_phone

    rec, err = record_visit_request(
        visit_requests,
        partner_phone=me_phone,
        partner_name=partner_name,
        land_code=land_code,
        land_title=land_title,
        visit_date=visit_date,
        visit_time=str(next_slot.get('time_en') or next_slot.get('time') or ''),
        notes=notes,
        require_customer=False,
        plus_user_phone=plus_user_phone,
        plus_user_name=plus_user_name,
        customer_first_name=customer_first_name,
        customer_last_name=customer_last_name,
        customer_phone=customer_phone,
    )
    if err == 'already_pending':
        already_msg = 'برای این فایل بازدید باز از قبل دارید.'
        chat_msgs = _inject_visit_registered_into_chat(
            me_phone,
            land_code=land_code,
            land_title=land_title,
            already=True,
            fallback_message=already_msg,
        )
        return jsonify({
            'ok': True,
            'already_pending': True,
            'message': already_msg,
            'messages': chat_msgs,
            'land_code': land_code,
            'redirect_url': url_for('express_partner.requests', tab='requests'),
        })
    if err == 'weekday_not_allowed':
        return _fail('تاریخ خودکار در روزهای مجاز نیست.')
    if err in ('no_hours', 'hour_not_allowed'):
        return _fail('برای این روز ساعت مجاز بازدید نمانده است.')
    if err or not rec:
        return _fail('ثبت درخواست بازدید ممکن نشد.')

    save_express_visit_requests(visit_requests)
    if customer_phone:
        _sync_visit_customer_to_club(
            customer_phone=customer_phone,
            customer_first_name=customer_first_name,
            customer_last_name=customer_last_name,
        )

    sms_notes = notes
    if plus_user_name or plus_user_phone:
        plus_bit = f"کاربر پلاس: {plus_user_name or plus_user_phone}"
        sms_notes = f"{sms_notes}\n{plus_bit}".strip() if sms_notes else plus_bit
    if land_title:
        land_bit = f"فایل: {land_title}"
        sms_notes = f"{sms_notes}\n{land_bit}".strip() if sms_notes else land_bit

    sms_admin = _send_visit_schedule_admin_sms(
        partner_phone=me_phone,
        partner_name=partner_name,
        notes=sms_notes,
        presence_address=str(rec.get('visit_presence_address') or ''),
    )
    sms_partner = _send_visit_schedule_partner_sms(
        partner_phone=me_phone,
        partner_name=partner_name,
        weekday=str(next_slot.get('weekday') or ''),
        jalali_date=str(next_slot.get('jalali_fa') or next_slot.get('jalali') or ''),
        visit_time=str(next_slot.get('time_en') or next_slot.get('time') or '').strip(),
        presence_address=str(rec.get('visit_presence_address') or ''),
        plus_user_phone=plus_user_phone,
        plus_user_name=plus_user_name,
        land_code=land_code,
    )

    time_bit = str(next_slot.get('time') or rec.get('visit_time') or '').strip()
    date_label = (
        f"{next_slot.get('weekday') or ''} {next_slot.get('jalali_fa') or visit_date}"
        f"{(' ساعت ' + time_bit) if time_bit else ''}"
    ).strip()
    msg = (
        f"درخواست تعیین وقت بازدید برای "
        f"{date_label} "
        f"ثبت شد."
    ).strip()
    if not sms_admin.get('ok') and not sms_admin.get('skipped'):
        msg += ' (پیامک پشتیبان ناموفق بود)'
    if sms_partner.get('partner_failed'):
        msg += ' (پیامک شما ناموفق بود)'
    if sms_partner.get('plus_failed'):
        msg += ' (پیامک کاربر پلاس ناموفق بود)'

    chat_msgs = _inject_visit_registered_into_chat(
        me_phone,
        land_code=land_code,
        land_title=land_title,
        visit_id=str(rec.get('id') or ''),
        date_label=date_label,
        already=False,
        fallback_message=msg,
    )
    return jsonify({
        'ok': True,
        'message': msg,
        'visit_id': rec.get('id'),
        'visit_date': rec.get('visit_date'),
        'visit_date_label': next_slot.get('label') or '',
        'land_code': land_code,
        'messages': chat_msgs,
        'redirect_url': url_for('express_partner.requests', tab='requests'),
    })


def _home_customer_modal_context(me_phone: str, is_approved: bool) -> Dict[str, Any]:
    """فایل‌ها، کاربران پلاس و نوبت‌های مجاز برای مدال ثبت مشتری."""
    from .visit_requests import (
        format_visit_slot_hint,
        list_plus_users_for_visit,
        list_upcoming_visit_slots,
        next_auto_visit_date,
        plus_phone_for_land_code,
    )

    out: Dict[str, Any] = {
        'customer_modal_lands': [],
        'customer_modal_plus_users': [],
        'next_auto_visit': None,
        'next_auto_visit_by_plus': {},
        'visit_slots_by_plus': {},
    }
    if not me_phone or not is_approved:
        return out
    try:
        default_slot = next_auto_visit_date()
        out['next_auto_visit'] = default_slot
        default_slots = list_upcoming_visit_slots()
        by_plus: Dict[str, str] = {'': format_visit_slot_hint(default_slot)}
        slots_by_plus: Dict[str, List[Dict[str, Any]]] = {'': default_slots}
        plus_users = list_plus_users_for_visit()
        out['customer_modal_plus_users'] = plus_users
        for user in plus_users:
            phone = str((user or {}).get('phone') or '').strip()
            if not phone:
                continue
            by_plus[phone] = format_visit_slot_hint(
                next_auto_visit_date(plus_user_phone=phone)
            )
            slots_by_plus[phone] = list_upcoming_visit_slots(plus_user_phone=phone)
        out['next_auto_visit_by_plus'] = by_plus
        out['visit_slots_by_plus'] = slots_by_plus
    except Exception:
        out['next_auto_visit'] = None
        out['customer_modal_plus_users'] = []
        out['next_auto_visit_by_plus'] = {}
        out['visit_slots_by_plus'] = {}
    try:
        from .special_listings import plus_listing_owner_by_code

        owners = plus_listing_owner_by_code() or {}
        lands, _ = _build_partner_dashboard_lands(me_phone, True)
        assigned_first: List[Dict[str, Any]] = []
        others: List[Dict[str, Any]] = []
        for land in lands or []:
            code = str(land.get('code') or '').strip()
            if not code:
                continue
            st = str(land.get('_assignment_status') or '').strip().lower()
            if st == 'sold':
                continue
            owner = owners.get(code) if isinstance(owners, dict) else None
            if not isinstance(owner, dict):
                owner = {}
            plus_phone = plus_phone_for_land_code(code) or str(owner.get('phone') or '').strip()
            item = {
                'code': code,
                'title': str(land.get('title') or code),
                'city': str(land.get('city') or ''),
                'plus_phone': plus_phone,
                'plus_name': str(owner.get('name') or '').strip(),
            }
            if land.get('_assignment_id'):
                assigned_first.append(item)
            else:
                others.append(item)
        out['customer_modal_lands'] = assigned_first + others
    except Exception:
        out['customer_modal_lands'] = []
    return out


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
    # آمار اول تا reconcile قبل از ساخت فید تراکنش اعمال شود (وگرنه ردیف‌ها کهنه می‌مانند).
    try:
        comm_stats = _partner_commission_stats(me_phone, my_comms)
    except Exception:
        current_app.logger.exception('commissions_transactions stats failed')
        comm_stats = {
            "total_confirmed_amount": 0,
            "total_confirmed_count": 0,
            "paid_withdrawal_amount": 0,
            "paid_withdrawal_count": 0,
            "received_amount": 0,
            "received_count": 0,
        }
    try:
        _attach_commission_txn_labels(my_comms)
    except Exception:
        current_app.logger.exception('attach_commission_txn_labels failed')
    try:
        txn_items = _partner_txn_items(me_phone, my_comms)
    except Exception:
        current_app.logger.exception('partner_txn_items failed')
        txn_items = []
    txn_summary = partner_txn_feed_summary(txn_items)

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
        return redirect(url_for("express_partner.home"))
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
    return redirect(url_for("express_partner.home"))


@express_partner_bp.post('/files/upload')
@require_partner_access(allow_pending=True)
def upload_file():
    me_phone = (session.get("user_phone") or "").strip()
    f = request.files.get('file')
    if not f or not f.filename:
        return redirect(url_for("express_partner.home"))
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
    return redirect(url_for("express_partner.home"))


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
        'VINOR_PLUS_ACTIVE',
        'VINOR_PORTAL_ROLES',
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
    """بعد از خروج → خانه با منوی باز (ورود فشرده داخل drawer)."""
    return url_for('express_partner.home', menu=1)


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

        issued_ok, issued_err = _issue_partner_login_otp(phone)
        if not issued_ok:
            msg, status = _partner_otp_fail_payload(issued_err)
            if wants_json:
                return jsonify({'ok': False, 'error': msg}), status
            flash(msg, FLASH_AUTH_WARNING if status == 429 else FLASH_AUTH_ERROR)
            return redirect(url_for('express_partner.login', next=_login_next_preserve() or None))

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
    from app.auth.otp.config import otp_digits
    from ..services.sms import normalize_otp_code

    code = normalize_otp_code(request.form.get('otp_code') or '')
    form_phone = _otp_canonical_phone((request.form.get('phone') or '').strip())
    sess_phone = _otp_session_phone()
    if not form_phone:
        form_phone = sess_phone
    if not form_phone:
        msg = 'شماره موبایل یافت نشد. لطفاً از ابتدا وارد شوید.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login')}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))
    if sess_phone and form_phone != sess_phone:
        msg = 'شماره موبایل با درخواست ورود همخوانی ندارد.'
        if wants_json:
            return jsonify({'ok': False, 'error': msg, 'redirect': url_for('express_partner.login', change=1)}), 400
        flash(msg, FLASH_AUTH_ERROR)
        return redirect(url_for('express_partner.login', change=1))

    if len(code) != otp_digits():
        msg = 'لطفاً کد تأیید را به‌درستی وارد کنید.'
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


@express_partner_bp.route('/help', methods=['GET'], endpoint='help')
@require_partner_access(allow_pending=True, allow_guest=True)
def help():
    """صفحه راهنما حذف شد — هدایت به دستیار AI روی داشبورد."""
    return redirect(url_for('express_partner.home', ai=1))


@express_partner_bp.route('/training', methods=['GET'], endpoint='training')
@require_partner_access(allow_pending=True, allow_guest=True)
def training():
    """صفحه آموزش — استایل داخل content برای soft-nav"""
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


def _redirect_login_next(fallback_endpoint: str = 'express_partner.home'):
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
    back_url = url_for('express_partner.home')
    if next_url.startswith('/express/partner'):
        back_url = next_url
    return render_template(
        'express_partner/cooperation_terms.html',
        hide_header=True,
        is_approved=is_approved,
        back_url=back_url,
    )


@express_partner_bp.route('/levels', methods=['GET'], endpoint='coop_levels')
@require_partner_access(allow_pending=True, allow_guest=True)
def coop_levels():
    """چهار سطح همکاری از پایین به بالا: عادی، بازاریاب، ویزیتور، پلاس."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    from .partner_roles import partner_coop_level

    if me_phone:
        current_level = partner_coop_level(profile)
    else:
        current_level = ''
    is_approved = current_level not in ('', 'regular')
    is_special = current_level == 'plus'
    return render_template(
        'express_partner/coop_levels.html',
        hide_header=True,
        is_approved=is_approved,
        is_special=is_special,
        current_level=current_level,
        back_url=url_for('express_partner.home'),
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
        bonus_per_invite = 100_000
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
    """صفحه جداگانه AI حذف شد — چت کامل روی /home."""
    thread = (request.args.get('thread') or '').strip()
    if thread:
        return redirect(url_for('express_partner.home', ai=1, thread=thread), code=302)
    return redirect(url_for('express_partner.home', ai=1), code=302)


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
    from app.ai.chat_store import messages_for_ui
    from app.lawyer.service import is_lawyer_thread, threads_with_lawyer_and_postchi
    from app.services.postchi import (
        is_postchi_thread,
        postchi_messages_for_ui,
    )

    phone = (session.get('user_phone') or '').strip()
    thread_id = (request.args.get('thread_id') or '').strip() or None
    threads_only = request.args.get('threads_only', '').lower() in ('1', 'true', 'yes')
    active = thread_id if (is_postchi_thread(thread_id) or is_lawyer_thread(thread_id)) else None
    if not active:
        from app.ai.chat_store import load_user_record

        record = load_user_record(phone, audience=AUDIENCE_PARTNER)
        active = record.get('active_id')
    payload = {
        'ok': True,
        'threads': threads_with_lawyer_and_postchi(
            phone,
            audience=AUDIENCE_PARTNER,
            active_thread_id=thread_id or active,
        ),
        'thread_id': thread_id,
    }
    if not threads_only:
        if is_postchi_thread(thread_id):
            payload['messages'] = postchi_messages_for_ui(phone)
            payload['mode'] = 'postchi'
        elif is_lawyer_thread(thread_id):
            payload['messages'] = messages_for_ui(phone, thread_id, audience=AUDIENCE_PARTNER)
            payload['mode'] = 'lawyer'
        else:
            payload['messages'] = messages_for_ui(phone, thread_id, audience=AUDIENCE_PARTNER)
            payload['mode'] = 'chat'
    return jsonify(payload)


@express_partner_bp.post('/ai/chat', endpoint='ai_chat')
@require_partner_access(allow_pending=True, json_response=True)
def ai_chat():
    from app.ai.audience import AUDIENCE_PARTNER, VOICE_LAWYER
    from app.ai.chat_store import (
        append_exchange,
        ensure_active_thread,
        history_for_api,
    )
    from app.ai.http_errors import ai_chat_http_status
    from app.ai.services import generate_reply
    from app.lawyer.config import lawyer_enabled
    from app.lawyer.service import (
        ensure_lawyer_thread,
        is_lawyer_thread,
        threads_with_lawyer_and_postchi,
    )
    from app.services.postchi import is_postchi_thread

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or request.form.get('message') or '').strip()
    thread_id = (data.get('thread_id') or '').strip() or None
    chip_intent = (data.get('intent') or data.get('chip_intent') or '').strip()
    hide_user = bool(data.get('hide_user') or data.get('silent') or data.get('hide_ui'))
    mode = (data.get('mode') or '').strip().lower()
    attachment = data.get('attachment') if isinstance(data.get('attachment'), dict) else None
    if attachment:
        att_url = str(attachment.get('url') or '').strip()
        att_name = str(attachment.get('name') or 'فایل').strip() or 'فایل'
        att_kind = str(attachment.get('kind') or 'file').strip().lower() or 'file'
        if att_url:
            kind_fa = {
                'image': 'تصویر',
                'video': 'ویدیو',
                'file': 'فایل',
            }.get(att_kind, 'فایل')
            att_line = f'[پیوست {kind_fa}: {att_name}]'
            if not message:
                message = att_line
            elif att_line not in message:
                message = f'{att_line}\n{message}'
            attachment = {
                'kind': att_kind,
                'url': att_url,
                'name': att_name,
                'mime': str(attachment.get('mime') or '').strip(),
                'size': int(attachment.get('size') or 0) or 0,
            }
        else:
            attachment = None
    if not message:
        return jsonify({'ok': False, 'error': 'پیام خالی است.'}), 400
    if is_postchi_thread(thread_id):
        return jsonify({'ok': False, 'error': 'برای پیام به وینور، گفتگوی پستچی را انتخاب کنید.'}), 400

    voice = None
    if mode in ('lawyer', 'vakil') or is_lawyer_thread(thread_id):
        if not lawyer_enabled():
            return jsonify({'ok': False, 'error': 'وکیل ملکی فعلاً غیرفعال است.'}), 403
        thread_id = ensure_lawyer_thread(phone, audience=AUDIENCE_PARTNER)
        voice = VOICE_LAWYER
        chip_intent = ''

    if not thread_id:
        thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)

    history = history_for_api(phone, thread_id, audience=AUDIENCE_PARTNER)
    result = generate_reply(
        message,
        history=history,
        user_key=phone,
        audience=AUDIENCE_PARTNER,
        thread_id=thread_id,
        chip_intent=chip_intent,
        voice=voice,
    )
    if not result.get('ok'):
        return jsonify(result), ai_chat_http_status(result)

    land_codes = [] if voice == VOICE_LAWYER else (result.get('land_codes') or [])
    agent_actions = [] if voice == VOICE_LAWYER else (result.get('agent_actions') or [])
    user_meta = {'attachment': attachment} if attachment else None
    msgs, tid = append_exchange(
        phone,
        message,
        result.get('reply') or '',
        thread_id=thread_id,
        assistant_land_codes=land_codes,
        assistant_agent_actions=agent_actions,
        audience=AUDIENCE_PARTNER,
        hide_user=hide_user,
        user_meta=user_meta,
    )
    result['messages'] = msgs
    result['audience'] = AUDIENCE_PARTNER
    result['thread_id'] = tid
    result['mode'] = 'lawyer' if is_lawyer_thread(tid) else 'chat'
    result['threads'] = threads_with_lawyer_and_postchi(
        phone,
        audience=AUDIENCE_PARTNER,
        active_thread_id=tid,
    )
    if voice == VOICE_LAWYER:
        result.pop('land_cards', None)
        result.pop('cards_html', None)
        result['land_codes'] = []
        result['agent_actions'] = []
    return jsonify(result)


@express_partner_bp.post('/ai/upload', endpoint='ai_upload')
@require_partner_access(allow_pending=True, json_response=True)
def ai_upload():
    """آپلود پیوست چت وینور (تصویر / ویدیو / فایل) — پاسخ JSON."""
    from werkzeug.utils import secure_filename
    from ..utils.images import normalize_upload_url, save_upload_image

    phone = (session.get('user_phone') or '').strip()
    if not phone:
        return jsonify({'ok': False, 'error': 'برای آپلود وارد شوید.', 'need_login': True}), 401

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    kind = (request.form.get('kind') or '').strip().lower()
    raw_name = str(f.filename or 'file')
    ext = os.path.splitext(raw_name)[1].lower()
    mime = (getattr(f, 'mimetype', None) or '').strip().lower()

    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif'}
    video_exts = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v'}
    file_exts = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.zip', '.rar',
        '.png', '.jpg', '.jpeg', '.webp',
    }

    if not kind:
        if mime.startswith('image/') or ext in image_exts:
            kind = 'image'
        elif mime.startswith('video/') or ext in video_exts:
            kind = 'video'
        else:
            kind = 'file'

    max_bytes = {
        'image': 12 * 1024 * 1024,
        'video': 80 * 1024 * 1024,
        'file': 25 * 1024 * 1024,
    }.get(kind, 25 * 1024 * 1024)

    # اندازه تقریبی از stream
    try:
        f.stream.seek(0, os.SEEK_END)
        size = int(f.stream.tell() or 0)
        f.stream.seek(0)
    except Exception:
        size = 0
    if size and size > max_bytes:
        return jsonify({'ok': False, 'error': 'حجم فایل بیش از حد مجاز است.'}), 400

    upload_folder = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)

    if kind == 'image':
        stored = save_upload_image(f, upload_folder)
        if not stored:
            return jsonify({'ok': False, 'error': 'ذخیره تصویر ناموفق بود.'}), 400
        url = normalize_upload_url(stored)
        path = stored
    else:
        if kind == 'video' and ext not in video_exts:
            return jsonify({'ok': False, 'error': 'فرمت ویدیو مجاز نیست.'}), 400
        if kind == 'file' and ext and ext not in file_exts and not mime.startswith('image/'):
            # اجازهٔ پسوندهای رایج؛ بدون پسوند هم قبول
            if ext not in {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.zip', '.rar'}:
                return jsonify({'ok': False, 'error': 'فرمت فایل مجاز نیست.'}), 400
        safe = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{raw_name}") or (
            datetime.now().strftime('%Y%m%d%H%M%S%f') + '_file'
        )
        f.save(os.path.join(upload_folder, safe))
        path = f'uploads/{safe}'
        url = normalize_upload_url(path)

    return jsonify({
        'ok': True,
        'kind': kind,
        'path': path,
        'url': url,
        'name': raw_name,
        'mime': mime,
        'size': size,
    })


@express_partner_bp.post('/ai/agent/confirm', endpoint='ai_agent_confirm')
@require_partner_access(allow_pending=True, json_response=True)
def ai_agent_confirm():
    """تأیید کاربر برای اقدام پیشنهادی AI — کارت زنده به‌روز می‌شود."""
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import ensure_active_thread
    from app.ai.confirmation import apply_confirm_to_chat, confirm_action

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    thread_id = (data.get('thread_id') or '').strip() or None
    if not token:
        return jsonify({'ok': False, 'error': 'توکن اقدام نامعتبر است.'}), 400

    if not thread_id:
        thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)

    out = confirm_action(phone=phone, token=token)
    if not out.get('ok'):
        return jsonify(out), 400

    chat = apply_confirm_to_chat(
        phone=phone,
        token=token,
        thread_id=thread_id,
        audience=AUDIENCE_PARTNER,
        confirm_out=out,
    )
    return jsonify({
        'ok': True,
        'message': chat.get('message') or out.get('message'),
        'already': bool(out.get('already')),
        'thread_id': chat.get('thread_id') or thread_id,
        'messages': chat.get('messages') or [],
        'card_updated': bool(chat.get('card_updated')),
        'visit_id': out.get('visit_id') or '',
        'land_code': out.get('land_code') or '',
        'tx_mode': out.get('tx_mode') or '',
    })


@express_partner_bp.post('/ai/agent/cancel', endpoint='ai_agent_cancel')
@require_partner_access(allow_pending=True, json_response=True)
def ai_agent_cancel():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.confirmation import cancel_action

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    thread_id = (data.get('thread_id') or '').strip() or None
    if not token:
        return jsonify({'ok': False, 'error': 'توکن نامعتبر است.'}), 400
    return jsonify(
        cancel_action(
            phone=phone,
            token=token,
            thread_id=thread_id,
            audience=AUDIENCE_PARTNER,
        )
    )


@express_partner_bp.post('/ai/clear', endpoint='ai_clear')
@require_partner_access(allow_pending=True, json_response=True)
def ai_clear():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import clear_chat, messages_for_ui
    from app.ai.http_errors import ai_chat_http_status
    from app.ai.welcome import opening_text

    phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None)
    if profile is None and phone:
        profile = _partner_profile_for_phone(phone)
    is_approved = _is_partner_approved(profile) if profile else False
    opening = opening_text(is_approved=is_approved)
    out = clear_chat(phone, audience=AUDIENCE_PARTNER, opening_text=opening)
    if not out.get('ok'):
        return jsonify(out), ai_chat_http_status(out)
    tid = out.get('thread_id')
    msgs = out.get('messages')
    if msgs is None:
        msgs = messages_for_ui(phone, thread_id=tid, audience=AUDIENCE_PARTNER)
    return jsonify({'ok': True, 'thread_id': tid, 'messages': msgs})


@express_partner_bp.post('/ai/thread/switch', endpoint='ai_switch_thread')
@require_partner_access(allow_pending=True, json_response=True)
def ai_switch_thread():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import messages_for_ui, ensure_active_thread
    from app.lawyer.config import lawyer_enabled
    from app.lawyer.service import (
        LAWYER_THREAD_ID,
        ensure_lawyer_thread,
        is_lawyer_thread,
        threads_with_lawyer_and_postchi,
    )
    from app.services.postchi import (
        POSTCHI_THREAD_ID,
        is_postchi_thread,
        open_postchi,
        postchi_messages_for_ui,
    )

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get('thread_id') or '').strip()
    if not thread_id:
        return jsonify({'ok': False, 'error': 'گفتگو یافت نشد.'}), 404
    if is_postchi_thread(thread_id):
        open_postchi(phone)
        return jsonify({
            'ok': True,
            'thread_id': POSTCHI_THREAD_ID,
            'mode': 'postchi',
            'messages': postchi_messages_for_ui(phone),
            'threads': threads_with_lawyer_and_postchi(
                phone,
                audience=AUDIENCE_PARTNER,
                active_thread_id=POSTCHI_THREAD_ID,
            ),
        })
    if is_lawyer_thread(thread_id) or thread_id in ('lawyer', 'vakil'):
        if not lawyer_enabled():
            return jsonify({'ok': False, 'error': 'وکیل ملکی فعلاً غیرفعال است.'}), 403
        tid = ensure_lawyer_thread(phone, audience=AUDIENCE_PARTNER)
        return jsonify({
            'ok': True,
            'thread_id': tid,
            'mode': 'lawyer',
            'messages': messages_for_ui(phone, tid, audience=AUDIENCE_PARTNER),
            'threads': threads_with_lawyer_and_postchi(
                phone,
                audience=AUDIENCE_PARTNER,
                active_thread_id=tid,
            ),
        })
    from app.ai.chat_store import ensure_active_thread

    thread_id = ensure_active_thread(phone, audience=AUDIENCE_PARTNER)
    return jsonify({
        'ok': True,
        'thread_id': thread_id,
        'mode': 'chat',
        'messages': messages_for_ui(phone, thread_id, audience=AUDIENCE_PARTNER),
        'threads': threads_with_lawyer_and_postchi(
            phone,
            audience=AUDIENCE_PARTNER,
            active_thread_id=thread_id,
        ),
    })


@express_partner_bp.post('/ai/thread/delete', endpoint='ai_delete_thread')
@require_partner_access(allow_pending=True, json_response=True)
def ai_delete_thread():
    from app.ai.audience import AUDIENCE_PARTNER
    from app.ai.chat_store import delete_thread, load_user_record, messages_for_ui
    from app.lawyer.service import is_lawyer_thread, threads_with_lawyer_and_postchi
    from app.services.postchi import is_postchi_thread

    phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    thread_id = (data.get('thread_id') or '').strip()
    if is_postchi_thread(thread_id) or is_lawyer_thread(thread_id):
        return jsonify({'ok': False, 'error': 'این گفتگو قابل حذف نیست.'}), 400
    if not thread_id or not delete_thread(phone, thread_id, audience=AUDIENCE_PARTNER):
        return jsonify({'ok': False, 'error': 'حذف ممکن نیست.'}), 400
    record = load_user_record(phone, audience=AUDIENCE_PARTNER)
    active = record.get('active_id')
    return jsonify({
        'ok': True,
        'thread_id': active,
        'messages': messages_for_ui(phone, active, audience=AUDIENCE_PARTNER),
        'threads': threads_with_lawyer_and_postchi(
            phone,
            audience=AUDIENCE_PARTNER,
            active_thread_id=active,
        ),
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
    can_revisit: bool | None = None,
    customer_phone: str | None = None,
    customer_name: str | None = None,
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
        if can_revisit is not None:
            payload['can_revisit'] = bool(can_revisit)
        if customer_phone:
            payload['customer_phone'] = str(customer_phone).strip()
        if customer_name:
            payload['customer_name'] = str(customer_name).strip()
        if success and redirect_url:
            home_path = '/express/partner/home'
            try:
                home_path = url_for('express_partner.home')
            except Exception:
                pass
            dest_path = str(redirect_url).split('?', 1)[0].rstrip('/') or '/'
            home_cmp = str(home_path).split('?', 1)[0].rstrip('/') or '/'
            if dest_path not in (home_cmp, '/express/partner/home', '/express/partner/dashboard'):
                payload['redirect_url'] = redirect_url
        return jsonify(payload), (200 if success else 400)
    if message:
        flash(message, 'land')
    if success:
        if redirect_url:
            return redirect(redirect_url)
        return redirect(url_for('express_partner.land_detail', code=code))
    return redirect(url_for('express_partner.home'))


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
    by_land_status, my_by_code = _express_assignment_indexes(assignments, ph)
    global_status = by_land_status.get(key, 'active')
    holder_phone = None
    for a in assignments:
        if str(a.get('land_code') or '').strip() != key:
            continue
        th = str(a.get('transaction_holder') or '').strip()
        if th:
            holder_phone = th
            break
    return {
        'global_status': global_status,
        'holder_phone': holder_phone,
        'my_assignment': my_by_code.get(key),
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
    commissions = load_express_commissions_cached() or []
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
    """پورسانت بازدید حذف شده — همیشه صفر."""
    return 0


def _has_visit_commission_record(commissions: List[Dict[str, Any]], phone: str, code: str) -> bool:
    return False


def _visit_commission_required_for(commissions: List[Dict[str, Any]], phone: str, code: str) -> bool:
    """پورسانت بازدید دیگر پیش‌نیاز معامله نیست."""
    return False


def _request_visit_field(name: str, payload: Dict[str, Any] | None = None) -> str:
    val = (request.form.get(name) or '').strip()
    if val:
        return val
    if payload is None and request.is_json:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
    if isinstance(payload, dict):
        return str(payload.get(name) or '').strip()
    return ''


def _sync_visit_customer_to_club(
    *,
    customer_phone: str,
    customer_first_name: str,
    customer_last_name: str,
) -> None:
    """ثبت/به‌روزرسانی مشتری بازدید در باشگاه مشتریان ادمین."""
    try:
        from admin.sms_recipients import (
            RECIPIENT_GROUP_CUSTOMER_CLUB,
            add_sms_recipient_member,
        )
        full_name = f"{(customer_first_name or '').strip()} {(customer_last_name or '').strip()}".strip()
        err = add_sms_recipient_member(
            RECIPIENT_GROUP_CUSTOMER_CLUB,
            customer_phone,
            full_name or customer_phone,
        )
        if err:
            current_app.logger.warning(
                'visit customer club sync skipped phone=%s err=%s',
                customer_phone,
                err,
            )
    except Exception:
        current_app.logger.exception(
            'visit customer club sync failed phone=%s', customer_phone
        )


@express_partner_bp.route('/visit-requests/<code>', methods=['POST'], endpoint='create_visit_request')
@require_partner_access()
def create_visit_request(code: str):
    """ثبت درخواست بازدید با تاریخ و مشخصات مشتری."""
    me_phone = (session.get('user_phone') or '').strip()
    json_payload = None
    if request.is_json:
        try:
            json_payload = request.get_json(silent=True) or {}
        except Exception:
            json_payload = {}
    visit_date = _request_visit_field('visit_date', json_payload)
    visit_time = _request_visit_field('visit_time', json_payload)
    customer_first_name = _request_visit_field('customer_first_name', json_payload)
    customer_last_name = _request_visit_field('customer_last_name', json_payload)
    customer_phone_raw = _request_visit_field('customer_phone', json_payload)
    customer_phone = normalize_iran_mobile(customer_phone_raw) or customer_phone_raw

    if not customer_first_name or not customer_last_name or not customer_phone_raw:
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='نام، نام خانوادگی و شماره تماس مشتری الزامی است.',
            category='error',
        )
    if not is_valid_iran_mobile(customer_phone):
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='شماره تماس مشتری معتبر نیست.',
            category='error',
        )

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
        try:
            from app.express_partner.partner_missions import claim_express_land_for_partner

            if claim_express_land_for_partner(me_phone, code, source='chat_claim'):
                ctx = _express_land_partner_ctx(code, me_phone) or ctx
        except Exception:
            pass
    if not ctx.get('my_assignment'):
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='این فایل برای ثبت بازدید در دسترس نیست (فروخته یا قفل همکار دیگر).',
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

    if not partner_can_request_new_visit(current_status, visit_requests, me_phone, str(code)):
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='در حال حاضر امکان ثبت بازدید جدید برای این فایل وجود ندارد.',
            category='error',
        )

    if partner_visit_completed(visit_requests, me_phone, str(code)):
        tx_revisit = _partner_land_tx_payload(
            code,
            me_phone,
            is_partner_approved=is_pa,
            global_assignment_status=current_status,
        )
        if not tx_revisit.get('can_revisit'):
            return _mark_in_transaction_finish(
                code,
                success=False,
                message='تا زمان تأیید ادمین، امکان ثبت بازدید مجدد وجود ندارد.',
                category='error',
            )

    rec, err = record_visit_request(
        visit_requests,
        partner_phone=me_phone,
        partner_name=partner_name,
        land_code=str(code),
        land_title=str(land_title),
        visit_date=visit_date,
        visit_time=visit_time,
        customer_first_name=customer_first_name,
        customer_last_name=customer_last_name,
        customer_phone=customer_phone,
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
            message=(
                'این بازدید از قبل ثبت شده. برای هماهنگی با 09121471301 تماس بگیر؛ '
                'بعد از بازدید از چت خانه بگو «بازدید انجام شد».'
            ),
            category='success',
            new_status='active',
        tx_mode=tx_state.get('tx_mode') or 'visit_done',
        visit_date=vdate,
        customer_phone=tx_state.get('customer_phone')
        or (open_rec or {}).get('customer_phone')
        or '',
        customer_name=tx_state.get('customer_name')
        or (open_rec or {}).get('customer_name')
        or '',
        redirect_url=url_for('express_partner.home'),
        )
    if err == 'customer_required':
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='نام، نام خانوادگی و شماره تماس مشتری الزامی است.',
            category='error',
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
        from .visit_requests import plus_phone_for_land_code, visit_allowed_weekdays_summary
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='تاریخ انتخاب‌شده در روزهای مجاز بازدید نیست. روزهای مجاز: ' + visit_allowed_weekdays_summary(plus_user_phone=plus_phone_for_land_code(code)),
            category='error',
        )
    if err in ('no_hours', 'hour_not_allowed'):
        from .visit_requests import plus_phone_for_land_code, visit_allowed_hours_summary
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='ساعت انتخاب‌شده در نوبت‌های مجاز نیست. ساعت‌های مجاز: ' + visit_allowed_hours_summary(plus_user_phone=plus_phone_for_land_code(code)),
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
    _sync_visit_customer_to_club(
        customer_phone=customer_phone,
        customer_first_name=customer_first_name,
        customer_last_name=customer_last_name,
    )
    # Phase 1 CRM: optional Contact upsert from Visit customer_* (flags default ON).
    try:
        from app.crm.visit_sync import sync_contact_from_visit
        sync_contact_from_visit(rec)
    except Exception:
        pass
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
            visit_time=str(rec.get('visit_time') or ''),
            reference_id=str(rec.get('id') or ''),
        )
    except Exception:
        current_app.logger.exception(
            'visit_submitted partner SMS failed phone=%s code=%s', me_phone, code
        )
    msg = (
        'بازدید ثبت شد. برای هماهنگی با 09121471301 تماس بگیر؛ '
        'بعد از بازدید از چت خانه بگو «بازدید انجام شد» — لازم نیست به صفحه دیگری بروی.'
    )
    if not sms_result.get('ok') and not sms_result.get('skipped'):
        msg = (
            'بازدید ثبت شد (پیامک ادمین ناموفق بود). برای هماهنگی با 09121471301 تماس بگیر؛ '
            'بعد از بازدید از چت خانه بگو «بازدید انجام شد».'
        )

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
        tx_mode=tx_state.get('tx_mode') or 'visit_done',
        visit_date=tx_state.get('visit_date') or rec.get('visit_date') or visit_date,
        can_revisit=tx_state.get('can_revisit'),
        customer_phone=tx_state.get('customer_phone') or customer_phone,
        customer_name=tx_state.get('customer_name')
        or f'{customer_first_name} {customer_last_name}'.strip(),
        redirect_url=url_for('express_partner.home'),
    )


@express_partner_bp.route('/visit-requests/<code>/complete', methods=['POST'], endpoint='complete_visit_request')
@require_partner_access()
def complete_visit_request(code: str):
    """ثبت اعلام «بازدید انجام شد» — پیش‌فرض بدون صف ادمین نهایی می‌شود."""
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
    from .partner_roles import partner_can_record_visit_attendance
    if not partner_can_record_visit_attendance(partner_profile):
        return _mark_in_transaction_finish(
            code,
            success=False,
            message='ثبت انجام بازدید فقط برای ویزیتور و پلاس فعال است.',
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
            message='ابتدا باید درخواست بازدید ثبت شده باشد.',
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

    auto_done = str(rec.get('status') or '').strip() == COMPLETED_STATUS
    if err is None and not auto_done:
        lands_all = load_ads_cached() or []
        land = next((l for l in lands_all if str(l.get('code')) == str(code)), None)
        land_title = (land.get('title') if land else None) or str(code)
        partner_name = (partner_profile.get('name') if partner_profile else None) or me_phone
        try:
            from .admin_action_sms import notify_admin_pending_action
            notify_admin_pending_action(
                'visit_done',
                partner_phone=me_phone,
                partner_name=partner_name,
                land_code=str(code),
                land_title=str(land_title),
            )
        except Exception:
            current_app.logger.exception('visit_done admin SMS failed phone=%s code=%s', me_phone, code)
        try:
            from .visit_sms import notify_partner_land_tx_sms
            notify_partner_land_tx_sms(
                partner_phone=me_phone,
                event='visit_done_pending',
                land_code=str(code),
                land_title=str(land_title),
                visit_date=str(rec.get('visit_date') or ''),
                reference_id=str(rec.get('id') or ''),
            )
        except Exception:
            current_app.logger.exception('visit_done_pending partner SMS failed phone=%s code=%s', me_phone, code)
    elif err is None and auto_done:
        lands_all = load_ads_cached() or []
        land = next((l for l in lands_all if str(l.get('code')) == str(code)), None)
        land_title = (land.get('title') if land else None) or str(code)
        try:
            from .visit_sms import notify_partner_land_tx_sms
            notify_partner_land_tx_sms(
                partner_phone=me_phone,
                event='visit_completed',
                land_code=str(code),
                land_title=str(land_title),
                visit_date=str(rec.get('visit_date') or ''),
                reference_id=str(rec.get('id') or ''),
            )
        except Exception:
            current_app.logger.exception('visit_completed partner SMS failed phone=%s code=%s', me_phone, code)

    tx_state = _partner_land_tx_payload(
        code,
        me_phone,
        is_partner_approved=True,
        global_assignment_status=ctx.get('global_status') or 'active',
    )
    if auto_done or err == 'already_completed':
        msg = 'بازدید انجام شد ثبت و تأیید شد. می‌توانی معامله را از چت ثبت کنی.'
        if err == 'already_completed':
            msg = 'بازدید قبلاً انجام‌شده ثبت شده. می‌توانی معامله را از چت ثبت کنی.'
        return _mark_in_transaction_finish(
            code,
            success=True,
            message=msg,
            category='success',
            new_status=ctx.get('global_status') or 'active',
            tx_mode=tx_state.get('tx_mode') or 'deal',
            visit_date=tx_state.get('visit_date') or None,
            can_revisit=tx_state.get('can_revisit'),
        )
    msg = 'بازدید انجام شد ثبت شد و منتظر تأیید ادمین است.'
    if err == 'already_pending':
        msg = 'بازدید انجام شد قبلاً ثبت شده و منتظر تأیید ادمین است.'
    return _mark_in_transaction_finish(
        code,
        success=True,
        message=msg,
        category='success',
        new_status=ctx.get('global_status') or 'active',
        tx_mode=tx_state.get('tx_mode') or 'visit_done_pending',
        visit_date=tx_state.get('visit_date') or None,
        can_revisit=tx_state.get('can_revisit'),
    )


@express_partner_bp.get('/lands/<string:code>/tx-status', endpoint='land_tx_status')
@require_partner_access()
def land_tx_status(code: str):
    """وضعیت دکمه بازدید/معامله — برای به‌روزرسانی خودکار پس از تأیید ادمین."""
    me_phone = (session.get('user_phone') or '').strip()
    ctx = _express_land_partner_ctx(code, me_phone)
    if ctx is None:
        return jsonify(success=False, message='فایل یافت نشد.'), 404

    partner_profile = _partner_profile_for_phone(me_phone) if me_phone else None
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
    # پولینگ tx-status هر چند ثانیه یک‌بار است؛ روتین را مسدود نکن
    if is_partner_approved:
        _defer_routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)
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
            if partner_open_visit(visit_requests, me_phone, code):
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='ابتدا روند بازدید جاری را تکمیل کنید یا بازدید مجدد ثبت کنید.',
                    category='error',
                )
            completed_visit = partner_visit_completed(visit_requests, me_phone, code)
            commissions_for_visit = load_express_commissions() or []
            if not isinstance(commissions_for_visit, list):
                commissions_for_visit = []
            if not completed_visit:
                return _mark_in_transaction_finish(
                    code,
                    success=False,
                    message='برای ثبت درخواست معامله، ابتدا بازدید را انجام‌شده ثبت کنید.',
                    category='error',
                )
            # هیچ‌کس معامله نکرده، این همکار می‌تواند معامله کند
            new_status = 'in_transaction'
        
        # اعمال تغییرات
        for a in assignments:
            if str(a.get('land_code')) == str(code):
                current_a_status = a.get('status', 'active')
                if current_a_status in ('active', 'pending', 'approved', 'closed', 'in_transaction'):
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
                            # معامله قبلاً تأیید شده ولی sold نشده → نهایی‌سازی
                            if has_finalized_deal_commission(commissions, partner_phone, str(code)):
                                if sync_sold_if_deal_already_approved(
                                    assignments, commissions, partner_phone, str(code)
                                ):
                                    save_express_assignments(assignments)
                                try:
                                    _mark_express_land_sold(str(code))
                                except Exception:
                                    current_app.logger.exception(
                                        'mark express land sold failed code=%s', code
                                    )
                                return _mark_in_transaction_finish(
                                    code,
                                    success=True,
                                    message='معامله قبلاً تأیید شده بود؛ فایل به‌عنوان فروخته‌شده نهایی شد.',
                                    category='success',
                                    new_status='sold',
                                    tx_mode='hidden',
                                    can_revisit=False,
                                )
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
                            
                            # همیشه پورسانت معاملهٔ pending بساز تا کارت تأیید ادمین در روند بازدید بیاید
                            if commission_blocks_new_deal_record(commissions, partner_phone, str(code)):
                                current_app.logger.info(
                                    "Pending deal commission already exists for partner %s land %s",
                                    partner_phone,
                                    code,
                                )
                                skipped_count += 1
                            else:
                                if commission_pct <= 0:
                                    current_app.logger.warning(
                                        "Commission percentage missing for partner %s land %s — creating pending deal for admin close",
                                        partner_phone,
                                        code,
                                    )
                                if commission_amount <= 0 and commission_pct > 0:
                                    current_app.logger.warning(
                                        "Commission amount is 0 for partner %s, land %s: price=%s, pct=%s",
                                        partner_phone, code, price_total, commission_pct,
                                    )
                                new_id = (max([int(x.get('id', 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
                                try:
                                    safe_amount = max(0, int(commission_amount or 0))
                                except Exception:
                                    safe_amount = 0
                                try:
                                    safe_pct = float(commission_pct or 0)
                                except Exception:
                                    safe_pct = 0.0
                                new_commission = {
                                    'id': new_id,
                                    'commission_type': 'deal',
                                    'partner_phone': partner_phone,
                                    'land_code': str(code),
                                    'sale_amount': price_total,
                                    'commission_pct': safe_pct,
                                    'commission_amount': safe_amount,
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
                                        amount=safe_amount,
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
                                        amount=safe_amount,
                                        land_code=str(code),
                                        reference_id=str(new_id),
                                    )
                                except Exception:
                                    current_app.logger.exception(
                                        'commission_pending SMS failed partner=%s land=%s',
                                        partner_phone,
                                        code,
                                    )
                                current_app.logger.info(
                                    f"Created commission record {new_id} for partner {partner_phone} and land {code}: amount={safe_amount}, pct={safe_pct}, price={price_total}"
                                )
                                # Phase 4 Closing: sync Deal adapter (fail-open; does not mutate commission).
                                try:
                                    from app.closing.deal_bridge import maybe_sync_deal_from_commission
                                    maybe_sync_deal_from_commission(
                                        partner_phone=partner_phone,
                                        land_code=str(code),
                                        commission_id=str(new_id),
                                        sale_amount=price_total,
                                        assignment_status='in_transaction',
                                        deal_status='in_transaction',
                                    )
                                except Exception:
                                    pass
                        
                        if created_count > 0:
                            save_express_commissions(commissions)
                            success_message = (
                                'فروش نهایی ثبت شد. پس از تأیید ادمین، فایل بسته می‌شود '
                                'و پورسانت به کیف پول شما اضافه می‌شود.'
                            )
                        else:
                            if skipped_count > 0:
                                success_message = (
                                    'فروش نهایی ثبت شد|پورسانت در صف تأیید ادمین است. '
                                    'پس از تأیید، فایل بسته و مبلغ به کیف پول اضافه می‌شود.'
                                )
                            else:
                                success_message = (
                                    'فروش نهایی ثبت شد. پس از تأیید ادمین، فایل بسته می‌شود '
                                    'و پورسانت به کیف پول شما اضافه می‌شود.'
                                )
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
                    # Phase 4 Closing: cancel mirrored Deal(s) on release (fail-open).
                    try:
                        from app.closing.deal_bridge import maybe_sync_deal_from_commission
                        maybe_sync_deal_from_commission(
                            partner_phone=me_phone,
                            land_code=str(code),
                            assignment_status='active',
                            deal_status='cancelled',
                        )
                    except Exception:
                        pass
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
                can_revisit=tx_state.get('can_revisit'),
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


@express_partner_bp.route('/logout', methods=['GET', 'POST'], endpoint='logout')
def logout():
    """خروج با POST؛ GET فقط برای جلوگیری از 405 اگر URL روی /logout مانده باشد."""
    from ..utils.flash_messages import FLASH_AUTH_INFO

    dest = _logout_dest_url()
    if request.method == 'GET':
        if session.get('user_phone'):
            _clear_express_partner_auth_session()
        r = redirect(dest)
        r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        r.headers['Pragma'] = 'no-cache'
        return r

    _clear_express_partner_auth_session()
    flash('از حساب خارج شدید.', FLASH_AUTH_INFO)
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

    issued_ok, issued_err = _issue_partner_login_otp(phone)
    if not issued_ok:
        msg, status = _partner_otp_fail_payload(issued_err)
        return jsonify({'success': False, 'error': msg}), status
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
    if sess_phone and req_phone != sess_phone:
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
        issued_ok, issued_err = _issue_partner_login_otp(phone)
        if not issued_ok:
            msg, status = _partner_otp_fail_payload(issued_err)
            return jsonify({'ok': False, 'error': msg}), status
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
    """صفحه پروفایل حذف شد — گزینه‌ها در منوی راست داشبورد هستند."""
    me_phone = (session.get('user_phone') or '').strip()
    if not me_phone:
        return redirect(url_for('express_partner.home', menu=1))
    return redirect(url_for('express_partner.home', menu=1), code=302)


@express_partner_bp.route('/listings', methods=['GET'], endpoint='special_listings')
@require_special_partner()
def special_listings_page():
    """آگهی‌های من — همکار ویژه."""
    me_phone = (session.get('user_phone') or '').strip()
    from .special_listings import listings_owned_by
    from ..utils.images import partner_card_image_url

    items = []
    for land in listings_owned_by(me_phone):
        items.append({
            'code': land.get('code') or '',
            'title': land.get('title') or '—',
            'city': land.get('city') or '',
            'price_total': int(land.get('price_total') or 0),
            'image_url': partner_card_image_url(land) or None,
            'detail_url': url_for('express_partner.land_detail', code=land.get('code')),
        })
    from .home_ads_config import partner_divar_profile_entries
    divar_entries = partner_divar_profile_entries(me_phone)
    return render_template(
        'express_partner/special_listings.html',
        items=items,
        divar_profile_entries=divar_entries,
        divar_profile_urls=[e.get('url') for e in divar_entries if e.get('url')],
        hide_header=True,
        bottom_nav_active='profile',
    )


@express_partner_bp.post('/listings/divar-profile', endpoint='special_listings_divar_profile')
@require_special_partner()
def special_listings_divar_profile():
    """افزودن، ویرایش پورسانت، یا حذف پروفایل دیوار Pro توسط همکار پلاس."""
    me_phone = (session.get('user_phone') or '').strip()
    from .home_ads_config import (
        add_partner_divar_profile_url,
        remove_partner_divar_profile_url,
        set_partner_divar_profile_commission,
    )

    action = (request.form.get('action') or '').strip()
    if action == 'add':
        ok, msg, _ = add_partner_divar_profile_url(
            me_phone,
            request.form.get('profile_url') or '',
            request.form.get('commission_pct'),
        )
        flash(msg, 'success' if ok else 'error')
    elif action == 'set_commission':
        ok, msg, _ = set_partner_divar_profile_commission(
            me_phone,
            request.form.get('profile_url') or '',
            request.form.get('commission_pct'),
        )
        flash(msg, 'success' if ok else 'error')
    elif action == 'remove':
        ok, msg, _ = remove_partner_divar_profile_url(
            me_phone, request.form.get('profile_url') or ''
        )
        flash(msg, 'success' if ok else 'error')
    else:
        flash('درخواست نامعتبر است.', 'error')
    return redirect(url_for('express_partner.special_listings', divar_open=1))


@express_partner_bp.route('/listings/upload-image', methods=['POST'], endpoint='special_listing_upload_image')
@require_special_partner(json_response=True)
def special_listing_upload_image():
    """آپلود فوری تصویر — همان رفتار فرم ادمین اکسپرس."""
    from werkzeug.utils import secure_filename
    from ..utils.images import normalize_upload_url, save_upload_image

    f = request.files.get('file') or request.files.get('image')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    upload_folder = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    stored = save_upload_image(f, upload_folder)
    if not stored:
        return jsonify({'ok': False, 'error': 'ذخیره تصویر ناموفق بود.'}), 400

    return jsonify({
        'ok': True,
        'path': stored,
        'url': normalize_upload_url(stored),
    })


@express_partner_bp.route('/listings/upload-video', methods=['POST'], endpoint='special_listing_upload_video')
@require_special_partner(json_response=True)
def special_listing_upload_video():
    """آپلود فوری ویدئو — همان رفتار فرم ادمین اکسپرس."""
    from werkzeug.utils import secure_filename
    from ..utils.images import normalize_upload_url

    f = request.files.get('file') or request.files.get('video')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    file_ext = os.path.splitext(f.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return jsonify({'ok': False, 'error': 'فرمت ویدئو مجاز نیست.'}), 400

    upload_folder = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{f.filename}")
    f.save(os.path.join(upload_folder, filename))
    stored = f'uploads/{filename}'
    return jsonify({
        'ok': True,
        'path': stored,
        'url': normalize_upload_url(stored),
        'name': f.filename,
    })


@express_partner_bp.route('/listings/upload-document', methods=['POST'], endpoint='special_listing_upload_document')
@require_special_partner(json_response=True)
def special_listing_upload_document():
    """آپلود فوری مدرک — همان رفتار فرم ادمین اکسپرس."""
    from .special_listings import save_special_listing_upload_document

    f = request.files.get('file') or request.files.get('document')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
    file_ext = os.path.splitext(f.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return jsonify({'ok': False, 'error': 'فرمت مدرک مجاز نیست (PDF · JPG · PNG).'}), 400

    stored = save_special_listing_upload_document(f)
    if not stored:
        return jsonify({'ok': False, 'error': 'ذخیره مدرک ناموفق بود.'}), 400

    return jsonify({
        'ok': True,
        'path': stored,
        'name': f.filename,
    })


def _render_special_listing_form(me_phone: str = ''):
    """فرم ثبت آگهی همکار ویژه — قالب مشترک با ادمین، داخل شِل پرتال."""
    cities = load_active_cities() or []
    phone = (me_phone or '').strip()
    return render_template(
        'express_partner/special_listing_new.html',
        cities=cities,
        is_edit=False,
        land={},
        form_values={'vinor_contact': phone} if phone else {},
        listing_code='',
        listing_form_action=url_for('express_partner.special_listing_new'),
        listing_back_url=url_for('express_partner.special_listings'),
        listing_upload_image_url=url_for('express_partner.special_listing_upload_image'),
        listing_upload_video_url=url_for('express_partner.special_listing_upload_video'),
        listing_upload_document_url=url_for('express_partner.special_listing_upload_document'),
        listing_page_title='ثبت آگهی',
        listing_page_subtitle='اطلاعات ملک را وارد و منتشر کنید',
        listing_vinor_contact_locked=True,
        listing_vinor_contact_default=phone,
        listing_hide_contact_section=True,
        listing_hide_builtin_header=True,
        listing_hide_expert_verified=True,
        listing_partner_shell=True,
        hide_header=True,
        listing_submit_label='ثبت و انتشار آگهی',
    )


@express_partner_bp.route('/listings/new', methods=['GET', 'POST'], endpoint='special_listing_new')
@require_special_partner()
def special_listing_new():
    """ثبت آگهی همکار ویژه — همان قالب و فیلدهای ثبت آگهی اکسپرس ادمین."""
    me_phone = (session.get('user_phone') or '').strip()
    cities = load_active_cities() or []

    if request.method == 'POST':
        from .special_listings import (
            SPECIAL_LISTING_ERRORS,
            assign_land_to_all_partners,
            create_special_listing_from_express_form,
        )

        rec, err = create_special_listing_from_express_form(
            owner_phone=me_phone,
            form=request.form,
            files=request.files,
            cities=cities,
        )
        if err:
            flash(SPECIAL_LISTING_ERRORS.get(err, 'ثبت آگهی ناموفق بود.'), 'error')
            return _render_special_listing_form(me_phone)

        try:
            from .new_land_sms import notify_all_partners_new_express_land_background
            notify_all_partners_new_express_land_background(rec)
        except Exception:
            current_app.logger.exception(
                'special listing SMS queue failed code=%s', rec.get('code')
            )

        if (request.form.get('auto_send_all_partners') or '').strip():
            extras = rec.get('extras') if isinstance(rec.get('extras'), dict) else {}
            pct = float(extras.get('express_commission_pct') or 0)
            assign_land_to_all_partners(rec, pct)

        flash(f'آگهی با کد {rec.get("code")} ثبت شد.', 'success')
        return redirect(url_for('express_partner.special_listings'))

    return _render_special_listing_form(me_phone)


@express_partner_bp.route('/inbox-visits', methods=['GET'], endpoint='special_visit_inbox')
@require_partner_access(allow_pending=True)
def special_visit_inbox_page():
    """صندوق بازدید پلاس — ادغام‌شده در صفحهٔ پیگیری."""
    kwargs = {'tab': 'visits'}
    if (request.args.get('schedule') or '').strip() == '1':
        kwargs['schedule'] = 1
    return redirect(_sales_pipeline_url(**kwargs))


@express_partner_bp.post('/inbox-visits/schedule', endpoint='special_visit_schedule')
@require_special_partner()
def special_visit_schedule():
    """وقت بازدید مجاز این همکار پلاس."""
    me_phone = (session.get('user_phone') or '').strip()
    from .visit_requests import (
        get_plus_visit_presence_address,
        save_plus_visit_schedule,
        visit_allowed_hours_summary,
        visit_allowed_weekdays_summary,
    )

    raw_days = request.form.getlist('visit_weekdays')
    raw_hours = request.form.getlist('visit_hours')
    try:
        parsed_days = [int(x) for x in raw_days]
    except ValueError:
        parsed_days = []
    parsed_hours: list[int] = []
    for item in raw_hours:
        try:
            parsed_hours.append(int(item))
        except ValueError:
            continue
    inbox_url = _sales_pipeline_url('visits', schedule=1)
    if not parsed_days:
        flash('حداقل یک روز هفته را برای بازدید انتخاب کنید.', 'warning')
        return redirect(inbox_url)
    if not parsed_hours:
        flash('حداقل یک ساعت مجاز بازدید را انتخاب کنید.', 'warning')
        return redirect(inbox_url)
    _days, _hrs, err = save_plus_visit_schedule(
        me_phone,
        weekdays=parsed_days,
        hours=parsed_hours,
        presence_address=(request.form.get('visit_presence_address') or ''),
    )
    if err:
        flash(err, 'warning')
        return redirect(inbox_url)
    addr = get_plus_visit_presence_address(me_phone)
    msg = (
        f'وقت‌های بازدید شما ذخیره شد: {visit_allowed_weekdays_summary(plus_user_phone=me_phone)} — ساعت {visit_allowed_hours_summary(plus_user_phone=me_phone)}'
    )
    if addr:
        msg += f' · آدرس حضور: {addr}'
    flash(msg, 'success')
    return redirect(_sales_pipeline_url('visits'))


@express_partner_bp.route('/inbox-offers', methods=['GET'], endpoint='special_offer_inbox')
@require_special_partner()
def special_offer_inbox_page():
    """Phase 3 — صندوق پیشنهاد روی آگهی‌های ویژه (فلگ commercial UI)."""
    try:
        from app.commercial.config import commercial_ui_enabled
        if not commercial_ui_enabled():
            from flask import abort
            abort(404)
    except Exception:
        from flask import abort
        abort(404)
    me_phone = (session.get('user_phone') or '').strip()
    from .special_offer_inbox import offers_for_special_owner

    items = offers_for_special_owner(me_phone)
    return render_template(
        'express_partner/special_offer_inbox.html',
        items=items,
        hide_header=True,
        bottom_nav_active='profile',
    )


@express_partner_bp.post('/inbox-offers/<oid>/<action>', endpoint='special_offer_action')
@require_special_partner()
def special_offer_action(oid: str, action: str):
    try:
        from app.commercial.config import commercial_ui_enabled
        if not commercial_ui_enabled():
            from flask import abort
            abort(404)
    except Exception:
        from flask import abort
        abort(404)
    me_phone = (session.get('user_phone') or '').strip()
    from .special_offer_inbox import apply_special_offer_action

    try:
        amount = int(request.form.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    _out, err = apply_special_offer_action(
        owner_phone=me_phone,
        offer_id=str(oid),
        action=str(action or ''),
        amount=amount,
        terms=(request.form.get('terms') or '').strip(),
    )
    if err == 'not_found':
        flash('پیشنهاد یافت نشد.', 'warning')
    elif err == 'forbidden':
        flash('اجازه ندارید.', 'warning')
    elif err == 'disabled':
        flash('ماژول پیشنهاد فعلاً فعال نیست.', 'warning')
    elif err:
        flash('اقدام ناموفق بود.', 'warning')
    else:
        flash('انجام شد.', 'success')
    if (request.form.get('return_to') or '').strip() == 'visits':
        return redirect(_sales_pipeline_url('deals'))
    return redirect(url_for('express_partner.special_offer_inbox'))


@express_partner_bp.post('/inbox-visits/<vid>/<action>', endpoint='special_visit_action')
@require_special_partner()
def special_visit_action(vid: str, action: str):
    """تأیید / رد / تأیید انجام بازدید توسط همکار ویژه."""
    me_phone = (session.get('user_phone') or '').strip()
    from .special_visit_inbox import apply_special_visit_action
    from .visit_sms import notify_partner_land_tx_sms, visit_status_change_event

    visit_requests = load_express_visit_requests() or []
    if not isinstance(visit_requests, list):
        visit_requests = []

    prev = next(
        (r for r in visit_requests if isinstance(r, dict) and str(r.get('id') or '') == str(vid)),
        None,
    )
    prev_status = str((prev or {}).get('status') or '') if prev else ''

    rec, err = apply_special_visit_action(
        visit_requests,
        owner_phone=me_phone,
        visit_id=str(vid),
        action=str(action or ''),
        outcome=(request.form.get('outcome') or '').strip(),
        notes=(request.form.get('notes') or '').strip(),
    )
    if err == 'not_found':
        flash('درخواست پیدا نشد.', 'warning')
        return redirect(_sales_pipeline_url('visits'))
    if err == 'forbidden':
        flash('اجازه مدیریت این درخواست را ندارید.', 'warning')
        return redirect(_sales_pipeline_url('visits'))
    if err == 'disabled':
        flash('ثبت نتیجه بازدید فعلاً فعال نیست.', 'warning')
        return redirect(_sales_pipeline_url('visits'))
    if err == 'invalid_transition':
        flash(
            'این تغییر مجاز نیست. تأیید انجام فقط وقتی ممکن است که همکار «بازدید انجام شد» را ثبت کرده باشد.',
            'warning',
        )
        return redirect(_sales_pipeline_url('visits'))
    extra_err = {
        'no_assignment': 'این همکار روی فایل اختصاص ندارد؛ معامله فقط از سمت همکار اختصاص‌یافته ممکن است.',
        'already_sold': 'این فایل قبلاً فروخته شده است.',
        'held_by_other': 'فایل در حال معامله توسط همکار دیگری است.',
        'deal_limit': 'این همکار هم‌زمان روی دو فایل در حال معامله است.',
        'already_pending': 'فروش نهایی قبلاً ثبت شده و منتظر تأیید شماست.',
        'blocked': 'رد معامله فعلاً ممکن نیست.',
        'invalid_status': 'اول «بازدید انجام شد» را ثبت کنید.',
        'invalid_outcome': 'یکی از سه نتیجه را انتخاب کنید.',
    }
    if err and err in extra_err:
        flash(extra_err[err], 'warning')
        return redirect(_sales_pipeline_url('visits'))
    if err and err not in ('unchanged', 'note_updated', 'already_completed'):
        flash('تغییر وضعیت ناموفق بود.', 'warning')
        return redirect(_sales_pipeline_url('visits'))

    act_l = str(action or '').strip().lower()
    deal_only = act_l in ('start_deal', 'approve_deal', 'reject_deal')
    if not deal_only:
        try:
            save_express_visit_requests(visit_requests)
        except Exception:
            current_app.logger.exception('special visit action save failed id=%s', vid)
            flash('ذخیره وضعیت ناموفق بود.', 'danger')
            return redirect(_sales_pipeline_url('visits'))

    if rec and err not in ('unchanged',):
        new_status = str(rec.get('status') or '')
        sms_event = visit_status_change_event(new_status, prev_status)
        if sms_event:
            try:
                notify_partner_land_tx_sms(
                    partner_phone=str(rec.get('partner_phone') or ''),
                    event=sms_event,
                    land_code=str(rec.get('land_code') or ''),
                    land_title=str(rec.get('land_title') or ''),
                    visit_date=str(rec.get('visit_date') or ''),
                    reference_id=str(rec.get('id') or ''),
                    visit_commission_pending=False,
                )
            except Exception:
                current_app.logger.exception(
                    'special visit partner SMS failed id=%s event=%s', vid, sms_event
                )
        if act_l in ('complete', 'no_show'):
            try:
                from .special_visit_inbox import inject_visit_attendance_chat

                inject_visit_attendance_chat(
                    rec, outcome='done' if act_l == 'complete' else 'no_show'
                )
            except Exception:
                current_app.logger.exception('visit attendance chat inject failed id=%s', vid)
        if act_l in ('confirm_deal', 'decline_deal', 'close_deal'):
            try:
                from .special_visit_inbox import inject_visit_deal_chat

                inject_visit_deal_chat(
                    rec,
                    decision={
                        'confirm_deal': 'approved',
                        'decline_deal': 'rejected',
                        'close_deal': 'closed',
                    }[act_l],
                )
            except Exception:
                current_app.logger.exception('deal decision chat inject failed id=%s', vid)
        if act_l == 'result':
            try:
                from .special_visit_inbox import inject_visit_outcome_chat

                inject_visit_outcome_chat(
                    rec, outcome=(request.form.get('outcome') or '').strip()
                )
            except Exception:
                current_app.logger.exception('visit outcome chat inject failed id=%s', vid)

    if act_l == 'approve':
        flash('بازدید تأیید شد.', 'success')
    elif act_l == 'reject':
        flash('بازدید رد شد.', 'info')
    elif act_l == 'complete':
        flash('بازدید انجام شد. حالا نتیجه را ثبت کنید.', 'success')
    elif act_l == 'no_show':
        flash('عدم حضور ثبت شد.', 'info')
    elif act_l == 'reject_done':
        flash('انجام بازدید رد شد. همکار می‌تواند دوباره اعلام کند.', 'info')
    elif act_l == 'start_deal':
        flash('فروش نهایی ثبت شد. با تأیید شما فایل بسته می‌شود.', 'success')
    elif act_l == 'approve_deal':
        flash('فروش نهایی تأیید شد: فایل بسته شد و پورسانت به کیف پول همکار اضافه شد.', 'success')
    elif act_l == 'reject_deal':
        flash('معامله رد شد. همکار می‌تواند دوباره درخواست بدهد.', 'info')
    elif act_l == 'confirm_deal':
        flash('معامله تأیید شد.', 'success')
    elif act_l == 'decline_deal':
        flash('معامله رد شد.', 'info')
    elif act_l == 'close_deal':
        flash('پرونده بسته شد.', 'success')
    elif act_l == 'result':
        oc = (request.form.get('outcome') or '').strip()
        if oc == 'interested':
            flash('علاقه‌مند ثبت شد. وقت بازدید دوباره یا قرارداد نهایی را تنظیم کنید.', 'success')
        elif oc == 'follow_up':
            flash('پیگیری دوباره ثبت شد. بازاریاب تا تعیین وقت بازدید دوم پیگیری می‌کند.', 'success')
        elif oc == 'not_interested':
            flash('بی‌علاقه ثبت شد — بدون پیگیری.', 'info')
        else:
            flash('نتیجه بازدید ثبت شد.', 'success')
    else:
        flash('وضعیت بروزرسانی شد.', 'success')
    if act_l in (
        'start_deal', 'approve_deal', 'reject_deal',
        'confirm_deal', 'decline_deal', 'close_deal',
    ):
        pipeline_tab = 'deals'
    elif act_l == 'result' and (request.form.get('outcome') or '').strip() == 'interested':
        pipeline_tab = 'deals'
    else:
        pipeline_tab = 'visits'
    return redirect(_sales_pipeline_url(pipeline_tab))


@express_partner_bp.get('/profile/data', endpoint='profile_data')
@require_partner_access(allow_pending=True, allow_guest=True)
def profile_data():
    """API JSON برای اپ اندروید: داده پروفایل همکار (برای صفحه من نیتیو)."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    try:
        is_approved = _is_partner_approved(profile)
    except Exception:
        is_approved = False
    me_name = (profile.get('name') or '').strip()
    avatar = (profile.get('avatar') or '').strip()
    from ..utils.images import display_avatar_url
    avatar_url = display_avatar_url(avatar, profile.get('avatar_updated_at')) if avatar else None
    _settings = _express_settings_cached()
    _raw_apk_url = (_settings.get('android_apk_url') or '').strip()
    android_apk_version = (_settings.get('android_apk_version') or '').strip()
    from ..utils.short_urls import canonical_public_apk_download_url
    android_apk_url = canonical_public_apk_download_url(_settings) if _raw_apk_url else ''
    from ..utils.apk_version import resolve_android_apk_version_code, should_show_apk_update
    show_app_update = should_show_apk_update(
        android_apk_version,
        apk_url=_raw_apk_url,
        req=request,
        server_version_code=resolve_android_apk_version_code(_settings),
    )
    try:
        from flask_wtf.csrf import generate_csrf
        csrf_token = generate_csrf()
    except Exception:
        csrf_token = ''
    is_special = _is_partner_special(profile) if is_approved else False
    visit_inbox_count = 0
    if is_special:
        try:
            from .special_visit_inbox import visit_inbox_badge_count

            visit_inbox_count = int(visit_inbox_badge_count(me_phone) or 0)
        except Exception:
            visit_inbox_count = 0
    plus_system_on = False
    lawyer_feature_on = False
    try:
        from .zarinpal_config import plus_system_enabled as _plus_system_enabled

        plus_system_on = bool(_plus_system_enabled())
    except Exception:
        plus_system_on = False
    try:
        from app.lawyer.config import lawyer_enabled as _lawyer_enabled

        lawyer_feature_on = bool(_lawyer_enabled())
    except Exception:
        lawyer_feature_on = False
    return jsonify({
        'success': True,
        'me_phone': me_phone,
        'me_name': me_name or 'همکار وینور',
        'avatar_url': avatar_url,
        'is_approved': is_approved,
        'is_special': is_special,
        'visit_inbox_count': visit_inbox_count,
        'partner_tier': _partner_tier_label(profile, is_approved=is_approved),
        'android_apk_url': android_apk_url if show_app_update else '',
        'android_apk_version': android_apk_version if show_app_update else '',
        'show_app_update': show_app_update,
        'csrf_token': csrf_token,
        'plus_system_enabled': plus_system_on,
        'lawyer_feature_on': lawyer_feature_on,
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


def _build_partner_memory_snapshot(me_phone: str) -> Dict[str, Any]:
    """خلاصهٔ سبک حافظهٔ زنده — برای صفحهٔ حافظه و polling (بدون KPI سنگین)."""
    ph = _canonical_partner_phone(me_phone or '')
    live_summary = ''
    updated_at = ''
    source = ''
    land_codes: List[str] = []
    land_cards: List[Dict[str, str]] = []
    try:
        from app.express_partner.partner_live_memory import (
            load_partner_live_memory,
            memory_source_of,
        )

        saved = load_partner_live_memory(ph)
        live_summary = str((saved or {}).get('summary') or '').strip()
        updated_at = str((saved or {}).get('updated_at') or '').strip()
        source = memory_source_of(saved)
        meta = (saved or {}).get('meta') if isinstance((saved or {}).get('meta'), dict) else {}
        raw_codes = meta.get('land_codes') if isinstance(meta.get('land_codes'), list) else []
        land_codes = [str(c).strip() for c in raw_codes if str(c).strip()][:3]
    except Exception:
        live_summary = ''
        updated_at = ''
        source = ''
        land_codes = []
    if not land_codes and ph:
        try:
            from app.express_partner.partner_missions import get_active_mission

            mission = get_active_mission(ph)
            code = str((mission or {}).get('land_code') or '').strip()
            if code:
                land_codes = [code]
        except Exception:
            pass
    if land_codes:
        try:
            from app.ai.land_cards import land_cards_payload, strip_visible_land_codes

            land_cards = land_cards_payload(
                ph, land_codes, audience='partner', layout='compact'
            ) or []
            if live_summary:
                live_summary = strip_visible_land_codes(live_summary, land_codes)
        except Exception:
            land_cards = []
    has_memory = bool(live_summary)
    if not updated_at:
        updated_at = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'ok': True,
        'updated_at': updated_at,
        'me_phone': ph,
        'summary': live_summary,
        'has_memory': has_memory,
        'source': source,
        'land_codes': land_codes,
        'land_cards': land_cards,
    }


@express_partner_bp.route('/settings', methods=['GET'], endpoint='settings')
@require_partner_access(allow_pending=True)
def settings_page():
    """هاب تنظیمات همکار — پروفایل، خروج."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    partners = load_express_partners() or []
    profile = _find_partner_record(partners, me_phone) or {'phone': me_phone}
    is_approved = _is_partner_approved(profile)
    me_name = (str((profile or {}).get('name') or '')).strip()
    partner_name = me_name or (_partner_display_name(me_phone) if me_phone else '')
    return render_template(
        'express_partner/settings.html',
        me_phone=me_phone,
        me_name=me_name,
        partner_name=partner_name,
        profile=profile,
        is_approved=is_approved,
        is_special=_is_partner_special(profile) if is_approved else False,
        hide_header=True,
        bottom_nav_active='profile',
        seo_title='تنظیمات | وینور اکسپرس',
    )


@express_partner_bp.route('/settings/memory', methods=['GET'], endpoint='settings_memory')
@require_partner_access(allow_pending=True)
def settings_memory_page():
    """صفحهٔ حافظهٔ همکار — خلاصهٔ زنده مثل Memory در ChatGPT."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    partners = load_express_partners() or []
    profile = _find_partner_record(partners, me_phone) or {'phone': me_phone}
    is_approved = _is_partner_approved(profile)
    is_special = _is_partner_special(profile) if is_approved else False
    me_name = (str((profile or {}).get('name') or '')).strip()
    partner_name = me_name or (_partner_display_name(me_phone) if me_phone else '')
    report = _build_partner_memory_snapshot(me_phone)
    return render_template(
        'express_partner/settings_memory.html',
        me_phone=me_phone,
        me_name=me_name,
        partner_name=partner_name,
        profile=profile,
        is_approved=is_approved,
        is_special=is_special,
        report=report,
        hide_header=True,
        bottom_nav_active='profile',
        seo_title='حافظه | وینور اکسپرس',
    )


@express_partner_bp.route('/plus', methods=['GET', 'POST'], endpoint='plus')
@require_partner_access(allow_pending=True, allow_guest=True)
def plus_page():
    """صفحهٔ خرید / ارتقا به وینور پلاس — پرداخت زرین‌پال (اولویت) یا درخواست SMS."""
    from .partner_session_sync import canonical_partner_phone, sync_partner_session_after_plus
    from .zarinpal_config import plus_system_enabled

    if not plus_system_enabled():
        flash('سیستم Vinor Plus در حال حاضر در دسترس نیست.', 'warning')
        return redirect(url_for('express_partner.home'))

    me_phone = canonical_partner_phone(session.get('user_phone') or '')
    if request.args.get('plus_activated') and me_phone:
        sync_partner_session_after_plus(me_phone)
    profile = getattr(g, 'express_partner_profile', None)
    if profile is None and me_phone:
        _ensure_session_partner_on_g()
        profile = getattr(g, 'express_partner_profile', None)
        if profile is None:
            profile = _partner_profile_for_phone(me_phone)
    elif me_phone:
        from .plus_subscription import persist_plus_expiry_backfill_for_phone

        if persist_plus_expiry_backfill_for_phone(me_phone):
            for key in ('_express_partners_list_cached', '_express_partner_by_phone', '_express_partner_ctx_ready'):
                if hasattr(g, key):
                    try:
                        delattr(g, key)
                    except Exception:
                        pass
            _ensure_session_partner_on_g()
            profile = getattr(g, 'express_partner_profile', None) or _partner_profile_for_phone(me_phone)
    is_special = _is_partner_special(profile) if isinstance(profile, dict) else False
    settings_root = load_settings() or {}
    from .plus_subscription import (
        PLUS_RENEW_WINDOW_DAYS,
        plus_period_label,
        plus_renew_allowed,
        plus_subscription_view,
    )
    from .zarinpal_config import (
        payment_flow_active,
        plus_amount_toman,
        plus_subscription_days,
        zarinpal_payment_primary,
    )

    sub_days = plus_subscription_days()
    plus_sub = plus_subscription_view(profile if isinstance(profile, dict) else None)
    plus_price = plus_amount_toman(settings_root)

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action not in ('pay_plus', 'request_plus'):
            return redirect(url_for('express_partner.plus'))
        if not me_phone:
            flash('برای دریافت پلاس ابتدا وارد شوید.', 'error')
            return redirect(url_for('express_partner.home', menu=1))
        if is_special and action == 'request_plus':
            flash('اشتراک پلاس شما از قبل فعال است.', 'success')
            return redirect(url_for('express_partner.plus'))

        if action == 'pay_plus' and is_special and not plus_renew_allowed(
            profile if isinstance(profile, dict) else None
        ):
            flash(
                f'تمدید اشتراک از {PLUS_RENEW_WINDOW_DAYS} روز قبل از پایان امکان‌پذیر است.',
                'error',
            )
            return redirect(url_for('express_partner.plus'))

        want_pay = action == 'pay_plus' or (
            zarinpal_payment_primary() and payment_flow_active()
        )
        if want_pay and payment_flow_active():
            from .plus_checkout import begin_plus_payment

            pname = (profile.get('name') if isinstance(profile, dict) else None) or me_phone
            ok, pay_url, err = begin_plus_payment(phone=me_phone, partner_name=str(pname))
            if ok and pay_url:
                return redirect(pay_url)
            detail = (err or '').strip()
            if detail and detail not in ('payment_not_configured', 'request_failed', 'invalid_response'):
                flash(
                    f'اتصال به درگاه پرداخت ممکن نشد ({detail}). لطفاً بعداً دوباره تلاش کنید.',
                    'error',
                )
            else:
                flash('اتصال به درگاه پرداخت ممکن نشد. لطفاً بعداً دوباره تلاش کنید.', 'error')
            return redirect(url_for('express_partner.plus'))

        if action == 'pay_plus':
            flash(
                'درگاه پرداخت آنلاین هنوز پیکربندی نشده است (مرچنت در حالت production لازم است). '
                'از دکمهٔ «دریافت پلاس» برای ثبت درخواست دستی استفاده کنید یا در پنل ادمین مرچنت را وارد کنید.',
                'error',
            )
            return redirect(url_for('express_partner.plus'))

        # fallback: SMS به ادمین — وقتی پرداخت غیرفعال است یا VINOR_ZARINPAL_PLUS_PAYMENT_PRIMARY=0
        try:
            from .admin_action_sms import notify_admin_pending_action

            notify_admin_pending_action(
                'vinor_plus',
                partner_phone=me_phone,
                partner_name=(
                    (profile.get('name') if isinstance(profile, dict) else None) or me_phone
                ),
                detail=f'درخواست Vinor Plus · {me_phone}',
            )
        except Exception:
            pass
        flash(
            'درخواست پلاس ثبت شد. به‌زودی برای فعال‌سازی با شما هماهنگ می‌شود.',
            'success',
        )
        return redirect(url_for('express_partner.plus'))

    pay_enabled = payment_flow_active() and zarinpal_payment_primary()
    renew_allowed = plus_renew_allowed(profile if isinstance(profile, dict) else None)
    return render_template(
        'express_partner/plus.html',
        me_phone=me_phone,
        is_special=is_special,
        plus_subscription=plus_sub,
        plus_price_toman=plus_price,
        plus_period_label=plus_period_label(sub_days),
        plus_payment_enabled=pay_enabled,
        plus_renew_allowed=renew_allowed,
        plus_renew_window_days=PLUS_RENEW_WINDOW_DAYS,
        hide_header=True,
        seo_title='وینور پلاس | ارتقا',
    )


@express_partner_bp.route('/plus/zarinpal/callback', methods=['GET'], endpoint='plus_zarinpal_callback')
@require_partner_access(allow_pending=True, allow_guest=True)
def plus_zarinpal_callback():
    """بازگشت از درگاه — Status=OK|NOK و Authority."""
    from .zarinpal_config import plus_system_enabled
    from .plus_checkout import handle_callback_http

    if not plus_system_enabled():
        flash('سیستم پرداخت Vinor Plus غیرفعال است.', 'error')
        return redirect(url_for('express_partner.home'))

    authority = (request.args.get('Authority') or request.args.get('authority') or '').strip()
    status_param = (request.args.get('Status') or request.args.get('status') or '').strip()
    return handle_callback_http(authority, status_param)


@express_partner_bp.get('/settings/data', endpoint='settings_data')
@require_partner_access(allow_pending=True, json_response=True)
def settings_data():
    """JSON سبک حافظهٔ زنده برای polling صفحهٔ حافظه."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    return jsonify(_build_partner_memory_snapshot(me_phone))


@express_partner_bp.post('/settings/memory/clear', endpoint='settings_memory_clear')
@require_partner_access(allow_pending=True, json_response=True)
def settings_memory_clear():
    """پاک‌کردن خلاصهٔ حافظهٔ زندهٔ همکار از صفحهٔ تنظیمات."""
    me_phone = _canonical_partner_phone(session.get('user_phone') or '')
    if not me_phone:
        return jsonify({'ok': False, 'error': 'نشست نامعتبر است.'}), 401
    try:
        from app.express_partner.partner_live_memory import clear_partner_live_memory

        clear_partner_live_memory(me_phone)
    except Exception:
        return jsonify({'ok': False, 'error': 'پاک‌کردن حافظه ممکن نشد.'}), 500
    snap = _build_partner_memory_snapshot(me_phone)
    snap['message'] = 'حافظه پاک شد.'
    return jsonify(snap)


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
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.home', menu=1))
    rel_path = _save_partner_avatar_upload(me_phone, f)
    if not rel_path:
        flash('خطا در ذخیره تصویر پروفایل.', 'profile')
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile_edit'))
    flash('عکس پروفایل به‌روز شد.', 'profile')
    return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile_edit'))


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
    return redirect(url_for("express_partner.home"))


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
    return redirect(url_for("express_partner.home"))


@express_partner_bp.post('/sales/<int:sid>/delete')
@require_partner_access(allow_pending=True)
def delete_sale(sid: int):
    me_phone = (session.get("user_phone") or "").strip()
    items = load_partner_sales() or []
    items = [s for s in items if not (int(s.get('id',0) or 0) == int(sid) and str(s.get('phone')) == me_phone)]
    save_partner_sales(items)
    return redirect(url_for("express_partner.home"))


@express_partner_bp.get('/notifications', endpoint='notifications')
@require_partner_access(allow_pending=True)
def notifications_page():
    from app.services.postchi import POSTCHI_THREAD_ID

    return redirect(url_for('express_partner.home', ai=1, thread=POSTCHI_THREAD_ID))


@express_partner_bp.get('/postchi', endpoint='postchi')
@require_partner_access(allow_pending=True)
def postchi_page():
    from app.services.postchi import POSTCHI_THREAD_ID

    return redirect(url_for('express_partner.home', ai=1, thread=POSTCHI_THREAD_ID))


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
    visit_inbox_count = 0
    try:
        profile = getattr(g, "express_partner_profile", None)
        if _is_partner_special(profile):
            from .special_visit_inbox import visit_inbox_badge_count

            visit_inbox_count = int(visit_inbox_badge_count(me_phone_raw) or 0)
    except Exception:
        visit_inbox_count = 0

    return jsonify({
        "success": True,
        "notifications": notifications,
        "unread_count": unread,
        "visit_inbox_count": visit_inbox_count,
    })


@express_partner_bp.route('/api/notifications/unread-count', methods=['GET'])
@require_partner_access(json_response=True, allow_pending=True)
def get_unread_count():
    """Get unread notifications count"""
    from app.services.notifications import unread_count, _normalize_user_id
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    # استفاده از همان تابع normalize که در notifications.py استفاده می‌شود
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    visit_inbox_count = 0
    try:
        profile = getattr(g, "express_partner_profile", None)
        if _is_partner_special(profile):
            from .special_visit_inbox import visit_inbox_badge_count

            visit_inbox_count = int(visit_inbox_badge_count(me_phone_raw) or 0)
    except Exception:
        visit_inbox_count = 0
    resp = jsonify({
        "success": True,
        "unread_count": unread_count(me_phone),
        "visit_inbox_count": visit_inbox_count,
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


@express_partner_bp.get('/lands/<string:code>/chat-detail', endpoint='land_chat_detail')
@require_partner_access(allow_pending=True, allow_guest=True)
def land_chat_detail(code: str):
    """جزئیات کامل فایل به‌صورت HTML برای تزریق در چت خانه."""
    from .land_chat_detail import render_land_chat_detail_html, track_land_view_async

    code_s = (code or '').strip()
    if not code_s:
        return jsonify({"ok": False, "error": "missing_code"}), 400

    if not _is_prefetch_request():
        track_land_view_async(code_s)
        me_phone = (session.get("user_phone") or "").strip()
        partner_profile = _partner_profile_for_phone(me_phone) if me_phone else None
        if me_phone and _is_partner_approved(partner_profile):
            _defer_routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)

    payload = render_land_chat_detail_html(code_s)
    if not payload:
        return jsonify({
            "ok": False,
            "error": "not_found",
            "message": "این فایل پیدا نشد یا دیگر در دسترس نیست.",
        }), 404

    try:
        from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
        from app.ai.chat_store import record_land_chat_view
        from app.ai.user_key import ai_user_key

        me_phone = (session.get("user_phone") or "").strip()
        uk = me_phone or ai_user_key()
        aud = AUDIENCE_PARTNER if me_phone else AUDIENCE_PUBLIC
        record_land_chat_view(
            uk,
            payload["code"],
            audience=aud,
            title=str(payload.get("title") or ""),
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "code": payload["code"],
        "title": payload.get("title") or "",
        "html": payload["html"],
    })


@express_partner_bp.get('/divar/<string:token>/chat-detail', endpoint='divar_chat_detail')
@require_partner_access(allow_pending=True, allow_guest=True)
def divar_chat_detail(token: str):
    """جزئیات آگهی دیوار به‌صورت HTML برای تزریق در چت خانه."""
    from .divar_pro_ads import sanitize_divar_post_token
    from .land_chat_detail import render_divar_chat_detail_html

    tok = sanitize_divar_post_token(token)
    if not tok:
        return jsonify({"ok": False, "error": "missing_token"}), 400
    payload = render_divar_chat_detail_html(tok)
    if not payload:
        return jsonify({
            "ok": False,
            "error": "not_found",
            "message": "این آگهی دیوار پیدا نشد یا دیگر در دسترس نیست.",
        }), 404
    try:
        from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
        from app.ai.chat_store import record_land_chat_view
        from app.ai.user_key import ai_user_key

        me_phone = (session.get("user_phone") or "").strip()
        uk = me_phone or ai_user_key()
        aud = AUDIENCE_PARTNER if me_phone else AUDIENCE_PUBLIC
        record_land_chat_view(
            uk,
            payload["code"],
            audience=aud,
            title=str(payload.get("title") or ""),
        )
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "code": payload["code"],
        "title": payload.get("title") or "",
        "html": payload["html"],
    })


@express_partner_bp.get('/divar/<string:token>', endpoint='divar_ad_detail')
@require_partner_access(allow_pending=True, allow_guest=True)
def divar_ad_detail(token: str):
    """لینک آگهی دیوار نوار خانه → جزئیات داخل چت وینور."""
    from .divar_pro_ads import sanitize_divar_post_token

    tok = sanitize_divar_post_token(token)
    if not tok:
        return redirect(url_for('express_partner.home'))
    return redirect(url_for('express_partner.home', divar=tok))


@express_partner_bp.get('/lands/<string:code>', endpoint='land_detail')
@require_partner_access(allow_pending=True, allow_guest=True)
def land_detail(code: str):
    """لینک‌های قدیمی جزئیات فایل → خانه + تزریق جزئیات در چت."""
    from ..utils.flash_messages import purge_stale_auth_flashes, purge_stale_land_flashes
    from .land_chat_detail import track_land_view_async

    purge_stale_land_flashes()
    purge_stale_auth_flashes()
    code_s = (code or '').strip()
    if not code_s:
        return redirect(url_for('express_partner.home'))

    lands = load_ads_cached() or []
    land = next((l for l in lands if l.get('code') == code_s and l.get('is_express')), None)
    if not land:
        flash('این آگهی اکسپرس پیدا نشد یا دیگر در دسترس نیست.', 'warning')
        return redirect(url_for('express_partner.home'))

    if not _is_prefetch_request():
        track_land_view_async(code_s)
        me_phone = (session.get("user_phone") or "").strip()
        partner_profile = _partner_profile_for_phone(me_phone) if me_phone else None
        if me_phone and _is_partner_approved(partner_profile):
            _defer_routine_auto_tick(me_phone, ROUTINE_STEP_VISIT)

    return redirect(url_for('express_partner.home', land=code_s))


