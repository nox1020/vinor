# app/admin/routes.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import re
import random
import threading
import uuid
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Dict, Any, Optional

from flask import (
    render_template, request, redirect, url_for,
    session, current_app, flash, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename



# -----------------------------------------------------------------------------
# اعلان‌ها (Vinor Notifications)
# -----------------------------------------------------------------------------
from app.services.notifications import add_notification


def _admin_audit(action: str, **kwargs) -> None:
    """Phase 7 — fail-open admin audit into Foundation Activity."""
    try:
        from app.hardening.audit import record_admin_audit

        record_admin_audit(action=action, **kwargs)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Express Listings Management
# -----------------------------------------------------------------------------
def _get_express_docs_dir():
    """مسیر ذخیره مدارک اکسپرس"""
    docs_dir = os.path.join(current_app.instance_path, 'data', 'express_docs')
    os.makedirs(docs_dir, exist_ok=True)
    return docs_dir

def _save_express_document(file, land_code):
    """ذخیره مدارک اکسپرس"""
    if not file or not file.filename:
        return None
    
    docs_dir = _get_express_docs_dir()
    # اضافه کردن timestamp برای جلوگیری از تداخل نام فایل
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    filename = secure_filename(f"{land_code}_{timestamp}_{file.filename}")
    file_path = os.path.join(docs_dir, filename)
    file.save(file_path)
    return filename
from app.api.push import _load_subs, _send_one
from app.express_partner.partner_withdrawals import (
    admin_row_dict,
    admin_can_transition,
    apply_paid_withdrawal_to_commissions,
    link_withdrawal_to_commissions,
    release_withdrawal_commissions,
)
from app.land_category_specs import apply_category_specs_from_form
from app.services.sms import send_sms_template, send_sms_direct, send_sms_code
from app.utils.storage import load_users, save_users, load_reports, save_reports, save_ads, load_ads_cached, load_express_lands_cached
from admin.people_directory import (
    build_admin_people_directory,
    get_admin_person_by_phone,
    group_people_for_admin_list,
    resolve_admin_person_name,
)
from admin.sms_recipients import (
    RECIPIENT_GROUP_LABELS,
    RECIPIENT_GROUP_HINTS,
    LARGE_GROUP_REQUIRE_BATCH,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_FILES,
    add_sms_recipient_member,
    count_sms_recipients,
    ensure_sms_recipient_groups_initialized,
    export_sms_recipient_phones_txt,
    format_import_result_message,
    get_sms_recipient_group_detail,
    import_sms_recipient_phones,
    list_sms_recipient_groups_summary,
    load_sms_recipients,
    normalize_recipient_group,
    read_phones_upload_files,
    recipient_group_counts,
    recipient_group_label,
    remove_sms_recipient_member,
    sync_sms_recipient_group,
    update_sms_recipient_group_meta,
    update_sms_recipient_member,
    get_saved_recipient_group,
    save_recipient_group_preference,
)
from admin.admin_otp_store import clear_admin_otp, load_admin_otp, save_admin_otp
from admin.sms_scheduled import (
    SEND_TIMING_INSTANT,
    SEND_TIMING_RECURRING,
    SEND_TIMING_SCHEDULED,
    cancel_scheduled_job,
    create_scheduled_job,
    format_tehran_iso_display,
    list_active_scheduled_jobs,
    recurrence_summary,
    send_batch_summary,
    send_direct_to_recipients,
)
from app.utils.storage import (
    load_express_partner_apps,
    save_express_partner_apps,
    load_express_partners,
    save_express_partners,
    load_express_assignments,
    save_express_assignments,
    load_express_commissions,
    save_express_commissions,
    load_partner_files_meta,
    save_partner_files_meta,
    load_active_cities,
    save_active_cities,
    load_sms_history,
    save_sms_history,
    load_landing_views,
    load_express_views,
    load_express_partner_views,
    load_partner_routines, load_partner_routines_cached,
    load_partner_notes,
    load_partner_withdrawals, save_partner_withdrawals,
    load_partner_bank_accounts,
    load_express_visit_requests, save_express_visit_requests,
)

def _ad_owner_id(ad: Dict[str, Any]) -> Optional[str]:
    """شناسه کاربر آگهی‌دهنده از فیلدهای رایج."""
    return ad.get('owner') or ad.get('user_phone') or ad.get('phone')

def _safe_action_url(ad_code: str) -> str:
    """اگر روت جزئیات آگهی نبود، به آگهی‌های من برگرد."""
    try:
        return url_for('main.land_detail', code=ad_code)
    except Exception:
        try:
            return url_for('main.my_lands')
        except Exception:
            return '/my-lands'

def notify_status_change(ad: Dict[str, Any], status: str, reason: Optional[str] = None):
    """ارسال اعلان براساس تغییر وضعیت."""
    uid = _ad_owner_id(ad)
    if not uid:
        return
    code = str(ad.get('code') or '')
    action_url = _safe_action_url(code)

    if status == 'approved':
        add_notification(
            user_id=uid,
            title="آگهی شما تأیید شد",
            body="آگهی شما در وینور منتشر شد.",
            ntype="success",
            ad_id=code,
            action_url=action_url
        )
        # تلاش برای ارسال Web Push به تمام مشترکین
        try:
            payload = {
                'title': 'آگهی شما تأیید شد',
                'body': 'آگهی شما در وینور منتشر شد.',
                'url': action_url,
                'icon': '/static/icons/icon-192.png',
                'badge': '/static/icons/monochrome-192.png',
                'tag': 'vinor-ad-approved'
            }
            for s in (_load_subs() or []):
                _send_one(s, payload)
        except Exception:
            pass
    elif status == 'rejected':
        body = "آگهی شما نیاز به اصلاح دارد."
        if reason:
            body += f" دلیل: {reason}"
        add_notification(
            user_id=uid,
            title="آگهی شما رد شد / نیاز به اصلاح",
            body=body,
            ntype="warning",
            ad_id=code,
            action_url=action_url
        )
        try:
            payload = {
                'title': 'آگهی شما رد شد / نیاز به اصلاح',
                'body': body,
                'url': action_url,
                'icon': '/static/icons/icon-192.png',
                'badge': '/static/icons/monochrome-192.png',
                'tag': 'vinor-ad-rejected'
            }
            for s in (_load_subs() or []):
                _send_one(s, payload)
        except Exception:
            pass
    elif status == 'expired':
        add_notification(
            user_id=uid,
            title="آگهی شما منقضی شد",
            body="برای تمدید از بخش آگهی‌های من اقدام کنید.",
            ntype="info",
            ad_id=code,
            action_url=url_for('main.my_lands')
        )
        try:
            payload = {
                'title': 'آگهی شما منقضی شد',
                'body': 'برای تمدید از بخش آگهی‌های من اقدام کنید.',
                'url': url_for('main.my_lands'),
                'icon': '/static/icons/icon-192.png',
                'badge': '/static/icons/monochrome-192.png',
                'tag': 'vinor-ad-expired'
            }
            for s in (_load_subs() or []):
                _send_one(s, payload)
        except Exception:
            pass

def notify_admin_edit(ad: Dict[str, Any]):
    """اعلان بعد از ویرایش توسط ادمین."""
    uid = _ad_owner_id(ad)
    if not uid:
        return
    code = str(ad.get('code') or '')
    add_notification(
        user_id=uid,
        title="ویرایش آگهی انجام شد",
        body="تغییرات آگهی شما توسط پشتیبانی وینور اعمال شد.",
        ntype="info",
        ad_id=code,
        action_url=_safe_action_url(code)
    )
    try:
        payload = {
            'title': 'ویرایش آگهی انجام شد',
            'body': 'تغییرات آگهی شما توسط پشتیبانی وینور اعمال شد.',
            'url': _safe_action_url(code),
            'icon': '/static/icons/icon-192.png',
            'badge': '/static/icons/monochrome-192.png',
            'tag': 'vinor-ad-edited'
        }
        for s in (_load_subs() or []):
            _send_one(s, payload)
    except Exception:
        pass

def notify_admin_create(ad: Dict[str, Any]):
    """اعلان بعد از ثبت آگهی توسط ادمین (در صورت وجود صاحب)."""
    uid = _ad_owner_id(ad)
    if not uid:
        return
    code = str(ad.get('code') or '')
    st = str(ad.get('status') or 'pending')
    if st == 'approved':
        title, body, ntype = "آگهی شما منتشر شد", "آگهی شما توسط پشتیبانی وینور ثبت و منتشر شد.", "success"
    else:
        title, body, ntype = "آگهی شما ثبت شد", "وضعیت: در انتظار تأیید.", "status"
    add_notification(
        user_id=uid, title=title, body=body, ntype=ntype,
        ad_id=code, action_url=_safe_action_url(code)
    )
    try:
        payload = {
            'title': title,
            'body': body,
            'url': _safe_action_url(code),
            'icon': '/static/icons/icon-192.png',
            'badge': '/static/icons/monochrome-192.png',
            'tag': 'vinor-ad-created'
        }
        for s in (_load_subs() or []):
            _send_one(s, payload)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# Blueprint (defined centrally)
# -----------------------------------------------------------------------------
try:
    from .blueprint import admin_bp
except Exception:
    from flask import Blueprint
    admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates')


@admin_bp.app_template_filter('admin_upload_src')
def _admin_upload_src_filter(path: str | None) -> str:
    if not path:
        return ''
    s = str(path).strip()
    if '://' in s:
        return s
    if s.startswith('/uploads/'):
        return s
    if s.startswith('uploads/'):
        return '/' + s
    if s.startswith('/'):
        return s
    return f'/uploads/{s}'


# -----------------------------------------------------------------------------
# پیکربندی ساده ادمین (برای شروع)
# -----------------------------------------------------------------------------
# نکته امنیتی: پس از استقرار، این‌ها را از config/DB بخوانید یا به سیستم کاربران/نقش‌ها مهاجرت کنید.
ADMIN_USERNAME = 'masood1528014@gmail.com'
ADMIN_PASSWORD = '09121471301'
ADMIN_LOGIN_OTP_PHONE = '09121471301'
ADMIN_OTP_COOLDOWN_SECONDS = 60

# پیش‌فرض صفحه‌بندی برای گرید 3 ستونه
PER_PAGE_DEFAULT = 9

# -----------------------------------------------------------------------------
# ردیابی همکاران آنلاین (Express Partners)
# -----------------------------------------------------------------------------
# Dict برای ذخیره آخرین فعالیت همکاران (آنلاین + اخیراً آنلاین)
# {phone: {'timestamp': float, 'name': str, 'ip': str, 'last_activity': str}}
_online_partners = {}
_ONLINE_NOW_TIMEOUT_S = 5 * 60
_RECENT_ONLINE_WINDOW_S = 24 * 60 * 60
_ONLINE_PARTNERS_MAX_AGE_S = 7 * 24 * 60 * 60


def _prune_old_online_partners(now: float | None = None) -> None:
    """حذف رکوردهای خیلی قدیمی برای جلوگیری از رشد بی‌حد حافظه."""
    ts = now if now is not None else datetime.utcnow().timestamp()
    stale = [
        phone for phone, data in _online_partners.items()
        if isinstance(data, dict) and (ts - float(data.get('timestamp') or 0)) > _ONLINE_PARTNERS_MAX_AGE_S
    ]
    for phone in stale:
        _online_partners.pop(phone, None)


def _normalize_last_activity_iso(raw: str) -> str:
    """یکسان‌سازی ISO UTC برای نمایش jalali-dt (زمان تهران در فرانت)."""
    raw = (raw or '').strip()
    if not raw:
        return ''
    if raw.endswith('Z') or '+' in raw[10:]:
        return raw
    s = raw.replace(' ', 'T', 1)
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', s):
        return s + 'Z'
    return raw


def _online_partner_entry(phone: str, data: dict) -> dict:
    ts = float(data.get('timestamp') or 0)
    return {
        'phone': phone,
        'name': data.get('name', 'همکار'),
        'ip': data.get('ip', 'نامشخص'),
        'last_activity': _normalize_last_activity_iso(data.get('last_activity', '')),
        'timestamp': ts,
        'online_now': (datetime.utcnow().timestamp() - ts) <= _ONLINE_NOW_TIMEOUT_S,
    }


def _update_online_partner(phone: str, name: str = None, ip: str = None):
    """ثبت/به‌روزرسانی آخرین فعالیت همکار (حتی پس از آفلاین شدن باقی می‌ماند)."""
    _ensure_online_partners_store_loaded()
    ph = _normalize_phone((phone or '').strip()) or (phone or '').strip()
    if not ph:
        return
    now = datetime.utcnow()
    display_name = _resolve_online_partner_display_name(ph, name)
    _online_partners[ph] = {
        'timestamp': now.timestamp(),
        'name': display_name,
        'ip': ip or 'نامشخص',
        'last_activity': now.replace(microsecond=0).isoformat() + 'Z',
    }
    if len(_online_partners) > 500:
        _prune_old_online_partners()
    _persist_online_partners_store()


def _get_recent_online_partners_list(max_age_seconds: int | None = None) -> List[Dict[str, Any]]:
    """لیست همکاران با فعالیت اخیر — جدیدترین آنلاین اول."""
    _ensure_online_partners_store_loaded()
    now = datetime.utcnow().timestamp()
    window = int(max_age_seconds or _RECENT_ONLINE_WINDOW_S)
    recent: List[Dict[str, Any]] = []
    for phone, data in _online_partners.items():
        if not isinstance(data, dict):
            continue
        ts = float(data.get('timestamp') or 0)
        if ts and (now - ts) <= window:
            recent.append(_online_partner_entry(phone, data))
    recent.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return recent


def _get_online_partners_list() -> List[Dict[str, Any]]:
    """همکاران آنلاین در این لحظه (۵ دقیقه اخیر)."""
    _ensure_online_partners_store_loaded()
    now = datetime.utcnow().timestamp()
    online_list = [
        _online_partner_entry(phone, data)
        for phone, data in _online_partners.items()
        if isinstance(data, dict) and (now - float(data.get('timestamp') or 0)) <= _ONLINE_NOW_TIMEOUT_S
    ]
    online_list.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return online_list

# -----------------------------------------------------------------------------
# مسیرهای فایل‌ها (instance/data با fallback)
# -----------------------------------------------------------------------------
def _settings_path() -> str:
    return current_app.config.get(
        'SETTINGS_FILE',
        os.path.join(current_app.instance_path, 'data', 'settings.json')
    )

def _lands_path() -> str:
    primary = current_app.config.get(
        "LANDS_FILE",
        os.path.join(current_app.instance_path, "data", "lands.json")
    )
    if os.path.exists(primary):
        return primary
    # fallback: مسیر قدیمی داخل app/data/lands.json
    fallback = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "data", "lands.json")
    return fallback


# ریشه آپلود تصاویر (static/uploads)
def _uploads_root() -> str:
    return os.path.join(current_app.static_folder, 'uploads')

# -----------------------------------------------------------------------------
# توابع کمکی JSON
# -----------------------------------------------------------------------------
def load_json(path: str):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return data if isinstance(data, (list, dict)) else []
            except json.JSONDecodeError:
                return []
    return []

def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_online_partners_store_loaded = False


def _online_partners_store_path() -> str:
    try:
        return os.path.join(current_app.instance_path, 'data', 'online_partners_last_seen.json')
    except Exception:
        return ''


def _ensure_online_partners_store_loaded() -> None:
    """بارگذاری آخرین فعالیت همکاران از دیسک (یک‌بار در هر process)."""
    global _online_partners_store_loaded
    if _online_partners_store_loaded:
        return
    _online_partners_store_loaded = True
    path = _online_partners_store_path()
    if not path or not os.path.isfile(path):
        return
    try:
        from app.services.notifications import _normalize_user_id
        data = load_json(path)
        if not isinstance(data, dict):
            return
        for ph, row in data.items():
            if not isinstance(row, dict):
                continue
            norm = _normalize_user_id(str(ph)) or str(ph).strip()
            if not norm:
                continue
            prev = _online_partners.get(norm) or {}
            if float(row.get('timestamp') or 0) >= float(prev.get('timestamp') or 0):
                if row.get('last_activity'):
                    row['last_activity'] = _normalize_last_activity_iso(str(row.get('last_activity')))
                _online_partners[norm] = row
    except Exception:
        try:
            current_app.logger.exception('online partners store load failed')
        except Exception:
            pass


def _persist_online_partners_store() -> None:
    path = _online_partners_store_path()
    if not path:
        return
    try:
        save_json(path, _online_partners)
    except Exception:
        try:
            current_app.logger.exception('online partners store save failed')
        except Exception:
            pass


def _resolve_online_partner_display_name(phone: str, hint: str | None = None) -> str:
    """نام نمایشی همکار — از hint، رکورد قبلی، یا پروفایل."""
    hint = (hint or '').strip()
    if hint and hint != 'همکار':
        return hint
    existing = _online_partners.get(phone) or {}
    prev = (existing.get('name') or '').strip()
    if prev and prev != 'همکار':
        return prev
    try:
        for p in load_express_partners() or []:
            if not isinstance(p, dict):
                continue
            pph = _normalize_phone(str(p.get('phone') or '')) or str(p.get('phone') or '').strip()
            if pph != phone:
                continue
            nm = (p.get('name') or p.get('full_name') or '').strip()
            if nm:
                return nm
    except Exception:
        pass
    return hint or prev or 'همکار'


# -----------------------------------------------------------------------------
# تنظیمات سیستم
# -----------------------------------------------------------------------------
def _default_settings() -> Dict[str, Any]:
    return {
        'approval_method': 'manual',
        'ad_expiry_days': 30,  # 0 = نامحدود
        'show_submit_button': True,
        'ad_post_price_toman': 10000,
        # Android APK info
        'android_apk_url': '',
        'android_apk_version': '',
        'android_apk_updated_at': '',
        'android_apk_size_bytes': '',
        'android_apk_sha256': '',
        'android_apk_original_name': '',
        # پیامک بروزرسانی اپ — {version} و {link}
        'android_apk_update_sms_message': (
            'نسخه {version}\n'
            '📢 وینور بروزرسانی شد!\n'
            'برای تجربه بهتر، نسخه جدید رو از لینک زیر دریافت کنید 👇\n'
            '🌐 {link}'
        ),
        'android_apk_update_sms_recipient_group': 'all_users',
        # تنظیمات SMS
        'sms_line_number': '09981801922',  # شماره خط اختصاصی SMS
        # پیام درخواست همکاری (برای همکار)
        'partner_application_sms_message': 'وینور\nدرخواست همکاری‌ت ثبت شد؛ منتظر بررسی.',
        # پیام تایید همکاری (برای همکار)
        'partner_approval_sms_message': 'وینور\nپنل همکاری‌ت فعاله. بزن بریم!',
        # شماره ادمین برای دریافت پیامک درخواست همکاری جدید
        'partner_application_admin_phone': '09121471301',
        # پیامک ارسالی به ادمین هنگام ثبت درخواست همکاری جدید
        'partner_application_admin_sms_message': 'وینور\nهمکاری جدید',
        # روزهای مجاز ثبت بازدید توسط همکار (۵=شنبه … ۴=جمعه)
        'visit_allowed_weekdays': [5, 6, 0, 1, 2, 3, 4],
        # مبلغ ثابت پورسانت هر بازدید (تومان)
        'visit_commission_amount_toman': 0,
        # Vinor AI — مقادیر پیش‌فرض (ویرایش از پنل سوالات AI)
        'ai': {},
    }

def get_settings() -> Dict[str, Any]:
    from app.utils.storage import load_settings

    data: Dict[str, Any] = dict(load_settings() or {})
    defaults = _default_settings()
    for k, v in defaults.items():
        data.setdefault(k, v)
    return data

def save_settings(new_data: Dict[str, Any]) -> None:
    from app.utils.storage import ensure_file, _SETTINGS_CACHE

    data = get_settings()
    data.update({k: v for k, v in new_data.items() if v is not None})
    path = ensure_file('SETTINGS_FILE', 'settings.json', _default_settings())
    save_json(path, data)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})

# -----------------------------------------------------------------------------
# تاریخ/زمان
# -----------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.utcnow()

def iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"

def parse_iso_to_naive_utc(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt.replace(tzinfo=None)
    except Exception:
        return None

# -----------------------------------------------------------------------------
# کمکی‌های لیست آگهی + متای انقضا
# -----------------------------------------------------------------------------
def counts_by_status(lands: List[Dict[str, Any]]):
    pending = sum(1 for l in lands if str(l.get("status", "pending")) == "pending")
    approved = sum(1 for l in lands if str(l.get("status")) == "approved")
    rejected = sum(1 for l in lands if str(l.get("status")) == "rejected")
    return pending, approved, rejected

def paginate(items: List[Any], page: int, per_page: int):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
    }

def find_by_code(lands: List[Dict[str, Any]], code: str) -> Optional[Dict[str, Any]]:
    return next((l for l in lands if str(l.get("code")) == str(code)), None)

def find_by_index(lands: List[Dict[str, Any]], idx: int) -> Optional[Dict[str, Any]]:
    if 0 <= idx < len(lands):
        return lands[idx]
    return None

def expiry_meta(ad: Dict[str, Any]) -> Dict[str, Any]:
    """
    خروجی:
      status: 'unlimited' | 'today' | 'days'
      days_left: int | None
      label: متن آماده نمایش
    """
    exp_str = ad.get("expires_at")
    if not exp_str:
        return {"status": "unlimited", "days_left": None, "label": "نامحدود"}
    exp_dt = parse_iso_to_naive_utc(exp_str)
    if not exp_dt:
        return {"status": "unlimited", "days_left": None, "label": "نامحدود"}
    now = utcnow()
    days_left = (exp_dt.date() - now.date()).days
    if days_left <= 0:
        return {"status": "today", "days_left": 0, "label": "امروز منقضی می‌شود"}
    return {"status": "days", "days_left": days_left, "label": f"{days_left} روز مانده"}

# -----------------------------------------------------------------------------
# پاکسازی آگهی‌های منقضی (حذف کامل + حذف تصاویر)
# -----------------------------------------------------------------------------
def _safe_unlink(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def _delete_ad_images(ad: Dict[str, Any]):
    imgs = ad.get("images") or []
    if isinstance(imgs, str):
        imgs = [imgs]
    for img in imgs:
        if not isinstance(img, str) or not img:
            continue
        candidates = []
        if os.path.isabs(img):
            candidates.append(img)
        else:
            candidates.append(os.path.join(_uploads_root(), img))
            candidates.append(os.path.join(_uploads_root(), os.path.basename(img)))
        
            if img.startswith('static/'):
                candidates.append(os.path.join(current_app.root_path, img))
        for c in candidates:
            try:
                abs_c = os.path.abspath(c)
                uploads_root = os.path.abspath(_uploads_root())
                if abs_c.startswith(uploads_root) or ('/static/uploads/' in abs_c.replace('\\', '/')):
                    _safe_unlink(abs_c)
            except Exception:
                pass

    # حذف ویدئو (اگر وجود داشته باشد)
    try:
        video = ad.get("video")
        if isinstance(video, str) and video:
            candidates = []
            if os.path.isabs(video):
                candidates.append(video)
            else:
                candidates.append(os.path.join(_uploads_root(), video))
                candidates.append(os.path.join(_uploads_root(), os.path.basename(video)))
            for c in candidates:
                try:
                    abs_c = os.path.abspath(c)
                    uploads_root = os.path.abspath(_uploads_root())
                    if abs_c.startswith(uploads_root):
                        _safe_unlink(abs_c)
                except Exception:
                    pass
    except Exception:
        pass

def _unlink_stored_upload(stored_path: str) -> None:
    """حذف یک فایل uploads/static از دیسک (تصویر یا ویدیو)."""
    if not stored_path or not isinstance(stored_path, str):
        return
    path = stored_path.strip()
    if not path:
        return
    candidates: List[str] = []
    if os.path.isabs(path):
        candidates.append(path)
    else:
        if path.startswith('uploads/'):
            candidates.append(os.path.join(_uploads_root(), path[8:]))
            candidates.append(os.path.join(_uploads_root(), path))
        candidates.append(os.path.join(_uploads_root(), os.path.basename(path)))
        if path.startswith('static/'):
            candidates.append(os.path.join(current_app.root_path, path))
    uploads_root = os.path.abspath(_uploads_root())
    for c in candidates:
        try:
            abs_c = os.path.abspath(c)
            if abs_c.startswith(uploads_root) or '/static/uploads/' in abs_c.replace('\\', '/'):
                _safe_unlink(abs_c)
        except Exception:
            pass


def _apply_express_image_edits(land: Dict[str, Any], form, files) -> None:
    """حذف/افزودن تصاویر."""
    images_changed = False

    if (form.get('remove_all_images') or '').strip() in ('1', 'on'):
        for img in land.get('images') or []:
            _unlink_stored_upload(str(img))
        land['images'] = []
        images_changed = True
    else:
        remove_set = {str(x).strip() for x in (form.getlist('remove_images') or []) if str(x).strip()}
        if remove_set:
            kept: List[str] = []
            for img in land.get('images') or []:
                s = str(img).strip()
                if s in remove_set:
                    _unlink_stored_upload(s)
                    images_changed = True
                else:
                    kept.append(img)
            land['images'] = kept

    new_images = _normalize_images_from_form(form, files)
    if not new_images:
        from app.utils.images import save_upload_image
        upload_folder = _uploads_root()
        os.makedirs(upload_folder, exist_ok=True)
        for i in range(1, 4):
            img_key = f'image_{i}'
            f = files.get(img_key)
            if f and f.filename:
                stored = save_upload_image(f, upload_folder)
                if stored:
                    new_images.append(stored)

    if new_images:
        land.setdefault('images', []).extend(new_images)
        images_changed = True

    if images_changed:
        land.pop('images_v2', None)


def _express_commission_from_form(land: Dict[str, Any], form, price_total: int) -> Optional[str]:
    """به‌روز extras پورسانت؛ خطا = پیام flash."""
    pct_raw = (form.get('express_commission_pct') or '').strip()
    if not pct_raw:
        return None
    try:
        pct = float(pct_raw)
    except (TypeError, ValueError):
        return 'درصد پورسانت باید عدد معتبر باشد.'
    if pct <= 0 or pct > 100:
        return 'درصد پورسانت باید بین ۰ و ۱۰۰ باشد.'
    extras = land.get('extras')
    if not isinstance(extras, dict):
        extras = {}
    extras['express_commission_pct'] = pct
    extras['express_commission_amount'] = int(round(price_total * (pct / 100.0))) if price_total else 0
    land['extras'] = extras
    return None


def cleanup_expired_ads() -> None:
    """حذف کامل آگهی‌های منقضی‌شده از JSON و حذف تصاویرشان."""
    try:
        lands_path = _lands_path()
        lands = load_json(lands_path)
        if not isinstance(lands, list) or not lands:
            return

        kept: List[Dict[str, Any]] = []
        changed = False

        for ad in lands:
            exp_str = ad.get("expires_at")
            expired_flag = False
            if exp_str:
                exp_dt = parse_iso_to_naive_utc(exp_str)
                if exp_dt is None or exp_dt < utcnow():
                    expired_flag = True

            if expired_flag:
                try:
                    _delete_ad_images(ad)
                except Exception as e:
                    # لاگ خطا در صورت عدم موفقیت در حذف تصاویر
                    try:
                        current_app.logger.warning(f"Failed to delete images for expired ad {ad.get('code')}: {e}")
                    except Exception:
                        pass
                changed = True
                continue
            kept.append(ad)

        if changed:
            try:
                save_json(lands_path, kept)
                try:
                    current_app.logger.info(f"Cleaned up {len(lands) - len(kept)} expired ads")
                except Exception:
                    pass
            except Exception as e:
                # لاگ خطا در صورت عدم موفقیت در ذخیره
                try:
                    current_app.logger.error(f"Failed to save cleaned ads: {e}")
                except Exception:
                    pass
    except Exception as e:
        # لاگ خطای کلی
        try:
            current_app.logger.error(f"Error in cleanup_expired_ads: {e}")
        except Exception:
            pass

# -----------------------------------------------------------------------------
# دکوراتور لاگین
# -----------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        return view(*args, **kwargs)
    return wrapper

# -----------------------------------------------------------------------------
# احراز هویت
# -----------------------------------------------------------------------------

def _store_admin_otp_session(code: str) -> None:
    save_admin_otp(code)


def _send_admin_login_otp_async(code: str, phone: str) -> None:
    """ارسال OTP در thread جدا — درخواست HTTP بلافاصله آزاد می‌شود (مهم برای LSAPI workers)."""
    app = current_app._get_current_object()

    def _worker() -> None:
        with app.app_context():
            sms_result = send_sms_code(phone, code)
            if not sms_result.get("ok"):
                current_app.logger.error(
                    "Admin login OTP send failed | phone=%s | status=%s | body=%s",
                    phone,
                    sms_result.get("status"),
                    sms_result.get("body"),
                )

    threading.Thread(target=_worker, daemon=True, name="admin-login-otp").start()


@admin_bp.before_request
def admin_force_https():
    """کوکی Secure روی HTTP ذخیره نمی‌شود — کل پنل ادمین فقط HTTPS."""
    if request.is_secure:
        return None
    host = (request.host or "").split(":")[0].lower()
    if host not in ("vinor.ir", "www.vinor.ir"):
        return None
    path = request.path or ""
    if not path.startswith("/admin"):
        return None
    url = request.url or ""
    if url.startswith("http://"):
        return redirect(url.replace("http://", "https://", 1), code=301)
    return None


@admin_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    """
    نکته امنیتی:
    - در تمپلیت admin/login.html CSRF token قرار دارد.
    - معافیت CSRF در app/__init__.py (پس از CSRFProtect.init_app) اعمال می‌شود.
    """
    # سشن هنوز معتبر است (همان مرورگر/دستگاه، کوکی در مدت PERMANENT_SESSION_LIFETIME)
    if session.get('logged_in'):
        return redirect(url_for('admin.dashboard'))

    now_ts = datetime.utcnow().timestamp()
    otp_state = load_admin_otp()
    last_sent_at = float((otp_state or {}).get('last_sent_at') or session.get('admin_otp_last_sent_at') or 0)
    cooldown_seconds = max(0, ADMIN_OTP_COOLDOWN_SECONDS - int(now_ts - last_sent_at)) if last_sent_at else 0

    def _render_login():
        return render_template(
            'admin/login.html',
            otp_phone=ADMIN_LOGIN_OTP_PHONE,
            otp_cooldown_seconds=max(0, int(cooldown_seconds)),
        )

    # ورود به صفحه لاگین: ارسال خودکار OTP (غیرهمزمان — worker LiteSpeed بلاک نمی‌شود)
    if request.method == 'GET':
        if cooldown_seconds == 0:
            code = f"{random.randint(10000, 99999)}"
            _store_admin_otp_session(code)
            cooldown_seconds = ADMIN_OTP_COOLDOWN_SECONDS
            _send_admin_login_otp_async(code, ADMIN_LOGIN_OTP_PHONE)
            flash('با اشتیاق منتظرتیم', 'info')
        return _render_login()

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip().lower()
        otp_code = (request.form.get('otp_code') or '').strip()

        if action == 'send':
            if cooldown_seconds > 0:
                flash(f'امکان ارسال مجدد تا {cooldown_seconds} ثانیه دیگر فعال می‌شود.', 'warning')
                return _render_login()
            code = f"{random.randint(10000, 99999)}"
            _store_admin_otp_session(code)
            cooldown_seconds = ADMIN_OTP_COOLDOWN_SECONDS
            _send_admin_login_otp_async(code, ADMIN_LOGIN_OTP_PHONE)
            flash('با اشتیاق منتظرتیم', 'info')
            return _render_login()

        # مرحله ۲: تایید کد پیامکی
        if otp_code:
            otp_state = load_admin_otp() or {}
            expected_code = str(otp_state.get('code') or session.get('admin_otp_code') or '')
            expires_at = otp_state.get('expires_at') or session.get('admin_otp_expires_at')
            now_ts = datetime.utcnow().timestamp()

            if (not expires_at) or (now_ts > float(expires_at)):
                clear_admin_otp()
                flash('کد ورود منقضی شده است. دوباره وارد شوید.', 'warning')
                return _render_login()

            if otp_code == expected_code:
                session['logged_in'] = True
                session['username'] = ADMIN_USERNAME
                session['admin_phone'] = ADMIN_LOGIN_OTP_PHONE
                session.permanent = True
                clear_admin_otp()
                _admin_audit(
                    'admin_login',
                    actor_key=ADMIN_LOGIN_OTP_PHONE,
                    entity_type='admin_session',
                    entity_id=ADMIN_USERNAME,
                    summary='Admin OTP login success',
                )
                flash('خوش آمدید؛ ورود موفق.', 'success')
                return redirect(url_for('admin.dashboard'))

            flash('کد ورود اشتباه است.', 'danger')
            return _render_login()
        flash('کد ورود را وارد کنید.', 'warning')
    return _render_login()

@admin_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    # فقط کلیدهای ادمین؛ ورود همکار (user_phone) روی همان مرورگر حفظ می‌ماند
    for k in (
        'logged_in',
        'username',
        'admin_phone',
    ):
        session.pop(k, None)
    clear_admin_otp()
    if not session.get('user_phone'):
        session.permanent = False
    flash('خروج انجام شد.', 'info')
    return redirect(url_for('admin.login'))

# -----------------------------------------------------------------------------
# PWA Routes
# -----------------------------------------------------------------------------
@admin_bp.route('/manifest.webmanifest')
def admin_manifest():
    """سرو manifest برای PWA ادمین"""
    from flask import send_from_directory, Response
    import os
    
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    manifest_path = os.path.join(static_dir, 'admin-manifest.webmanifest')
    
    if os.path.exists(manifest_path):
        resp = send_from_directory(static_dir, 'admin-manifest.webmanifest', mimetype='application/manifest+json')
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    # Fallback
    fallback = {
        "id": "/admin",
        "name": "پنل مدیریت وینور",
        "short_name": "وینور ادمین",
        "description": "پنل مدیریت وینور اکسپرس",
        "dir": "rtl",
        "lang": "fa",
        "start_url": "/admin/?source=pwa",
        "scope": "/admin/",
        "display": "standalone",
        "background_color": "#7C3AED",
        "theme_color": "#7C3AED",
        "icons": [
            { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
            { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
        ]
    }
    resp = Response(json.dumps(fallback, ensure_ascii=False), mimetype='application/manifest+json')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@admin_bp.route('/sw.js')
def admin_service_worker():
    """سرو service worker برای PWA ادمین"""
    from flask import send_from_directory
    import os
    
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    sw_path = os.path.join(static_dir, 'admin-sw.js')
    
    if os.path.exists(sw_path):
        resp = send_from_directory(static_dir, 'admin-sw.js', mimetype='application/javascript')
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    return ('// Admin Service Worker not found', 404)

# -----------------------------------------------------------------------------
# داشبورد و صفحات کلی
# -----------------------------------------------------------------------------
@admin_bp.route('/select', endpoint='select_portal')
@login_required
def select_portal():
    """صفحه انتخاب پنل بعد از لاگین: وینور اصلی یا وینور اکسپرس."""
    return render_template('admin/select_portal.html')


# dashboard / admin_root → admin.ops_chat_routes (چت عملیات)


@admin_bp.route('/super-admin', endpoint='super_admin_info')
@login_required
def super_admin_info():
    """Phase 5 — صفحه اطلاعات Super Admin (روی login_required موجود)."""
    from app.roles.service import is_super_admin
    from app.roles.config import super_admin_phones

    if not is_super_admin():
        flash('دسترسی Super Admin لازم است.', 'error')
        return redirect(url_for('admin.dashboard'))

    return render_template(
        'admin/super_admin_info.html',
        allowlist=super_admin_phones(),
        admin_phone=session.get('admin_phone') or ADMIN_LOGIN_OTP_PHONE,
    )


@admin_bp.route('/audit', endpoint='audit_log')
@login_required
def audit_log_page():
    """Phase 7 — Audit ادمین (Foundation Activity source=admin)."""
    try:
        from app.hardening.config import hardening_ui_enabled
        from app.hardening.permissions import PERM_AUDIT, has_permission
        from app.hardening.service import list_admin_audit

        if not hardening_ui_enabled():
            abort(404)
        if not has_permission(PERM_AUDIT):
            flash('دسترسی Audit ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
        events = list_admin_audit(limit=100)
    except Exception:
        abort(404)

    return render_template(
        'admin/audit.html',
        events=events,
    )


@admin_bp.route('/partners/activity', methods=['GET'], endpoint='partners_activity')
@login_required
def partners_activity():
    """فعالیت همکاران → فیلتر آنلاین در لیست یکپارچه."""
    return redirect(url_for('admin.express_partners', filter='online'))


@admin_bp.route('/top-sellers', methods=['GET'], endpoint='top_sellers')
@login_required
def top_sellers_page():
    """رتبه‌بندی فروشنده‌های برتر (فقط ادمین)."""
    try:
        partners = load_express_partners() or []
        commissions = load_express_commissions() or []

        def _i(v):
            try:
                return int(str(v).replace(',', '').strip() or '0')
            except Exception:
                return 0

        partner_stats: dict[str, dict] = {}
        for partner in partners:
            partner_phone = str(partner.get('phone', '')).strip()
            if not partner_phone:
                continue
            my_comms = [
                c for c in commissions
                if str(c.get('partner_phone', '')).strip() == partner_phone
            ]
            total_commission = sum(
                _i(c.get('commission_amount'))
                for c in my_comms
                if (c.get('status') or '').strip() in ('approved', 'paid')
            )
            sales_count = sum(
                1 for c in my_comms
                if (c.get('status') or '').strip() in ('approved', 'paid')
            )
            partner_stats[partner_phone] = {
                'partner': partner,
                'total_commission': total_commission,
                'sales_count': sales_count,
                'total_income': _i(partner.get('total_income', 0)),
                'approved_sales_count': _i(partner.get('approved_sales_count', 0)),
            }

        top_sellers = sorted(
            partner_stats.values(),
            key=lambda x: max(x['total_income'], x['total_commission']),
            reverse=True,
        )
        top_sellers = [
            s for s in top_sellers
            if s['sales_count'] > 0 or s['approved_sales_count'] > 0
        ]
    except Exception as e:
        current_app.logger.error(f"Error loading top sellers: {e}", exc_info=True)
        top_sellers = []

    return render_template('admin/top_sellers.html', top_sellers=top_sellers)


@admin_bp.route('/users')
@login_required
def users_page():
    q = (request.args.get('q') or '').strip()
    return redirect(url_for('admin.express_partners', q=q, filter='users'))

# -----------------------------------------------------------------------------
# ارسال اعلان همگانی به همهٔ کاربران
# -----------------------------------------------------------------------------
@admin_bp.route('/notifications/broadcast', methods=['GET', 'POST'])
@login_required
def notifications_broadcast():
    message = None
    error = None
    # Diagnostics for push configuration/subscribers
    try:
        subs_for_diag = _load_subs()
    except Exception:
        subs_for_diag = []
    push_diag = {
        'has_public': bool(current_app.config.get('VAPID_PUBLIC_KEY')),
        'has_private': bool(current_app.config.get('VAPID_PRIVATE_KEY')),
        'subs_count': len(subs_for_diag or []),
        'tagged_count': sum(1 for s in (subs_for_diag or []) if s.get('user_phone')),
    }
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body  = (request.form.get('body') or '').strip()
        ntype = (request.form.get('type') or 'info').strip() or 'info'
        # واکشی کاربران
        try:
            users = load_users()
        except Exception:
            users = []
        user_ids = []
        for u in users if isinstance(users, list) else []:
            uid = str(u.get('id') or u.get('user_id') or u.get('phone') or u.get('mobile') or '').strip()
            if uid:
                user_ids.append(uid)
        if not title or not body:
            error = 'عنوان و متن اعلان الزامی است.'
        elif not user_ids:
            error = 'هیچ کاربری یافت نشد.'
        else:
            sent = 0
            # ثبت اعلان در in-app notifications
            for uid in user_ids:
                try:
                    add_notification(uid, title=title, body=body, ntype=ntype)
                    sent += 1
                except Exception:
                    pass

            # تلاش برای ارسال Web Push با صدا (در کلاینت)
            try:
                subs = _load_subs()
            except Exception:
                subs = []
            push_sent = 0
            payload = {
                "title": title,
                "body": body,
                "icon": "/static/icons/icon-192.png",
                "badge": "/static/icons/monochrome-192.png",
                "url": url_for('main.app_home', _external=True),
                "sound": "/static/sounds/notify.mp3"
            }
            for s in subs:
                res = _send_one(s, payload)
                if res.get('ok'): push_sent += 1
            message = f'اعلان برای {sent} کاربر ثبت و {push_sent} پوش ارسال شد.'
            # update diagnostics after send
            try:
                subs_for_diag = _load_subs()
            except Exception:
                subs_for_diag = []
            push_diag.update({'subs_count': len(subs_for_diag or [])})

    return render_template('admin/broadcast.html', message=message, error=error, push_diag=push_diag)

# -----------------------------------------------------------------------------
# ارسال اعلان به همکاران (Express Partners)
# -----------------------------------------------------------------------------
def _normalize_phone(phone: str) -> str:
    """Normalize phone number to standard format (09xxxxxxxxx) - استفاده از همان تابع notifications"""
    from app.services.notifications import _normalize_user_id
    return _normalize_user_id(phone)


def _load_approved_express_partners() -> List[Dict[str, str]]:
    from app.express_partner.new_land_sms import list_approved_express_partners
    return list_approved_express_partners()


def _send_colleagues_notification_broadcast(
    title: str,
    body: str,
    ntype: str,
    approved_partners: List[Dict[str, str]],
    *,
    source: str = 'admin_colleagues',
    broadcast_id: Optional[str] = None,
) -> Dict[str, Any]:
    from app.services.notifications import add_notifications_batch
    from app.services.notification_history import append_broadcast
    from app.services.fcm_tokens import fcm_stats_for_phones
    from app.services.fcm_push import is_fcm_configured
    from app.services.firebase_config import ensure_firebase_ready

    ensure_firebase_ready()
    bid = broadcast_id or str(uuid.uuid4())
    notify_url = url_for('express_partner.home', ai=1, thread='__postchi__')
    phones = [p['phone'] for p in approved_partners if p.get('phone')]
    fcm_stats = fcm_stats_for_phones(phones)

    batch = add_notifications_batch(
        user_ids=phones,
        title=title,
        body=body,
        ntype=ntype,
        action_url=notify_url,
        broadcast_id=bid,
        source=source,
    )
    sent = int(batch.get('success_count') or 0)
    failed = int(batch.get('failed_count') or 0)

    push_targets = int(fcm_stats.get('devices') or 0)
    push_queued = push_targets > 0 and is_fcm_configured()
    push_sent = 0
    push_failed = 0

    admin_user = session.get('admin_user') or session.get('username') or None
    record = append_broadcast(
        title=title,
        body=body,
        ntype=ntype,
        recipient_count=len(approved_partners),
        success_count=sent,
        failed_count=failed,
        push_sent=push_sent,
        push_failed=push_failed,
        push_queued=push_queued,
        push_targets=push_targets,
        fcm_users=int(fcm_stats.get('users') or 0),
        source=source,
        broadcast_id=bid,
        admin_user=admin_user,
    )

    try:
        from app.supervisor_agent.hooks import report_admin_broadcast_push

        report_admin_broadcast_push(sent=sent, failed=failed, title=title)
    except Exception:
        pass

    return {
        'broadcast': record,
        'sent': sent,
        'failed': failed,
        'push_sent': push_sent,
        'push_failed': push_failed,
        'push_queued': push_queued,
        'push_targets': push_targets,
        'fcm_configured': is_fcm_configured(),
    }


@admin_bp.route('/notifications/colleagues', methods=['GET', 'POST'])
@login_required
def notifications_colleagues():
    from app.services.notification_history import list_broadcasts, broadcast_stats
    from app.services.notifications import get_all_notifications_stats

    message = None
    error = None
    test_message = None
    test_error = None
    test_result = None
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        from app.services.firebase_config import ensure_firebase_ready, get_firebase_status
        from app.services.fcm_tokens import fcm_stats_for_phones
        ensure_firebase_ready()
        fcm_diag = get_firebase_status()
        partner_phones = [p.get('phone') for p in _load_approved_express_partners() if p.get('phone')]
        fcm_stats = fcm_stats_for_phones(partner_phones)
    except Exception:
        fcm_diag = {}
        fcm_stats = {"users": 0, "devices": 0}
    push_diag = {
        'fcm_send_ready': bool(fcm_diag.get('send_ready')),
        'fcm_mobile_ready': bool(fcm_diag.get('mobile_ready')),
        'fcm_project_id': fcm_diag.get('project_id'),
        'fcm_users': int(fcm_stats.get('users') or 0),
        'fcm_devices': int(fcm_stats.get('devices') or 0),
    }

    approved_partners = _load_approved_express_partners()

    if request.method == 'POST' and request.form.get('test_action') == 'test':
        from app.services.notifications import (
            get_user_notifications,
            _normalize_user_id,
        )
        from app.services.fcm_tokens import tokens_for_phone
        from app.services.firebase_config import ensure_firebase_ready
        ensure_firebase_ready()
        test_phone = (request.form.get('test_phone') or '').strip()
        test_title = (request.form.get('test_title') or '').strip() or 'تست اعلان'
        test_body = (request.form.get('test_body') or '').strip() or 'این یک اعلان تستی است برای بررسی سیستم.'
        if not test_phone:
            test_error = 'شماره تلفن تست الزامی است.'
        else:
            try:
                normalized = _normalize_user_id(test_phone)
                test_notif = add_notification(
                    user_id=normalized,
                    title=test_title,
                    body=test_body,
                    ntype="info",
                    source="admin_test",
                )
                notifications = get_user_notifications(normalized, limit=10)
                test_result = {
                    "phone_normalized": normalized,
                    "notification_added": test_notif.get("id") if test_notif else None,
                    "notifications_found": len(notifications),
                    "fcm_tokens": len(tokens_for_phone(normalized)),
                }
                fcm_n = test_result["fcm_tokens"]
                test_message = (
                    f'تست موفق. اعلان برای {normalized} ثبت شد'
                    + (f' و FCM به {fcm_n} دستگاه در صف ارسال قرار گرفت.' if fcm_n else ' (FCM token ثبت نشده — در APK لاگین کنید).')
                )
            except Exception as e:
                test_error = f'خطا در تست: {str(e)}'
                current_app.logger.error(f"Notification test error: {e}", exc_info=True)

        if is_ajax:
            status = 400 if test_error else 200
            return jsonify({
                'success': not test_error,
                'message': test_message,
                'error': test_error,
                'test_result': test_result,
            }), status

    elif request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body = (request.form.get('body') or '').strip()
        ntype = (request.form.get('type') or 'info').strip() or 'info'

        if not title or not body:
            error = 'عنوان و متن اعلان الزامی است.'
        elif not approved_partners:
            error = 'هیچ همکار تأییدشده‌ای با شماره معتبر یافت نشد.'
        else:
            try:
                result = _send_colleagues_notification_broadcast(
                    title, body, ntype, approved_partners
                )
                sent = result['sent']
                failed = result['failed']
                push_sent = result['push_sent']
                push_failed = result['push_failed']
                if failed > 0:
                    message = f'اعلان برای {sent} همکار ثبت شد ({failed} خطا).'
                else:
                    message = f'اعلان برای {sent} همکار ثبت شد.'
                if result.get('push_queued'):
                    targets = result.get('push_targets') or result.get('broadcast', {}).get('push_targets', 0)
                    message += f' FCM به {targets} دستگاه در حال ارسال است.'
                elif not result.get('fcm_configured'):
                    message += ' (FCM روی سرور فعال نیست — push موبایل ارسال نمی‌شود).'
                elif (result.get('push_targets') or 0) == 0:
                    message += ' (هیچ FCM token ثبت‌شده‌ای نیست — همکاران باید APK را نصب و لاگین کنند).'
                if is_ajax:
                    return jsonify({
                        'success': True,
                        'message': message,
                        'broadcast': result.get('broadcast'),
                        'sent': sent,
                        'failed': failed,
                        'push_sent': push_sent,
                        'push_failed': push_failed,
                        'push_queued': result.get('push_queued', False),
                    })
            except Exception as e:
                error = f'خطا در ارسال: {str(e)}'
                current_app.logger.error(f"Colleagues notification broadcast failed: {e}", exc_info=True)
                if is_ajax:
                    return jsonify({'success': False, 'error': error}), 500

        if is_ajax:
            return jsonify({'success': False, 'error': error or 'خطا در ارسال'}), 400

    try:
        stats = get_all_notifications_stats()
    except Exception:
        stats = {}

    history = list_broadcasts(limit=40)
    history_stats = broadcast_stats()

    return render_template(
        'admin/colleagues_broadcast.html',
        message=message,
        error=error,
        push_diag=push_diag,
        partners_count=len(approved_partners),
        stats=stats,
        history=history,
        history_stats=history_stats,
        test_message=test_message,
        test_error=test_error,
        test_result=test_result,
    )


@admin_bp.route('/api/notifications/colleagues/history', methods=['GET'])
@login_required
def api_colleagues_notification_history():
    from app.services.notification_history import list_broadcasts, broadcast_stats
    try:
        limit = min(100, max(1, int(request.args.get('limit', 40))))
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        limit, offset = 40, 0
    items = list_broadcasts(limit=limit, offset=offset)
    return jsonify({
        'success': True,
        'items': items,
        'stats': broadcast_stats(),
    })

# -----------------------------------------------------------------------------
# ارسال پیامک به همکاران (Express Partners)
# -----------------------------------------------------------------------------
def _normalize_for_sms_ir(mobile: str) -> str:
    """Convert various Iran mobile formats to 09xxxxxxxxx expected by sms.ir verify API."""
    if not mobile:
        return ''
    s = str(mobile).strip().replace(' ', '').replace('-', '')
    # +98XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('+98') and len(s) == 13 and s[3:].startswith('9'):
        return '0' + s[3:]
    # 0098XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('0098') and len(s) == 14 and s[4:].startswith('9'):
        return '0' + s[4:]
    # 98XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('98') and len(s) == 12 and s[2:].startswith('9'):
        return '0' + s[2:]
    # 9XXXXXXXXX → 09XXXXXXXXX
    if s.startswith('9') and len(s) == 10:
        return '0' + s
    # already 09XXXXXXXXX
    if s.startswith('0') and len(s) == 11:
        return s
    return s

@admin_bp.route('/sms/recipients', methods=['GET'])
@login_required
def sms_recipients():
    """فهرست گروه‌های گیرنده پیامک."""
    ensure_sms_recipient_groups_initialized()
    return render_template(
        'admin/sms_recipients_index.html',
        groups=list_sms_recipient_groups_summary(),
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
        max_upload_files=MAX_UPLOAD_FILES,
    )


@admin_bp.route('/sms/recipients/<group_key>/upload', methods=['POST'])
@login_required
def sms_recipients_upload(group_key):
    """آپلود یک یا چند فایل .txt به یک گروه — پشتیبانی حجم بالا و پاسخ JSON."""
    from flask import flash

    key = normalize_recipient_group(group_key)
    label = recipient_group_label(key)
    replace = (request.form.get('replace') or '').strip() in ('1', 'on', 'true', 'yes')
    text = (request.form.get('phones_text') or '').strip()
    want_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or (request.accept_mimetypes.best and 'application/json' in str(request.accept_mimetypes))
        or (request.form.get('ajax') or '').strip() == '1'
    )

    def _respond(payload: dict, *, status: int = 200, flash_cat: str | None = None):
        if want_json:
            return jsonify(payload), status
        if flash_cat and payload.get('message'):
            flash(payload['message'], flash_cat)
        if payload.get('error') and flash_cat != 'error':
            flash(payload['error'], 'error')
        return redirect(url_for('admin.sms_recipients'))

    uploads = request.files.getlist('phones_files')
    if not any(getattr(u, 'filename', None) for u in uploads):
        legacy = request.files.get('phones_file')
        uploads = [legacy] if legacy and getattr(legacy, 'filename', None) else []

    file_text, ok_files, bad_files, meta = read_phones_upload_files(uploads)
    if meta.get('error'):
        return _respond({'ok': False, 'error': meta['error'], 'message': meta['error']}, status=400, flash_cat='error')

    if file_text:
        text = ((text + '\n') if text else '') + file_text
    elif any(getattr(u, 'filename', None) for u in uploads):
        err = 'خواندن فایل(های) آپلود ممکن نشد.'
        if bad_files:
            err += ' ' + '، '.join(bad_files[:5])
        return _respond({'ok': False, 'error': err, 'message': err}, status=400, flash_cat='error')

    if not (text or '').strip():
        err = 'حداقل یک فایل .txt یا متن شماره وارد کنید.'
        return _respond({'ok': False, 'error': err, 'message': err}, status=400, flash_cat='error')

    result = import_sms_recipient_phones(key, text, replace=replace)
    result['files'] = len(ok_files)
    result['bytes_read'] = int(meta.get('bytes_read') or 0)
    msg = format_import_result_message(label, result, replace=replace)
    if ok_files:
        files_note = f'{len(ok_files)} فایل'
        if len(ok_files) <= 4:
            files_note += ': ' + '، '.join(ok_files)
        msg = files_note + ' — ' + msg

    payload = {
        'ok': True,
        'message': msg,
        'label': label,
        'group': key,
        'result': result,
        'ok_files': ok_files,
        'bad_files': bad_files,
    }
    if bad_files and not want_json:
        flash('خوانده نشد: ' + '، '.join(bad_files[:8]), 'error')
    return _respond(payload, flash_cat='success')


@admin_bp.route('/sms/recipients/<group_key>/phones.txt', methods=['GET'])
@login_required
def sms_recipients_phones_txt(group_key):
    """دانلود شماره‌های گروه — یک شماره در هر خط."""
    from flask import Response

    key = normalize_recipient_group(group_key)
    body = export_sms_recipient_phones_txt(key)
    filename = f"sms-recipients-{key}.txt"
    return Response(
        body,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_bp.route('/sms/recipients/<group_key>', methods=['GET', 'POST'])
@login_required
def sms_recipients_edit(group_key):
    """ویرایش اعضای یک گروه گیرنده."""
    key = normalize_recipient_group(group_key)
    message = None
    error = None

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'sync':
            count = sync_sms_recipient_group(key)
            message = f'گروه از سیستم همگام شد — {count} عضو.'
        elif action == 'meta':
            update_sms_recipient_group_meta(
                key,
                label=(request.form.get('label') or '').strip(),
                hint=(request.form.get('hint') or '').strip(),
            )
            message = 'عنوان و توضیح گروه ذخیره شد.'
        elif action == 'add':
            err = add_sms_recipient_member(
                key,
                (request.form.get('phone') or '').strip(),
                (request.form.get('name') or '').strip(),
            )
            if err:
                error = err
            else:
                message = 'عضو جدید اضافه شد.'
        elif action == 'update':
            err = update_sms_recipient_member(
                key,
                (request.form.get('phone') or '').strip(),
                (request.form.get('name') or '').strip(),
            )
            if err:
                error = err
            else:
                message = 'عضو به‌روزرسانی شد.'
        elif action == 'delete':
            err = remove_sms_recipient_member(key, (request.form.get('phone') or '').strip())
            if err:
                error = err
            else:
                message = 'عضو حذف شد.'

    detail = get_sms_recipient_group_detail(
        key,
        page=request.args.get('page', 1),
        per_page=request.args.get('per_page', 50),
    )
    return render_template(
        'admin/sms_recipients_edit.html',
        group=detail,
        message=message,
        error=error,
    )


@admin_bp.route('/sms/colleagues', methods=['GET', 'POST'])
@login_required
def sms_colleagues():
    """ارسال پیامک به گروه‌های انتخاب‌شده (همکار / همه کاربران / باشگاه مشتریان)"""
    from datetime import datetime
    from app.services.sms_config import get_sms_line_number

    message = None
    error = None
    send_mode = request.form.get('send_mode', request.args.get('mode', 'direct'))
    form_direct_message = ''
    form_template_id = ''
    form_message_text = ''
    recipient_group = normalize_recipient_group(
        request.form.get('recipient_group')
        or request.args.get('recipient_group')
        or get_saved_recipient_group()
        or ''
    )
    ensure_sms_recipient_groups_initialized()
    recipient_counts = recipient_group_counts()
    partners_count = int(recipient_counts.get(recipient_group) or 0)
    groups_summary = list_sms_recipient_groups_summary()
    dynamic_labels = {g["key"]: g["label"] for g in groups_summary}
    dynamic_hints = {g["key"]: g["hint"] for g in groups_summary}
    group_label = dynamic_labels.get(recipient_group) or recipient_group_label(recipient_group)
    default_line = (get_sms_line_number() or '09981801922').strip()
    form_send_timing = SEND_TIMING_INSTANT
    form_scheduled_at = ''
    form_recurrence_freq = 'daily'
    form_recurrence_time = '09:00'
    form_recurrence_weekday = 5
    form_recurrence_day = 1
    form_send_limit = ''

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'save_recipient_group':
            group = save_recipient_group_preference(request.form.get('recipient_group') or '')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
                request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json'
            ):
                return jsonify({'ok': True, 'recipient_group': group})
            return redirect(url_for('admin.sms_colleagues', recipient_group=group))
        if action == 'cancel_scheduled':
            job_id = (request.form.get('job_id') or '').strip()
            if cancel_scheduled_job(job_id):
                message = 'زمان‌بندی لغو شد.'
            else:
                error = 'زمان‌بندی یافت نشد یا قبلاً اجرا/لغو شده است.'
        else:
            send_mode = request.form.get('send_mode', 'direct')
            recipient_group = normalize_recipient_group(request.form.get('recipient_group') or recipient_group)
            save_recipient_group_preference(recipient_group)
            groups_summary = list_sms_recipient_groups_summary()
            dynamic_labels = {g["key"]: g["label"] for g in groups_summary}
            dynamic_hints = {g["key"]: g["hint"] for g in groups_summary}
            group_label = dynamic_labels.get(recipient_group) or recipient_group_label(recipient_group)
            partners_count = count_sms_recipients(recipient_group)

            if partners_count < 1:
                error = f'هیچ گیرنده‌ای در گروه «{group_label}» با شماره معتبر یافت نشد.'
            elif send_mode == 'direct':
                form_direct_message = (request.form.get('direct_message') or '').strip()
                line_number = default_line
                form_send_timing = (request.form.get('send_timing') or SEND_TIMING_INSTANT).strip()
                form_scheduled_at = (request.form.get('scheduled_at') or '').strip()
                form_recurrence_freq = (request.form.get('recurrence_freq') or 'daily').strip()
                form_recurrence_time = (request.form.get('recurrence_time') or '09:00').strip()
                try:
                    form_recurrence_weekday = int(request.form.get('recurrence_weekday') or 5)
                except ValueError:
                    form_recurrence_weekday = 5
                try:
                    form_recurrence_day = int(request.form.get('recurrence_day') or 1)
                except ValueError:
                    form_recurrence_day = 1
                form_send_limit = (request.form.get('send_limit') or '').strip()

                if not form_direct_message:
                    error = 'متن پیامک الزامی است.'
                elif form_send_timing == SEND_TIMING_INSTANT:
                    from admin.sms_scheduled import parse_send_limit
                    batch_limit, limit_err = parse_send_limit(form_send_limit or None, partners_count)
                    if limit_err:
                        error = limit_err
                    elif partners_count >= LARGE_GROUP_REQUIRE_BATCH and not batch_limit:
                        error = (
                            f'گروه {partners_count} نفره است؛ برای جلوگیری از کندی، '
                            '«تعداد ارسال در هر مرحله» را مشخص کنید (مثلاً ۵۰ تا ۵۰۰).'
                        )
                    else:
                        recipients = load_sms_recipients(
                            recipient_group,
                            limit=batch_limit,
                            offset=0,
                            validate=False,
                        )
                        sent, failed, failed_details = send_direct_to_recipients(
                            recipients,
                            form_direct_message,
                            line_number,
                        )
                        if failed > 0:
                            message = f'پیامک به {sent} نفر از گروه «{group_label}» ارسال شد ({failed} خطا).'
                            if len(failed_details) <= 5:
                                error = 'خطاها: ' + '; '.join(
                                    f"{d['name']} ({d['phone']}): {d['error']}" for d in failed_details
                                )
                        else:
                            message = f'پیامک با موفقیت به {sent} نفر از گروه «{group_label}» ارسال شد.'
                            form_direct_message = ''
                elif form_send_timing in (SEND_TIMING_SCHEDULED, SEND_TIMING_RECURRING):
                    job, job_error = create_scheduled_job(
                        recipient_group=recipient_group,
                        message=form_direct_message,
                        line_number=line_number,
                        send_timing=form_send_timing,
                        scheduled_at=form_scheduled_at,
                        recurrence_freq=form_recurrence_freq,
                        recurrence_time=form_recurrence_time,
                        recurrence_weekday=form_recurrence_weekday,
                        recurrence_day=form_recurrence_day,
                        send_limit=form_send_limit or None,
                    )
                    if job_error:
                        error = job_error
                    else:
                        next_at = format_tehran_iso_display(job.get('next_run_at'))
                        batch_label = send_batch_summary(job)
                        if form_send_timing == SEND_TIMING_RECURRING:
                            message = (
                                f'ارسال تکرارشونده ثبت شد ({recurrence_summary(job)} — {batch_label} — وقت تهران). '
                                f'اجرای بعدی: {next_at}'
                            )
                        else:
                            message = (
                                f'ارسال زمان‌دار ثبت شد ({batch_label} — وقت تهران). '
                                f'زمان اجرا: {next_at}'
                            )
                        form_direct_message = ''
                else:
                    error = 'نوع زمان‌بندی نامعتبر است.'

            elif send_mode == 'template':
                form_template_id = (request.form.get('template_id') or '').strip()
                form_message_text = (request.form.get('message_text') or '').strip()

                if not form_template_id:
                    error = 'شناسه قالب الزامی است.'
                else:
                    try:
                        template_id = int(form_template_id)
                    except ValueError:
                        error = 'شناسه قالب باید عدد باشد.'
                        template_id = None

                    if template_id is not None:
                        if partners_count >= LARGE_GROUP_REQUIRE_BATCH:
                            error = (
                                f'گروه {partners_count} نفره است؛ برای قالب از ارسال مستقیم/زمان‌دار '
                                'با «تعداد در هر مرحله» استفاده کنید.'
                            )
                        else:
                            recipients = load_sms_recipients(recipient_group, validate=False)
                            parameters = {}
                            for k, v in request.form.items():
                                if k.startswith('param_') and k not in ('param_key[]', 'param_value[]'):
                                    param_name = k.replace('param_', '')
                                    if param_name and v:
                                        parameters[param_name] = v
                            param_keys = request.form.getlist('param_key[]')
                            param_values = request.form.getlist('param_value[]')
                            for i, key in enumerate(param_keys):
                                if key and i < len(param_values):
                                    parameters[key.strip()] = param_values[i].strip()
                            if form_message_text and not parameters:
                                parameters['MESSAGE'] = form_message_text

                            sent, failed, failed_details = 0, 0, []
                            history_batch = []
                            for partner in recipients:
                                phone_normalized = partner['phone']
                                try:
                                    result = send_sms_template(
                                        mobile=phone_normalized,
                                        template_id=template_id,
                                        parameters=parameters if parameters else None,
                                    )
                                    history_batch.append({
                                        'mobile': phone_normalized,
                                        'recipient_name': partner['name'],
                                        'template_id': template_id,
                                        'parameters': parameters or {},
                                        'success': result.get('ok', False),
                                        'status_code': result.get('status', 0),
                                        'response': result.get('body', {}),
                                        'source': 'admin_colleagues',
                                        'created_at': datetime.now().isoformat(),
                                        'error': None if result.get('ok') else str(result.get('body', {}).get('message', 'Unknown error')),
                                    })
                                    if result.get('ok'):
                                        sent += 1
                                    else:
                                        failed += 1
                                        failed_details.append({
                                            'phone': phone_normalized,
                                            'name': partner['name'],
                                            'error': result.get('body', {}).get('message', 'Unknown error'),
                                        })
                                except Exception as e:
                                    failed += 1
                                    failed_details.append({
                                        'phone': partner.get('phone', 'unknown'),
                                        'name': partner.get('name', 'unknown'),
                                        'error': str(e),
                                    })
                            try:
                                history = load_sms_history() or []
                                base_id = len(history)
                                for i, row in enumerate(history_batch):
                                    row['id'] = base_id + i + 1
                                history.extend(history_batch)
                                if len(history) > 10000:
                                    history = history[-10000:]
                                save_sms_history(history)
                            except Exception as hist_err:
                                current_app.logger.error(f"Failed to save SMS history: {hist_err}")

                            if failed > 0:
                                message = f'پیامک به {sent} نفر از گروه «{group_label}» ارسال شد ({failed} خطا).'
                                if len(failed_details) <= 5:
                                    error = 'خطاها: ' + '; '.join(
                                        f"{d['name']} ({d['phone']}): {d['error']}" for d in failed_details
                                    )
                            else:
                                message = f'پیامک با موفقیت به {sent} نفر از گروه «{group_label}» ارسال شد.'

    recipient_counts = recipient_group_counts()
    partners_count = int(recipient_counts.get(recipient_group) or partners_count or 0)
    groups_summary = list_sms_recipient_groups_summary()
    dynamic_labels = {g["key"]: g["label"] for g in groups_summary}
    dynamic_hints = {g["key"]: g["hint"] for g in groups_summary}
    group_label = dynamic_labels.get(recipient_group) or recipient_group_label(recipient_group)

    try:
        history = load_sms_history() or []
        colleagues_history = [
            h for h in history
            if h.get('source') in (
                'admin_colleagues',
                'admin_colleagues_direct',
                'admin_colleagues_scheduled',
                'admin_colleagues_recurring',
            )
        ]
        colleagues_history.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        history_page = max(1, int(request.args.get('history_page', 1)))
        history_per_page = 15
        history_total = len(colleagues_history)
        history_start = (history_page - 1) * history_per_page
        paginated_history = colleagues_history[history_start:history_start + history_per_page]
        history_stats = {
            'total': history_total,
            'sent': len([h for h in colleagues_history if h.get('success')]),
            'failed': len([h for h in colleagues_history if not h.get('success')]),
        }
        history_total_pages = (history_total + history_per_page - 1) // history_per_page if history_total else 0
    except Exception as e:
        current_app.logger.error(f"Error loading SMS history: {e}")
        paginated_history = []
        history_stats = {'total': 0, 'sent': 0, 'failed': 0}
        history_page = 1
        history_per_page = 15
        history_total = 0
        history_total_pages = 0

    scheduled_jobs = list_active_scheduled_jobs()

    return render_template(
        'admin/colleagues_sms.html',
        message=message,
        error=error,
        partners_count=partners_count,
        recipient_group=recipient_group,
        recipient_counts=recipient_counts,
        recipient_group_labels=dynamic_labels,
        recipient_group_hints=dynamic_hints,
        sms_line_number=default_line,
        send_mode=send_mode,
        form_direct_message=form_direct_message,
        form_template_id=form_template_id,
        form_message_text=form_message_text,
        form_send_timing=form_send_timing,
        form_scheduled_at=form_scheduled_at,
        form_recurrence_freq=form_recurrence_freq,
        form_recurrence_time=form_recurrence_time,
        form_recurrence_weekday=form_recurrence_weekday,
        form_recurrence_day=form_recurrence_day,
        form_send_limit=form_send_limit,
        scheduled_jobs=scheduled_jobs,
        history=paginated_history,
        history_stats=history_stats,
        history_page=history_page,
        history_per_page=history_per_page,
        history_total=history_total,
        history_total_pages=history_total_pages,
    )

# -----------------------------------------------------------------------------
# سابقه ارسال پیامک‌ها
# -----------------------------------------------------------------------------
@admin_bp.route('/sms/history', methods=['GET'])
@login_required
def sms_history():
    """نمایش سابقه ارسال پیامک‌ها"""
    try:
        history = load_sms_history() or []
        
        # فیلترها
        mobile_filter = request.args.get('mobile', '').strip()
        success_filter = request.args.get('success')
        source_filter = request.args.get('source', '').strip()
        
        filtered_history = history
        
        if mobile_filter:
            mobile_normalized = _normalize_for_sms_ir(mobile_filter)
            filtered_history = [h for h in filtered_history if h.get('mobile') == mobile_normalized]
        
        if success_filter is not None and success_filter != '':
            success_bool = success_filter.lower() == 'true'
            filtered_history = [h for h in filtered_history if h.get('success') == success_bool]
        
        if source_filter:
            filtered_history = [h for h in filtered_history if h.get('source') == source_filter]
        
        # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
        filtered_history.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        page = int(request.args.get('page', 1))
        per_page = 50
        total = len(filtered_history)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_history = filtered_history[start:end]
        
        # آمار
        total_sent = len([h for h in history if h.get('success')])
        total_failed = len([h for h in history if not h.get('success')])
        
        return render_template(
            'admin/sms_history.html',
            history=paginated_history,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=(total + per_page - 1) // per_page,
            mobile_filter=mobile_filter,
            success_filter=success_filter,
            source_filter=source_filter,
            stats={
                'total_records': len(history),
                'total_sent': total_sent,
                'total_failed': total_failed,
                'filtered_total': total
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error loading SMS history: {e}", exc_info=True)
        flash('خطا در بارگذاری سابقه ارسال‌ها', 'danger')
        return render_template(
            'admin/sms_history.html',
            history=[],
            total=0,
            page=1,
            per_page=50,
            total_pages=0,
            mobile_filter='',
            success_filter='',
            source_filter='',
            stats={'total_records': 0, 'total_sent': 0, 'total_failed': 0, 'filtered_total': 0}
        )

# -----------------------------------------------------------------------------
# تست سیستم اعلان‌ها
# -----------------------------------------------------------------------------
@admin_bp.route('/notifications/test', methods=['GET', 'POST'])
@login_required
def notifications_test():
    """تست سیستم اعلان‌ها"""
    from app.services.notifications import (
        add_notification, get_user_notifications, get_all_notifications_stats,
        _load_all, _normalize_user_id
    )
    
    message = None
    error = None
    test_result = None
    
    if request.method == 'POST':
        test_phone = (request.form.get('test_phone') or '').strip()
        test_title = (request.form.get('test_title') or '').strip() or 'تست اعلان'
        test_body = (request.form.get('test_body') or '').strip() or 'این یک اعلان تستی است برای بررسی سیستم.'
        if not test_phone:
            error = 'شماره تلفن تست الزامی است.'
        else:
            try:
                normalized = _normalize_user_id(test_phone)
                
                # افزودن اعلان تست
                test_notif = add_notification(
                    user_id=normalized,
                    title=test_title,
                    body=test_body,
                    ntype="info"
                )
                
                # دریافت اعلان‌ها
                notifications = get_user_notifications(normalized, limit=10)
                
                # آمار کلی
                stats = get_all_notifications_stats()
                
                # بررسی داده‌های خام
                all_data = _load_all()
                all_keys = list(all_data.keys())
                
                test_result = {
                    "phone_raw": test_phone,
                    "phone_normalized": normalized,
                    "notification_added": test_notif.get("id") if test_notif else None,
                    "notifications_found": len(notifications),
                    "notifications_list": notifications[:5],  # فقط 5 تا اول
                    "all_keys_in_storage": all_keys,
                    "stats": stats
                }
                
                message = f'تست موفقیت‌آمیز بود. اعلان برای {normalized} اضافه شد و {len(notifications)} اعلان پیدا شد.'
            except Exception as e:
                error = f'خطا در تست: {str(e)}'
                current_app.logger.error(f"Notification test error: {e}", exc_info=True)
    
    # آمار کلی
    try:
        stats = get_all_notifications_stats()
    except Exception:
        stats = {}
    
    return render_template(
        'admin/notifications_test.html',
        message=message,
        error=error,
        test_result=test_result,
        stats=stats
    )

def _save_uploaded_android_apk(
    file_storage,
    *,
    sms_message: Optional[str] = None,
    send_update_sms: bool = True,
    recipient_group: Optional[str] = None,
) -> Dict[str, Any]:
    """ذخیره APK + استخراج versionName + به‌روزرسانی settings. خطا → exception با پیام فارسی."""
    from app.express_partner.apk_update_sms import (
        DEFAULT_APK_UPDATE_LINK,
        default_apk_update_sms_message,
        normalize_apk_update_sms_group,
        notify_partners_apk_update_background,
        render_apk_update_sms_message,
    )
    from admin.sms_recipients import recipient_group_label
    from app.utils.apk_meta import extract_apk_version_name

    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("فایلی انتخاب نشده است.")
    fname_lower = str(file_storage.filename or "").lower()
    if not fname_lower.endswith(".apk"):
        raise ValueError("فقط فایل APK مجاز است.")

    max_bytes = 200 * 1024 * 1024
    content_len = getattr(file_storage, "content_length", None)
    if content_len and content_len > max_bytes:
        raise ValueError("حجم فایل بیش از ۲۰۰ مگابایت است.")

    uploads_root = os.path.join(
        current_app.config.get("UPLOAD_FOLDER")
        or os.path.join(current_app.root_path, "data", "uploads"),
        "apk",
    )
    os.makedirs(uploads_root, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = secure_filename(f"vinor_{ts}.apk")
    dest = os.path.join(uploads_root, safe_name)
    file_storage.save(dest)

    try:
        size_bytes = os.path.getsize(dest)
    except Exception:
        size_bytes = None
    if size_bytes is not None and size_bytes > max_bytes:
        try:
            os.remove(dest)
        except Exception:
            pass
        raise ValueError("حجم فایل بیش از ۲۰۰ مگابایت است.")

    try:
        import hashlib

        h = hashlib.sha256()
        with open(dest, "rb") as fp:
            for chunk in iter(lambda: fp.read(8192), b""):
                h.update(chunk)
        sha256 = h.hexdigest()
    except Exception:
        sha256 = ""

    try:
        original_name = secure_filename(file_storage.filename)
    except Exception:
        original_name = ""

    version = extract_apk_version_name(dest, original_name=original_name or file_storage.filename)
    if not version:
        try:
            os.remove(dest)
        except Exception:
            pass
        raise ValueError("نسخه از فایل APK خوانده نشد. فایل معتبر وینور انتخاب کنید.")

    current = get_settings()
    prev_version = str(current.get("android_apk_version") or "").strip()
    apk_url = f"/uploads/apk/{safe_name}"
    updated_at = datetime.utcnow().isoformat() + "Z"

    sms_tpl = (sms_message if sms_message is not None else current.get("android_apk_update_sms_message") or "").strip()
    if not sms_tpl:
        sms_tpl = default_apk_update_sms_message()
    sms_group = normalize_apk_update_sms_group(
        recipient_group
        if recipient_group is not None
        else current.get("android_apk_update_sms_recipient_group")
    )
    sms_group_label = recipient_group_label(sms_group)

    save_settings(
        {
            "android_apk_url": apk_url,
            "android_apk_version": version,
            "android_apk_updated_at": updated_at,
            "android_apk_size_bytes": size_bytes if size_bytes is not None else "",
            "android_apk_sha256": sha256,
            "android_apk_original_name": original_name,
            "android_apk_update_sms_message": sms_tpl,
            "android_apk_update_sms_recipient_group": sms_group,
        }
    )
    short_url = ""
    try:
        from app.utils.short_urls import public_apk_download_url

        short_url = public_apk_download_url(
            {
                "android_apk_url": apk_url,
                "android_apk_version": version,
            },
            external=True,
        )
    except Exception:
        short_url = "/d"
    link = DEFAULT_APK_UPDATE_LINK
    preview = render_apk_update_sms_message(sms_tpl, version=version, link=link)

    sms_queued = False
    if send_update_sms and version and version != prev_version:
        try:
            notify_partners_apk_update_background(
                version=version,
                message=sms_tpl,
                link=link,
                recipient_group=sms_group,
            )
            sms_queued = True
        except Exception as e:
            current_app.logger.exception("Failed to queue APK update SMS: %s", e)

    return {
        "ok": True,
        "android_apk_url": apk_url,
        "android_apk_version": version,
        "android_apk_updated_at": updated_at,
        "android_apk_size_bytes": size_bytes if size_bytes is not None else "",
        "android_apk_sha256": sha256,
        "android_apk_original_name": original_name,
        "android_apk_update_sms_message": sms_tpl,
        "android_apk_update_sms_recipient_group": sms_group,
        "sms_recipient_group_label": sms_group_label,
        "sms_preview": preview,
        "sms_queued": sms_queued,
        "sms_skipped_same_version": bool(version and version == prev_version),
        "short_url": short_url,
    }


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        defaults = _default_settings()
        scope = (request.form.get('settings_scope') or 'site').strip().lower()
        if scope not in ('site', 'app', 'all'):
            scope = 'site'
        current = get_settings()
        patch: Dict[str, Any] = {}

        if scope in ('site', 'all'):
            approval_method = request.form.get('approval_method', 'manual')
            if approval_method not in ('manual', 'auto'):
                approval_method = 'manual'

            # مقدار انتخابی از UI: 0 (نامحدود) یا 30/60/90
            raw_exp = request.form.get('ad_expiry_days', '30')
            try:
                ad_expiry_days = int(raw_exp)
            except Exception:
                ad_expiry_days = 30
            if ad_expiry_days < 0:
                ad_expiry_days = 0
            if ad_expiry_days not in (0, 30, 60, 90):
                ad_expiry_days = 30

            try:
                post_price_toman = int(request.form.get('ad_post_price_toman', '10000') or '10000')
            except Exception:
                post_price_toman = 10000
            if post_price_toman < 0:
                post_price_toman = 0

            # پورسانت بازدید حذف شده — همیشه صفر
            visit_commission_amount_toman = 0

            # تنظیمات SMS — خط ارسال ثابت است
            from app.services.sms_config import get_sms_line_number
            sms_line_number = get_sms_line_number()
            partner_application_sms_message = (
                request.form.get('partner_application_sms_message', '').strip()
                or defaults['partner_application_sms_message']
            )
            partner_approval_sms_message = (
                request.form.get('partner_approval_sms_message', '').strip()
                or defaults['partner_approval_sms_message']
            )
            partner_application_admin_phone = (
                request.form.get('partner_application_admin_phone', '').strip()
                or defaults['partner_application_admin_phone']
            )
            partner_application_admin_sms_message = (
                request.form.get('partner_application_admin_sms_message', '').strip()
                or defaults['partner_application_admin_sms_message']
            )

            patch.update({
                'approval_method': approval_method,
                'ad_expiry_days': ad_expiry_days,
                'show_submit_button': (request.form.get('show_submit_button') == 'on'),
                'ad_post_price_toman': post_price_toman,
                'visit_commission_amount_toman': visit_commission_amount_toman,
                'sms_line_number': sms_line_number,
                'partner_application_sms_message': partner_application_sms_message,
                'partner_approval_sms_message': partner_approval_sms_message,
                'partner_application_admin_phone': partner_application_admin_phone,
                'partner_application_admin_sms_message': partner_application_admin_sms_message,
            })

        if scope in ('app', 'all'):
            # آپلود فوری از UI جداست؛ اینجا فقط نسخهٔ دستی (در صورت ارسال بدون فایل)
            f = request.files.get('android_apk')
            if f and f.filename:
                try:
                    _save_uploaded_android_apk(f)
                    flash('اپلیکیشن با موفقیت آپلود شد.', 'success')
                except ValueError as e:
                    flash(str(e) or 'خطا در بارگذاری فایل APK.', 'error')
                except Exception as e:
                    current_app.logger.exception("APK upload failed: %s", e)
                    flash('خطا در بارگذاری فایل APK.', 'error')
                return redirect(url_for('admin.settings'))

            android_apk_version = (request.form.get('android_apk_version') or '').strip()
            if android_apk_version:
                patch['android_apk_version'] = android_apk_version

        if patch:
            save_settings(patch)
            if scope == 'app':
                flash('تنظیمات اپلیکیشن ذخیره شد.', 'success')
            elif scope == 'site':
                flash('تنظیمات سایت ذخیره شد.', 'success')
            else:
                flash('تنظیمات با موفقیت ذخیره شد.', 'success')
        return redirect(url_for('admin.settings'))

    cleanup_expired_ads()
    lands = load_json(_lands_path())
    p, a, r = counts_by_status(lands if isinstance(lands, list) else [])
    settings_data = get_settings()
    from admin.sms_recipients import list_sms_recipient_groups_summary
    from app.express_partner.apk_update_sms import normalize_apk_update_sms_group
    apk_sms_groups = list_sms_recipient_groups_summary()
    apk_sms_group = normalize_apk_update_sms_group(
        (settings_data or {}).get('android_apk_update_sms_recipient_group')
    )
    return render_template(
        'admin/settings.html',
        settings=settings_data,
        pending_count=p,
        approved_count=a,
        rejected_count=r,
        apk_sms_groups=apk_sms_groups,
        apk_sms_group=apk_sms_group,
    )


@admin_bp.route('/settings/apk-upload', methods=['POST'], endpoint='settings_apk_upload')
@login_required
def settings_apk_upload():
    """آپلود فوری APK با انتخاب فایل — نسخه از مانیفست خوانده می‌شود."""
    f = request.files.get('android_apk') or request.files.get('file')
    sms_message = request.form.get('android_apk_update_sms_message')
    recipient_group = request.form.get('android_apk_update_sms_recipient_group')
    send_flag = (request.form.get('send_update_sms') or '1').strip().lower()
    send_update_sms = send_flag not in ('0', 'false', 'no', 'off')
    try:
        result = _save_uploaded_android_apk(
            f,
            sms_message=sms_message,
            send_update_sms=send_update_sms,
            recipient_group=recipient_group,
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e) or 'آپلود ناموفق بود.'}), 400
    except Exception as e:
        current_app.logger.exception("APK ajax upload failed: %s", e)
        return jsonify({'ok': False, 'error': 'خطا در بارگذاری فایل APK.'}), 500


@admin_bp.route('/settings/apk-sms-template', methods=['POST'], endpoint='settings_apk_sms_template')
@login_required
def settings_apk_sms_template():
    """ذخیره متن و گروه پیامک بروزرسانی اپ."""
    from admin.sms_recipients import recipient_group_label
    from app.express_partner.apk_update_sms import (
        DEFAULT_APK_UPDATE_LINK,
        default_apk_update_sms_message,
        normalize_apk_update_sms_group,
        render_apk_update_sms_message,
    )

    raw = (request.form.get('android_apk_update_sms_message') or '').strip()
    if not raw:
        raw = default_apk_update_sms_message()
    group = normalize_apk_update_sms_group(
        request.form.get('android_apk_update_sms_recipient_group')
    )
    save_settings({
        'android_apk_update_sms_message': raw,
        'android_apk_update_sms_recipient_group': group,
    })
    version = str((get_settings() or {}).get('android_apk_version') or '1.0.0').strip() or '1.0.0'
    preview = render_apk_update_sms_message(
        raw,
        version=version,
        link=DEFAULT_APK_UPDATE_LINK,
    )
    return jsonify({
        'ok': True,
        'android_apk_update_sms_message': raw,
        'android_apk_update_sms_recipient_group': group,
        'sms_recipient_group_label': recipient_group_label(group),
        'sms_preview': preview,
    })


# -----------------------------------------------------------------------------
# سوالات Vinor AI (ارجاع از چت همکار)
# -----------------------------------------------------------------------------
@admin_bp.route('/ai-questions', methods=['GET', 'POST'], endpoint='ai_questions')
@login_required
def ai_questions():
    from app.ai.escalations import answer_escalation, list_pending_for_admin, list_recent_answered
    from app.ai.runtime_settings import get_ai_settings, get_stored_ai_api_key, mask_api_key, save_ai_settings
    from app.ai.services import ai_config
    from app.keys import get_deepseek_api_key

    if request.method == 'POST':
        action = (request.form.get('action') or 'answer').strip()
        if action == 'save_config':
            try:
                from app.ai.runtime_settings import default_ai_settings
                ai_def = default_ai_settings()
                patch = {
                    'enabled': request.form.get('ai_enabled') == '1',
                    'escalation_sms_enabled': request.form.get('ai_escalation_sms_enabled') == '1',
                    'spend_fuse_enabled': request.form.get('ai_spend_fuse_enabled') == '1',
                    'model_choice': 'flash',
                    'thinking_enabled': False,
                    'min_interval_sec': float(request.form.get('ai_min_interval_sec') or ai_def['min_interval_sec']),
                    'dedup_ttl_sec': int(request.form.get('ai_dedup_ttl_sec') or ai_def['dedup_ttl_sec']),
                    'max_history': int(request.form.get('ai_max_history') or ai_def['max_history']),
                    'max_msg_chars': int(request.form.get('ai_max_msg_chars') or ai_def['max_msg_chars']),
                    'max_assistant_history_chars': int(
                        request.form.get('ai_max_assistant_history_chars') or ai_def['max_assistant_history_chars']
                    ),
                    'max_context_chars': int(request.form.get('ai_max_context_chars') or ai_def['max_context_chars']),
                    'max_tokens': int(request.form.get('ai_max_tokens') or ai_def['max_tokens']),
                    'temperature': float(request.form.get('ai_temperature') or ai_def['temperature']),
                    'public_ctx_ttl_sec': int(request.form.get('ai_public_ctx_ttl_sec') or ai_def['public_ctx_ttl_sec']),
                    'partner_ctx_ttl_sec': int(request.form.get('ai_partner_ctx_ttl_sec') or ai_def['partner_ctx_ttl_sec']),
                    'min_message_chars': int(request.form.get('ai_min_message_chars') or ai_def['min_message_chars']),
                    'spend_fuse_window_sec': int(
                        request.form.get('ai_spend_fuse_window_sec') or ai_def['spend_fuse_window_sec']
                    ),
                    'spend_fuse_max_tokens': int(
                        request.form.get('ai_spend_fuse_max_tokens') or ai_def['spend_fuse_max_tokens']
                    ),
                    'spend_fuse_max_requests': int(
                        request.form.get('ai_spend_fuse_max_requests') or ai_def['spend_fuse_max_requests']
                    ),
                    'api_key': (request.form.get('ai_api_key') or '').strip(),
                    'clear_api_key': request.form.get('ai_clear_api_key') == '1',
                }
                save_ai_settings(patch)
                flash('تنظیمات پیکربندی AI ذخیره شد.', 'success')
            except (TypeError, ValueError):
                flash('مقدار نامعتبر در فرم تنظیمات.', 'error')
            return redirect(url_for('admin.ai_questions'))

        if action == 'clear_spend_fuse':
            try:
                from app.ai.credits import clear_spend_fuse

                st = clear_spend_fuse(reset_counters=True)
                flash(
                    'شیر اطمینان مصرف باز شد — API دوباره فعال است. '
                    f"(شمارنده صفر شد؛ سقف: {st.get('max_tokens'):,} توکن / {st.get('max_requests')} درخواست)",
                    'success',
                )
            except Exception:
                flash('باز کردن شیر اطمینان ممکن نشد.', 'error')
            return redirect(url_for('admin.ai_questions'))

        eid = (request.form.get('escalation_id') or '').strip()
        ans = (request.form.get('admin_answer') or '').strip()
        result = answer_escalation(eid, ans)
        if result.get('ok'):
            n = int(result.get('delivered_count') or 0)
            sim = int(result.get('similar_count') or 0)
            msg = f'پاسخ در {n} چت کاربر نمایش داده شد.'
            if sim:
                msg += f' ({sim} سوال مشابه دیگر هم پاسخ داده شد.)'
            flash(msg, 'success')
        else:
            flash(result.get('error') or 'خطا در ثبت پاسخ.', 'error')
        return redirect(url_for('admin.ai_questions'))

    pending = list_pending_for_admin()
    answered = list_recent_answered()
    ai_settings = get_ai_settings()
    ai_status = ai_config()
    site_settings = get_settings()
    stored_api_key = get_stored_ai_api_key()
    active_api_key = get_deepseek_api_key()
    from app.ai.runtime_settings import model_choice_options
    try:
        lands = load_json(_lands_path())
        p, a, r = counts_by_status(lands if isinstance(lands, list) else [])
    except Exception:
        p, a, r = 0, 0, 0
    return render_template(
        'admin/ai_questions.html',
        pending=pending,
        answered=answered,
        pending_count=p,
        approved_count=a,
        rejected_count=r,
        ai_settings=ai_settings,
        ai_status=ai_status,
        ai_model_options=model_choice_options(),
        site_settings=site_settings,
        api_key_masked=mask_api_key(active_api_key),
        api_key_source='settings' if stored_api_key else ('file' if active_api_key else 'none'),
        has_stored_api_key=bool(stored_api_key),
    )


# -----------------------------------------------------------------------------
# وکیل ملکی — کنترل کامل شخصیت و دانش
# -----------------------------------------------------------------------------
@admin_bp.route('/lawyer', methods=['GET', 'POST'], endpoint='lawyer')
@login_required
def lawyer_admin():
    from app.lawyer.config import (
        default_lawyer_settings,
        get_lawyer_settings,
        lawyer_feature_enabled,
        save_lawyer_settings,
    )

    if request.method == 'POST':
        action = (request.form.get('action') or 'save').strip()
        if action == 'reset_defaults':
            save_lawyer_settings(default_lawyer_settings())
            flash('تنظیمات وکیل ملکی به پیش‌فرض بازگشت.', 'success')
            return redirect(url_for('admin.lawyer'))

        feature_on = lawyer_feature_enabled()
        current = get_lawyer_settings()
        patch = {
            'enabled': (
                current.get('enabled')
                if not feature_on
                else (request.form.get('lawyer_enabled') == '1')
            ),
            'show_disclaimer': request.form.get('lawyer_show_disclaimer') == '1',
            'display_name': (request.form.get('lawyer_display_name') or '').strip(),
            'welcome': (request.form.get('lawyer_welcome') or '').strip(),
            'system_prompt': (request.form.get('lawyer_system_prompt') or '').strip(),
            'knowledge_notes': (request.form.get('lawyer_knowledge_notes') or '').strip(),
        }
        try:
            save_lawyer_settings(patch)
            flash('تنظیمات وکیل ملکی ذخیره شد.', 'success')
        except Exception:
            flash('ذخیره تنظیمات وکیل ممکن نشد.', 'error')
        return redirect(url_for('admin.lawyer'))

    lawyer = get_lawyer_settings()
    try:
        lands = load_json(_lands_path())
        p, a, r = counts_by_status(lands if isinstance(lands, list) else [])
    except Exception:
        p, a, r = 0, 0, 0
    return render_template(
        'admin/lawyer.html',
        lawyer=lawyer,
        lawyer_feature_flag=lawyer_feature_enabled(),
        pending_count=p,
        approved_count=a,
        rejected_count=r,
    )


# -----------------------------------------------------------------------------
# فهرست آگهی‌ها (با صفحه‌بندی)
# -----------------------------------------------------------------------------
@admin_bp.route('/lands')
@login_required
def lands():
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    # متای نمایش اعتبار
    for ad in lands_list:
        ad["_expiry"] = expiry_meta(ad)

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", PER_PAGE_DEFAULT))
    pagination = paginate(lands_list, page, per_page)
    p, a, r = counts_by_status(lands_list)
    return render_template(
        'admin/lands.html',
        lands=pagination["items"],
        pagination={"page": pagination["page"], "pages": pagination["pages"]},
        pending_count=p, approved_count=a, rejected_count=r
    )

@admin_bp.route('/pending-lands')
@login_required
def pending_lands():
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    subset = [l for l in lands_list if str(l.get("status", "pending")) == "pending"]
    for ad in subset:
        ad["_expiry"] = expiry_meta(ad)

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", PER_PAGE_DEFAULT))
    pagination = paginate(subset, page, per_page)
    p, a, r = counts_by_status(lands_list)
    return render_template(
        'admin/pending_lands.html',
        lands=pagination["items"],
        pagination={"page": pagination["page"], "pages": pagination["pages"]},
        pending_count=p, approved_count=a, rejected_count=r
    )

@admin_bp.route('/approved-lands')
@login_required
def approved_lands():
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    subset = [l for l in lands_list if str(l.get("status")) == "approved"]
    for ad in subset:
        ad["_expiry"] = expiry_meta(ad)

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", PER_PAGE_DEFAULT))
    pagination = paginate(subset, page, per_page)
    p, a, r = counts_by_status(lands_list)
    return render_template(
        'admin/approved_lands.html',
        lands=pagination["items"],
        pagination={"page": pagination["page"], "pages": pagination["pages"]},
        pending_count=p, approved_count=a, rejected_count=r
    )

@admin_bp.route('/rejected-lands')
@login_required
def rejected_lands():
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    subset = [l for l in lands_list if str(l.get("status")) == "rejected"]
    for ad in subset:
        ad["_expiry"] = expiry_meta(ad)

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", PER_PAGE_DEFAULT))
    pagination = paginate(subset, page, per_page)
    p, a, r = counts_by_status(lands_list)
    return render_template(
        'admin/rejected_lands.html',
        lands=pagination["items"],
        pagination={"page": pagination["page"], "pages": pagination["pages"]},
        pending_count=p, approved_count=a, rejected_count=r
    )

# -----------------------------------------------------------------------------
# گزارش‌های کاربران (Reported Ads)
# -----------------------------------------------------------------------------
@admin_bp.route('/reports')
@login_required
def reports_list():
    items = load_reports() or []
    if not isinstance(items, list):
        items = []
    # تازه‌ترین بالا
    try:
        items.sort(key=lambda x: x.get('created_at',''), reverse=True)
    except Exception:
        pass
    page = int(request.args.get('page', 1) or 1)
    per_page = int(request.args.get('per_page', 20) or 20)
    pagination = paginate(items, page, per_page)
    return render_template(
        'admin/reports.html',
        reports=pagination['items'],
        pagination={"page": pagination["page"], "pages": pagination["pages"]}
    )

@admin_bp.post('/reports/<int:rid>/resolve')
@login_required
def report_resolve(rid: int):
    items = load_reports() or []
    if not isinstance(items, list):
        items = []
    changed = False
    for r in items:
        try:
            if int(r.get('id', 0)) == int(rid):
                r['status'] = 'resolved'
                r['resolved_at'] = iso_z(utcnow())
                changed = True
                break
        except Exception:
            continue
    if changed:
        save_reports(items)
    return redirect(url_for('admin.reports_list'))

# -----------------------------------------------------------------------------
# مشاهده آگهی
# -----------------------------------------------------------------------------
@admin_bp.route('/land/<string:code>')
@login_required
def view_land(code):
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    land = find_by_code(lands_list, code)
    if not land:
        abort(404)
    p, a, r = counts_by_status(lands_list)
    return render_template('admin/land_view.html', land=land,
                           pending_count=p, approved_count=a, rejected_count=r)

@admin_bp.route('/land/index/<int:land_id>')
@login_required
def view_land_by_index(land_id):
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    land = find_by_index(lands_list, land_id)
    if not land:
        abort(404)
    p, a, r = counts_by_status(lands_list)
    return render_template('admin/land_view.html', land=land,
                           pending_count=p, approved_count=a, rejected_count=r)

# -----------------------------------------------------------------------------
# ثبت/ویرایش/حذف آگهی (پشتیبانی همزمان از آپلود فایل و ورودی متنی تصاویر)
# -----------------------------------------------------------------------------
def _next_numeric_code(lands: List[Dict[str, Any]]) -> str:
    existing_codes = [
        int(l['code']) for l in lands
        if isinstance(l, dict) and 'code' in l and str(l['code']).isdigit()
    ]
    return str(max(existing_codes) + 1) if existing_codes else '1'

def _normalize_images_from_form(form, files) -> List[str]:
    """
    پذیرش هر دو ورودی:
    - images[] متنی (URL/مسیر)
    - images فایل
    """
    from app.utils.images import save_upload_image

    image_urls: List[str] = []

    text_list = form.getlist('images') or []
    for t in text_list:
        t = (t or '').strip()
        if t:
            image_urls.append(t)

    upload_files = files.getlist('images')
    if upload_files:
        upload_folder = _uploads_root()
        os.makedirs(upload_folder, exist_ok=True)
        for f in upload_files:
            if f and f.filename:
                stored = save_upload_image(f, upload_folder)
                if stored:
                    image_urls.append(stored)
                else:
                    filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{f.filename}")
                    f.stream.seek(0)
                    f.save(os.path.join(upload_folder, filename))
                    image_urls.append(f'uploads/{filename}')

    return image_urls

def _save_video_from_form(files) -> str | None:
    """
    ذخیره ویدیو از فرم و برگرداندن مسیر نسبی مثل 'uploads/video.mp4'
    """
    video_file = files.get('video')
    if not video_file or not video_file.filename:
        return None

    # بررسی فرمت
    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    file_ext = os.path.splitext(video_file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return None

    upload_folder = _uploads_root()
    os.makedirs(upload_folder, exist_ok=True)
    filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{video_file.filename}")
    video_file.save(os.path.join(upload_folder, filename))
    return f'uploads/{filename}'

@admin_bp.route('/add-land', methods=['GET', 'POST'])
@login_required
def add_land():
    lands = load_json(_lands_path())
    if not isinstance(lands, list):
        lands = []

    if request.method == 'POST':
        form = request.form

        settings = get_settings()
        approval_method = settings.get('approval_method', 'manual')
        status = 'approved' if approval_method == 'auto' else 'pending'

        # محاسبه تاریخ‌ها (۰ = نامحدود → expires_at ست نمی‌شود)
        created_at_dt = utcnow()
        try:
            expiry_days = int(settings.get('ad_expiry_days', 30))
        except Exception:
            expiry_days = 30
        if expiry_days < 0:
            expiry_days = 0

        new_code = form.get("code") or _next_numeric_code(lands)
        images = _normalize_images_from_form(request.form, request.files)

        deal_type = (form.get('deal_type') or '').strip()
        if not deal_type:
            flash('نوع معامله را انتخاب کنید.', 'warning')
            return render_template('admin/add-land.html',
                                   pending_count=0, approved_count=0, rejected_count=0)

        new_land = {
            'code': str(new_code),
            'title': form.get('title', '').strip() or 'بدون عنوان',
            'size': form.get('size', '').strip(),
            'location': form.get('location', '').strip(),
            'category': form.get('category', '').strip(),
            'document_type': form.get('document_type', '').strip(),
            'description': form.get('description', '').strip(),
            'features': form.getlist('features'),
            'price_total': form.get('price_total', '').strip(),
            'price_per_meter': form.get('price_per_meter', '').strip(),
            'images': images,
            'approval_method': approval_method,
            'status': status,
            'created_at': iso_z(created_at_dt),
            'deal_type': deal_type,
            # اگر ادمین به اسم کاربر خاص ثبت می‌کند، می‌تواند owner را نیز ست کند:
            'owner': form.get('owner', '').strip() or None,
        }

        if expiry_days > 0:
            expires_at_dt = created_at_dt + timedelta(days=expiry_days)
            new_land['expires_at'] = iso_z(expires_at_dt)

        lands.append(new_land)
        save_json(_lands_path(), lands)

        # ✅ اعلان (در صورت داشتن owner)
        notify_admin_create(new_land)

        flash(f'آگهی با کد {new_code} با موفقیت ثبت شد. حالا می‌توانید کلیپ آن را بارگذاری کنید.', 'success')
        # هدایت به مرحله دوم: آپلود ویدیو
        return redirect(url_for('admin.add_land_video', code=new_code))

    # GET
    cleanup_expired_ads()
    p, a, r = counts_by_status(lands if isinstance(lands, list) else [])
    return render_template('admin/add-land.html',
                           pending_count=p, approved_count=a, rejected_count=r)


@admin_bp.route('/add-land/<string:code>/video', methods=['GET', 'POST'])
@login_required
def add_land_video(code: str):
    """
    مرحله دوم ثبت آگهی: بارگذاری کلیپ (ویدیو) به‌صورت مجزا
    """
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    land = find_by_code(lands_list, code)
    if not land:
        flash('آگهی مورد نظر پیدا نشد.', 'warning')
        return redirect(url_for('admin.lands'))

    if request.method == 'POST':
        # اگر کاربر این مرحله را رد کرده
        if request.form.get('skip') == '1':
            flash('ثبت آگهی بدون کلیپ انجام شد.', 'info')
            return redirect(url_for('admin.lands'))

        video_path = _save_video_from_form(request.files)
        if not video_path:
            flash('هیچ فایلی انتخاب نشده یا فرمت ویدیو نامعتبر است.', 'warning')
            return redirect(url_for('admin.add_land_video', code=code))

        # اگر ویدیوی قبلی وجود دارد، حذف شود
        old_video = land.get('video')
        if old_video:
            old_path = os.path.join(current_app.static_folder, old_video)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass

        land['video'] = video_path
        save_json(_lands_path(), lands_list)

        flash('کلیپ آگهی با موفقیت ثبت شد.', 'success')
        return redirect(url_for('admin.lands'))

    return render_template('admin/add_land_video.html', land=land)

# ویرایش – سازگاری با هر دو الگو: querystring code/land_id و مسیر <int:land_id>
@admin_bp.route('/edit-land', methods=['GET', 'POST'])
@admin_bp.route('/edit-land/<int:land_id>', methods=['GET', 'POST'])
@login_required
def edit_land(land_id: Optional[int] = None):
    cleanup_expired_ads()
    lands = load_json(_lands_path())
    if not isinstance(lands, list):
        lands = []

    code = request.args.get("code") or request.form.get("code")
    land = None

    if code:
        land = find_by_code(lands, code)
        land_index = lands.index(land) if land in lands else None
    elif land_id is not None:
        land = find_by_index(lands, land_id)
        land_index = land_id
    else:
        land_index = None

    if not land or land_index is None:
        flash('آگهی مورد نظر پیدا نشد.', 'warning')
        return redirect(url_for('admin.lands'))

    if request.method == 'POST':
        form = request.form
        # فیلدها
        deal_type = form.get('deal_type', '').strip()
        if not deal_type:
            deal_type = land.get('deal_type', 'sale')  # پیش‌فرض: فروش
        
        land.update({
            'title': form.get('title', '').strip() or land.get('title', ''),
            'size': form.get('size', '').strip() or land.get('size', ''),
            'location': form.get('location', '').strip() or land.get('location', ''),
            'code': str(form.get('code', land.get('code', ''))).strip() or land.get('code', ''),
            'category': form.get('category', '').strip() or land.get('category', ''),
            'document_type': form.get('document_type', '').strip() or land.get('document_type', ''),
            'description': form.get('description', '').strip() or land.get('description', ''),
            'features': form.getlist('features') or land.get('features', []),
            'price_total': form.get('price_total', '').strip() or land.get('price_total', ''),
            'price_per_meter': form.get('price_per_meter', '').strip() or land.get('price_per_meter', ''),
            'status': form.get('status', land.get('status', 'pending')),
            'deal_type': deal_type
        })

        # حذف همه تصاویر (اختیاری)
        if request.form.get('remove_all_images') == 'on':
            for img in land.get('images', []):
                path = os.path.join(current_app.static_folder, img)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            land['images'] = []

        # افزودن تصاویر جدید (متنی/فایل)
        new_images = _normalize_images_from_form(request.form, request.files)
        if new_images:
            land.setdefault('images', []).extend(new_images)

        # حذف ویدیو (اگر درخواست شده)
        if request.form.get('remove_video') == 'on':
            old_video = land.get('video')
            if old_video:
                old_path = os.path.join(current_app.static_folder, old_video)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
                land.pop('video', None)

        # ذخیره ویدیو جدید (اگر آپلود شده)
        new_video = _save_video_from_form(request.files)
        if new_video:
            # حذف ویدیو قدیمی در صورت وجود
            old_video = land.get('video')
            if old_video:
                old_path = os.path.join(current_app.static_folder, old_video)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            land['video'] = new_video

        save_json(_lands_path(), lands)

        # ✅ اعلان: ویرایش توسط ادمین
        notify_admin_edit(land)

        flash('آگهی ویرایش شد.', 'success')
        return redirect(url_for('admin.lands'))

    p, a, r = counts_by_status(lands)
    return render_template('admin/edit-land.html', land=land, land_id=land_index,
                           pending_count=p, approved_count=a, rejected_count=r)

# حذف – سازگاری با هر دو الگو: querystring/route
@admin_bp.route('/delete-land', methods=['POST'])
@admin_bp.route('/delete-land/<int:land_id>', methods=['POST'])
@login_required
def delete_land(land_id: Optional[int] = None):
    lands = load_json(_lands_path())
    if not isinstance(lands, list):
        lands = []

    code = request.args.get("code") or request.form.get("code")
    idx_to_delete = None

    if code:
        for i, l in enumerate(lands):
            if str(l.get("code")) == str(code):
                idx_to_delete = i
                break
    elif land_id is not None:
        if 0 <= land_id < len(lands):
            idx_to_delete = land_id

    if idx_to_delete is None:
        abort(404)

    land = lands.pop(idx_to_delete)
    # حذف فایل‌های تصویر روی دیسک
    _delete_ad_images(land)

    # استفاده از save_ads برای همگام‌سازی کش سمت کاربر
    save_ads(lands)
    flash('آگهی با موفقیت حذف شد.', 'success')
    return redirect(url_for('admin.lands'))

# -----------------------------------------------------------------------------
# تغییر وضعیت: تأیید/رد
# -----------------------------------------------------------------------------
@admin_bp.route('/approve/<string:code>', methods=['POST'])
@admin_bp.route('/approve-land/<string:code>', methods=['POST'])
@login_required
def approve_land(code):
    cleanup_expired_ads()
    lands = load_json(_lands_path())
    land = find_by_code(lands if isinstance(lands, list) else [], code)
    if not land:
        flash('آگهی یافت نشد.', 'warning')
        return redirect(request.referrer or url_for('admin.pending_lands'))
    land['status'] = 'approved'
    try:
        land['approved_at'] = iso_z(utcnow())
    except Exception:
        pass
    save_ads(lands)

    # ✅ اعلان: تأیید شد
    notify_status_change(land, 'approved')

    flash('آگهی تأیید شد.', 'success')
    return redirect(request.referrer or url_for('admin.approved_lands'))

@admin_bp.route('/reject/<string:code>', methods=['POST'])
@admin_bp.route('/reject-land/<string:code>', methods=['POST'])
@login_required
def reject_land(code):
    cleanup_expired_ads()
    lands = load_json(_lands_path())
    land = find_by_code(lands if isinstance(lands, list) else [], code)
    if not land:
        flash('آگهی یافت نشد.', 'warning')
        return redirect(request.referrer or url_for('admin.pending_lands'))

    land['status'] = 'rejected'
    reason = request.form.get("reject_reason", "").strip()
    if reason:
        land["reject_reason"] = reason

    save_ads(lands)

    # ✅ اعلان: رد شد + دلیل
    notify_status_change(land, 'rejected', reason=reason or None)

    flash('آگهی رد شد / نیاز به اصلاح دارد.', 'info')
    return redirect(request.referrer or url_for('admin.rejected_lands'))

# -----------------------------------------------------------------------------
# Express Listings Management
# -----------------------------------------------------------------------------
def _express_land_price_int(land: Dict[str, Any]) -> int:
    try:
        raw = str(land.get('price_total') or land.get('price') or '0').replace(',', '').strip()
        return int(raw) if raw else 0
    except (TypeError, ValueError):
        return 0


def _enrich_admin_express_land(
    land: Dict[str, Any],
    *,
    public_views: int = 0,
    partner_views: int = 0,
    assignment_count: int = 0,
) -> Dict[str, Any]:
    """فیلدهای نمایشی کارت پریمیوم ادمین."""
    express_status = str(land.get('express_status') or land.get('status') or 'approved').strip().lower()
    land['_assignment_status'] = 'sold' if express_status == 'sold' else 'active'

    extras = land.get('extras') if isinstance(land.get('extras'), dict) else {}
    from app.express_partner.new_land_sms import attach_express_land_commission
    attach_express_land_commission(land)

    land['_public_views_count'] = public_views
    land['_partner_views_count'] = partner_views
    land['_assignment_count'] = assignment_count
    return land


@admin_bp.route('/express')
@login_required
def express_listings():
    """لیست آگهی‌های اکسپرس"""
    cleanup_expired_ads()
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []

    express_all = [land for land in lands_list if land.get('is_express', False)]

    public_views_data = load_express_views() or []
    if not isinstance(public_views_data, list):
        public_views_data = []

    partner_views_data = load_express_partner_views() or []
    if not isinstance(partner_views_data, list):
        partner_views_data = []

    public_views_count_by_code: Dict[str, int] = {}
    for v in public_views_data:
        try:
            v_code = str(v.get('code') or '')
            if v_code:
                public_views_count_by_code[v_code] = public_views_count_by_code.get(v_code, 0) + 1
        except Exception:
            pass

    partner_views_count_by_code: Dict[str, int] = {}
    for v in partner_views_data:
        try:
            v_code = str(v.get('code') or '')
            if v_code:
                partner_views_count_by_code[v_code] = partner_views_count_by_code.get(v_code, 0) + 1
        except Exception:
            pass

    assignment_count_by_code: Dict[str, int] = {}
    for a in (load_express_assignments() or []):
        try:
            code = str(a.get('land_code') or '')
            if code:
                assignment_count_by_code[code] = assignment_count_by_code.get(code, 0) + 1
        except Exception:
            pass

    filter_kind = (request.args.get('filter') or 'all').strip().lower()
    express_lands = list(express_all)
    if filter_kind == 'sold':
        express_lands = [
            l for l in express_lands
            if str(l.get('express_status') or '').strip().lower() == 'sold'
        ]
    elif filter_kind == 'active':
        express_lands = [
            l for l in express_lands
            if str(l.get('express_status') or '').strip().lower() != 'sold'
        ]

    # جدیدترین اول؛ فروخته‌شده‌ها همیشه پایین لیست (در تب «همه»)
    express_lands.sort(
        key=lambda l: str(l.get('created_at') or l.get('updated_at') or ''),
        reverse=True,
    )
    express_lands.sort(
        key=lambda l: str(l.get('express_status') or '').strip().lower() == 'sold',
    )

    for land in express_lands:
        code = str(land.get('code') or '')
        _enrich_admin_express_land(
            land,
            public_views=public_views_count_by_code.get(code, 0),
            partner_views=partner_views_count_by_code.get(code, 0),
            assignment_count=assignment_count_by_code.get(code, 0),
        )

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", PER_PAGE_DEFAULT))
    pagination = paginate(express_lands, page, per_page)

    sold_count = sum(
        1 for l in express_all
        if str(l.get('express_status') or '').strip().lower() == 'sold'
    )
    stats = {
        'total': len(express_all),
        'active': len(express_all) - sold_count,
        'sold': sold_count,
        'shown': len(express_lands),
    }

    p, a, r = counts_by_status(express_all)
    return render_template(
        'admin/express_listings.html',
        lands=pagination["items"],
        pagination={"page": pagination["page"], "pages": pagination["pages"]},
        pending_count=p, approved_count=a, rejected_count=r,
        filter_kind=filter_kind,
        stats=stats,
    )


@admin_bp.post('/express/transfer')
@login_required
def express_transfer():
    """انتقال داده‌های اکسپرس از مجموعه داده‌های وینور به ساختار اکسپرس (idempotent)."""
    # داده‌ها در فایل‌های JSON ذخیره می‌شوند؛ این تابع اقلام مرتبط را به فایل‌های مقصد merge می‌کند
    try:
        # مبداً: lands.json حاوی آگهی‌هایی که ممکن است فیلدهای express داشته باشند
        lands = load_json(_lands_path()) or []
        if not isinstance(lands, list):
            lands = []

        # مقصدها: فایل‌های express_*
        partners = load_express_partners() or []
        partner_apps = load_express_partner_apps() or []
        assignments = load_express_assignments() or []
        commissions = load_express_commissions() or []

        # از app.routes.public توابع کمکی بارگذاری متعلقات همکار استفاده نمی‌کنیم؛ تنها merge ایمن
        # چون در این پروژه، متعلقات همکار در فایل‌های جدا ذخیره می‌شوند، انتقال اینجا idempotent است.

        # اگر آگهی‌های اکسپرس در lands باشند، فقط ensure کنیم is_express و express_status ست است.
        changed_lands = False
        for ad in lands:
            if ad.get('is_express') and not ad.get('ad_type'):
                ad['ad_type'] = 'express'
                changed_lands = True
            if ad.get('is_express') and not ad.get('express_status'):
                ad['express_status'] = str(ad.get('status') or 'approved')
                changed_lands = True
        if changed_lands:
            save_ads(lands)

        # چون داده‌های partner_* در فایل‌های مستقل هستند، تنها normalize ساده انجام می‌دهیم
        def _unique(items, key):
            seen = set()
            out = []
            for it in items:
                k = str(it.get(key))
                if not k or k in seen:
                    continue
                seen.add(k)
                out.append(it)
            return out

        save_express_partners(partners if isinstance(partners, list) else [])
        save_express_partner_apps(partner_apps if isinstance(partner_apps, list) else [])
        save_express_assignments(assignments if isinstance(assignments, list) else [])
        save_express_commissions(commissions if isinstance(commissions, list) else [])

        flash('انتقال داده‌های اکسپرس انجام شد.', 'success')
    except Exception as e:
        current_app.logger.error(f"Express transfer error: {e}")
        flash('خطا در اجرای انتقال.', 'danger')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/express/upload-image', methods=['POST'])
@login_required
def express_upload_image():
    """آپلود فوری تصویر هنگام ثبت آگهی (قبل از submit فرم)."""
    from app.utils.images import normalize_upload_url, save_upload_image

    f = request.files.get('file') or request.files.get('image')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    upload_folder = _uploads_root()
    os.makedirs(upload_folder, exist_ok=True)
    stored = save_upload_image(f, upload_folder)
    if not stored:
        return jsonify({'ok': False, 'error': 'ذخیره تصویر ناموفق بود.'}), 400

    return jsonify({
        'ok': True,
        'path': stored,
        'url': normalize_upload_url(stored),
    })


@admin_bp.route('/express/upload-video', methods=['POST'])
@login_required
def express_upload_video():
    """آپلود فوری ویدئو هنگام ثبت آگهی."""
    from app.utils.images import normalize_upload_url

    f = request.files.get('file') or request.files.get('video')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    allowed_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    file_ext = os.path.splitext(f.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return jsonify({'ok': False, 'error': 'فرمت ویدئو مجاز نیست.'}), 400

    upload_folder = _uploads_root()
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


@admin_bp.route('/express/upload-document', methods=['POST'])
@login_required
def express_upload_document():
    """آپلود فوری مدرک هنگام ثبت آگهی."""
    f = request.files.get('file') or request.files.get('document')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'فایلی ارسال نشده است.'}), 400

    allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
    file_ext = os.path.splitext(f.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return jsonify({'ok': False, 'error': 'فرمت مدرک مجاز نیست (PDF · JPG · PNG).'}), 400

    stored = _save_express_document(f, 'draft')
    if not stored:
        return jsonify({'ok': False, 'error': 'ذخیره مدرک ناموفق بود.'}), 400

    return jsonify({
        'ok': True,
        'path': stored,
        'name': f.filename,
    })

def _express_listing_form_values(land: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """مقادیر اولیه فرم ثبت/ویرایش از روی آگهی."""
    if not land:
        return {}
    extras = land.get('extras') if isinstance(land.get('extras'), dict) else {}
    docs = land.get('express_documents') or []
    if not isinstance(docs, list):
        docs = []
    return {
        'title': land.get('title') or '',
        'location': land.get('location') or '',
        'city': land.get('city') or '',
        'size': land.get('size') or '',
        'price_total': land.get('price_total') or '',
        'price_per_meter': land.get('price_per_meter') or '',
        'category': land.get('category') or '',
        'description': land.get('description') or '',
        'payment_method': land.get('payment_method') or '',
        'express_commission_pct': extras.get('express_commission_pct', land.get('express_commission_pct')) or '2',
        'vinor_contact': land.get('vinor_contact') or '09121471301',
        'latitude': land.get('latitude') or '',
        'longitude': land.get('longitude') or '',
        'video': land.get('video') or '',
        'document_1': docs[0] if len(docs) > 0 else '',
        'document_2': docs[1] if len(docs) > 1 else '',
        'images': land.get('images') or [],
        'payment_terms': land.get('payment_terms') or [],
        'expert_verified': land.get('expert_verified'),
    }


def _render_express_listing_form(cities, land: Optional[Dict[str, Any]] = None):
    """فرم واحد ثبت/ویرایش آگهی اکسپرس — قالب دیوار."""
    is_edit = bool(land)
    return render_template(
        'admin/add_express_listing.html',
        cities=cities,
        is_edit=is_edit,
        land=land or {},
        form_values=_express_listing_form_values(land) if land else {},
        listing_code=str((land or {}).get('code') or ''),
    )


def _add_express_listing_form(cities, land: Optional[Dict[str, Any]] = None):
    """رندر فرم ثبت/ویرایش آگهی — با حفظ request.form پس از خطا."""
    return _render_express_listing_form(cities, land=land)

@admin_bp.route('/express/add', methods=['GET', 'POST'])
@login_required
def add_express_listing():
    """افزودن آگهی اکسپرس جدید"""
    cities = load_active_cities() or []
    if request.method == 'POST':
        form = request.form
        files = request.files
        
        # اعتبارسنجی فیلدهای اجباری
        title = form.get('title', '').strip()
        location = form.get('location', '').strip()
        city = (form.get('city') or '').strip()
        size_raw = form.get('size', '').strip()
        price_total_raw = form.get('price_total', '').strip()
        
        # پاک کردن فرمت از اعداد (حذف کاما و کاراکترهای غیر عددی)
        size_clean = re.sub(r'[^\d]', '', size_raw) if size_raw else ''
        price_total_clean = re.sub(r'[^\d]', '', price_total_raw) if price_total_raw else ''
        
        if not all([title, location, city, size_clean, price_total_clean]):
            flash('لطفاً فیلدهای اجباری را پر کنید.', 'error')
            return _add_express_listing_form(cities)

        if cities and city not in cities:
            flash('شهر آگهی باید از بین شهرهای فعال انتخاب شود.', 'error')
            return _add_express_listing_form(cities)
        
        if len(title) < 10:
            flash('عنوان باید حداقل ۱۰ کاراکتر باشد.', 'error')
            return _add_express_listing_form(cities)
        
        # تبدیل به عدد
        try:
            size = int(size_clean)
            price_total = int(price_total_clean)
        except (ValueError, TypeError):
            flash('متراژ و قیمت باید عدد معتبر باشند.', 'error')
            return _add_express_listing_form(cities)
        
        if size <= 0 or price_total <= 0:
            flash('متراژ و قیمت باید بیشتر از صفر باشند.', 'error')
            return _add_express_listing_form(cities)

        payment_method = (form.get('payment_method') or '').strip()
        if not payment_method:
            flash('نحوه پرداخت را انتخاب کنید.', 'error')
            return _add_express_listing_form(cities)

        vinor_contact = re.sub(r'[^\d]', '', (form.get('vinor_contact') or '').strip())
        if not vinor_contact or len(vinor_contact) < 10:
            flash('شماره تماس پشتیبانی معتبر نیست.', 'error')
            return _add_express_listing_form(cities)
        
        # بارگذاری لیست آگهی‌ها برای تولید کد
        lands = load_json(_lands_path())
        if not isinstance(lands, list):
            lands = []
        
        # تولید کد منحصر به فرد
        new_code = form.get("code") or _next_numeric_code(lands)
        
        # ذخیره مدارک (آپلود فوری از hidden یا فایل فرم)
        documents = []
        for doc_key in ('document_1', 'document_2'):
            pre = (form.get(doc_key) or '').strip()
            if pre:
                documents.append(pre)
        for key, file in files.items():
            if key.startswith('document_') and file.filename:
                doc_filename = _save_express_document(file, new_code)
                if doc_filename and doc_filename not in documents:
                    documents.append(doc_filename)
        
        # پردازش تصاویر (آپلود فوری از hidden یا فایل فرم)
        images = _normalize_images_from_form(form, files)
        
        # کمیسیون همکاران (الزامی)
        pct_raw = (form.get('express_commission_pct') or '').strip()
        if not pct_raw:
            flash('درصد پورسانت الزامی است.', 'error')
            return _add_express_listing_form(cities)
        try:
            express_commission_pct = float(pct_raw)
            if express_commission_pct <= 0 or express_commission_pct > 100:
                flash('درصد پورسانت باید بین ۰ و ۱۰۰ باشد.', 'error')
                return _add_express_listing_form(cities)
        except (ValueError, TypeError):
            flash('درصد پورسانت باید یک عدد معتبر باشد.', 'error')
            return _add_express_listing_form(cities)
        # محاسبه قیمت در متر
        price_per_meter_raw = form.get('price_per_meter', '').strip()
        price_per_meter_clean = re.sub(r'[^\d]', '', price_per_meter_raw) if price_per_meter_raw else ''
        try:
            price_per_meter = int(price_per_meter_clean) if price_per_meter_clean else 0
            # اگر قیمت در متر محاسبه نشده، خودمان محاسبه می‌کنیم
            if price_per_meter == 0 and size > 0:
                price_per_meter = int(round(price_total / size))
        except (ValueError, TypeError):
            price_per_meter = int(round(price_total / size)) if size > 0 else 0
        
        # محاسبه کمیسیون
        try:
            price_int = price_total  # قبلاً تبدیل شده
        except Exception:
            price_int = 0
        express_commission_amount = int(round(price_int * ((express_commission_pct or 0)/100.0))) if price_int and (express_commission_pct is not None) else None

        # دریافت مختصات جغرافیایی
        latitude = None
        longitude = None
        try:
            lat_str = form.get('latitude', '').strip()
            lon_str = form.get('longitude', '').strip()
            if lat_str:
                latitude = float(lat_str)
            if lon_str:
                longitude = float(lon_str)
        except (ValueError, TypeError):
            pass  # اگر مقدار نامعتبر بود، None می‌ماند

        # ویدئو (اختیاری — آپلود فوری از hidden یا فایل فرم)
        video_path = (form.get('video') or '').strip() or None
        if not video_path:
            try:
                video_path = _save_video_from_form(files)
            except Exception:
                video_path = None

        # ایجاد آگهی اکسپرس
        payment_terms = []
        try:
            if payment_method == 'اقساطی':
                months_list = request.form.getlist('installment_months[]')
                amounts_list = request.form.getlist('installment_amounts[]')
                for i in range(max(len(months_list), len(amounts_list))):
                    m_raw = (months_list[i] if i < len(months_list) else '') or ''
                    a_raw = (amounts_list[i] if i < len(amounts_list) else '') or ''
                    try:
                        m = int(re.sub(r'[^\d]', '', str(m_raw))) if m_raw else 0
                    except Exception:
                        m = 0
                    try:
                        a = int(re.sub(r'[^\d]', '', str(a_raw))) if a_raw else 0
                    except Exception:
                        a = 0
                    if m > 0 and a > 0:
                        payment_terms.append({'months': m, 'amount': a})
        except Exception:
            payment_terms = []

        if payment_method == 'اقساطی' and not payment_terms:
            flash('برای پرداخت اقساطی حداقل یک قسط معتبر وارد کنید.', 'error')
            return _add_express_listing_form(cities)

        new_express_land = {
            'code': new_code,
            'title': title,
            'location': location,
            'city': city,
            'size': size,  # حالا int است
            'price_total': price_total,  # حالا int است
            'price_per_meter': price_per_meter,
            'description': form.get('description', '').strip(),
            'images': images,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'owner': 'vinor_support',  # شماره پشتیبانی وینور
            'status': 'approved',  # آگهی‌های اکسپرس مستقیماً تأیید می‌شوند
            'ad_type': 'express',
            'category': form.get('category', ''),
            'payment_method': payment_method,
            'payment_terms': payment_terms,
            'is_express': True,
            'express_status': 'approved',
            'expert_verified': bool((form.get('expert_verified') or '').strip()),
            'express_documents': documents,
            'vinor_contact': vinor_contact,
            'extras': {
                'express_commission_pct': express_commission_pct,
                'express_commission_amount': express_commission_amount,
            }
        }

        if video_path:
            new_express_land['video'] = video_path
        
        # افزودن مختصات جغرافیایی در صورت وجود
        if latitude is not None:
            new_express_land['latitude'] = latitude
        if longitude is not None:
            new_express_land['longitude'] = longitude

        apply_category_specs_from_form(new_express_land, form)
        
        # ذخیره در فایل
        lands = load_json(_lands_path())
        lands.append(new_express_land)
        save_ads(lands)

        try:
            from app.express_partner.new_land_sms import notify_all_partners_new_express_land_background
            notify_all_partners_new_express_land_background(new_express_land)
        except Exception:
            current_app.logger.exception(
                'New express land partner SMS queue failed code=%s', new_code
            )
        
        # ارسال نوتیفیکیشن به کاربران منطقه
        # در صورت انتخاب «ارسال خودکار برای تمامی همکاران» → ساخت انتساب برای همه + اعلان
        if (form.get('auto_send_all_partners') or '').strip():
            try:
                partners = load_express_partners() or []
                items = load_express_assignments() or []
                existing = {(str(a.get('partner_phone')), str(a.get('land_code'))) for a in items if isinstance(a, dict)}
                for p in partners:
                    phone = str((p or {}).get('phone') or '').strip()
                    if not phone:
                        continue
                    key = (phone, new_code)
                    if key not in existing:
                        new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
                        items.append({
                            'id': new_id,
                            'partner_phone': phone,
                            'land_code': new_code,
                            'commission_pct': express_commission_pct or 0,
                            'status': 'active',
                            'created_at': iso_z(utcnow())
                        })
                        existing.add(key)
                    try:
                        phone_normalized = _normalize_phone(phone)
                        if phone_normalized and len(phone_normalized) == 11:
                            add_notification(
                                user_id=phone_normalized,
                                title='فایل جدید اکسپرس',
                                body=f"کد فایل: {new_code} - {title}",
                                ntype='info',
                                ad_id=new_code,
                                action_url=url_for('express_partner.land_detail', code=new_code, _external=True)
                            )
                    except Exception as e:
                        current_app.logger.error(f"Error sending file assignment notification to {phone}: {e}", exc_info=True)
                        continue
                save_express_assignments(items)
            except Exception:
                pass
        
        flash(f'آگهی اکسپرس با کد {new_code} با موفقیت ثبت شد.', 'success')
        return redirect(url_for('admin.express_listings'))
    
    # GET — فرم سبک بدون cleanup سنگین
    return _add_express_listing_form(cities)

@admin_bp.route('/express/<string:code>/edit', methods=['GET', 'POST'])
@login_required
def edit_express_listing(code):
    """ویرایش آگهی اکسپرس"""
    lands_list = load_json(_lands_path())
    if not isinstance(lands_list, list):
        lands_list = []
    cities = load_active_cities() or []

    land = find_by_code(lands_list, code)
    if not land or not land.get('is_express', False):
        flash('آگهی اکسپرس یافت نشد.', 'warning')
        return redirect(url_for('admin.express_listings'))

    def _render_edit():
        return _render_express_listing_form(cities, land=land)

    if request.method == 'POST':
        form = request.form
        files = request.files

        title = form.get('title', '').strip()
        location = form.get('location', '').strip()
        city = (form.get('city') or '').strip()
        size_clean = re.sub(r'[^\d]', '', form.get('size', '') or '')
        price_clean = re.sub(r'[^\d]', '', form.get('price_total', '') or '')

        if not all([title, location, city, size_clean, price_clean]):
            flash('لطفاً فیلدهای اجباری را پر کنید.', 'error')
            return _render_edit()

        if len(title) < 10:
            flash('عنوان باید حداقل ۱۰ کاراکتر باشد.', 'error')
            return _render_edit()

        if cities and city not in cities:
            flash('شهر آگهی باید از بین شهرهای فعال انتخاب شود.', 'error')
            return _render_edit()

        payment_method = (form.get('payment_method') or '').strip()
        if not payment_method:
            flash('نحوه پرداخت را انتخاب کنید.', 'error')
            return _render_edit()

        vinor_contact = re.sub(r'[^\d]', '', (form.get('vinor_contact') or '').strip())
        if not vinor_contact or len(vinor_contact) < 10:
            flash('شماره تماس پشتیبانی معتبر نیست.', 'error')
            return _render_edit()

        try:
            size = int(size_clean)
            price_total = int(price_clean)
        except (ValueError, TypeError):
            flash('متراژ و قیمت باید عدد معتبر باشند.', 'error')
            return _render_edit()

        if size <= 0 or price_total <= 0:
            flash('متراژ و قیمت باید بیشتر از صفر باشند.', 'error')
            return _render_edit()

        price_per_meter_raw = form.get('price_per_meter', '').strip()
        price_per_meter_clean = re.sub(r'[^\d]', '', price_per_meter_raw) if price_per_meter_raw else ''
        try:
            price_per_meter = int(price_per_meter_clean) if price_per_meter_clean else 0
            if price_per_meter <= 0 and size > 0:
                price_per_meter = int(round(price_total / size))
        except (ValueError, TypeError):
            price_per_meter = int(round(price_total / size)) if size > 0 else 0

        comm_err = _express_commission_from_form(land, form, price_total)
        if comm_err:
            flash(comm_err, 'error')
            return _render_edit()

        land['title'] = title
        land['location'] = location
        land['city'] = city
        land['category'] = (form.get('category') or '').strip()
        land['size'] = size
        land['price_total'] = price_total
        land['price_per_meter'] = price_per_meter
        land['description'] = form.get('description', '').strip()
        if (form.get('expert_verified') or '').strip():
            land['expert_verified'] = True
        else:
            land.pop('expert_verified', None)
        land['vinor_contact'] = vinor_contact
        land['payment_method'] = payment_method

        try:
            if payment_method == 'اقساطی':
                payment_terms = []
                months_list = form.getlist('installment_months[]')
                amounts_list = form.getlist('installment_amounts[]')
                for i in range(max(len(months_list), len(amounts_list))):
                    m_raw = (months_list[i] if i < len(months_list) else '') or ''
                    a_raw = (amounts_list[i] if i < len(amounts_list) else '') or ''
                    try:
                        m = int(re.sub(r'[^\d]', '', str(m_raw))) if m_raw else 0
                    except Exception:
                        m = 0
                    try:
                        a = int(re.sub(r'[^\d]', '', str(a_raw))) if a_raw else 0
                    except Exception:
                        a = 0
                    if m > 0 and a > 0:
                        payment_terms.append({'months': m, 'amount': a})
                land['payment_terms'] = payment_terms
            else:
                land.pop('payment_terms', None)
        except Exception:
            pass

        if payment_method == 'اقساطی' and not (land.get('payment_terms') or []):
            flash('برای پرداخت اقساطی حداقل یک قسط معتبر وارد کنید.', 'error')
            return _render_edit()

        try:
            lat_str = form.get('latitude', '').strip()
            lon_str = form.get('longitude', '').strip()
            if lat_str:
                land['latitude'] = float(lat_str)
            else:
                land.pop('latitude', None)
            if lon_str:
                land['longitude'] = float(lon_str)
            else:
                land.pop('longitude', None)
        except (ValueError, TypeError):
            pass

        new_images = _normalize_images_from_form(form, files)
        old_images = [str(x).strip() for x in (land.get('images') or []) if str(x).strip()]
        for img in old_images:
            if img not in new_images:
                _unlink_stored_upload(img)
        land['images'] = new_images
        if new_images != old_images:
            land.pop('images_v2', None)

        documents: List[str] = []
        for doc_key in ('document_1', 'document_2'):
            pre = (form.get(doc_key) or '').strip()
            if pre:
                documents.append(pre)
        for key, file in files.items():
            if key.startswith('document_') and file.filename:
                doc_filename = _save_express_document(file, code)
                if doc_filename and doc_filename not in documents:
                    documents.append(doc_filename)
        land['express_documents'] = documents

        video_path = (form.get('video') or '').strip() or None
        if not video_path:
            try:
                video_path = _save_video_from_form(files)
            except Exception:
                video_path = None
        old_video = land.get('video')
        if old_video and isinstance(old_video, str) and old_video != video_path:
            _unlink_stored_upload(old_video)
        if video_path:
            land['video'] = video_path
        else:
            land.pop('video', None)

        apply_category_specs_from_form(land, form)

        save_ads(lands_list)
        flash('آگهی اکسپرس با موفقیت به‌روزرسانی شد.', 'success')
        return redirect(url_for('admin.express_listings'))

    return _render_express_listing_form(cities, land=land)

@admin_bp.post('/express/<string:code>/delete')
@login_required
def delete_express_listing(code):
    """حذف آگهی اکسپرس"""
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    
    land = find_by_code(lands_list, code)
    if not land or not land.get('is_express', False):
        flash('آگهی اکسپرس یافت نشد.', 'warning')
        return redirect(url_for('admin.express_listings'))
    
    # حذف تصاویر آگهی
    _delete_ad_images(land)
    
    # حذف از لیست
    lands_list = [l for l in lands_list if str(l.get('code')) != str(code)]
    save_ads(lands_list)
    save_ads(lands_list)
    
    flash(f'آگهی اکسپرس با کد {code} با موفقیت حذف شد.', 'success')
    return redirect(url_for('admin.express_listings'))

@admin_bp.post('/express/<string:code>/toggle-sold')
@login_required
def toggle_express_sold(code):
    """تغییر وضعیت فروخته شد / در انتظار فروش"""
    lands_data = load_json(_lands_path())
    lands_list = lands_data if isinstance(lands_data, list) else []
    
    land = find_by_code(lands_list, code)
    if not land or not land.get('is_express', False):
        flash('آگهی اکسپرس یافت نشد.', 'warning')
        return redirect(url_for('admin.express_listings'))
    
    current_status = land.get('express_status', 'active')
    if current_status == 'sold':
        land['express_status'] = 'active'
        # برگرداندن وضعیت انتساب‌ها به active
        assignments = load_express_assignments() or []
        for a in assignments:
            if str(a.get('land_code')) == str(code):
                a['status'] = 'active'
                a['transaction_holder'] = None
                a['transaction_started_at'] = None
        save_express_assignments(assignments)
        flash(f'آگهی {code} به حالت در انتظار فروش برگشت.', 'success')
    else:
        land['express_status'] = 'sold'
        try:
            assignments = load_express_assignments() or []
            updated = False
            for a in assignments:
                if str(a.get('land_code')) == str(code):
                    a['status'] = 'sold'
                    a['sold_at'] = iso_z(utcnow())
                    a.pop('transaction_holder', None)
                    a.pop('transaction_started_at', None)
                    updated = True
            if updated:
                save_express_assignments(assignments)
        except Exception as e:
            current_app.logger.error('toggle_express_sold assignments: %s', e)
        flash(f'آگهی {code} به فروخته شد تغییر کرد.', 'success')
    
    save_ads(lands_list)
    return redirect(url_for('admin.express_listings'))

@admin_bp.route('/express-docs/<filename>')
@login_required
def serve_express_document(filename):
    """سرو کردن مدارک اکسپرس"""
    try:
        docs_dir = _get_express_docs_dir()
        return send_from_directory(docs_dir, filename)
    except Exception as e:
        current_app.logger.error(f"Error serving express document {filename}: {e}")
        abort(404)

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Express Partners: Applications & Partners list + actions
# -----------------------------------------------------------------------------
@admin_bp.route('/express/partners/applications')
@login_required
def express_partner_applications():
    """درخواست‌های همکاری → فیلتر در انتظار در لیست یکپارچه."""
    return redirect(url_for('admin.express_partners', filter='pending'))


def _lands_title_lookup() -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    try:
        lands = load_json(_lands_path()) or []
        if isinstance(lands, list):
            for land in lands:
                if not isinstance(land, dict):
                    continue
                code = str(land.get('code') or '').strip()
                if code:
                    lookup[code] = str(land.get('title') or '').strip()
    except Exception:
        pass
    return lookup


def _admin_people_directory_kwargs() -> Dict[str, Any]:
    return {
        'normalize_phone': _normalize_phone,
        'load_users': load_users,
        'load_express_partners': load_express_partners,
        'load_express_partner_apps': load_express_partner_apps,
        'load_express_assignments': load_express_assignments,
        'load_express_commissions': load_express_commissions,
        'load_partner_files_meta': load_partner_files_meta,
        'load_partner_withdrawals': load_partner_withdrawals,
        'load_partner_bank_accounts': load_partner_bank_accounts,
        'get_online_partners_list': _get_online_partners_list,
        'get_recent_online_partners_list': _get_recent_online_partners_list,
        'load_partner_notes': load_partner_notes,
        'load_partner_routines_cached': load_partner_routines_cached,
        'load_express_visit_requests': load_express_visit_requests,
        'lands_lookup': _lands_title_lookup(),
    }


@admin_bp.route('/express/partners')
@login_required
def express_partners():
    q = (request.args.get('q') or '').strip()
    filter_kind = (request.args.get('filter') or 'all').strip()
    try:
        people, stats = build_admin_people_directory(
            **_admin_people_directory_kwargs(),
            q=q,
            filter_kind=filter_kind,
            detail_level='summary',
        )
    except Exception:
        current_app.logger.exception('build_admin_people_directory failed')
        _empty_agg = {
            'visits_total': 0, 'visits_pending': 0, 'assignments_active': 0, 'assignments_total': 0,
            'commissions_total': 0, 'commissions_approved': 0, 'files': 0, 'withdrawals_active': 0,
            'notes': 0, 'routine_days': 0,
        }
        people, stats = [], {
            'total': 0, 'shown': 0, 'partners': 0, 'pending': 0, 'site_users': 0, 'online': 0,
            'agg': dict(_empty_agg),
            'agg_shown': dict(_empty_agg),
        }
    people_groups = group_people_for_admin_list(people, filter_kind)
    return render_template(
        'admin/express_partners.html',
        people=people,
        people_groups=people_groups,
        stats=stats,
        q=q,
        filter_kind=filter_kind,
    )


@admin_bp.route('/express/partners/<path:phone>')
@login_required
def express_partner_detail(phone: str):
    phone = (phone or '').strip()
    back_q = (request.args.get('q') or '').strip()
    back_filter = (request.args.get('filter') or 'all').strip()
    try:
        person = get_admin_person_by_phone(phone, **_admin_people_directory_kwargs())
    except Exception:
        current_app.logger.exception('get_admin_person_by_phone failed')
        person = None
    if not person:
        flash('کاربر یا همکار یافت نشد.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))
    display_name = (person.get('name') or person.get('phone') or 'همکار').strip()
    show_referral_retry = False
    try:
        partner_rec = person.get('partner') or {}
        prof = person.get('profile') or {}
        ref_by = (partner_rec.get('referred_by_phone') or prof.get('referred_by_phone') or '').strip()
        if not ref_by:
            from app.express_partner.referrals import _normalize_phone, _phones_match
            from app.utils.storage import load_express_referrals
            invitee_norm = _normalize_phone(phone)
            for r in load_express_referrals() or []:
                if _phones_match(r.get('invitee_phone'), invitee_norm):
                    ref_by = (r.get('inviter_phone') or '').strip()
                    if ref_by:
                        partner_rec['referred_by_phone'] = ref_by
                        prof['referred_by_phone'] = ref_by
                        person['profile'] = prof
                        person['partner'] = partner_rec
                    break
        if ref_by:
            if not (prof.get('referred_by_name') or '').strip():
                dir_kw = _admin_people_directory_kwargs()
                prof['referred_by_name'] = resolve_admin_person_name(
                    ref_by,
                    normalize_phone=dir_kw['normalize_phone'],
                    load_users=dir_kw['load_users'],
                    load_express_partners=dir_kw['load_express_partners'],
                )
            prof['referred_by_phone'] = ref_by
            person['profile'] = prof
        if ref_by and (person.get('access') or {}).get('partner_approved'):
            if partner_rec.get('referral_grant_pending'):
                show_referral_retry = True
            else:
                from app.express_partner.referrals import _active_referral_commission_exists
                show_referral_retry = not _active_referral_commission_exists(ref_by, phone)
    except Exception:
        show_referral_retry = False

    fcm_token_count = 0
    try:
        from app.services.fcm_tokens import tokens_for_phone
        fcm_token_count = len(tokens_for_phone(phone))
    except Exception:
        pass

    return render_template(
        'admin/express_partner_detail.html',
        person=person,
        back_q=back_q,
        back_filter=back_filter,
        page_title=f'پروفایل {display_name}',
        show_referral_retry=show_referral_retry,
        fcm_token_count=fcm_token_count,
    )


@admin_bp.post('/express/partners/<path:phone>/send-message')
@login_required
def express_partner_send_message(phone: str):
    """ارسال پیام به یک همکار/کاربر — نوتیف، پیامک، یا هر دو."""
    phone = _normalize_phone((phone or '').strip())
    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()
    redirect_kw = {'phone': phone, 'q': back_q, 'filter': back_filter}

    if not phone or len(phone) != 11:
        flash('شماره همراه معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))

    channel = (request.form.get('channel') or 'both').strip().lower()
    if channel not in ('notify', 'sms', 'both'):
        channel = 'notify'

    title = (request.form.get('title') or '').strip() or 'پیام وینور'
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('متن پیام الزامی است.', 'warning')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    send_notify = channel in ('notify', 'both')
    send_sms = channel in ('sms', 'both')
    parts: list[str] = []
    errors: list[str] = []

    if send_notify:
        try:
            add_notification(
                user_id=phone,
                title=title,
                body=body,
                ntype='info',
                action_url=url_for('express_partner.home', ai=1, thread='__postchi__'),
                source='admin_partner_message',
            )
            parts.append('نوتیف (درون‌برنامه + FCM)')
        except Exception as e:
            current_app.logger.error('Partner message notification failed: %s', e, exc_info=True)
            errors.append('نوتیف')

    if send_sms:
        if not phone.startswith('09'):
            errors.append('پیامک (شماره نامعتبر)')
        else:
            try:
                settings = get_settings()
                sms_line_number = (settings.get('sms_line_number') or '').strip() or None
                sms_text = body if len(body) <= 500 else body[:497] + '...'
                sms_result = send_sms_direct(
                    mobile=phone,
                    message=sms_text,
                    line_number=sms_line_number,
                )
                try:
                    history = load_sms_history() or []
                    record = {
                        'id': len(history) + 1,
                        'mobile': phone,
                        'recipient_name': (request.form.get('recipient_name') or '').strip() or None,
                        'template_id': None,
                        'message': sms_text,
                        'parameters': {},
                        'success': sms_result.get('ok', False),
                        'status_code': sms_result.get('status', 0),
                        'response': sms_result.get('body', {}),
                        'source': 'admin_partner_message',
                        'created_at': datetime.now().isoformat(),
                        'error': None if sms_result.get('ok') else str(
                            (sms_result.get('body') or {}).get('message', 'خطای ارسال')
                        ),
                    }
                    history.insert(0, record)
                    save_sms_history(history)
                except Exception:
                    pass
                if sms_result.get('ok'):
                    parts.append('پیامک')
                else:
                    errors.append('پیامک')
                    current_app.logger.warning(
                        'Partner SMS failed phone=%s status=%s',
                        phone,
                        sms_result.get('status'),
                    )
            except Exception as e:
                current_app.logger.error('Partner SMS error: %s', e, exc_info=True)
                errors.append('پیامک')

    if parts and not errors:
        flash(f'ارسال شد: {", ".join(parts)}', 'success')
    elif parts and errors:
        flash(f'بخشی ارسال شد ({", ".join(parts)}) — خطا: {", ".join(errors)}', 'warning')
    elif errors:
        flash(f'ارسال ناموفق: {", ".join(errors)}', 'danger')
    else:
        flash('کانال ارسال انتخاب نشده است.', 'warning')

    return redirect(url_for('admin.express_partner_detail', **redirect_kw))


@admin_bp.post('/express/partners/<path:phone>/set-special')
@login_required
def express_partner_set_special(phone: str):
    """اعطای/حذف سطح همکار ویژه."""
    try:
        from app.hardening.permissions import PERM_PARTNERS, has_permission
        if not has_permission(PERM_PARTNERS):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    from app.express_partner.partner_roles import partner_is_approved, set_partner_tier
    from app.utils.storage import load_express_partners, save_express_partners

    phone = _normalize_phone((phone or '').strip())
    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()
    redirect_kw = {'phone': phone, 'q': back_q, 'filter': back_filter}
    want_special = str(request.form.get('special') or '').strip() in ('1', 'true', 'on', 'yes')

    if not phone:
        flash('شماره معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))

    partners = load_express_partners() or []
    if not isinstance(partners, list):
        partners = []
    found = None
    for p in partners:
        if isinstance(p, dict) and _normalize_phone(str(p.get('phone') or '')) == phone:
            found = p
            break
    if not found or not partner_is_approved(found):
        flash('فقط همکار تأییدشده را می‌توان ویژه کرد.', 'warning')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    set_partner_tier(found, want_special)
    try:
        save_express_partners(partners)
    except Exception:
        current_app.logger.exception('set_special save failed phone=%s', phone)
        flash('ذخیره سطح ویژه ناموفق بود.', 'danger')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    _admin_audit(
        'admin_partner_set_special',
        entity_type='partner',
        entity_id=phone,
        summary=f"Partner special={'on' if want_special else 'off'}",
        payload={'special': want_special},
    )
    flash('همکار ویژه فعال شد.' if want_special else 'سطح ویژه برداشته شد.', 'success')
    return redirect(url_for('admin.express_partner_detail', **redirect_kw))


@admin_bp.post('/express/partners/<path:phone>/adjust-balance')
@login_required
def express_partner_adjust_balance(phone: str):
    from app.express_partner.partner_withdrawals import (
        apply_manual_balance_target,
        partner_commission_dashboard,
    )

    phone = (phone or '').strip()
    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()
    redirect_kw = {'phone': phone, 'q': back_q, 'filter': back_filter}

    if not phone:
        flash('شماره همراه معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))

    raw_target = (request.form.get('balance_target') or '').strip().replace(',', '').replace('،', '')
    try:
        target = max(0, int(float(raw_target or '0')))
    except (TypeError, ValueError):
        flash('مبلغ موجودی معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    note = (request.form.get('admin_note') or '').strip()[:240]
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []
    withdrawals = load_partner_withdrawals() or []
    if not isinstance(withdrawals, list):
        withdrawals = []

    ok, reason, rec = apply_manual_balance_target(
        commissions,
        withdrawals,
        phone,
        target,
        note,
        created_at=iso_z(utcnow()),
    )
    if not ok:
        if reason == 'no_change':
            flash('موجودی تغییری نکرد.', 'info')
        else:
            flash('تنظیم موجودی انجام نشد.', 'warning')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    try:
        save_express_commissions(commissions)
    except Exception:
        current_app.logger.exception('save_express_commissions failed adjust-balance')
        flash('ذخیره تعدیل موجودی ناموفق بود.', 'danger')
        return redirect(url_for('admin.express_partner_detail', **redirect_kw))

    after = int(partner_commission_dashboard(commissions, withdrawals, phone).get('withdrawable_balance') or 0)
    delta = int((rec or {}).get('commission_amount') or 0)
    sign = 'افزایش' if delta > 0 else 'کاهش'
    flash(f'موجودی قابل برداشت به {after:,} تومان رسید ({sign} {abs(delta):,} تومان).'.replace(',', '،'), 'success')
    return redirect(url_for('admin.express_partner_detail', **redirect_kw))


@admin_bp.post('/express/partners/<path:phone>/retry-referral-grant')
@login_required
def express_partner_retry_referral_grant(phone: str):
    from app.services.notifications import _normalize_user_id
    from app.express_partner.referrals import (
        REFERRAL_BONUS_AMOUNT,
        REFERRAL_GRANT_REASONS_FA,
        grant_referral_for_partner_record,
    )

    phone = _normalize_user_id((phone or '').strip())
    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()
    if not phone:
        flash('شماره همراه معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))

    partners = load_express_partners() or []
    partner = next(
        (
            p for p in partners
            if isinstance(p, dict) and _normalize_user_id(str(p.get('phone') or '')) == phone
        ),
        None,
    )
    if not partner:
        flash('همکار یافت نشد.', 'warning')
        return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))

    if not (partner.get('referred_by_phone') or '').strip():
        from app.express_partner.referrals import _phones_match
        from app.utils.storage import load_express_referrals
        for r in load_express_referrals() or []:
            if _phones_match(r.get('invitee_phone'), phone):
                inv = (r.get('inviter_phone') or '').strip()
                if inv:
                    partner['referred_by_phone'] = inv
                    try:
                        partner['referral_application_id'] = int(r.get('application_id') or 0)
                    except Exception:
                        pass
                break

    try:
        ok, reason = grant_referral_for_partner_record(partner)
        for p in partners:
            if isinstance(p, dict) and _normalize_user_id(str(p.get('phone') or '')) == phone:
                if ok:
                    p.pop('referral_grant_pending', None)
                else:
                    p['referral_grant_pending'] = True
                break
        save_express_partners(partners)
        if ok:
            flash(f'پورسانت دعوت ({REFERRAL_BONUS_AMOUNT:,} ت) برای معرف ثبت شد.', 'success')
        else:
            reason_fa = REFERRAL_GRANT_REASONS_FA.get(reason or '')
            flash(reason_fa or 'ثبت پورسانت دعوت انجام نشد.', 'warning')
    except Exception as e:
        current_app.logger.error('Retry referral grant for %s: %s', phone, e, exc_info=True)
        flash('خطا در ثبت پورسانت دعوت.', 'danger')

    return redirect(url_for('admin.express_partner_detail', phone=phone, q=back_q, filter=back_filter))


@admin_bp.post('/express/partners/<path:phone>/delete')
@login_required
def express_partner_delete(phone: str):
    from app.services.notifications import _normalize_user_id
    from app.utils.partner_account import admin_purge_person_account

    phone = _normalize_user_id((phone or '').strip())
    if not phone:
        flash('شماره همراه معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners'))

    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()

    try:
        result = admin_purge_person_account(phone)
        if result.get('ok'):
            flash('حساب کاربر حذف شد.', 'success')
        else:
            current_app.logger.error('Admin person delete incomplete for %s: %s', phone, result.get('errors'))
            flash('حذف کامل انجام نشد. لاگ سرور را بررسی کنید.', 'danger')
    except Exception as e:
        current_app.logger.error('Failed to delete person %s: %s', phone, e, exc_info=True)
        flash('خطا در حذف حساب.', 'danger')

    return redirect(url_for('admin.express_partners', q=back_q, filter=back_filter))


@admin_bp.post('/express/applications/<int:aid>/delete')
@login_required
def express_partner_application_delete(aid: int):
    try:
        apps = load_express_partner_apps() or []
        filtered = [app for app in apps if int(app.get('id', 0) or 0) != int(aid)]
        if len(filtered) == len(apps):
            flash('درخواست یافت نشد.', 'warning')
            return redirect(url_for('admin.express_partners', filter='pending'))
        save_express_partner_apps(filtered)
        flash('درخواست حذف شد.', 'success')
    except Exception as e:
        current_app.logger.error(f"Failed to delete application {aid}: {e}")
        flash('حذف درخواست با خطا مواجه شد.', 'danger')
    return redirect(url_for('admin.express_partners', filter='pending'))

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Express visit requests redirect helper
# -----------------------------------------------------------------------------
def _express_visit_requests_redirect(filter_hint: str = '', vid: str = '') -> str:
    flt = (filter_hint or 'workflow').strip()
    if flt == 'actions':
        flt = 'workflow'
    url = url_for('admin.express_visit_requests', filter=flt or None)
    vid = (vid or '').strip()
    if vid:
        url = f'{url}#visit-{vid}'
    return url


# -----------------------------------------------------------------------------
# Express Commissions (list/approve/pay)
# -----------------------------------------------------------------------------
def _express_commissions_redirect(filter_hint: str = '') -> str:
    return_to = (request.form.get('return_to') or request.args.get('return_to') or '').strip()
    if return_to == 'visit_requests':
        visit_filter = (request.form.get('visit_filter') or request.args.get('visit_filter') or 'workflow').strip()
        visit_vid = (request.form.get('visit_vid') or request.args.get('visit_vid') or '').strip()
        return _express_visit_requests_redirect(visit_filter, visit_vid)
    flt = (filter_hint or request.form.get('filter') or request.args.get('filter') or 'pending').strip()
    if flt:
        return url_for('admin.express_commissions', filter=flt)
    return url_for('admin.express_commissions')


def _land_title_lookup() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for land in load_express_lands_cached() or []:
            if not isinstance(land, dict):
                continue
            code = str(land.get('code') or '').strip()
            if code and code not in out:
                out[code] = str(land.get('title') or land.get('name') or '').strip()
    except Exception:
        pass
    if len(out) < 50:
        try:
            for land in load_ads_cached() or []:
                if not isinstance(land, dict):
                    continue
                code = str(land.get('code') or '').strip()
                if code and code not in out:
                    out[code] = str(land.get('title') or land.get('name') or '').strip()
        except Exception:
            pass
    return out


@admin_bp.route('/express/commissions')
@login_required
def express_commissions():
    from app.express_partner.commissions_flow import (
        APPROVED_STATUS,
        PAID_STATUS,
        PENDING_STATUS,
        REJECTED_STATUS,
        admin_commission_row_dict,
    )

    try:
        items_raw = load_express_commissions() or []
        if not isinstance(items_raw, list):
            items_raw = []
    except Exception:
        items_raw = []
    settings_data = get_settings()

    name_map = _partner_name_lookup()
    title_map = _land_title_lookup()
    withdrawals = load_partner_withdrawals() or []
    if not isinstance(withdrawals, list):
        withdrawals = []

    items = []
    for row in items_raw:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        ph = str(r.get('partner_phone') or '').strip()
        if not (r.get('partner_name') or '').strip() and ph in name_map:
            r['partner_name'] = name_map[ph]
        code = str(r.get('land_code') or '').strip()
        if code and code != 'referral' and not (r.get('land_title') or '').strip():
            r['land_title'] = title_map.get(code, '')
        item = admin_commission_row_dict(r)
        from app.express_partner.commissions_flow import commission_linked_to_active_withdrawal
        item['withdrawal_locked'] = commission_linked_to_active_withdrawal(r, withdrawals)
        items.append(item)

    pending_count = sum(1 for x in items if x.get('status') == PENDING_STATUS)
    approved_count = sum(1 for x in items if x.get('status') == APPROVED_STATUS)
    paid_count = sum(1 for x in items if x.get('status') == PAID_STATUS)
    rejected_count = sum(1 for x in items if x.get('status') == REJECTED_STATUS)
    active_count = pending_count + approved_count

    flt = (request.args.get('filter') or 'pending').strip().lower()
    if flt == 'approved':
        visible = [x for x in items if x.get('status') == APPROVED_STATUS]
    elif flt == 'paid':
        visible = [x for x in items if x.get('status') == PAID_STATUS]
    elif flt == 'rejected':
        visible = [x for x in items if x.get('status') == REJECTED_STATUS]
    elif flt == 'active':
        visible = [x for x in items if x.get('status') in (PENDING_STATUS, APPROVED_STATUS)]
    elif flt == 'all':
        visible = items
    else:
        flt = 'pending'
        visible = [x for x in items if x.get('status') == PENDING_STATUS]

    visible.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    visible.sort(key=lambda x: {PENDING_STATUS: 0, APPROVED_STATUS: 1, PAID_STATUS: 2, REJECTED_STATUS: 3}.get(x.get('status') or '', 9))

    return render_template(
        'admin/express_commissions.html',
        items=visible,
        pending_count=pending_count,
        approved_count=approved_count,
        paid_count=paid_count,
        rejected_count=rejected_count,
        active_count=active_count,
        all_count=len(items),
        current_filter=flt,
        visit_commission_amount_toman=int(settings_data.get('visit_commission_amount_toman') or 0),
    )

@admin_bp.post('/express/commissions/new')
@login_required
def express_commission_new():
    partner_phone = (request.form.get('partner_phone') or '').strip()
    land_code = (request.form.get('land_code') or '').strip()
    commission_type = (request.form.get('commission_type') or 'deal').strip().lower()
    # پورسانت بازدید حذف شده — فقط فروش
    if commission_type != 'deal':
        commission_type = 'deal'
    sale_amount = (request.form.get('sale_amount') or '').strip()
    commission_pct = (request.form.get('commission_pct') or '').strip()
    direct_amount = (request.form.get('commission_amount') or '').strip()
    try:
        sale = int(str(sale_amount).replace(',','').strip() or '0')
    except Exception:
        sale = 0
    try:
        pct = float(commission_pct or '0')
    except Exception:
        pct = 0.0
    try:
        commission_amount = int(str(direct_amount).replace(',', '').replace('،', '').strip() or '0')
    except Exception:
        commission_amount = 0
    commission_amount = max(0, commission_amount)
    if commission_amount <= 0:
        commission_amount = int(round(sale * (pct/100.0))) if sale and pct else 0
    items = load_express_commissions() or []
    new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
    items.append({
        'id': new_id,
        'commission_type': commission_type,
        'partner_phone': partner_phone,
        'land_code': land_code,
        'sale_amount': sale,
        'commission_pct': pct,
        'commission_amount': commission_amount,
        'status': 'pending',
        'created_at': iso_z(utcnow())
    })
    save_express_commissions(items)
    try:
        from app.express_partner.commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=partner_phone,
            event='commission_pending',
            amount=commission_amount,
            land_code=land_code,
            commission_type=commission_type,
            reference_id=str(new_id),
        )
    except Exception:
        current_app.logger.exception('commission_pending SMS failed admin new cid=%s', new_id)
    flash('پورسانت ثبت شد (در انتظار تایید).', 'success')
    return redirect(_express_commissions_redirect('pending'))

@admin_bp.post('/express/commissions/<int:cid>/approve')
@login_required
def express_commission_approve(cid: int):
    try:
        from app.hardening.permissions import PERM_FINANCE, has_permission
        if not has_permission(PERM_FINANCE):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    from app.express_partner.commissions_flow import commission_is_deal, commission_is_referral, commission_is_visit

    filter_hint = (request.form.get('filter') or 'pending').strip()
    items = load_express_commissions() or []
    changed = False
    commission_record = None
    for c in items:
        try:
            if int(c.get('id',0) or 0) == int(cid):
                # فقط اگر در وضعیت pending باشد، تایید کن
                if c.get('status') == 'pending':
                    c['status'] = 'approved'
                    c['approved_at'] = iso_z(utcnow())
                    commission_record = c
                    changed = True
                break
        except Exception:
            continue
    if changed and commission_record:
        save_express_commissions(items)
        is_referral = commission_is_referral(commission_record)
        is_visit = commission_is_visit(commission_record)
        is_deal = commission_is_deal(commission_record)

        if is_referral:
            try:
                from app.express_partner.referrals import sync_referral_on_commission_status
                sync_referral_on_commission_status(commission_record)
            except Exception as e:
                current_app.logger.error('Referral sync on commission approve: %s', e)

        # تغییر وضعیت فایل به "فروخته شده" + کیف پول + بستن مأموریت
        if is_deal:
            try:
                from app.express_partner.commissions_flow import mark_assignments_sold_for_land
                land_code = str(commission_record.get('land_code', ''))
                partner_phone_deal = str(commission_record.get('partner_phone') or '').strip()
                if land_code and land_code != 'referral':
                    assignments = load_express_assignments() or []
                    if mark_assignments_sold_for_land(
                        assignments,
                        land_code,
                        sold_at=iso_z(utcnow()),
                    ):
                        save_express_assignments(assignments)
                    # همگام‌سازی وضعیت آگهی اکسپرس — فایل کاملاً بسته می‌شود
                    try:
                        from app.utils.storage import load_ads_cached, save_ads
                        lands = load_ads_cached() or []
                        for land in lands:
                            if not isinstance(land, dict):
                                continue
                            if str(land.get('code') or '').strip() != land_code:
                                continue
                            if str(land.get('express_status') or '').strip().lower() != 'sold':
                                land['express_status'] = 'sold'
                                save_ads(lands)
                            break
                    except Exception as e:
                        current_app.logger.error('Error marking express land sold: %s', e)
                    # مأموریت همکار روی این فایل تمام شود
                    if partner_phone_deal:
                        try:
                            from app.express_partner.partner_missions import complete_mission
                            complete_mission(partner_phone_deal, land_code=land_code)
                        except Exception as e:
                            current_app.logger.error('complete mission after deal approve: %s', e)
                    # Phase 4 Closing: sync Deal → closed (fail-open).
                    try:
                        from app.closing.deal_bridge import maybe_sync_deal_on_commission_status
                        maybe_sync_deal_on_commission_status(
                            partner_phone=partner_phone_deal,
                            land_code=land_code,
                            commission_id=str(commission_record.get('id') or ''),
                            commission_status='approved',
                            sale_amount=int(commission_record.get('sale_amount') or 0),
                        )
                    except Exception:
                        pass
            except Exception as e:
                current_app.logger.error(f"Error updating assignment status to sold: {e}")

        # به‌روزرسانی آمار همکار
        try:
            partner_phone = str(commission_record.get('partner_phone', '')).strip()
            commission_amount = int(commission_record.get('commission_amount') or 0)
            sale_amount = int(commission_record.get('sale_amount') or 0)

            if partner_phone:
                partners = load_express_partners() or []
                for p in partners:
                    if str(p.get('phone')) == partner_phone:
                        current_income = int(p.get('total_income', 0) or 0)
                        p['total_income'] = current_income + commission_amount
                        if is_deal:
                            current_sales = int(p.get('approved_sales_count', 0) or 0)
                            p['approved_sales_count'] = current_sales + 1
                            current_total_sales = int(p.get('total_approved_sales', 0) or 0)
                            p['total_approved_sales'] = current_total_sales + sale_amount
                        p['last_updated'] = iso_z(utcnow())
                        break

                save_express_partners(partners)
        except Exception as e:
            current_app.logger.error(f"Error updating partner stats: {e}")

        try:
            from app.express_partner.commission_sms import notify_partner_commission_txn
            notify_partner_commission_txn(
                partner_phone=str(commission_record.get('partner_phone') or ''),
                event='commission_approved',
                amount=int(commission_record.get('commission_amount') or 0),
                land_code=str(commission_record.get('land_code') or ''),
                commission_type=str(commission_record.get('commission_type') or ''),
                reference_id=str(commission_record.get('id') or cid),
            )
        except Exception:
            current_app.logger.exception('commission_approved SMS failed cid=%s', cid)
        if is_referral:
            flash('پورسانت دعوت همکار تأیید شد و به موجودی قابل برداشت اضافه شد.', 'success')
        elif is_visit:
            flash('پورسانت بایگانی‌شده تأیید و به موجودی همکار اضافه شد.', 'success')
        elif is_deal:
            flash(
                'فروش نهایی تأیید شد: فایل بسته شد و پورسانت فروش به کیف پول همکار اضافه شد.',
                'success',
            )
        else:
            flash('پورسانت تأیید شد و به موجودی همکار اضافه شد.', 'success')
        _admin_audit(
            'admin_commission_approve',
            entity_type='commission',
            entity_id=str(cid),
            land_code=str(commission_record.get('land_code') or ''),
            summary=f"Commission {cid} approved",
            payload={'partner_phone': str(commission_record.get('partner_phone') or '')},
        )
    elif not changed:
        flash('پورسانت قبلاً تایید شده است.', 'warning')
    return redirect(_express_commissions_redirect(filter_hint))

@admin_bp.post('/express/commissions/<int:cid>/pay')
@login_required
def express_commission_pay(cid: int):
    try:
        from app.hardening.permissions import PERM_FINANCE, has_permission
        if not has_permission(PERM_FINANCE):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    flash(
        'واریز پورسانت فقط از مسیر «مالی → درخواست‌های برداشت» انجام می‌شود. '
        'پس از تأیید پورسانت، همکار درخواست برداشت می‌دهد و شما وضعیت را «پرداخت‌شده» می‌کنید.',
        'info',
    )
    return redirect(url_for('admin.financial_withdrawals', filter='pending'))

@admin_bp.post('/express/commissions/<int:cid>/reject')
@login_required
def express_commission_reject(cid: int):
    try:
        from app.hardening.permissions import PERM_FINANCE, has_permission
        if not has_permission(PERM_FINANCE):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    from app.express_partner.commissions_flow import (
        commission_is_deal,
        commission_is_referral,
        commission_is_visit,
        commission_reject_blocked_reason,
    )
    from app.express_partner.visit_requests import restore_visit_approved_after_deal_release

    filter_hint = (request.form.get('filter') or 'pending').strip()
    items = load_express_commissions() or []
    withdrawals = load_partner_withdrawals() or []
    if not isinstance(withdrawals, list):
        withdrawals = []

    commission_record = None
    old_status = None
    for c in items:
        try:
            if int(c.get('id', 0) or 0) == int(cid):
                commission_record = c
                old_status = c.get('status')
                break
        except Exception:
            continue

    if not commission_record:
        flash('پورسانت یافت نشد.', 'error')
        return redirect(_express_commissions_redirect(filter_hint))

    block = commission_reject_blocked_reason(commission_record, withdrawals)
    if block:
        flash(block, 'error')
        return redirect(_express_commissions_redirect(filter_hint))

    changed = False
    if commission_record.get('status') in ('pending', 'approved'):
        commission_record['status'] = 'rejected'
        commission_record['rejected_at'] = iso_z(utcnow())
        changed = True

    if changed:
        save_express_commissions(items)

        partner_phone = str(commission_record.get('partner_phone', '')).strip()
        land_code = str(commission_record.get('land_code', '')).strip()
        is_referral = commission_is_referral(commission_record)
        is_visit = commission_is_visit(commission_record)
        is_deal = commission_is_deal(commission_record)

        if is_deal and land_code and land_code != 'referral':
            try:
                from app.express_partner.commissions_flow import revert_land_assignments_after_deal_cancel
                assignments = load_express_assignments() or []
                if old_status == 'pending':
                    if revert_land_assignments_after_deal_cancel(
                        assignments,
                        land_code,
                        holder_phone=partner_phone,
                        from_statuses=frozenset({'in_transaction'}),
                    ):
                        save_express_assignments(assignments)
                    visit_requests = load_express_visit_requests() or []
                    if not isinstance(visit_requests, list):
                        visit_requests = []
                    if restore_visit_approved_after_deal_release(
                        visit_requests, partner_phone, land_code
                    ):
                        save_express_visit_requests(visit_requests)
                elif old_status == 'approved':
                    if revert_land_assignments_after_deal_cancel(
                        assignments,
                        land_code,
                        from_statuses=frozenset({'sold', 'in_transaction'}),
                    ):
                        save_express_assignments(assignments)
            except Exception as e:
                current_app.logger.error('Error reverting after commission reject: %s', e)
            # Phase 4 Closing: sync Deal → cancelled (fail-open).
            try:
                from app.closing.deal_bridge import maybe_sync_deal_on_commission_status
                maybe_sync_deal_on_commission_status(
                    partner_phone=partner_phone,
                    land_code=land_code,
                    commission_id=str(commission_record.get('id') or ''),
                    commission_status='rejected',
                    sale_amount=int(commission_record.get('sale_amount') or 0),
                )
            except Exception:
                pass

        if old_status == 'approved':
            try:
                commission_amount = int(commission_record.get('commission_amount') or 0)
                sale_amount = int(commission_record.get('sale_amount') or 0)
                if partner_phone:
                    partners = load_express_partners() or []
                    for p in partners:
                        if str(p.get('phone')) == partner_phone:
                            current_income = int(p.get('total_income', 0) or 0)
                            p['total_income'] = max(0, current_income - commission_amount)
                            if is_deal:
                                current_sales = int(p.get('approved_sales_count', 0) or 0)
                                p['approved_sales_count'] = max(0, current_sales - 1)
                                current_total_sales = int(p.get('total_approved_sales', 0) or 0)
                                p['total_approved_sales'] = max(0, current_total_sales - sale_amount)
                            p['last_updated'] = iso_z(utcnow())
                            break
                    save_express_partners(partners)
            except Exception as e:
                current_app.logger.error('Error updating partner stats after reject: %s', e)

        try:
            from app.express_partner.commission_sms import notify_partner_commission_txn
            notify_partner_commission_txn(
                partner_phone=str(commission_record.get('partner_phone') or ''),
                event='commission_rejected',
                amount=int(commission_record.get('commission_amount') or 0),
                land_code=str(commission_record.get('land_code') or ''),
                commission_type=str(commission_record.get('commission_type') or ''),
                reference_id=str(commission_record.get('id') or cid),
            )
        except Exception:
            current_app.logger.exception('commission_rejected SMS failed cid=%s', cid)

        if is_referral:
            try:
                from app.express_partner.referrals import sync_referral_on_commission_status
                sync_referral_on_commission_status(commission_record)
            except Exception as e:
                current_app.logger.error('Referral sync on commission reject: %s', e)

        if is_visit:
            flash('پورسانت بایگانی‌شده رد شد.', 'info')
        else:
            flash('پورسانت فروش رد شد.', 'info')
        _admin_audit(
            'admin_commission_reject',
            entity_type='commission',
            entity_id=str(cid),
            land_code=str(commission_record.get('land_code') or ''),
            summary=f"Commission {cid} rejected",
            payload={'partner_phone': str(commission_record.get('partner_phone') or '')},
        )
    else:
        flash('فقط پورسانت‌های در انتظار یا تأییدشده قابل رد هستند.', 'warning')
    return redirect(_express_commissions_redirect(filter_hint))

@admin_bp.post('/express/commissions/clear-all')
@login_required
def clear_all_commissions():
    try:
        from app.hardening.permissions import PERM_SUPER, has_permission
        if not has_permission(PERM_SUPER):
            flash('فقط Super Admin می‌تواند همه پورسانت‌ها را پاک کند.', 'error')
            return redirect(url_for('admin.express_commissions'))
    except Exception:
        pass
    save_express_commissions([])
    _admin_audit(
        'admin_commission_clear_all',
        entity_type='commission',
        summary='All commissions cleared',
    )
    flash('همه پورسانت‌ها حذف شدند.', 'info')
    return redirect(url_for('admin.express_commissions'))

@admin_bp.route('/express/commissions/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def express_commission_edit(cid: int):
    from app.express_partner.commissions_flow import commission_is_deal

    items = load_express_commissions() or []
    commission = None
    for c in items:
        try:
            if int(c.get('id',0) or 0) == int(cid):
                commission = c
                break
        except Exception:
            continue
    
    if not commission:
        flash('پورسانت یافت نشد.', 'error')
        return redirect(url_for('admin.express_commissions'))
    
    if request.method == 'POST':
        form = request.form
        sale_amount = (form.get('sale_amount') or '').strip()
        commission_pct = (form.get('commission_pct') or '').strip()
        
        try:
            sale = int(str(sale_amount).replace(',','').strip() or '0')
        except Exception:
            sale = int(commission.get('sale_amount') or 0)
        
        try:
            pct = float(commission_pct or '0')
        except Exception:
            pct = float(commission.get('commission_pct') or 0)
        
        commission_amount = int(round(sale * (pct/100.0))) if sale and pct else 0
        
        # اگر پورسانت تایید شده است، باید آمار را به‌روز کنم
        old_sale = int(commission.get('sale_amount') or 0)
        old_commission = int(commission.get('commission_amount') or 0)
        is_approved = commission.get('status') == 'approved'
        is_deal = commission_is_deal(commission)
        
        # به‌روزرسانی رکورد
        commission['sale_amount'] = sale
        commission['commission_pct'] = pct
        commission['commission_amount'] = commission_amount
        commission['updated_at'] = iso_z(utcnow())
        
        save_express_commissions(items)
        
        # اگر تایید شده بود، آمار را به‌روز کن
        if is_approved and (sale != old_sale or commission_amount != old_commission):
            try:
                partner_phone = str(commission.get('partner_phone', '')).strip()
                if partner_phone:
                    partners = load_express_partners() or []
                    for p in partners:
                        if str(p.get('phone')) == partner_phone:
                            # به‌روزرسانی کل درآمد (تفاوت مبلغ جدید و قدیم)
                            current_income = int(p.get('total_income', 0) or 0)
                            diff_commission = commission_amount - old_commission
                            p['total_income'] = max(0, current_income + diff_commission)
                            
                            if is_deal:
                                # فقط پورسانت معامله روی آمار فروش اثر دارد.
                                current_total_sales = int(p.get('total_approved_sales', 0) or 0)
                                diff_sale = sale - old_sale
                                p['total_approved_sales'] = max(0, current_total_sales + diff_sale)
                            
                            p['last_updated'] = iso_z(utcnow())
                            break
                    
                    save_express_partners(partners)
            except Exception as e:
                current_app.logger.error(f"Error updating partner stats after edit: {e}")
        
        flash('پورسانت با موفقیت ویرایش شد.', 'success')
        return redirect(url_for('admin.express_commissions'))
    
    # GET - نمایش فرم ویرایش
    return render_template('admin/edit_commission.html', commission=commission)

# -----------------------------------------------------------------------------
# مالی — درخواست‌های برداشت همکاران
# -----------------------------------------------------------------------------
def _partner_name_lookup() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for p in load_express_partners() or []:
            if not isinstance(p, dict):
                continue
            ph = str(p.get('phone') or '').strip()
            if ph:
                out[ph] = str(p.get('name') or '').strip()
    except Exception:
        pass
    return out


@admin_bp.route('/financial/withdrawals', endpoint='financial_withdrawals')
@login_required
def financial_withdrawals():
    items_raw = load_partner_withdrawals() or []
    if not isinstance(items_raw, list):
        items_raw = []
    name_map = _partner_name_lookup()
    items = []
    for row in items_raw:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        ph = str(r.get('phone') or '').strip()
        if not (r.get('partner_name') or '').strip() and ph in name_map:
            r['partner_name'] = name_map[ph]
        items.append(admin_row_dict(r))
    items.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    pending_count = sum(1 for x in items if x.get('status') == 'pending')
    approved_count = sum(1 for x in items if x.get('status') == 'approved')
    processing_count = sum(1 for x in items if x.get('status') == 'processing')
    active_count = sum(1 for x in items if x.get('is_active'))
    paid_count = sum(1 for x in items if x.get('status') == 'paid')

    flt = (request.args.get('filter') or 'active').strip().lower()
    if flt == 'all':
        filtered = items
    elif flt == 'pending':
        filtered = [x for x in items if x.get('status') == 'pending']
    elif flt == 'approved':
        filtered = [x for x in items if x.get('status') == 'approved']
    elif flt == 'processing':
        filtered = [x for x in items if x.get('status') == 'processing']
    elif flt == 'paid':
        filtered = [x for x in items if x.get('status') == 'paid']
    elif flt == 'closed':
        filtered = [x for x in items if x.get('filter_bucket') == 'closed']
    else:
        flt = 'active'
        filtered = [x for x in items if x.get('is_active')]

    return render_template(
        'admin/financial_withdrawals.html',
        items=filtered,
        all_count=len(items),
        pending_count=pending_count,
        approved_count=approved_count,
        processing_count=processing_count,
        active_count=active_count,
        paid_count=paid_count,
        current_filter=flt,
    )


@admin_bp.route('/express/visit-requests', methods=['GET', 'POST'], endpoint='express_visit_requests')
@login_required
def express_visit_requests():
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        CANCELLED_STATUS,
        COMPLETED_STATUS,
        DONE_PENDING_STATUS,
        NO_SHOW_STATUS,
        PENDING_STATUS,
        VISIT_WEEKDAY_LABELS,
        VISIT_WEEKDAY_ORDER,
        admin_row_dict as visit_admin_row,
        admin_can_transition_visit,
        admin_visit_in_workflow,
        admin_visit_status_options,
        admin_visit_workflow_needs_action,
        admin_visit_workflow_steps,
        get_visit_allowed_weekdays,
        merge_admin_visit_cards_by_partner_land,
        save_visit_allowed_weekdays,
        visit_allowed_weekdays_summary,
    )

    if request.method == 'POST' and (request.form.get('action') or '').strip() == 'save_visit_weekdays':
        raw_days = request.form.getlist('visit_weekdays')
        try:
            parsed = [int(x) for x in raw_days]
        except ValueError:
            parsed = []
        if not parsed:
            flash('حداقل یک روز هفته را برای بازدید انتخاب کنید.', 'warning')
            flt = (request.form.get('filter') or 'workflow').strip().lower()
            return redirect(url_for('admin.express_visit_requests', filter=flt or None))
        save_visit_allowed_weekdays(parsed)
        flash(f'روزهای مجاز بازدید ذخیره شد: {visit_allowed_weekdays_summary()}', 'success')
        flt = (request.form.get('filter') or request.args.get('filter') or 'workflow').strip().lower()
        return redirect(url_for('admin.express_visit_requests', filter=flt or None))

    flt = (request.args.get('filter') or 'workflow').strip().lower()
    items_raw = load_express_visit_requests() or []
    if not isinstance(items_raw, list):
        items_raw = []
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []
    withdrawals = load_partner_withdrawals() or []
    if not isinstance(withdrawals, list):
        withdrawals = []
    try:
        from app.express_partner.commissions_flow import (
            admin_commission_row_dict as commission_admin_row,
            commission_is_deal,
            commission_is_visit,
            commission_linked_to_active_withdrawal,
        )
        settings_data = get_settings()
        visit_commission_amount = int(settings_data.get('visit_commission_amount_toman') or 0)
    except Exception:
        commission_admin_row = None
        commission_is_deal = None
        commission_is_visit = None
        commission_linked_to_active_withdrawal = None
        visit_commission_amount = 0

    from app.express_partner.visit_requests import commission_for_visit_request

    def _commission_for_visit_row(
        phone: str,
        code: str,
        kind: str,
        visit_request_id: str | None = None,
    ) -> dict | None:
        if not commission_admin_row:
            return None
        ph = (phone or '').strip()
        ck = str(code or '').strip()
        if not ph or not ck:
            return None
        predicate = commission_is_visit if kind == 'visit' else commission_is_deal
        if not predicate:
            return None
        vid = str(visit_request_id or '').strip()
        if kind == 'visit' and vid:
            matched = commission_for_visit_request(
                commissions, ph, ck, vid, kind='visit', visit_requests=items_raw,
            )
            if not matched:
                return None
            row = commission_admin_row(matched)
            row['withdrawal_locked'] = (
                commission_linked_to_active_withdrawal(matched, withdrawals)
                if commission_linked_to_active_withdrawal
                else False
            )
            return row
        pending_row = None
        latest_row = None
        for c in reversed(commissions):
            if not isinstance(c, dict):
                continue
            if str(c.get('partner_phone') or '').strip() != ph:
                continue
            if str(c.get('land_code') or '').strip() != ck:
                continue
            if not predicate(c):
                continue
            row = commission_admin_row(c)
            row['withdrawal_locked'] = (
                commission_linked_to_active_withdrawal(c, withdrawals)
                if commission_linked_to_active_withdrawal
                else False
            )
            st = str(c.get('status') or '').strip().lower()
            if st == 'pending' and pending_row is None:
                pending_row = row
            if latest_row is None:
                latest_row = row
        return pending_row or latest_row

    def _visit_commission_required_for_admin(phone: str, code: str) -> bool:
        """پورسانت بازدید حذف شده — دیگر پیش‌نیاز معامله نیست."""
        return False

    name_map = _partner_name_lookup()
    items = []
    for row in items_raw:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        ph = str(r.get('partner_phone') or '').strip()
        if not (r.get('partner_name') or '').strip() and ph in name_map:
            r['partner_name'] = name_map[ph]
        r['visit_commission_required'] = _visit_commission_required_for_admin(
            ph,
            str(r.get('land_code') or '').strip(),
        )
        item = visit_admin_row(r, commissions)
        item['status_options'] = admin_visit_status_options(item.get('status'))
        item['visit_commission_required'] = bool(r.get('visit_commission_required'))
        visit_row_id = str(r.get('id') or '').strip()
        item['visit_commission'] = _commission_for_visit_row(
            ph,
            str(r.get('land_code') or '').strip(),
            'visit',
            visit_request_id=visit_row_id,
        )
        item['deal_commission'] = _commission_for_visit_row(ph, str(r.get('land_code') or '').strip(), 'deal')
        item['admin_workflow_steps'] = admin_visit_workflow_steps(
            item,
            visit_commission=item.get('visit_commission'),
            deal_commission=item.get('deal_commission'),
            visit_commission_required=item.get('visit_commission_required'),
        )
        item['workflow_needs_action'] = admin_visit_workflow_needs_action(item['admin_workflow_steps'])
        item['in_workflow'] = admin_visit_in_workflow(item, item['admin_workflow_steps'])
        _st = (str(item.get('status') or '')).strip()
        item['can_close'] = (
            _st in (PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS)
            and admin_can_transition_visit(_st, CANCELLED_STATUS)
        )
        items.append(item)

    # یک کارت به ازای هر همکار+فایل؛ بازدیدهای بعدی داخل همان کارت
    items = merge_admin_visit_cards_by_partner_land(items)

    def _group_has_status(card: dict, *statuses: str) -> bool:
        wanted = {str(s) for s in statuses}
        for m in card.get('merged_visits') or []:
            if str(m.get('status') or '').strip() in wanted:
                return True
        return str(card.get('status') or '').strip() in wanted

    pending_count = sum(1 for x in items if _group_has_status(x, PENDING_STATUS))
    approved_count = sum(1 for x in items if _group_has_status(x, APPROVED_STATUS))
    done_pending_count = sum(1 for x in items if _group_has_status(x, DONE_PENDING_STATUS))
    done_count = sum(1 for x in items if _group_has_status(x, COMPLETED_STATUS))
    closed_count = sum(1 for x in items if x.get('group_all_cancelled'))
    no_show_count = sum(1 for x in items if _group_has_status(x, NO_SHOW_STATUS))
    active_count = sum(
        1
        for x in items
        if _group_has_status(x, PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS)
    )
    workflow_count = sum(1 for x in items if x.get('in_workflow'))
    action_count = sum(1 for x in items if x.get('workflow_needs_action'))

    visit_result_ui = False
    try:
        from app.visit_result.config import visit_result_ui_enabled
        visit_result_ui = bool(visit_result_ui_enabled())
    except Exception:
        visit_result_ui = False

    if flt == 'actions':
        visible = [x for x in items if x.get('workflow_needs_action')]
        visible.sort(key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
    elif flt == 'workflow':
        visible = [x for x in items if x.get('in_workflow')]
        visible.sort(key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
        visible.sort(key=lambda x: 0 if x.get('workflow_needs_action') else 1)
    elif flt == 'approved':
        visible = [x for x in items if _group_has_status(x, APPROVED_STATUS)]
    elif flt == 'done_pending':
        visible = [x for x in items if _group_has_status(x, DONE_PENDING_STATUS)]
    elif flt == 'done':
        visible = [x for x in items if _group_has_status(x, COMPLETED_STATUS)]
    elif flt == 'no_show' and visit_result_ui:
        visible = [x for x in items if _group_has_status(x, NO_SHOW_STATUS)]
    elif flt == 'closed':
        visible = [x for x in items if x.get('group_all_cancelled')]
    elif flt == 'active':
        visible = [
            x
            for x in items
            if _group_has_status(x, PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS)
        ]
    elif flt == 'all':
        visible = items
    else:
        flt = 'workflow'
        visible = [x for x in items if x.get('in_workflow')]
        visible.sort(key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
        visible.sort(key=lambda x: 0 if x.get('workflow_needs_action') else 1)

    if flt not in ('workflow', 'actions'):
        visible.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        visible.sort(key=lambda x: {
            PENDING_STATUS: 0,
            DONE_PENDING_STATUS: 1,
            APPROVED_STATUS: 2,
            COMPLETED_STATUS: 3,
            NO_SHOW_STATUS: 4,
            CANCELLED_STATUS: 5,
        }.get(x.get('status') or '', 9))
    all_count = len(items)

    return render_template(
        'admin/express_visit_requests.html',
        items=visible,
        pending_count=pending_count,
        approved_count=approved_count,
        done_pending_count=done_pending_count,
        done_count=done_count,
        closed_count=closed_count,
        no_show_count=no_show_count,
        active_count=active_count,
        workflow_count=workflow_count,
        action_count=action_count,
        all_count=all_count,
        current_filter=flt,
        visit_result_ui_enabled=visit_result_ui,
        visit_weekday_labels=VISIT_WEEKDAY_LABELS,
        visit_weekday_order=VISIT_WEEKDAY_ORDER,
        visit_allowed_weekdays=get_visit_allowed_weekdays(),
        visit_allowed_weekdays_summary=visit_allowed_weekdays_summary(),
    )


def _flash_visit_request_status_change(rec: dict, new_status: str) -> None:
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        CANCELLED_STATUS,
        COMPLETED_STATUS,
        DONE_PENDING_STATUS,
        PENDING_STATUS,
    )

    name = (rec or {}).get('partner_name') or (rec or {}).get('partner_phone') or 'همکار'
    labels = {
        PENDING_STATUS: 'در انتظار تأیید',
        APPROVED_STATUS: 'تأیید شده',
        DONE_PENDING_STATUS: 'در انتظار تأیید انجام بازدید',
        COMPLETED_STATUS: 'بازدید انجام شد',
        CANCELLED_STATUS: 'بسته شد',
    }
    label = labels.get(new_status, new_status)
    if new_status == APPROVED_STATUS:
        flash(
            f'وضعیت درخواست بازدید {name} به «{label}» تغییر کرد. همکار باید پس از انجام بازدید، آن را روی فایل ثبت کند.',
            'success',
        )
    elif new_status == DONE_PENDING_STATUS:
        flash(
            f'انجام بازدید برای {name} ثبت شد و منتظر تأیید ادمین است.',
            'info',
        )
    elif new_status == COMPLETED_STATUS:
        flash(f'انجام بازدید {name} تأیید شد.', 'success')
    elif new_status == CANCELLED_STATUS:
        flash(f'پرونده بازدید {name} بسته شد.', 'success')
    else:
        flash(f'وضعیت درخواست بازدید {name} به «{label}» تغییر کرد.', 'success')


@admin_bp.post('/express/visit-requests/<vid>/recreate-visit-commission')
@login_required
def express_visit_request_recreate_commission(vid: str):
    """پورسانت بازدید حذف شده — فقط پورسانت فروش باقی است."""
    filter_hint = (request.form.get('filter') or 'workflow').strip()
    flash('پورسانت بازدید حذف شده است؛ فقط پورسانت فروش از مسیر معامله ثبت می‌شود.', 'info')
    return redirect(_express_visit_requests_redirect(filter_hint, vid))


@admin_bp.post('/express/visit-requests/<vid>/status')
@login_required
def express_visit_request_status(vid: str):
    try:
        from app.hardening.permissions import PERM_VISITS, has_permission
        if not has_permission(PERM_VISITS):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        COMPLETED_STATUS,
        NO_SHOW_STATUS,
        admin_can_transition_visit,
        admin_update_visit_request_status,
    )
    from app.express_partner.visit_sms import (
        notify_partner_land_tx_sms,
        visit_status_change_event,
    )

    new_status = (request.form.get('status') or '').strip()
    admin_note = (request.form.get('admin_note') or '').strip()
    filter_hint = (request.form.get('filter') or 'workflow').strip()
    outcome = (request.form.get('outcome') or '').strip()
    items = load_express_visit_requests() or []
    if not isinstance(items, list):
        items = []
    prev_status = ''
    for row in items:
        if isinstance(row, dict) and str(row.get('id') or '') == str(vid).strip():
            prev_status = (str(row.get('status') or '')).strip()
            break

    if new_status == NO_SHOW_STATUS:
        try:
            from app.visit_result.status_bridge import is_no_show_writable
            if not is_no_show_writable():
                flash('ثبت عدم حضور فعلاً فعال نیست.', 'error')
                return redirect(_express_visit_requests_redirect(filter_hint, vid))
        except Exception:
            flash('ثبت عدم حضور در دسترس نیست.', 'error')
            return redirect(_express_visit_requests_redirect(filter_hint, vid))

    if prev_status and new_status and not admin_can_transition_visit(prev_status, new_status):
        flash('این تغییر وضعیت مجاز نیست. ابتدا همکار باید «بازدید انجام شد» را از روی صفحه فایل ثبت کند.', 'error')
        return redirect(_express_visit_requests_redirect(filter_hint, vid))

    rec, err = admin_update_visit_request_status(
        items, vid, new_status, admin_note=admin_note
    )
    if err == 'not_found':
        flash('درخواست بازدید یافت نشد.', 'error')
        return redirect(_express_visit_requests_redirect(filter_hint, vid))
    if err == 'invalid_status':
        flash('وضعیت انتخاب‌شده نامعتبر است.', 'error')
        return redirect(_express_visit_requests_redirect(filter_hint, vid))
    if err == 'unchanged':
        flash('تغییری ذخیره نشد. وضعیت یا یادداشت را ویرایش کنید.', 'info')
        return redirect(_express_visit_requests_redirect(filter_hint, vid))
    visit_commission_pending = False
    try:
        save_express_visit_requests(items)
        if err == 'note_updated':
            flash('یادداشت درخواست بازدید ذخیره شد.', 'success')
        else:
            _flash_visit_request_status_change(rec or {}, new_status)
            _admin_audit(
                'admin_visit_status',
                entity_type='visit_request',
                entity_id=str(vid),
                land_code=str((rec or {}).get('land_code') or ''),
                summary=f"Visit {vid}: {prev_status} → {new_status}",
                payload={'prev_status': prev_status, 'new_status': new_status},
            )
            # Phase 2: persist VisitResult on no_show or optional outcome (never commission).
            if rec and new_status == NO_SHOW_STATUS:
                try:
                    from app.visit_result.service import register_result

                    register_result(
                        visit_request_id=str(rec.get('id') or vid),
                        partner_phone=str(rec.get('partner_phone') or ''),
                        land_code=str(rec.get('land_code') or ''),
                        outcome='no_show',
                        notes=admin_note,
                        actor_key='admin',
                        source='admin',
                    )
                except Exception:
                    current_app.logger.exception('admin visit no_show result failed vid=%s', vid)
            elif rec and outcome:
                try:
                    from app.visit_result.config import visit_result_ui_enabled
                    from app.visit_result.service import register_result, valid_outcome

                    if visit_result_ui_enabled() and valid_outcome(outcome) and outcome != 'no_show':
                        register_result(
                            visit_request_id=str(rec.get('id') or vid),
                            partner_phone=str(rec.get('partner_phone') or ''),
                            land_code=str(rec.get('land_code') or ''),
                            outcome=outcome,
                            notes=admin_note,
                            actor_key='admin',
                            source='admin',
                        )
                except Exception:
                    current_app.logger.exception('admin visit result failed vid=%s', vid)
            if rec and new_status == COMPLETED_STATUS:
                flash('همکار اکنون می‌تواند درخواست معامله ثبت کند.', 'info')
            if rec:
                sms_event = visit_status_change_event(new_status, prev_status)
                if sms_event:
                    try:
                        sms_result = notify_partner_land_tx_sms(
                            partner_phone=str(rec.get('partner_phone') or ''),
                            event=sms_event,
                            land_code=str(rec.get('land_code') or ''),
                            land_title=str(rec.get('land_title') or ''),
                            visit_date=str(rec.get('visit_date') or ''),
                            admin_note=admin_note,
                            reference_id=str(rec.get('id') or vid),
                            visit_commission_pending=False,
                        )
                        if sms_result.get('ok'):
                            flash('پیامک وضعیت بازدید برای همکار ارسال شد.', 'success')
                        elif not sms_result.get('skipped'):
                            flash(
                                'وضعیت ذخیره شد، اما ارسال پیامک به همکار ناموفق بود.',
                                'warning',
                            )
                    except Exception:
                        current_app.logger.exception(
                            'visit status partner SMS failed vid=%s event=%s',
                            vid,
                            sms_event,
                        )
    except Exception:
        flash('خطا در ذخیره وضعیت.', 'error')
    return redirect(_express_visit_requests_redirect(filter_hint, vid))


def _financial_withdrawals_redirect(filter_hint: str = '') -> str:
    flt = (filter_hint or request.form.get('filter') or request.args.get('filter') or 'active').strip()
    if flt:
        return url_for('admin.financial_withdrawals', filter=flt)
    return url_for('admin.financial_withdrawals')


@admin_bp.post('/financial/withdrawals/<wid>/status')
@login_required
def financial_withdrawal_status(wid: str):
    try:
        from app.hardening.permissions import PERM_FINANCE, has_permission
        if not has_permission(PERM_FINANCE):
            flash('دسترسی کافی برای این عملیات ندارید.', 'error')
            return redirect(url_for('admin.dashboard'))
    except Exception:
        pass
    new_status = (request.form.get('status') or '').strip().lower()
    admin_note = (request.form.get('admin_note') or '').strip()
    filter_hint = (request.form.get('filter') or 'active').strip()

    items = load_partner_withdrawals() or []
    if not isinstance(items, list):
        items = []
    withdrawal_row = None
    old_status = None
    for row in items:
        if not isinstance(row, dict):
            continue
        if str(row.get('id') or '') == str(wid):
            withdrawal_row = row
            old_status = (str(row.get('status') or 'pending')).strip().lower()
            break

    if not withdrawal_row:
        flash('درخواست یافت نشد.', 'error')
        return redirect(_financial_withdrawals_redirect(filter_hint))

    if old_status == 'cancelled':
        flash('این درخواست توسط همکار لغو شده و قابل تغییر نیست.', 'warning')
        return redirect(_financial_withdrawals_redirect(filter_hint))

    if old_status == 'paid' and new_status != 'paid':
        flash('درخواست پرداخت‌شده قابل بازگشت به وضعیت قبلی نیست.', 'warning')
        return redirect(_financial_withdrawals_redirect(filter_hint))

    if not admin_can_transition(old_status, new_status):
        flash('تغییر وضعیت انتخاب‌شده مجاز نیست.', 'error')
        return redirect(_financial_withdrawals_redirect(filter_hint))

    note_only = new_status == old_status
    if note_only and not admin_note:
        flash('تغییری ذخیره نشد. وضعیت یا یادداشت را ویرایش کنید.', 'info')
        return redirect(_financial_withdrawals_redirect(filter_hint))

    wid_str = str(withdrawal_row.get('id') or wid)
    partner_phone = str(withdrawal_row.get('phone') or '').strip()

    try:
        commissions = load_express_commissions() or []
        if not isinstance(commissions, list):
            commissions = []
        commissions_dirty = False
        withdrawals_dirty = False

        if not note_only:
            withdrawal_row['status'] = new_status
            withdrawal_row['updated_at'] = iso_z(utcnow())
            withdrawals_dirty = True

            if new_status == 'approved' and old_status not in ('approved', 'processing', 'paid'):
                linked = link_withdrawal_to_commissions(
                    commissions,
                    partner_phone,
                    int(withdrawal_row.get('amount') or 0),
                    wid_str,
                    items,
                )
                if linked > 0:
                    commissions_dirty = True
                elif int(withdrawal_row.get('amount') or 0) > 0:
                    flash(
                        'وضعیت تأیید شد؛ پورسانت تأییدشدهٔ کافی برای تخصیص خودکار یافت نشد. قبل از «پرداخت‌شده» بررسی کنید.',
                        'warning',
                    )

            if new_status == 'rejected' and old_status != 'rejected':
                release_withdrawal_commissions(commissions, wid_str)
                commissions_dirty = True

            if new_status == 'pending' and old_status in ('approved', 'processing'):
                release_withdrawal_commissions(commissions, wid_str)
                commissions_dirty = True

            if new_status == 'paid' and old_status != 'paid':
                now_iso = iso_z(utcnow())
                wd_amount = int(withdrawal_row.get('amount') or 0)
                already = int(withdrawal_row.get('commission_allocated_amount') or 0)
                need = max(0, wd_amount - already)
                allocated = 0
                if need > 0:
                    if old_status not in ('approved', 'processing'):
                        link_withdrawal_to_commissions(
                            commissions,
                            partner_phone,
                            wd_amount,
                            wid_str,
                            items,
                        )
                        commissions_dirty = True
                    allocated = apply_paid_withdrawal_to_commissions(
                        commissions,
                        partner_phone,
                        need,
                        wid_str,
                        now_iso,
                        items,
                    )
                if allocated > 0:
                    commissions_dirty = True
                    withdrawal_row['commission_allocated_amount'] = already + allocated
                    withdrawals_dirty = True
                elif wd_amount > 0 and already <= 0:
                    flash(
                        'وضعیت «پرداخت‌شده» ثبت شد اما پورسانتی برای تخصیص پیدا نشد. پورسانت‌ها را در بخش مالی بررسی کنید.',
                        'warning',
                    )

        if admin_note or (note_only and withdrawal_row.get('admin_note')):
            withdrawal_row['admin_note'] = admin_note
            withdrawals_dirty = True

        if commissions_dirty:
            save_express_commissions(commissions)
        if withdrawals_dirty:
            save_partner_withdrawals(items)

        if not note_only and old_status != new_status:
            wd_event = None
            if new_status == 'approved':
                wd_event = 'withdrawal_approved'
            elif new_status == 'rejected':
                wd_event = 'withdrawal_rejected'
            elif new_status == 'paid':
                wd_event = 'withdrawal_paid'
            if wd_event:
                try:
                    from app.express_partner.commission_sms import notify_partner_commission_txn
                    notify_partner_commission_txn(
                        partner_phone=partner_phone,
                        event=wd_event,
                        amount=int(withdrawal_row.get('amount') or 0),
                        bank_summary=str(withdrawal_row.get('bank_summary') or ''),
                        reference_id=wid_str,
                    )
                except Exception:
                    current_app.logger.exception(
                        'withdrawal status SMS failed wid=%s event=%s', wid, wd_event
                    )

        if note_only:
            flash('یادداشت درخواست برداشت ذخیره شد.', 'success')
        else:
            labels = {
                'pending': 'در انتظار بررسی',
                'approved': 'تأیید شده',
                'processing': 'در حال پردازش',
                'paid': 'پرداخت‌شده',
                'rejected': 'رد شده',
            }
            flash(
                f'وضعیت درخواست به «{labels.get(new_status, new_status)}» تغییر کرد.',
                'success',
            )
            _admin_audit(
                'admin_withdrawal_status',
                entity_type='withdrawal',
                entity_id=wid_str,
                summary=f"Withdrawal {wid_str}: {old_status} → {new_status}",
                payload={
                    'partner_phone': partner_phone,
                    'old_status': old_status,
                    'new_status': new_status,
                },
            )
    except Exception:
        current_app.logger.exception('save_partner_withdrawals status failed')
        flash('خطا در ذخیره.', 'error')

    return redirect(_financial_withdrawals_redirect(filter_hint))

def _partner_record_for_phone(partners: List[Dict[str, Any]], phone: str) -> Optional[Dict[str, Any]]:
    norm = _normalize_phone(phone) or phone.strip()
    for p in partners:
        if not isinstance(p, dict):
            continue
        pph = _normalize_phone(str(p.get('phone') or '')) or str(p.get('phone') or '').strip()
        if pph == norm:
            return p
    return None


def _ensure_site_user_record(phone: str) -> None:
    users = load_users() or []
    norm = _normalize_phone(phone) or phone.strip()
    for u in users:
        if not isinstance(u, dict):
            continue
        uph = _normalize_phone(str(u.get('phone') or u.get('mobile') or '')) or str(u.get('phone') or '').strip()
        if uph == norm:
            return
    users.append({
        'phone': norm,
        'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    save_users(users)


def _approve_express_partner(
    *,
    phone: str,
    name: str = '',
    city: str = '',
    national_id: str = '',
    referred_by_phone: str = '',
    application: Optional[Dict[str, Any]] = None,
    remove_application: bool = True,
    send_sms: bool = True,
    send_notification: bool = True,
    auto_assign_lands: bool = True,
    source: str = 'admin_partner_approval',
) -> Dict[str, Any]:
    """تأیید همکار: ثبت در partners، انتساب فایل، اعلان و پیامک."""
    from admin.people_directory import partner_is_approved

    phone = _normalize_phone(phone) or str(phone or '').strip()
    if not phone or len(phone) != 11:
        return {'ok': False, 'error': 'invalid_phone'}

    name = (name or '').strip()
    city = (city or '').strip()
    national_id = (national_id or '').strip()
    app = dict(application) if isinstance(application, dict) else None

    if app:
        name = name or (app.get('name') or '').strip()
        city = city or (app.get('city') or '').strip()
        national_id = national_id or (app.get('national_id') or '').strip()
        referred_by_phone = referred_by_phone or (app.get('referred_by_phone') or '').strip()

    partners = load_express_partners() or []
    partner = _partner_record_for_phone(partners, phone)
    already_approved = bool(partner and partner_is_approved(partner))
    if not partner:
        partner = {
            'id': (max([int(x.get('id', 0) or 0) for x in partners if isinstance(x, dict)], default=0) or 0) + 1,
            'name': name,
            'phone': phone,
            'city': city,
            'national_id': national_id,
            'status': 'approved',
            'created_at': iso_z(utcnow()),
        }
        partners.append(partner)
    else:
        partner.update({
            'name': name or partner.get('name'),
            'city': city or partner.get('city'),
            'national_id': national_id or partner.get('national_id'),
            'status': 'approved',
        })

    ref_by = (referred_by_phone or '').strip()
    if ref_by:
        try:
            from app.express_partner.referrals import _normalize_phone as _ref_norm_phone
            partner['referred_by_phone'] = _ref_norm_phone(ref_by) or ref_by
        except Exception:
            partner['referred_by_phone'] = ref_by
        if app and app.get('id'):
            try:
                partner['referral_application_id'] = int(app.get('id') or 0)
            except Exception:
                pass

    if app:
        app['status'] = 'approved'
        app['approved_at'] = iso_z(utcnow())

    save_express_partners(partners)

    ref_granted = False
    ref_skip_reason = None
    if app:
        try:
            from app.express_partner.referrals import grant_referral_commission_for_application
            ref_granted, ref_skip_reason = grant_referral_commission_for_application(app)
        except Exception as ref_err:
            current_app.logger.error('Referral commission on partner approve: %s', ref_err, exc_info=True)
            ref_skip_reason = 'exception'
    elif ref_by:
        try:
            from app.express_partner.referrals import grant_referral_for_partner_record
            ref_granted, ref_skip_reason = grant_referral_for_partner_record(partner)
        except Exception as ref_err:
            current_app.logger.error('Referral commission on manual partner approve: %s', ref_err, exc_info=True)
            ref_skip_reason = 'exception'

    if ref_by:
        if ref_granted:
            partner.pop('referral_grant_pending', None)
        else:
            partner['referral_grant_pending'] = True
        save_express_partners(partners)

    if remove_application and app and app.get('id'):
        apps = load_express_partner_apps() or []
        aid = int(app.get('id') or 0)
        try:
            apps = [a for a in apps if int(a.get('id', 0) or 0) != aid]
        except Exception:
            apps = [a for a in apps if a is not app]
        save_express_partner_apps(apps)

    new_assignments_count = 0
    if auto_assign_lands and not already_approved:
        try:
            lands = load_json(_lands_path()) or []
            express_lands = [l for l in lands if l.get('is_express', False)]
            assignments = load_express_assignments() or []
            existing_codes = {
                a.get('land_code')
                for a in assignments
                if _normalize_phone(str(a.get('partner_phone') or '')) == phone
            }
            for land in express_lands:
                land_code = land.get('code')
                if land_code and land_code not in existing_codes:
                    new_id = (max([int(x.get('id', 0) or 0) for x in assignments if isinstance(x, dict)], default=0) or 0) + 1
                    assignments.append({
                        'id': new_id,
                        'partner_phone': phone,
                        'land_code': land_code,
                        'commission_pct': 2.0,
                        'status': 'active',
                        'created_at': iso_z(utcnow()),
                    })
                    new_assignments_count += 1
            if new_assignments_count > 0:
                save_express_assignments(assignments)
        except Exception as e:
            current_app.logger.error('Error auto-assigning lands to partner: %s', e)

    if send_notification:
        try:
            add_notification(
                user_id=phone,
                title='تأیید همکاری وینور اکسپرس',
                body=(
                    'درخواست شما تأیید شد. همان چت قبلی‌ات باز است — '
                    'الان می‌تونی بازدید و معامله را از چت ثبت کنی.'
                ),
                ntype='success',
                action_url=url_for('express_partner.home', _external=True),
            )
        except Exception as e:
            current_app.logger.error('Error sending approval notification: %s', e, exc_info=True)

    # ارتقای همان thread: چت public → partner تا ابزارهای کامل فعال شوند
    chat_migrated = 0
    try:
        from app.ai.chat_store import promote_public_chat_to_partner

        mig = promote_public_chat_to_partner(phone)
        chat_migrated = int(mig.get("migrated") or 0)
    except Exception as e:
        current_app.logger.error('promote_public_chat_to_partner failed: %s', e, exc_info=True)

    if send_sms and phone.startswith('09'):
        try:
            settings = get_settings()
            sms_message = settings.get('partner_approval_sms_message', 'وینور\nپنل همکاری‌ت فعاله. بزن بریم!')
            sms_line_number = settings.get('sms_line_number', '09981801922')
            if not sms_message or not sms_message.strip():
                sms_message = 'وینور\nپنل همکاری‌ت فعاله. بزن بریم!'
            current_app.logger.info('Sending approval SMS to partner: %s (%s)', name, phone)
            sms_result = send_sms_direct(mobile=phone, message=sms_message, line_number=sms_line_number)
            try:
                history = load_sms_history() or []
                record = {
                    'id': len(history) + 1,
                    'mobile': phone,
                    'recipient_name': name,
                    'template_id': None,
                    'message': sms_message,
                    'parameters': {},
                    'success': sms_result.get('ok', False),
                    'status_code': sms_result.get('status', 0),
                    'response': sms_result.get('body', {}),
                    'source': source,
                    'created_at': datetime.now().isoformat(),
                    'error': None if sms_result.get('ok') else str(sms_result.get('body', {}).get('message', 'Unknown error')),
                }
                history.append(record)
                if len(history) > 10000:
                    history = history[-10000:]
                save_sms_history(history)
            except Exception as hist_err:
                current_app.logger.error('Failed to save SMS history: %s', hist_err)
        except Exception as sms_err:
            current_app.logger.error('Error sending partner approval SMS: %s', sms_err, exc_info=True)

    return {
        'ok': True,
        'phone': phone,
        'already_approved': already_approved,
        'new_assignments_count': new_assignments_count,
        'ref_granted': ref_granted,
        'ref_skip_reason': ref_skip_reason,
        'referred_by_phone': ref_by,
        'application_id': int(app.get('id') or 0) if app else 0,
        'chat_migrated': chat_migrated,
    }


def _flash_partner_approval_result(result: Dict[str, Any], *, prefix: str = '') -> None:
    if not result.get('ok'):
        flash(result.get('error_fa') or 'تأیید همکار انجام نشد.', 'warning')
        return
    if result.get('already_approved'):
        flash(f'{prefix}این شماره قبلاً به‌عنوان همکار تأیید شده است.'.strip(), 'info')
        return
    msg = f'{prefix}همکار تأیید شد'
    n = int(result.get('new_assignments_count') or 0)
    if n:
        msg += f' و {n} فایل انتساب یافت'
    msg += '.'
    if result.get('ref_granted'):
        from app.express_partner.referrals import REFERRAL_BONUS_AMOUNT
        msg += f' پورسانت دعوت ({REFERRAL_BONUS_AMOUNT:,} ت) به موجودی معرف اضافه شد.'
    elif result.get('referred_by_phone'):
        from app.express_partner.referrals import REFERRAL_GRANT_REASONS_FA
        reason_fa = REFERRAL_GRANT_REASONS_FA.get(result.get('ref_skip_reason') or '')
        if reason_fa:
            msg += f' (پورسانت دعوت ثبت نشد: {reason_fa})'
    flash(msg, 'success')


@admin_bp.post('/express/partners/add')
@login_required
def express_partner_add_manual():
    """افزودن دستی همکار و تأیید فوری."""
    back_q = (request.form.get('q') or '').strip()
    back_filter = (request.form.get('filter') or 'all').strip()
    redirect_kw = {'q': back_q, 'filter': back_filter}

    phone = _normalize_phone((request.form.get('phone') or '').strip())
    name = (request.form.get('name') or '').strip()
    city = (request.form.get('city') or '').strip()
    national_id = (request.form.get('national_id') or '').strip()
    referred_by_phone = _normalize_phone((request.form.get('referred_by_phone') or '').strip()) or ''
    send_sms = request.form.get('send_sms') == '1'

    if not phone or len(phone) != 11:
        flash('شماره موبایل معتبر نیست (مثال: 09123456789).', 'warning')
        return redirect(url_for('admin.express_partners', **redirect_kw))
    if not name:
        flash('نام همکار الزامی است.', 'warning')
        return redirect(url_for('admin.express_partners', **redirect_kw))

    if national_id:
        try:
            from app.utils.iran_ids import is_valid_iran_national_id
            if not is_valid_iran_national_id(national_id):
                flash('کد ملی معتبر نیست.', 'warning')
                return redirect(url_for('admin.express_partners', **redirect_kw))
        except Exception:
            pass

    _ensure_site_user_record(phone)

    apps = load_express_partner_apps() or []
    application = None
    for a in apps:
        if not isinstance(a, dict):
            continue
        aph = _normalize_phone(str(a.get('phone') or '')) or str(a.get('phone') or '').strip()
        if aph == phone:
            application = a
            break

    result = _approve_express_partner(
        phone=phone,
        name=name,
        city=city,
        national_id=national_id,
        referred_by_phone=referred_by_phone,
        application=application,
        remove_application=bool(application),
        send_sms=send_sms,
        source='admin_partner_manual_add',
    )
    _flash_partner_approval_result(result, prefix='همکار جدید اضافه شد — ')
    return redirect(url_for('admin.express_partners', **redirect_kw))


@admin_bp.post('/express/partners/<path:phone>/approve')
@login_required
def express_partner_approve_by_phone(phone: str):
    """تأیید همکار با شماره (درخواست معلق، کاربر سایت، یا افزودن دستی از پروفایل)."""
    back_q = (request.form.get('q') or request.args.get('q') or '').strip()
    back_filter = (request.form.get('filter') or request.args.get('filter') or 'all').strip()
    redirect_phone = _normalize_phone(phone) or str(phone or '').strip()
    redirect_kw = {'phone': redirect_phone, 'q': back_q, 'filter': back_filter}
    list_kw = {'q': back_q, 'filter': back_filter}

    if not redirect_phone or len(redirect_phone) != 11:
        flash('شماره موبایل معتبر نیست.', 'warning')
        return redirect(url_for('admin.express_partners', **list_kw))

    person = None
    try:
        person = get_admin_person_by_phone(redirect_phone, **_admin_people_directory_kwargs())
    except Exception:
        current_app.logger.exception('get_admin_person_by_phone failed on approve')

    prof = (person or {}).get('profile') or {}
    app = (person or {}).get('application') or {}
    partner_rec = (person or {}).get('partner') or {}

    name = (request.form.get('name') or prof.get('name') or app.get('name') or partner_rec.get('name') or '').strip()
    city = (request.form.get('city') or prof.get('city') or app.get('city') or partner_rec.get('city') or '').strip()
    national_id = (
        request.form.get('national_id')
        or prof.get('national_id')
        or app.get('national_id')
        or partner_rec.get('national_id')
        or ''
    ).strip()
    referred_by_phone = (
        request.form.get('referred_by_phone')
        or prof.get('referred_by_phone')
        or app.get('referred_by_phone')
        or partner_rec.get('referred_by_phone')
        or ''
    ).strip()

    send_sms = request.form.get('send_sms', '1') == '1'
    _ensure_site_user_record(redirect_phone)

    application = app if isinstance(app, dict) and app.get('id') else None
    if not application:
        for a in load_express_partner_apps() or []:
            if not isinstance(a, dict):
                continue
            aph = _normalize_phone(str(a.get('phone') or '')) or str(a.get('phone') or '').strip()
            if aph == redirect_phone:
                application = a
                break

    result = _approve_express_partner(
        phone=redirect_phone,
        name=name,
        city=city,
        national_id=national_id,
        referred_by_phone=referred_by_phone,
        application=application,
        remove_application=bool(application),
        send_sms=send_sms,
        source='admin_partner_approve_by_phone',
    )

    if (request.headers.get('Accept') or '').lower().find('application/json') >= 0:
        return jsonify(result)

    _flash_partner_approval_result(result)
    next_url = (request.form.get('next') or '').strip()
    if next_url == 'list':
        return redirect(url_for('admin.express_partners', **list_kw))
    return redirect(url_for('admin.express_partner_detail', **redirect_kw))


@admin_bp.post('/express/partners/applications/<int:aid>/approve')
@login_required
def express_partner_application_approve(aid: int):
    apps = load_express_partner_apps() or []
    target = None
    for a in apps:
        try:
            if int(a.get('id', 0)) == int(aid):
                target = a
                break
        except Exception:
            continue
    if not target:
        flash('درخواست یافت نشد.', 'warning')
        return redirect(url_for('admin.express_partners', filter='pending'))

    phone = str(target.get('phone') or '').strip()
    result = _approve_express_partner(
        phone=phone,
        name=(target.get('name') or '').strip(),
        city=(target.get('city') or '').strip(),
        national_id=(target.get('national_id') or '').strip(),
        application=target,
        remove_application=True,
        send_sms=True,
        source='admin_partner_approval',
    )

    if (request.headers.get('Accept') or '').lower().find('application/json') >= 0:
        return jsonify({'ok': True, 'id': int(aid), 'status': 'approved', **result})

    if not result.get('ref_granted') and target.get('referred_by_phone'):
        current_app.logger.warning(
            'Referral commission NOT granted for app id=%s invitee=%s inviter=%s reason=%s',
            aid,
            target.get('phone'),
            target.get('referred_by_phone'),
            result.get('ref_skip_reason') or 'unknown',
        )
    _flash_partner_approval_result(result, prefix='درخواست تأیید شد — ')
    return redirect(url_for('admin.express_partners', filter='pending'))

@admin_bp.post('/express/partners/applications/<int:aid>/reject')
@login_required
def express_partner_application_reject(aid: int):
    apps = load_express_partner_apps() or []
    target = None
    for a in apps:
        try:
            if int(a.get('id', 0)) == int(aid):
                target = a
                break
        except Exception:
            continue
    if not target:
        flash('درخواست یافت نشد.', 'warning')
        return redirect(url_for('admin.express_partners', filter='pending'))

    # وضعیت رد شده را فقط برای ثبت زمان در آبجکت نگه می‌داریم
    target['status'] = 'rejected'
    target['rejected_at'] = iso_z(utcnow())

    try:
        from app.express_partner.referrals import mark_referral_rejected_for_application
        mark_referral_rejected_for_application(target)
    except Exception as ref_err:
        current_app.logger.error('Referral reject on application: %s', ref_err, exc_info=True)

    # بعد از رد شدن، درخواست از لیست درخواست‌ها حذف شود
    try:
        apps = [a for a in apps if int(a.get('id', 0) or 0) != int(aid)]
    except Exception:
        apps = [a for a in apps if a is not target]
    save_express_partner_apps(apps)

    # اعلان به کاربر (با normalize کردن شماره تلفن)
    try:
        phone = str(target.get('phone') or '')
        if phone:
            phone_normalized = _normalize_phone(phone)
            if phone_normalized and len(phone_normalized) == 11:
                add_notification(
                    user_id=phone_normalized,
                    title='رد درخواست همکاری وینور اکسپرس',
                    body='درخواست شما در حال حاضر تأیید نشد.',
                    ntype='warning',
                    action_url=url_for('express_partner.apply', _external=True)
                )
    except Exception as e:
        current_app.logger.error(f"Error sending rejection notification: {e}", exc_info=True)

    if (request.headers.get('Accept') or '').lower().find('application/json') >= 0:
        return jsonify({ 'ok': True, 'id': int(aid), 'status': 'rejected' })
    flash('درخواست رد شد.', 'info')
    return redirect(url_for('admin.express_partners', filter='pending'))


# ─────────────────────────────────────────────────────────────────────────────
# مدیریت شهرهای فعال برای همکاری
# ─────────────────────────────────────────────────────────────────────────────
@admin_bp.route('/express/cities', methods=['GET', 'POST'])
@login_required
def express_cities():
    """مدیریت شهرهای فعال برای درخواست همکاری"""
    cities = load_active_cities() or []
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            from app.utils.iran_cities import is_allowed_service_city
            new_city = (request.form.get('city') or '').strip()
            if new_city and not is_allowed_service_city(new_city):
                flash('فقط شهرهای محدودهٔ سرویس (استان تهران / گرمابسرد دماوند) مجاز است.', 'warning')
            elif new_city and new_city not in cities:
                cities.append(new_city)
                cities.sort()
                save_active_cities(cities)
                flash(f'شهر "{new_city}" اضافه شد.', 'success')
            elif new_city in cities:
                flash('این شهر قبلاً اضافه شده است.', 'warning')

        elif action == 'delete':
            city_to_delete = request.form.get('city')
            if city_to_delete in cities:
                cities.remove(city_to_delete)
                save_active_cities(cities)
                flash(f'شهر "{city_to_delete}" حذف شد.', 'info')

        elif action == 'set_focus':
            from app.utils.iran_cities import FOCUS_SERVICE_CITIES
            save_active_cities(list(FOCUS_SERVICE_CITIES))
            flash('تمرکز سرویس: استان تهران · شهرستان دماوند · روستای گرمابسرد.', 'success')

        elif action == 'add_tehran':
            from app.utils.iran_cities import normalize_active_tehran_cities
            before = len(cities)
            cities = normalize_active_tehran_cities(cities)
            save_active_cities(cities)
            added = len(cities) - before
            flash(f'{added} شهر استان تهران به لیست اضافه شد. (مجموع: {len(cities)})', 'success')

        return redirect(url_for('admin.express_cities'))

    from app.utils.iran_cities import FOCUS_SERVICE_CITIES, TEHRAN_PROVINCE_CITIES
    picker_cities = list(FOCUS_SERVICE_CITIES) + [
        c for c in TEHRAN_PROVINCE_CITIES if c not in FOCUS_SERVICE_CITIES
    ]
    return render_template(
        'admin/express_cities.html',
        cities=cities,
        tehran_cities=picker_cities,
    )
