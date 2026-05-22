from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

from flask import (
    render_template, request, redirect, url_for, session,
    send_from_directory, current_app, abort, flash, g
)
from functools import wraps
import random, re, time

from . import express_partner_bp
from ..utils.storage import (
    load_express_partner_apps, save_express_partner_apps,
    load_express_partners, save_express_partners, load_partner_notes, save_partner_notes,
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
)
from .partner_bank_accounts import (
    validate_new_account,
    public_account_dict,
    accounts_for_phone,
    catalog_public,
)
from ..services.notifications import get_user_notifications, unread_count, mark_read, mark_all_read
from ..services.sms import send_sms_direct
from flask import jsonify, make_response


def _sort_by_created_at_desc(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..utils.dates import parse_datetime_safe
    return sorted(items, key=lambda x: parse_datetime_safe(x.get('created_at', '1970-01-01')), reverse=True)


def _express_partners_cached() -> List[Dict[str, Any]]:
    """در هر درخواست فقط یک‌بار لیست همکاران از دیسک خوانده می‌شود."""
    cached = getattr(g, '_express_partners_list_cached', None)
    if cached is not None:
        return cached
    try:
        lst = load_express_partners() or []
    except Exception:
        lst = []
    g._express_partners_list_cached = lst
    return lst


def _partner_profile_for_phone(phone: str) -> Dict[str, Any] | None:
    """پروفایل یک همکار از لیست کش‌شدهٔ درخواست (بدون خواندن مجدد فایل)."""
    phone = (phone or '').strip()
    if not phone:
        return None
    by_phone = getattr(g, '_express_partner_by_phone', None)
    if by_phone is None:
        partners = _express_partners_cached()
        by_phone = {
            str(p.get('phone') or '').strip(): p
            for p in partners
            if isinstance(p, dict) and str(p.get('phone') or '').strip()
        }
        g._express_partner_by_phone = by_phone
    return by_phone.get(phone)


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
    cache_key = '_express_my_comms_' + phone
    cached = getattr(g, cache_key, None)
    if cached is not None:
        return cached
    mine = [c for c in _express_commissions_cached() if str(c.get('partner_phone') or '').strip() == phone]
    setattr(g, cache_key, mine)
    return mine


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
        if (c.get('commission_type') or '').strip() == 'referral':
            name = (str(c.get('referred_name') or '')).strip()
            phone = (str(c.get('referred_phone') or '')).strip()
            if name:
                c['_txn_label'] = f'پورسانت دعوت همکار ({name})'
            elif phone:
                c['_txn_label'] = f'پورسانت دعوت همکار ({phone})'
            else:
                c['_txn_label'] = 'پورسانت دعوت همکار'
            continue
        L = lo.get(str(c.get('land_code', '') or ''))
        if L:
            title = (str(L.get('title') or L.get('category') or 'ملک')).strip() or 'ملک'
            city = (str(L.get('city') or '')).strip()
            c['_txn_label'] = f'پورسانت فروش {title}' + (f' در {city}' if city else '')
        else:
            c.setdefault('_txn_label', 'پورسانت فروش')


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


def _normalize_phone(phone: str) -> str:
    """Normalize phone number - استفاده از همان تابع notifications"""
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(phone)
    p = (phone or "").strip()
    p = re.sub(r"\D+", "", p)
    if p.startswith("0098"): p = "0" + p[4:]
    elif p.startswith("98"): p = "0" + p[2:]
    if not p.startswith("0"): p = "0" + p
    return p[:11]


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
        global_status = code_to_global_status.get(code, 'active')
        a = my_by_code.get(code)
        if a and is_approved:
            item['_assignment_id'] = a.get('id')
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_commission_pct'] = a.get('commission_pct')
            item['_is_expired'] = is_ad_expired(land)
            try:
                total_price_str = str(item.get('price_total') or item.get('price') or '0').replace(',', '').strip()
                total_price = int(total_price_str) if total_price_str else 0
            except Exception:
                total_price = 0
            try:
                pct = float(item.get('_commission_pct') or 0)
            except Exception:
                pct = 0.0
            item['_commission_amount'] = int(round(total_price * (pct / 100.0))) if (total_price and pct) else 0
            item['_share_url'] = ''
            item['_share_token'] = ''
            item['_reposted_by_me'] = code in my_reposted_codes
        else:
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_is_expired'] = is_ad_expired(land)
        item.setdefault('created_at', land.get('created_at') or '1970-01-01')
        item['_detail_url'] = url_for('express_partner.land_detail', code=code)
        result.append(item)
    return result


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
        apps = load_express_partner_apps() or []
        mine = [a for a in apps if isinstance(a, dict) and str(a.get('phone')) == str(phone)]
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
        apps = load_express_partner_apps() or []
        active_statuses = {None, '', 'new', 'pending', 'under_review'}
        for a in apps:
            if not isinstance(a, dict):
                continue
            if str(a.get('phone')) != str(phone):
                continue
            status = str(a.get('status') or '').strip().lower()
            if status in ('approved', 'rejected', 'cancelled'):
                continue
            # anything else counts as active/in-progress
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
                    return render_template(
                        'express_partner/thanks.html',
                        name=(last_app.get('name') or ''),
                        pending=True,
                        waiting=True
                    )
                flash('برای ورود به پنل، لطفاً ابتدا درخواست همکاری خود را ثبت و تکمیل کنید.', 'warning')
                return redirect(url_for('express_partner.apply_step1'))

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


# به‌روزرسانی خودکار timestamp همکاران آنلاین در تمام route‌های express_partner
@express_partner_bp.before_request
def track_online_partner():
    """فعالیت آنلاین سبک — بدون نوشتن فایل روتین روی هر درخواست."""
    if not session.get("user_phone"):
        return
    session.permanent = True
    try:
        phone = (session.get("user_phone") or "").strip()
        if not phone:
            return
        _ensure_session_partner_on_g()
        profile = getattr(g, 'express_partner_profile', None)
        name = (profile.get('name') or '').strip() if profile else None

        now_ts = time.time()
        last_ping = session.get('_express_online_ping_ts') or 0
        if now_ts - float(last_ping) >= 120:
            session['_express_online_ping_ts'] = now_ts
            try:
                import admin.routes as admin_routes_module
                if hasattr(admin_routes_module, '_update_online_partner'):
                    ip = request.remote_addr or 'نامشخص'
                    admin_routes_module._update_online_partner(phone, name, ip)
            except Exception:
                pass

        ep = request.endpoint or ''
        if ep.startswith('express_partner.routine'):
            try:
                today = datetime.now().strftime('%Y-%m-%d')
                if session.get('routine_marked_date') != today:
                    records = load_partner_routines_cached() or []
                    rec = next((r for r in records if str(r.get('phone')) == phone), None)
                    changed = False
                    if not rec:
                        rec = {"phone": phone, "days": [], "steps": {}, "updated_at": None}
                        records.append(rec)
                        changed = True
                    rec.setdefault('days', [])
                    rec.setdefault('steps', {})
                    if today not in rec['days']:
                        rec['days'].append(today)
                        rec['days'] = sorted(set(rec['days']))
                        changed = True
                    if changed:
                        rec['updated_at'] = datetime.utcnow().isoformat() + "Z"
                        save_partner_routines(records)
                    session['routine_marked_date'] = today
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
    
    return {
        "VINOR_IS_EXPRESS_PARTNER": is_express_partner,
        "VAPID_PUBLIC_KEY": vapid_public,
    }


# -------------------------
# PWA Routes (Separate from main VINOR PWA)
# -------------------------
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
      "start_url": "/express/partner/dashboard?source=pwa",
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
        return send_from_directory(static_dir, sw_file, mimetype="application/javascript")
    
    # Fallback: return empty service worker if file not found
    current_app.logger.warning(f"Service worker file not found: {sw_path}")
    return Response("// Express Partner Service Worker not found", 
                   mimetype="application/javascript", 
                   status=404)


@express_partner_bp.route('/offline', methods=['GET'], endpoint='offline')
def offline_page():
    """Express Partner offline page"""
    return render_template('express_partner/offline.html')


@express_partner_bp.route('/apply', methods=['GET'], endpoint='apply')
def apply():
    """Backward-compatible: redirect to step1 of multi-step flow"""
    if not session.get("user_phone"):
        return redirect(url_for("express_partner.login", next=url_for("express_partner.apply")))
    me_phone = (session.get("user_phone") or "").strip()
    # اگر قبلاً درخواست ثبت شده، کاربر را به صفحه تشکر ببر
    last_app = _get_my_last_application(me_phone)
    if last_app:
        return render_template('express_partner/thanks.html', name=(last_app.get('name') or ''))
    return redirect(url_for('express_partner.apply_step1'))


@express_partner_bp.route('/apply/step1', methods=['GET', 'POST'], endpoint='apply_step1')
def apply_step1():
    if not session.get("user_phone"):
        return redirect(url_for("express_partner.login", next=url_for("express_partner.apply_step1")))
    me_phone = (session.get("user_phone") or "").strip()
    try:
        from .referrals import stash_referrer_from_request
        stash_referrer_from_request(me_phone)
    except Exception:
        pass
    # اگر قبلاً درخواست ثبت شده، کاربر را به صفحه تشکر ببر
    last_app = _get_my_last_application(me_phone)
    if last_app:
        return render_template('express_partner/thanks.html', name=(last_app.get('name') or ''))
    # اگر قبلاً همکار است، به داشبورد برود
    try:
        partners = load_express_partners() or []
        if any(str(p.get('phone')) == me_phone for p in partners if isinstance(p, dict)):
            return redirect(url_for('express_partner.dashboard'))
    except Exception:
        pass

    if request.method == 'POST':
        # جلوگیری از ایجاد درخواست موازی
        if _has_active_application(me_phone):
            last_app = _get_my_last_application(me_phone)
            return render_template('express_partner/thanks.html', name=(last_app.get('name') if last_app else ''))
        name = (request.form.get('name') or '').strip()
        city = (request.form.get('city') or '').strip()
        if not name or not city:
            flash('لطفاً نام و شهر را وارد کنید.', 'error')
            return render_template('express_partner/apply_step1.html', name=name, city=city)
        session['apply_data'] = {**(session.get('apply_data') or {}), 'name': name, 'city': city}
        return redirect(url_for('express_partner.apply_step2'))

    data = session.get('apply_data') or {}
    cities = load_active_cities() or []
    return render_template('express_partner/apply_step1.html', name=data.get('name',''), city=data.get('city',''), cities=cities)


@express_partner_bp.route('/apply/step2', methods=['GET', 'POST'], endpoint='apply_step2')
def apply_step2():
    if not session.get("user_phone"):
        return redirect(url_for("express_partner.login", next=url_for("express_partner.apply_step2")))
    me_phone = (session.get("user_phone") or "").strip()
    # اگر قبلاً درخواست ثبت شده، کاربر را به صفحه تشکر ببر
    last_app = _get_my_last_application(me_phone)
    if last_app:
        return render_template('express_partner/thanks.html', name=(last_app.get('name') or ''))
    # اطمینان از تکمیل step1
    if not (session.get('apply_data') and session['apply_data'].get('name') and session['apply_data'].get('city')):
        return redirect(url_for('express_partner.apply_step1'))

    if request.method == 'POST':
        # جلوگیری از ایجاد درخواست موازی
        me_phone = (session.get('user_phone') or '').strip()
        if _has_active_application(me_phone):
            last_app = _get_my_last_application(me_phone)
            return render_template('express_partner/thanks.html', name=(last_app.get('name') if last_app else ''))
        experience = (request.form.get('experience') or '').strip()
        note = (request.form.get('note') or '').strip()
        session['apply_data'] = {**(session.get('apply_data') or {}), 'experience': experience, 'note': note}
        return redirect(url_for('express_partner.apply_step3'))

    data = session.get('apply_data') or {}
    return render_template('express_partner/apply_step2.html', experience=data.get('experience',''), note=data.get('note',''))


@express_partner_bp.route('/apply/step3', methods=['GET', 'POST'], endpoint='apply_step3')
def apply_step3():
    if not session.get("user_phone"):
        return redirect(url_for("express_partner.login", next=url_for("express_partner.apply_step3")))
    me_phone = (session.get("user_phone") or "").strip()
    data = session.get('apply_data') or {}
    # اگر قبلاً درخواست ثبت شده، کاربر را به صفحه تشکر ببر
    last_app = _get_my_last_application(me_phone)
    if last_app and request.method == 'GET':
        return render_template('express_partner/thanks.html', name=(last_app.get('name') or ''))
    if not (data.get('name') and data.get('city')):
        return redirect(url_for('express_partner.apply_step1'))

    if request.method == 'POST':
        # اگر قبلاً درخواست فعال دارد، به صفحه تشکر هدایت شود
        if _has_active_application(me_phone):
            last_app = _get_my_last_application(me_phone)
            session.pop('apply_data', None)
            return render_template('express_partner/thanks.html', name=(last_app.get('name') if last_app else ''))
        # ذخیره نهایی
        apps = load_express_partner_apps() or []
        partners = load_express_partners() or []
        if any(str(p.get("phone")) == me_phone for p in partners if isinstance(p, dict)):
            session.pop('apply_data', None)
            return redirect(url_for("express_partner.dashboard"))

        new_id = (max([int(x.get("id", 0) or 0) for x in apps if isinstance(x, dict)], default=0) or 0) + 1
        referrer_phone = ''
        try:
            from .referrals import pop_referrer_phone, register_referral_on_application
            referrer_phone = pop_referrer_phone(me_phone)
        except Exception:
            referrer_phone = ''
        record = {
            "id": new_id,
            "name": data.get('name',''),
            "phone": me_phone,
            "city": data.get('city',''),
            "experience": data.get('experience',''),
            "note": data.get('note',''),
            "status": "new",
            "created_at": datetime.utcnow().isoformat()+"Z",
        }
        if referrer_phone:
            record["referred_by_phone"] = referrer_phone
        apps.append(record)
        save_express_partner_apps(apps)
        if referrer_phone:
            try:
                register_referral_on_application(
                    inviter_phone=referrer_phone,
                    invitee_phone=me_phone,
                    invitee_name=record.get('name', ''),
                    application_id=new_id,
                )
            except Exception:
                pass
        
        # ارسال پیامک "در حال بررسی" به همکار و اطلاع‌رسانی به ادمین
        try:
            settings = load_settings(current_app) or {}

            # Normalize شماره تلفن همکار قبل از ارسال
            phone_normalized = _normalize_phone(me_phone)
            
            # بررسی اعتبار شماره تلفن همکار
            if phone_normalized and len(phone_normalized) == 11 and phone_normalized.startswith('09'):
                sms_message = settings.get('partner_application_sms_message', 'درخواست همکاری شما ثبت شد و در حال بررسی است. وینور')
                sms_line_number = settings.get('sms_line_number', '300089930616')
                
                # اگر پیام خالی است، از پیش‌فرض استفاده کن
                if not sms_message or not sms_message.strip():
                    sms_message = 'درخواست همکاری شما ثبت شد و در حال بررسی است. وینور'
                
                current_app.logger.info(f"Attempting to send SMS to {phone_normalized} (original: {me_phone})")
                
                sms_result = send_sms_direct(mobile=phone_normalized, message=sms_message, line_number=sms_line_number)
                
                # ذخیره سابقه ارسال پیامک به همکار
                try:
                    history = load_sms_history(current_app) or []
                    record = {
                        'id': len(history) + 1,
                        'mobile': phone_normalized,
                        'recipient_name': data.get('name', ''),
                        'template_id': None,
                        'message': sms_message,
                        'parameters': {},
                        'success': sms_result.get('ok', False),
                        'status_code': sms_result.get('status', 0),
                        'response': sms_result.get('body', {}),
                        'source': 'express_partner_application',
                        'created_at': datetime.utcnow().isoformat() + 'Z',
                        'error': None if sms_result.get('ok') else str(sms_result.get('body', {}).get('message', 'Unknown error'))
                    }
                    history.append(record)
                    if len(history) > 10000:
                        history = history[-10000:]
                    save_sms_history(history, current_app)
                except Exception as hist_err:
                    current_app.logger.error(f"Failed to save SMS history: {hist_err}")
                
                if sms_result.get('ok'):
                    current_app.logger.info(f"✅ Application confirmation SMS sent successfully to {phone_normalized}")
                else:
                    current_app.logger.error(f"❌ Failed to send application confirmation SMS to {phone_normalized}. Status: {sms_result.get('status')}, Body: {sms_result.get('body')}")
            else:
                current_app.logger.error(f"❌ Invalid phone number format: {me_phone} -> normalized: {phone_normalized}")

            # ارسال پیامک اطلاع‌رسانی به ادمین درباره درخواست جدید
            try:
                admin_phone_raw = settings.get('partner_application_admin_phone', '09121471301')
                admin_phone = _normalize_phone(admin_phone_raw)
                admin_sms_message = settings.get('partner_application_admin_sms_message',
                                                 'درخواست همکاری جدید همکار در وینور ثبت شد.')

                # اگر پیام خالی است، از پیش‌فرض استفاده کن
                if not admin_sms_message or not admin_sms_message.strip():
                    admin_sms_message = 'درخواست همکاری جدید همکار در وینور ثبت شد.'

                if admin_phone and len(admin_phone) == 11 and admin_phone.startswith('09'):
                    current_app.logger.info(f"Attempting to send admin SMS about new partner application to {admin_phone}")

                    admin_sms_result = send_sms_direct(
                        mobile=admin_phone,
                        message=admin_sms_message,
                        line_number=sms_line_number,
                    )

                    # ذخیره سابقه ارسال پیامک به ادمین
                    try:
                        history = load_sms_history(current_app) or []
                        record_admin = {
                            'id': len(history) + 1,
                            'mobile': admin_phone,
                            'recipient_name': 'admin',
                            'template_id': None,
                            'message': admin_sms_message,
                            'parameters': {},
                            'success': admin_sms_result.get('ok', False),
                            'status_code': admin_sms_result.get('status', 0),
                            'response': admin_sms_result.get('body', {}),
                            'source': 'express_partner_application_admin',
                            'created_at': datetime.utcnow().isoformat() + 'Z',
                            'error': None if admin_sms_result.get('ok') else str(admin_sms_result.get('body', {}).get('message', 'Unknown error'))
                        }
                        history.append(record_admin)
                        if len(history) > 10000:
                            history = history[-10000:]
                        save_sms_history(history, current_app)
                    except Exception as hist_err_admin:
                        current_app.logger.error(f"Failed to save admin SMS history: {hist_err_admin}")

                    if admin_sms_result.get('ok'):
                        current_app.logger.info(f"✅ Admin notification SMS sent successfully to {admin_phone}")
                    else:
                        current_app.logger.error(f"❌ Failed to send admin notification SMS to {admin_phone}. Status: {admin_sms_result.get('status')}, Body: {admin_sms_result.get('body')}")
                else:
                    current_app.logger.error(f"❌ Invalid admin phone format: {admin_phone_raw} -> normalized: {admin_phone}")
            except Exception as admin_err:
                current_app.logger.error(f"❌ Error sending admin notification SMS about partner application: {admin_err}", exc_info=True)

        except Exception as e:
            current_app.logger.error(f"❌ Error in application SMS flow (partner/admin): {e}", exc_info=True)
        
        session.pop('apply_data', None)
        return render_template("express_partner/thanks.html", name=record.get('name',''), brand="وینور", domain="vinor.ir")

    return render_template('express_partner/apply_step3.html', data=data)


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
        flash('درخواست شما با موفقیت لغو شد. هر زمان می‌توانید دوباره درخواست همکاری ثبت کنید.', 'info')
    # اگر درخواستی پیدا نشود (مثلاً قبلاً تأیید/رد یا حذف شده)، بدون خطا فقط به مرحله ۱ برگرد
    return redirect(url_for('express_partner.apply_step1'))


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

    try:
        assignments = load_express_assignments() or []
        _maybe_auto_release_expired_transactions(assignments)
    except Exception:
        assignments = []
    my_assignments = [a for a in assignments if str(a.get('partner_phone')) == me_phone and a.get('status') in (None,'active','pending','approved','in_transaction','sold')]
    lands_all = load_ads_cached() or []
    code_to_land = {str(l.get('code')): l for l in lands_all}
    assigned_lands = []
    expired_count = 0
    
    # بررسی اعتبار فایل‌ها
    from ..utils.dates import is_ad_expired
    
    # وضعیت بازنشرهای من برای رنگ دکمه
    try:
        my_reposts = [r for r in (load_express_reposts() or []) if str(r.get('partner_phone')) == me_phone]
        my_reposted_codes = {str(r.get('code')) for r in my_reposts}
    except Exception:
        my_reposted_codes = set()

    for a in my_assignments:
        land = code_to_land.get(str(a.get('land_code')))
        if not land:
            continue
        
        # بررسی انقضای فایل
        is_expired = is_ad_expired(land)
        if is_expired:
            expired_count += 1
        
        item = dict(land)
        item['_assignment_id'] = a.get('id')
        item['_assignment_status'] = _assignment_display_status(a)
        item['_commission_pct'] = a.get('commission_pct')
        item['_is_expired'] = is_expired
        # اطمینان از وجود created_at برای مرتب‌سازی (بر اساس تاریخ ثبت آگهی)
        # item از dict(land) ساخته شده، پس created_at باید از land بیاید
        if not item.get('created_at'):
            item['created_at'] = land.get('created_at') or '1970-01-01'
        # محاسبه مبلغ پورسانت همکار از روی price_total (اگر موجود) و درصد کمیسیون
        try:
            total_price_str = str(item.get('price_total') or item.get('price') or '0').replace(',', '').strip()
            total_price = int(total_price_str) if total_price_str else 0
        except Exception:
            total_price = 0
        try:
            pct = float(item.get('_commission_pct') or 0)
        except Exception:
            pct = 0.0
        item['_commission_amount'] = int(round(total_price * (pct / 100.0))) if (total_price and pct) else 0
        item['_share_url'] = ''
        item['_share_token'] = ''
        item['_reposted_by_me'] = str(item.get('code')) in my_reposted_codes
        # اطمینان از وجود created_at برای مرتب‌سازی (بر اساس تاریخ ثبت آگهی)
        # item از dict(land) ساخته شده، پس created_at باید از land بیاید
        if not item.get('created_at'):
            item['created_at'] = land.get('created_at') or '1970-01-01'
        assigned_lands.append(item)

    is_approved = bool(profile and (profile.get("status") in ("approved", True)))

    # همه فایل‌های اکسپرس برای همه کاربران (وارد نشده، تاییدنشده، تاییدشده) در داشبورد نمایش داده می‌شود.
    try:
        display_lands = load_express_lands_cached() or []
    except Exception:
        display_lands = []
    if selected_cities:
        city_set = set(selected_cities)
        display_lands = [
            l for l in display_lands
            if str(l.get('city') or '').strip() in city_set
        ]
    if search_query:
        terms = search_query.split()
        def _matches(l):
            text = ' '.join([
                str(l.get('title') or ''),
                str(l.get('location') or ''),
                str(l.get('city') or ''),
                str(l.get('category') or ''),
                str(l.get('description') or ''),
            ]).lower()
            return all(t in text for t in terms)
        display_lands = [l for l in display_lands if _matches(l)]

    filter_tag = (request.args.get('tag') or '').strip().lower()
    filter_cat = (request.args.get('cat') or '').strip()

    def _land_text_blob(ln):
        parts = [
            str(ln.get('title') or ''),
            str(ln.get('description') or ''),
            str(ln.get('features') or ''),
            str(ln.get('location') or ''),
            str(ln.get('category') or ''),
            str(ln.get('payment_method') or ''),
        ]
        return ' '.join(parts).lower()

    if filter_cat == 'land_garden':
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('category') or '').strip() in ('زمین', 'باغ')
        ]
    elif filter_cat:
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('category') or '').strip() == filter_cat
        ]

    if filter_tag == 'pool':
        display_lands = [ln for ln in display_lands if 'استخر' in _land_text_blob(ln)]
    elif filter_tag == 'forest':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('جنگل', 'جنگلی', 'بوستان'))
        ]
    elif filter_tag == 'town':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('شهرک', 'شهرکی', 'مجتمع'))
        ]
    elif filter_tag == 'urgent':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('فوری', 'فرصت', 'فوریت'))
        ]
    elif filter_tag == 'deed':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('سند', 'سنددار', 'تک‌برگ', 'تک برگ'))
        ]
    elif filter_tag == 'invest':
        display_lands = [
            ln for ln in display_lands
            if any(k in _land_text_blob(ln) for k in ('سرمایه', 'سرمایه‌گذاری', 'سودآور'))
        ]
    elif filter_tag == 'installment':
        display_lands = [
            ln for ln in display_lands
            if str(ln.get('payment_method') or '').strip() == 'اقساطی'
            or 'قسط' in _land_text_blob(ln)
        ]

    display_lands = _sort_by_created_at_desc(display_lands)

    # برای همکاران تاییدشده: روی کارت‌هایی که به آن‌ها اختصاص داده شده پورسانت و لینک اشتراک تزریق کن
    code_to_assigned = {str(item.get('code')): item for item in assigned_lands}
    code_to_global_status = {}
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
    assigned_lands = []
    for land in display_lands:
        code = str(land.get('code') or '')
        item = dict(land)
        assigned_item = code_to_assigned.get(code)
        global_status = code_to_global_status.get(code, item.get('_assignment_status') or 'active')
        if assigned_item and is_approved:
            item['_assignment_id'] = assigned_item.get('_assignment_id')
            item['_assignment_status'] = global_status
            item['_in_transaction'] = global_status == 'in_transaction'
            item['_commission_pct'] = assigned_item.get('_commission_pct')
            item['_commission_amount'] = assigned_item.get('_commission_amount', 0)
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
        assigned_lands.append(item)

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
    def _img_url(land):
        imgs = land.get('images') or []
        if isinstance(imgs, str):
            imgs = [imgs] if imgs else []
        first = imgs[0] if imgs else None
        if not first:
            return None
        if isinstance(first, str) and (first.startswith('http') or first.startswith('/')):
            return first if first.startswith('/') else None
        return f"/uploads/{first}" if first else None

    lands_json = []
    for land in assigned_lands:
        code = land.get('code') or ''
        try:
            detail_url = url_for('express_partner.land_detail', code=code, _external=True)
        except Exception:
            detail_url = ''
        lands_json.append({
            'code': code,
            'title': (land.get('title') or '—').strip(),
            'price_total': int(land.get('price_total') or land.get('price') or 0),
            'commission_amount': int(land.get('_commission_amount') or 0),
            'commission_pct': land.get('_commission_pct'),
            'assignment_status': (land.get('_assignment_status') or 'active').strip(),
            'is_expired': bool(land.get('_is_expired')),
            'size': (land.get('size') or '').strip(),
            'location': (land.get('location') or '').strip(),
            'city': (land.get('city') or '').strip(),
            'category': (land.get('category') or '').strip(),
            'created_at': (land.get('created_at') or '').strip(),
            'image_url': _img_url(land),
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
    def _img_url(land):
        imgs = land.get('images') or []
        if isinstance(imgs, str):
            imgs = [imgs] if imgs else []
        first = imgs[0] if imgs else None
        if not first:
            return None
        if isinstance(first, str) and (first.startswith('http') or first.startswith('/')):
            return first if first.startswith('/') else None
        return f"/uploads/{first}" if first else None

    try:
        express_lands = load_express_lands_cached() or []
    except Exception:
        express_lands = []
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

    try:
        assignments = load_express_assignments() or []
        _auto_release_expired_transactions(assignments)
    except Exception:
        assignments = []
    my_assignments = [a for a in assignments if str(a.get('partner_phone')) == me_phone and a.get('status') in (None, 'active', 'pending', 'approved', 'in_transaction', 'sold')]
    lands_all = load_ads_cached() or []
    code_to_land = {str(l.get('code')): l for l in lands_all}
    assigned_lands = []
    expired_count = 0
    from ..utils.dates import is_ad_expired
    try:
        my_reposts = [r for r in (load_express_reposts() or []) if str(r.get('partner_phone')) == me_phone]
        my_reposted_codes = {str(r.get('code')) for r in my_reposts}
    except Exception:
        my_reposted_codes = set()

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
        item['_commission_pct'] = a.get('commission_pct')
        item['_is_expired'] = is_expired
        if not item.get('created_at'):
            item['created_at'] = land.get('created_at') or '1970-01-01'
        try:
            total_price_str = str(item.get('price_total') or item.get('price') or '0').replace(',', '').strip()
            total_price = int(total_price_str) if total_price_str else 0
        except Exception:
            total_price = 0
        try:
            pct = float(item.get('_commission_pct') or 0)
        except Exception:
            pct = 0.0
        item['_commission_amount'] = int(round(total_price * (pct / 100.0))) if (total_price and pct) else 0
        if not item.get('created_at'):
            item['created_at'] = land.get('created_at') or '1970-01-01'
        assigned_lands.append(item)

    assigned_lands = _sort_by_created_at_desc(assigned_lands)
    my_comms = _commissions_for_phone(me_phone)
    total_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
    pending_commission = sum(int(c.get('commission_amount') or 0) for c in my_comms if (c.get('status') or 'pending').strip() == 'pending')
    sold_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))
    is_approved = bool(profile and (profile.get("status") in ("approved", True)))
    payload = _dashboard_data_payload(me_phone, profile, has_pending_app, assigned_lands, total_commission, pending_commission, sold_count, expired_count, is_approved)
    # همیشه لیست عمومی را بفرست تا اپ در صورت خالی بودن assigned_lands هم کارت‌ها را نشان دهد
    try:
        payload['public_lands'] = _public_lands_payload(limit=50)
    except Exception:
        payload['public_lands'] = []
    return jsonify(payload)


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
@require_partner_access(allow_pending=True, allow_guest=True)
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
@require_partner_access(allow_pending=True, allow_guest=True)
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


@express_partner_bp.get('/notes', endpoint='notes')
@require_partner_access(allow_pending=True, allow_guest=True)
def notes_page():
    me_phone = (session.get("user_phone") or "").strip()
    items = [n for n in (load_partner_notes() or []) if str(n.get('phone')) == me_phone]
    # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
    items = _sort_by_created_at_desc(items)
    return render_template("express_partner/notes.html", notes=items, hide_header=True, SHOW_SUBMIT_BUTTON=False, brand="وینور", domain="vinor.ir")


@express_partner_bp.get('/commissions', endpoint='commissions')
@require_partner_access(allow_pending=True, allow_guest=True)
def commissions_page():
    me_phone = (session.get("user_phone") or "").strip()
    profile = getattr(g, 'express_partner_profile', None)
    is_approved = _is_partner_approved(profile)
    my_comms = _commissions_for_phone(me_phone)

    def _i(v):
        try:
            return int(str(v).replace(',', '').strip() or '0')
        except Exception:
            return 0

    # کل درآمد: فقط پورسانت‌های تایید شده و پرداخت شده (نه pending و rejected)
    total_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or '') in ('approved', 'paid'))
    
    # در انتظار: فقط پورسانت‌هایی که status='pending' یا None/خالی است (default به pending)
    pending_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or 'pending').strip() == 'pending')
    
    # پرداخت شده: فقط پورسانت‌هایی که status='paid'
    paid_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or '').strip() == 'paid')
    
    # فروش‌های تایید شده: تعداد پورسانت‌هایی که status='approved' یا 'paid' دارند
    sold_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))

    def _norm_st(c):
        try:
            return (str(c.get('status') or 'pending')).strip()
        except Exception:
            return 'pending'

    pending_count = sum(1 for c in my_comms if _norm_st(c) == 'pending')
    approved_count = sum(1 for c in my_comms if _norm_st(c) == 'approved')
    paid_count = sum(1 for c in my_comms if _norm_st(c) == 'paid')
    approved_commission = sum(_i(c.get('commission_amount')) for c in my_comms if _norm_st(c) == 'approved')
    # موجودی که همکار می‌تواند درخواست برداشت/واریز بزند: پورسانت‌های تأییدشده و هنوز پرداخت‌نشده
    withdrawable_balance = approved_commission

    _attach_commission_txn_labels(my_comms)

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
        items=my_comms,
        total_commission=total_commission,
        pending_commission=pending_commission,
        paid_commission=paid_commission,
        sold_count=sold_count,
        pending_count=pending_count,
        approved_count=approved_count,
        paid_count=paid_count,
        approved_commission=approved_commission,
        withdrawable_balance=withdrawable_balance,
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


@express_partner_bp.get('/commissions/data', endpoint='commissions_data')
@require_partner_access(allow_pending=True, allow_guest=True)
def commissions_data():
    """API JSON برای اپ اندروید: خلاصه و لیست پورسانت‌های همکار جاری."""
    me_phone = (session.get("user_phone") or "").strip()
    my_comms = _commissions_for_phone(me_phone)

    def _i(v):
        try:
            return int(str(v).replace(',', '').strip() or '0')
        except Exception:
            return 0

    total_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or '') in ('approved', 'paid'))
    pending_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or 'pending').strip() == 'pending')
    paid_commission = sum(_i(c.get('commission_amount')) for c in my_comms if (c.get('status') or '').strip() == 'paid')
    sold_count = sum(1 for c in my_comms if (c.get('status') or '').strip() in ('approved', 'paid'))

    def _norm_st(c):
        try:
            return (str(c.get('status') or 'pending')).strip()
        except Exception:
            return 'pending'

    approved_commission = sum(_i(c.get('commission_amount')) for c in my_comms if _norm_st(c) == 'approved')
    withdrawable_balance = approved_commission
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
        'total_commission': total_commission,
        'pending_commission': pending_commission,
        'paid_commission': paid_commission,
        'sold_count': sold_count,
        'withdrawable_balance': withdrawable_balance,
        'items': items,
    })


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
    mine = [r for r in all_rows if isinstance(r, dict) and str(r.get('phone') or '').strip() == me_phone]
    mine = _sort_bank_accounts_by_created(mine)
    return jsonify({
        'success': True,
        'accounts': [public_account_dict(r) for r in mine],
        'banks': catalog_public(),
    })


@express_partner_bp.post('/bank-accounts/add', endpoint='bank_accounts_add')
@require_partner_access(json_response=True)
def bank_accounts_add():
    """افزودن حساب؛ شمارهٔ کامل کارت ذخیره نمی‌شود (فقط ۴ رقم اول و ۴ رقم آخر + چک Luhn)."""
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

    for r in all_rows:
        if not isinstance(r, dict) or str(r.get('phone') or '').strip() != me_phone:
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


@express_partner_bp.post('/notes/add')
@require_partner_access(allow_pending=True)
def add_note():
    me_phone = (session.get("user_phone") or "").strip()
    content = (request.form.get("content") or "").strip()
    if not content:
        return redirect(url_for("express_partner.dashboard"))
    items = load_partner_notes() or []
    new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
    items.append({"id": new_id, "phone": me_phone, "content": content, "created_at": datetime.utcnow().isoformat()+"Z"})
    save_partner_notes(items)
    try:
        ref = request.referrer or ""
    except Exception:
        ref = ""
    if "/express/partner/notes" in ref:
        return redirect(url_for("express_partner.notes"))
    nxt = (request.form.get("next") or request.args.get("next") or "").strip()
    if nxt.startswith("/express/partner/notes"):
        return redirect(nxt)
    return redirect(url_for("express_partner.dashboard"))


@express_partner_bp.post('/notes/<int:nid>/delete')
@require_partner_access(allow_pending=True)
def delete_note(nid: int):
    me_phone = (session.get("user_phone") or "").strip()
    items = load_partner_notes() or []
    items = [n for n in items if not (int(n.get('id',0) or 0) == int(nid) and str(n.get('phone')) == me_phone)]
    save_partner_notes(items)
    try:
        ref = request.referrer or ""
    except Exception:
        ref = ""
    if "/express/partner/notes" in ref:
        return redirect(url_for("express_partner.notes"))
    nxt = (request.form.get("next") or request.args.get("next") or "").strip()
    if nxt.startswith("/express/partner/notes"):
        return redirect(nxt)
    return redirect(url_for("express_partner.dashboard"))


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
    for k in ('user_id', 'user_phone', 'otp_code', 'otp_phone', 'next'):
        session.pop(k, None)
    if not session.get('logged_in'):
        session.permanent = False
    try:
        session.modified = True
    except Exception:
        pass


@express_partner_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
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
        nxt = request.args.get('next') or session.get('next')
        if nxt and nxt.startswith('/'):
            return redirect(nxt)
        return redirect(url_for('express_partner.dashboard'))

    if request.method == 'POST':
        phone_raw = request.form.get('phone', '')
        phone = _normalize_phone(phone_raw)
        if not phone or len(phone) != 11:
            flash('لطفاً یک شماره موبایل ۱۱ رقمی معتبر وارد کنید.', 'error')
            return redirect(url_for('express_partner.login'))

        code = f"{random.randint(10000, 99999)}"
        session.update({'otp_code': code, 'otp_phone': phone})
        session.permanent = True

        # Try sending SMS; ignore errors in dev
        try:
            from ..services.sms import send_sms_code
            sms_result = send_sms_code(phone, code)
            if sms_result.get('ok'):
                flash('کد تأیید ارسال شد.', 'info')
            else:
                current_app.logger.error(
                    "OTP send failed in login | phone=%s | status=%s | body=%s",
                    phone,
                    sms_result.get('status'),
                    sms_result.get('body'),
                )
                flash('ارسال کد تأیید با خطا مواجه شد. لطفاً دوباره تلاش کنید.', 'warning')
        except Exception:
            flash('ارسال کد تأیید با خطا مواجه شد. لطفاً دوباره تلاش کنید.', 'warning')

        nxt = request.args.get('next')
        if nxt:
            session['next'] = nxt
        return render_template('express_partner/auth/login_step2.html', phone=phone)
    return render_template('express_partner/auth/login_step1.html')


@express_partner_bp.route('/verify', methods=['POST'], endpoint='verify')
def verify():
    code = (request.form.get('otp_code') or '').strip()
    phone = _normalize_phone(request.form.get('phone') or '')
    if not code or not phone:
        flash('لطفاً همه فیلدها را به‌درستی تکمیل کنید.', 'error')
        return redirect(url_for('express_partner.login'))

    if session.get('otp_code') == code and session.get('otp_phone') == phone:
        session['user_id'] = phone
        session['user_phone'] = phone
        session.permanent = True
        _invalidate_partner_session_cache()
        # ensure user exists
        try:
            from ..utils.storage import load_users, save_users
            users = load_users()
            if not any(u.get('phone') == phone for u in users):
                from datetime import datetime
                users.append({'phone': phone, 'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                save_users(users)
        except Exception:
            pass
        prof = _partner_profile_for_phone(phone)
        session['VINOR_IS_EXPRESS_PARTNER'] = _is_partner_approved(prof)
        flash('ورود شما با موفقیت انجام شد.', 'success')
        nxt = session.pop('next', None)
        if nxt:
            return redirect(nxt)
        # همکار تاییدشده یا کاربر عادی: هر دو به داشبورد (برای کاربر عادی، دسترسی محدود است)
        return redirect(url_for('express_partner.dashboard'))

    flash('کد تأیید نادرست است. لطفاً دوباره تلاش کنید.', 'error')
    return redirect(url_for('express_partner.login'))


@express_partner_bp.route('/support', methods=['GET'], endpoint='support')
@require_partner_access(allow_pending=True, allow_guest=True)
def support():
    """صفحه پشتیبانی مجزا برای Express Partner"""
    return render_template('express_partner/support.html', hide_header=True)


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


@express_partner_bp.route('/cooperation-terms', methods=['GET'], endpoint='cooperation_terms')
@require_partner_access(allow_pending=True, allow_guest=True)
def cooperation_terms():
    """شرایط همکاری برای کاربران عادی و متقاضیان همکاری."""
    return render_template('express_partner/cooperation_terms.html', hide_header=True)


@express_partner_bp.route('/invite', methods=['GET'], endpoint='invite_colleagues')
@require_partner_access(allow_pending=True)
def invite_colleagues():
    """صفحهٔ اشتراک لینک دعوت همکار — برای همکاران تأییدشده و سایر کاربران واردشده."""
    me_phone = (session.get('user_phone') or '').strip()
    profile = getattr(g, 'express_partner_profile', None) or {}
    me_name = (profile.get('name') or '').strip()
    from ..utils.share_tokens import encode_partner_ref
    ref_token = encode_partner_ref(me_phone)
    apply_next = url_for('express_partner.apply_step1', ref=ref_token)
    invite_url = url_for('express_partner.login', next=apply_next, _external=True)
    inviter = me_name or 'همکار وینور'
    share_text = f'{inviter} شما را به همکاری در وینور اکسپرس دعوت می‌کند.'
    try:
        from .referrals import referral_stats_for_inviter, REFERRAL_BONUS_AMOUNT
        ref_stats = referral_stats_for_inviter(me_phone)
        bonus_per_invite = REFERRAL_BONUS_AMOUNT
    except Exception:
        ref_stats = {
            'invite_count': 0,
            'approved_count': 0,
            'pending_invites': 0,
            'pending_commission': 0,
            'approved_commission': 0,
            'paid_commission': 0,
        }
        bonus_per_invite = 1_000_000
    return render_template(
        'express_partner/invite_colleagues.html',
        invite_url=invite_url,
        share_text=share_text,
        me_name=me_name,
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


@express_partner_bp.route('/routine/steps', methods=['POST'], endpoint='routine_steps')
@require_partner_access(allow_pending=True)
def routine_steps():
    """ثبت تعداد مراحل تیک‌خورده برای نمایش در تقویم (پیش‌فرض: امروز؛ قابل تعیین با 'date')."""
    phone = (session.get("user_phone") or "").strip()
    payload = request.get_json(silent=True) or {}
    # detail: optional list of step ids (strings)
    detail = payload.get('detail')
    try:
        detail = [str(x).strip() for x in (detail or []) if str(x).strip()]
    except Exception:
        detail = []
    count = int(payload.get('count') or (len(detail) if detail else 0))
    req_date = (payload.get('date') or '').strip()
    # YYYY-MM-DD ساده؛ اگر نامعتبر، روی today
    try:
        if req_date:
            datetime.strptime(req_date, "%Y-%m-%d")
    except Exception:
        req_date = ''
    if count < 0:
        count = 0
    if count > 10:
        count = 10  # سقف معقول

    target_day = req_date or datetime.now().strftime('%Y-%m-%d')
    records = load_partner_routines_cached()
    rec = next((r for r in records if str(r.get('phone')) == phone), None)
    if not rec:
        rec = {"phone": phone, "days": [], "steps": {}, "steps_detail": {}, "updated_at": None}
        records.append(rec)

    rec.setdefault('days', [])
    rec.setdefault('steps', {})
    rec.setdefault('steps_detail', {})
    # فقط وقتی حداقل یک تیک ثبت است، روز را در لیست days نگه داریم؛ در غیر این صورت حذف شود
    if count > 0:
        if target_day not in rec['days']:
            rec['days'].append(target_day)
            rec['days'] = sorted(set(rec['days']))
    else:
        if target_day in rec['days']:
            rec['days'] = [d for d in rec['days'] if d != target_day]
    rec['steps'][target_day] = count
    # همواره جزئیات امروز را بازنویسی کن (حتی اگر خالی باشد تا داده قدیمی نماند)
    rec['steps_detail'][target_day] = detail or []
    rec['updated_at'] = datetime.utcnow().isoformat() + "Z"
    if not req_date:
        session['routine_marked_date'] = target_day  # ثبت شده برای امروز

    save_partner_routines(records)
    resp = make_response(jsonify({
        "success": True,
        "date": target_day,
        "count": count,
        "days": rec.get('days', []),
        "steps": rec.get('steps', {}),
        "detail": rec.get('steps_detail', {}).get(target_day, [])
    }))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@express_partner_bp.get('/routine/steps/detail')
@require_partner_access(allow_pending=True)
def routine_steps_detail():
    """برگرداندن لیست تیک‌های روز مشخص شده (detail) برای بازگردانی وضعیت."""
    phone = (session.get("user_phone") or "").strip()
    date = (request.args.get('date') or '').strip()
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    records = load_partner_routines_cached()
    rec = next((r for r in records if str(r.get('phone')) == phone), None)
    detail = []
    if rec and isinstance(rec.get('steps_detail'), dict):
        try:
            d = rec['steps_detail'].get(date)
            if isinstance(d, list):
                detail = [str(x) for x in d]
        except Exception:
            detail = []
    resp = make_response(jsonify({"success": True, "date": date, "detail": detail}))
    resp.headers["Cache-Control"] = "public, max-age=20, stale-while-revalidate=40"
    return resp


def _mark_in_transaction_finish(
    code: str,
    *,
    success: bool,
    message: str,
    category: str = 'success',
    new_status: str | None = None,
):
    """پاسخ HTML (redirect) یا JSON برای درخواست AJAX جزئیات فایل."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(
            success=success,
            message=message,
            new_status=new_status,
            category=category,
        ), (200 if success else 400)
    if message:
        flash(message, category)
    if success:
        return redirect(url_for('express_partner.land_detail', code=code))
    return redirect(url_for('express_partner.dashboard'))


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
                            commission_pct_raw = my_assignment_for_commission.get('commission_pct')
                            
                            try:
                                commission_pct = float(commission_pct_raw) if commission_pct_raw is not None else 0.0
                            except (ValueError, TypeError):
                                commission_pct = 0.0
                                current_app.logger.warning(f"Invalid commission_pct for partner {partner_phone}, land {code}: {commission_pct_raw}")
                            
                            # بررسی اینکه آیا قبلاً برای این همکار و این فایل پورسانتی ثبت شده یا نه
                            existing_commission = next(
                                (c for c in commissions 
                                 if (str(c.get('partner_phone', '')).strip() == partner_phone and 
                                     str(c.get('land_code')) == str(code))),
                                None
                            )
                            
                            if existing_commission:
                                current_app.logger.info(f"Commission already exists for partner {partner_phone} and land {code}, skipping")
                                skipped_count += 1
                            elif commission_pct > 0:
                                # محاسبه مبلغ پورسانت
                                try:
                                    price_total_str = str(land.get('price_total') or land.get('price') or '0')
                                    price_total = int(price_total_str.replace(',', '').replace(' ', '').strip() or '0')
                                except Exception as e:
                                    price_total = 0
                                    current_app.logger.warning(f"Error parsing price_total for land {code}: {e}")
                                
                                commission_amount = int(round(price_total * (commission_pct / 100.0))) if price_total > 0 else 0
                                
                                if commission_amount > 0:
                                    # ایجاد ID جدید
                                    new_id = (max([int(x.get('id', 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
                                    
                                    # ایجاد رکورد پورسانت
                                    new_commission = {
                                        'id': new_id,
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
                                    current_app.logger.info(f"Created commission record {new_id} for partner {partner_phone} and land {code}: amount={commission_amount}, pct={commission_pct}, price={price_total}")
                                else:
                                    current_app.logger.warning(f"Commission amount is 0 for partner {partner_phone}, land {code}: price={price_total}, pct={commission_pct}")
                            else:
                                current_app.logger.warning(f"Commission percentage is 0 or missing for partner {partner_phone}, land {code}")
                        
                        if created_count > 0:
                            save_express_commissions(commissions)
                            success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد و پورسانت شما به لیست انتظار اضافه شد.'
                        else:
                            if skipped_count > 0:
                                success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد. (پورسانت شما قبلاً ثبت شده بود)'
                            else:
                                success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد.'
                        if not success_message:
                            success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد.'
                except Exception as e:
                    current_app.logger.error(f"Error creating commission records: {e}", exc_info=True)
                    success_message = 'ملک به عنوان «در حال معامله» علامت‌گذاری شد، اما در ثبت پورسانت خطایی رخ داد.'
                    success_category = 'warning'
            else:
                # اگر وضعیت از "در حال معامله" به "فعال" برگشت، پورسانت‌های pending مربوط به این فایل را حذف کن
                try:
                    commissions = load_express_commissions() or []
                    removed_count = 0
                    
                    # پیدا کردن و حذف پورسانت‌های pending مربوط به این فایل
                    commissions_to_keep = []
                    for c in commissions:
                        if (str(c.get('land_code')) == str(code) and 
                            c.get('status') == 'pending'):
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
            return _mark_in_transaction_finish(
                code,
                success=True,
                message=success_message,
                category=success_category,
                new_status=new_status,
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
    _clear_express_partner_auth_session()
    flash('از حساب خارج شدید.', 'info')
    r = redirect(url_for('express_partner.login'))
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    r.headers['Pragma'] = 'no-cache'
    return r


@express_partner_bp.post('/api/logout')
def api_logout():
    """خروج برای اپ اندروید (بدون CSRF؛ با کوکی سشن)."""
    _clear_express_partner_auth_session()
    return jsonify({'success': True})


@express_partner_bp.post('/api/login-request')
def api_login_request():
    """درخواست ارسال کد OTP برای اپ اندروید (ورود نیتیو). ورودی JSON: {"phone": "09..."}."""
    data = request.get_json(silent=True) or {}
    phone_raw = (data.get('phone') or '').strip()
    phone = _normalize_phone(phone_raw)
    if not phone or len(phone) != 11:
        return jsonify({'success': False, 'error': 'شماره موبایل معتبر نیست.'}), 400
    code = f"{random.randint(10000, 99999)}"
    session.update({'otp_code': code, 'otp_phone': phone})
    session.permanent = True
    try:
        from ..services.sms import send_sms_code
        sms_result = send_sms_code(phone, code)
        if not sms_result.get('ok'):
            return jsonify({
                'success': False,
                'error': 'ارسال کد ناموفق بود.',
                'status': sms_result.get('status'),
                'details': sms_result.get('body'),
            }), 502
    except Exception:
        return jsonify({'success': False, 'error': 'خطا در ارسال کد تأیید.'}), 502
    return jsonify({'success': True, 'message': 'کد تأیید ارسال شد.'})


@express_partner_bp.post('/api/verify')
def api_verify():
    """تأیید کد OTP برای اپ اندروید. ورودی JSON: {"code": "123456", "phone": "09..."}. سشن باید از مرحله login-request باشد."""
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    phone = _normalize_phone((data.get('phone') or '').strip())
    if not code or not phone:
        return jsonify({'success': False, 'error': 'کد و شماره را وارد کنید.'}), 400
    if session.get('otp_code') != code or session.get('otp_phone') != phone:
        return jsonify({'success': False, 'error': 'کد تأیید نادرست است.'}), 400
    session['user_id'] = phone
    session['user_phone'] = phone
    session.permanent = True
    _invalidate_partner_session_cache()
    try:
        from ..utils.storage import load_users, save_users
        users = load_users()
        if not any(u.get('phone') == phone for u in users):
            users.append({'phone': phone, 'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            save_users(users)
    except Exception:
        pass
    prof = _partner_profile_for_phone(phone)
    session['VINOR_IS_EXPRESS_PARTNER'] = _is_partner_approved(prof)
    return jsonify({'success': True, 'message': 'ورود با موفقیت انجام شد.'})


@express_partner_bp.route('/otp/resend', methods=['POST'], endpoint='otp_resend')
def otp_resend():
    # پشتیبانی از JSON (اپ) و form (وب)
    data = request.get_json(silent=True) or {}
    phone = _normalize_phone(
        (data.get('phone') or request.form.get('phone') or session.get('otp_phone') or '').strip()
    )
    if not phone or len(phone) != 11:
        if request.is_json:
            return jsonify({'ok': False, 'error': 'شماره معتبر نیست.'}), 400
        return {'ok': False, 'error': 'شماره معتبر نیست.'}, 400
    try:
        code = f"{random.randint(10000, 99999)}"
        session.update({'otp_code': code, 'otp_phone': phone})
        session.permanent = True
        from ..services.sms import send_sms_code
        sms_result = send_sms_code(phone, code)
        if not sms_result.get('ok'):
            if request.is_json:
                return jsonify({
                    'ok': False,
                    'error': 'ارسال مجدد کد ناموفق بود.',
                    'status': sms_result.get('status'),
                    'details': sms_result.get('body'),
                }), 502
            return {'ok': False, 'error': 'ارسال مجدد کد ناموفق بود.'}, 502
        if request.is_json:
            return jsonify({'ok': True, 'message': 'کد تأیید مجدد ارسال شد.'})
        return {'ok': True}
    except Exception:
        if request.is_json:
            return jsonify({'ok': False, 'error': 'خطا در ارسال مجدد کد.'}), 502
        return {'ok': False, 'error': 'خطا در ارسال مجدد کد.'}, 502


@express_partner_bp.route('/profile', methods=['GET'], endpoint='profile')
@require_partner_access(allow_pending=True)
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
    android_apk_url = _settings.get('android_apk_url') or ''
    android_apk_version = _settings.get('android_apk_version') or ''
    android_apk_updated_at = _settings.get('android_apk_updated_at') or ''
    android_apk_size_bytes = _settings.get('android_apk_size_bytes') or ''
    resp = make_response(render_template(
        'express_partner/profile.html',
        me_phone=me_phone,
        me_name=me_name,
        profile=profile,
        is_approved=is_approved,
        android_apk_url=android_apk_url,
        android_apk_version=android_apk_version,
        android_apk_updated_at=android_apk_updated_at,
        android_apk_size_bytes=android_apk_size_bytes,
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
    avatar_url = (f"/uploads/{avatar}" if avatar else None)
    _settings = _express_settings_cached()
    android_apk_url = (_settings.get('android_apk_url') or '').strip()
    android_apk_version = (_settings.get('android_apk_version') or '').strip()
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
        'android_apk_url': android_apk_url,
        'android_apk_version': android_apk_version,
        'csrf_token': csrf_token,
    })


@express_partner_bp.route('/profile/edit', methods=['GET', 'POST'], endpoint='profile_edit')
@require_partner_access(allow_pending=True)
def profile_edit_page():
    """
    ویرایش مشخصات همکار: نام، شهر، بیو، تلفن ثابت، ایمیل، تاریخ تولد؛ موبایل فقط نمایش.
    هر همکار با شمارهٔ session (user_phone) در لیست express_partners شناسایی می‌شود؛
    تمام فیلدها فقط روی همان دیکشنری پروفایل همان شماره ذخیره می‌شوند (مجزا از بقیهٔ کاربران).
    """
    me_phone = (session.get('user_phone') or '').strip()
    partners = load_express_partners() or []
    profile = next((p for p in partners if str(p.get('phone') or '').strip() == me_phone), None)
    if not profile:
        profile = {"phone": me_phone}
        partners.append(profile)

    cities_allowed = _active_cities_cached()

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()[:60]
        city = (request.form.get('city') or '').strip()[:60]
        bio = (request.form.get('bio') or '').strip()[:200]
        landline = (request.form.get('landline') or '').strip()[:20]
        email = (request.form.get('email') or '').strip()[:120]
        birth_date = (request.form.get('birth_date') or '').strip()[:32]
        prev_birth = (profile.get('birth_date') or '').strip()
        if birth_date and prev_birth and '/' in prev_birth:
            parts = [p.strip() for p in prev_birth.split('/') if p.strip()]
            head = parts[0] if parts else ''
            if head and birth_date.isdigit() and len(birth_date) <= 4:
                if birth_date == head:
                    birth_date = prev_birth
                elif len(parts) >= 2:
                    birth_date = birth_date + '/' + '/'.join(parts[1:])
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
        if landline:
            profile['landline'] = landline
        else:
            profile.pop('landline', None)
        if email:
            profile['email'] = email
        else:
            profile.pop('email', None)
        if birth_date:
            profile['birth_date'] = birth_date
        else:
            profile.pop('birth_date', None)
        try:
            save_express_partners(partners)
            _invalidate_partner_session_cache()
            flash('مشخصات با موفقیت به‌روزرسانی شد.', 'success')
        except Exception:
            current_app.logger.error("Failed to save partner profile edits", exc_info=True)
            flash('خطا در ذخیره مشخصات.', 'error')
        return redirect(url_for('express_partner.profile'))

    me_name = (profile.get('name') or '').strip()
    me_city = (profile.get('city') or '').strip()
    me_bio = (profile.get('bio') or '').strip()
    me_landline = (profile.get('landline') or '').strip()
    me_email = (profile.get('email') or '').strip()
    me_birth_date = (profile.get('birth_date') or '').strip()
    me_birth_year = ''
    birth_year_custom = False
    if me_birth_date:
        me_birth_year = me_birth_date.split('/', 1)[0].strip() if '/' in me_birth_date else me_birth_date
        if me_birth_year:
            try:
                yi = int(me_birth_year)
                birth_year_custom = yi < 1320 or yi > 1393
            except ValueError:
                birth_year_custom = True
    cities = cities_allowed
    return render_template('express_partner/profile_edit.html',
                           me_phone=me_phone,
                           me_name=me_name,
                           me_city=me_city,
                           me_bio=me_bio,
                           me_landline=me_landline,
                           me_email=me_email,
                           me_birth_date=me_birth_date,
                           me_birth_year=me_birth_year,
                           birth_year_custom=birth_year_custom,
                           profile=profile,
                           cities=cities)


@express_partner_bp.get('/profile/edit/data', endpoint='profile_edit_data')
@require_partner_access(allow_pending=True)
def profile_edit_data():
    """API JSON برای اپ اندروید: داده فرم ویرایش پروفایل."""
    me_phone = (session.get('user_phone') or '').strip()
    partners = load_express_partners() or []
    profile = next((p for p in partners if str(p.get('phone') or '').strip() == me_phone), None)
    if not profile:
        profile = {"phone": me_phone}
    me_name = (profile.get('name') or '').strip()
    me_city = (profile.get('city') or '').strip()
    me_bio = (profile.get('bio') or '').strip()
    me_landline = (profile.get('landline') or '').strip()
    me_email = (profile.get('email') or '').strip()
    me_birth_date = (profile.get('birth_date') or '').strip()
    avatar = (profile.get('avatar') or '').strip()
    avatar_url = (f"/uploads/{avatar}" if avatar else None)
    cities = _active_cities_cached()
    return jsonify({
        'success': True,
        'me_phone': me_phone,
        'me_name': me_name,
        'me_city': me_city,
        'me_bio': me_bio,
        'me_landline': me_landline,
        'me_email': me_email,
        'me_birth_date': me_birth_date,
        'avatar_url': avatar_url,
        'cities': cities if isinstance(cities, list) else [],
    })


@express_partner_bp.post('/api/profile/update')
def api_profile_update():
    """به‌روزرسانی نام، شهر، درباره من برای اپ اندروید (بدون CSRF)."""
    if not session.get('user_phone'):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    me_phone = (session.get('user_phone') or '').strip()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    city = (data.get('city') or '').strip()
    bio = (data.get('bio') or '').strip()
    landline = (data.get('landline') or '').strip()[:20]
    email = (data.get('email') or '').strip()[:120]
    birth_date = (data.get('birth_date') or '').strip()[:32]
    partners = load_express_partners() or []
    profile = next((p for p in partners if str(p.get('phone') or '').strip() == me_phone), None)
    if not profile:
        profile = {"phone": me_phone}
        partners.append(profile)
    cities_allowed = _active_cities_cached()
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
        profile['bio'] = bio[:200]
    else:
        profile.pop('bio', None)
    if landline:
        profile['landline'] = landline
    else:
        profile.pop('landline', None)
    if email:
        profile['email'] = email
    else:
        profile.pop('email', None)
    if birth_date:
        profile['birth_date'] = birth_date
    else:
        profile.pop('birth_date', None)
    try:
        save_express_partners(partners)
        _invalidate_partner_session_cache()
        return jsonify({'success': True})
    except Exception:
        current_app.logger.error("Failed to save partner profile edits", exc_info=True)
        return jsonify({'success': False, 'error': 'save_failed'}), 500


@express_partner_bp.post('/profile/delete-account', endpoint='profile_delete_account')
@require_partner_access(allow_pending=True)
def profile_delete_account():
    """حذف رکورد همکار از لیست و خروج از سشن (غیرقابل بازگشت از این مسیر)."""
    me_phone = (session.get('user_phone') or '').strip()
    if not me_phone:
        return redirect(url_for('express_partner.login'))
    partners = load_express_partners() or []
    new_partners = [p for p in partners if str(p.get('phone') or '').strip() != me_phone]
    try:
        save_express_partners(new_partners)
    except Exception:
        current_app.logger.error('Failed to save partners after account delete', exc_info=True)
        flash('حذف حساب انجام نشد. دوباره تلاش کنید.', 'error')
        return redirect(url_for('express_partner.profile_edit'))
    _clear_express_partner_auth_session()
    flash('حساب کاربری شما حذف شد.', 'info')
    r = redirect(url_for('express_partner.login'))
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    r.headers['Pragma'] = 'no-cache'
    return r


@express_partner_bp.post('/profile/avatar')
@require_partner_access(allow_pending=True)
def profile_avatar_upload():
    """
    آپلود و تنظیم آواتار پروفایل همکار
    """
    me_phone = (session.get('user_phone') or '').strip()
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    f = request.files.get('avatar')
    if not f or not f.filename:
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))
    # مسیر ذخیره‌سازی: instance/data/uploads/partner/avatars/<phone>/
    base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', 'avatars', me_phone)
    os.makedirs(base, exist_ok=True)
    # حذف آواتارهای قبلی
    try:
        for fn in os.listdir(base):
            try:
                if fn.startswith('avatar.'):
                    os.remove(os.path.join(base, fn))
            except Exception:
                continue
    except Exception:
        pass
    # ذخیره آواتار جدید با تبدیل به JPEG و کوچک‌سازی سمت سرور (برای موبایل)
    tmp_path = os.path.join(base, '_tmp_upload')
    final_name = 'avatar.jpg'
    final_path = os.path.join(base, final_name)
    try:
        f.save(tmp_path)
        converted = False
        try:
            from PIL import Image, ImageOps  # type: ignore
            im = Image.open(tmp_path)
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            if im.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            # کوچک‌سازی: حداکثر ضلع 1200px
            im.thumbnail((1200, 1200), Image.LANCZOS)
            im.save(final_path, format='JPEG', quality=82, optimize=True)
            converted = True
        except Exception:
            converted = False
        # اگر تبدیل موفق نبود، همان فایل را به عنوان fallback ذخیره کنیم
        if not converted:
            # اگر نام اصلی پسوند داشت، همان را استفاده کنیم؛ وگرنه jpg
            orig_lower = (f.filename or '').lower()
            ext = '.jpg'
            for e in ('.jpg', '.jpeg', '.png', '.webp'):
                if orig_lower.endswith(e):
                    ext = e
                    break
            final_name = 'avatar' + ext
            final_path = os.path.join(base, final_name)
            # کپی فایل موقت به مسیر نهایی
            try:
                import shutil
                shutil.move(tmp_path, final_path)
            except Exception:
                # آخرین تلاش: دوباره ذخیره مستقیم
                f.stream.seek(0)
                with open(final_path, 'wb') as out:
                    out.write(f.read())
        # پاک‌سازی فایل موقت
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    except Exception:
        flash('خطا در ذخیره تصویر پروفایل.', 'error')
        return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))
    # به‌روزرسانی پروفایل همکار
    partners = load_express_partners() or []
    prof = next((p for p in partners if str(p.get('phone') or '').strip() == me_phone), None)
    if not prof:
        prof = {"phone": me_phone}
        partners.append(prof)
    rel_path = f'partner/avatars/{me_phone}/{os.path.basename(final_path)}'
    prof['avatar'] = rel_path
    try:
        from time import time as _now
        prof['avatar_updated_at'] = int(_now())
    except Exception:
        prof['avatar_updated_at'] = 0
    try:
        save_express_partners(partners)
    except Exception:
        current_app.logger.error("Failed to save partner avatar path", exc_info=True)
    return redirect(next_url if next_url.startswith('/express/partner/') else url_for('express_partner.profile'))


@express_partner_bp.route('/top-sellers', methods=['GET'], endpoint='top_sellers')
@require_partner_access(allow_pending=True)
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
    from app.services.notifications import get_user_notifications, unread_count, _normalize_user_id, merge_duplicate_keys
    
    me_phone_raw = (session.get("user_phone") or "").strip()
    # استفاده از همان تابع normalize که در notifications.py استفاده می‌شود
    me_phone = _normalize_user_id(me_phone_raw) if me_phone_raw else ""
    
    # اجرای merge خودکار کلیدهای تکراری (فقط یک بار)
    try:
        merge_result = merge_duplicate_keys()
        if merge_result.get("merged_count", 0) > 0:
            try:
                from flask import current_app
                current_app.logger.info(f"Page: Merged {merge_result['merged_count']} duplicate keys")
            except Exception:
                pass
    except Exception:
        pass
    
    # Debug logging
    try:
        from flask import current_app
        current_app.logger.info(f"Page: Getting notifications for phone: {me_phone_raw} -> normalized: {me_phone}")
    except Exception:
        pass
    
    notifications = get_user_notifications(me_phone, limit=200)
    unread = unread_count(me_phone)
    
    try:
        from flask import current_app
        current_app.logger.info(f"Page: Found {len(notifications)} notifications for {me_phone}")
    except Exception:
        pass
    
    return render_template(
        'express_partner/notifications.html',
        notifications=notifications,
        unread_count=unread,
    )


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
    return jsonify({
        "success": True,
        "unread_count": unread_count(me_phone)
    })


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
        
        profile = next((p for p in partners if str(p.get("phone") or "").strip() == me_phone), None)
        
        if profile:
            current_app.logger.info(f"check_status: Profile found for {me_phone}, status: {profile.get('status')}")
            is_approved = _is_partner_approved(profile)
            current_app.logger.info(f"check_status: Is approved: {is_approved}")
            
            if is_approved:
                redirect_url = url_for("express_partner.dashboard")
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

    # وضعیت تایید همکاری برای نمایش مشروط پورسانت
    try:
        is_approved = _is_partner_approved(partner_profile)
    except Exception:
        is_approved = False
    
    if assignment:
        land['_assignment_id'] = assignment.get('id')
        land['_assignment_status'] = global_assignment_status
        land['_commission_pct'] = assignment.get('commission_pct')
        # محاسبه مبلغ پورسانت
        try:
            total_price = float(land.get('price_total') or 0)
        except Exception:
            total_price = 0
        try:
            pct = float(land.get('_commission_pct') or 0)
        except Exception:
            pct = 0.0
        land['_commission_amount'] = int(round(total_price * (pct / 100.0))) if (total_price and pct) else 0
    else:
        land['_assignment_status'] = global_assignment_status

    share_token = ''
    share_url = ''

    # تصاویر با سایز thumb/full برای لود تدریجی سریع‌تر در جزئیات
    try:
        from app.utils.images import prepare_variants_dict
        imgs = land.get('images') or []
        if imgs and not land.get('images_v2'):
            land = dict(land)
            land['images_v2'] = [prepare_variants_dict(str(i)) for i in imgs if i]
    except Exception:
        pass

    is_logged_in = bool(me_phone)

    return render_template(
        'express_partner/land_detail.html',
        land=land,
        share_url=share_url,
        share_token=share_token,
        partner_profile=partner_profile,
        is_approved=is_approved,
        is_logged_in=is_logged_in,
        is_partner_context=True,
        ref_partner=None,
        brand="وینور",
        domain="vinor.ir"
    )


