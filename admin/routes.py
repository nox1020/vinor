# app/admin/routes.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import re
import random
import uuid
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Dict, Any, Optional

from flask import (
    render_template, request, redirect, url_for,
    session, current_app, flash, abort, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename


# اگر CSRFProtect در app factory فعال است، فقط روی روت لاگین موقتاً معاف می‌کنیم
try:
    from flask_wtf.csrf import csrf  # LocalProxy
except Exception:
    csrf = None

# -----------------------------------------------------------------------------
# اعلان‌ها (Vinor Notifications)
# -----------------------------------------------------------------------------
from app.services.notifications import add_notification

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
from app.api.push import _load_subs, _send_one, _save_subs, send_push_batch_background
from app.express_partner.partner_withdrawals import (
    admin_row_dict,
    admin_can_transition,
    apply_paid_withdrawal_to_commissions,
    link_withdrawal_to_commissions,
    release_withdrawal_commissions,
)
from app.land_category_specs import apply_category_specs_from_form
from app.services.sms import send_sms_template, send_sms_direct, send_sms_code
from app.utils.storage import load_users, load_reports, save_reports, save_ads, load_ads_cached, load_express_lands_cached
from admin.people_directory import build_admin_people_directory, get_admin_person_by_phone
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
    load_support_tickets, save_support_tickets,
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
# ردیابی کاربران آنلاین
# -----------------------------------------------------------------------------
# Dict برای ذخیره اطلاعات کاربران آنلاین
# {session_id: {'timestamp': float, 'username': str, 'ip': str, 'last_activity': str}}
_online_users = {}

def _update_online_user(session_id: str, username: str = None, ip: str = None):
    """به‌روزرسانی timestamp آخرین فعالیت کاربر"""
    if session_id:
        now = datetime.utcnow()
        _online_users[session_id] = {
            'timestamp': now.timestamp(),
            'username': username or session.get('username') or 'کاربر',
            'ip': ip or request.remote_addr or 'نامشخص',
            'last_activity': now.strftime('%Y-%m-%d %H:%M:%S')
        }

def _get_online_users_count() -> int:
    """شمارش کاربران آنلاین (فعال در 5 دقیقه گذشته)"""
    now = datetime.utcnow().timestamp()
    timeout = 5 * 60  # 5 دقیقه
    online = 0
    # پاک‌سازی session‌های منقضی شده
    expired = [sid for sid, data in _online_users.items() if isinstance(data, dict) and (now - data.get('timestamp', 0)) > timeout]
    for sid in expired:
        _online_users.pop(sid, None)
    # شمارش کاربران آنلاین
    for sid, data in _online_users.items():
        if isinstance(data, dict) and (now - data.get('timestamp', 0)) <= timeout:
            online += 1
    return online

def _get_online_users_list() -> List[Dict[str, Any]]:
    """دریافت لیست کاربران آنلاین با اطلاعات کامل"""
    now = datetime.utcnow().timestamp()
    timeout = 5 * 60  # 5 دقیقه
    online_list = []
    # پاک‌سازی session‌های منقضی شده
    expired = [sid for sid, data in _online_users.items() if isinstance(data, dict) and (now - data.get('timestamp', 0)) > timeout]
    for sid in expired:
        _online_users.pop(sid, None)
    # جمع‌آوری کاربران آنلاین
    for sid, data in _online_users.items():
        if isinstance(data, dict) and (now - data.get('timestamp', 0)) <= timeout:
            online_list.append({
                'session_id': sid,
                'username': data.get('username', 'کاربر'),
                'ip': data.get('ip', 'نامشخص'),
                'last_activity': data.get('last_activity', ''),
                'timestamp': data.get('timestamp', 0)
            })
    # مرتب‌سازی بر اساس timestamp (جدیدترین اول)
    online_list.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return online_list

# -----------------------------------------------------------------------------
# ردیابی همکاران آنلاین (Express Partners)
# -----------------------------------------------------------------------------
# Dict برای ذخیره اطلاعات همکاران آنلاین
# {phone: {'timestamp': float, 'name': str, 'ip': str, 'last_activity': str}}
_online_partners = {}

def _update_online_partner(phone: str, name: str = None, ip: str = None):
    """به‌روزرسانی timestamp آخرین فعالیت همکار"""
    if phone:
        now = datetime.utcnow()
        _online_partners[phone] = {
            'timestamp': now.timestamp(),
            'name': name or 'همکار',
            'ip': ip or 'نامشخص',
            'last_activity': now.strftime('%Y-%m-%d %H:%M:%S')
        }

def _get_online_partners_count() -> int:
    """شمارش همکاران آنلاین (فعال در 5 دقیقه گذشته)"""
    now = datetime.utcnow().timestamp()
    timeout = 5 * 60  # 5 دقیقه
    online = 0
    # پاک‌سازی همکاران منقضی شده
    expired = [phone for phone, data in _online_partners.items() if isinstance(data, dict) and (now - data.get('timestamp', 0)) > timeout]
    for phone in expired:
        _online_partners.pop(phone, None)
    # شمارش همکاران آنلاین
    for phone, data in _online_partners.items():
        if isinstance(data, dict) and (now - data.get('timestamp', 0)) <= timeout:
            online += 1
    return online


def _get_online_partners_list() -> List[Dict[str, Any]]:
    """دریافت لیست همکاران آنلاین با اطلاعات کامل"""
    now = datetime.utcnow().timestamp()
    timeout = 5 * 60  # 5 دقیقه
    online_list: List[Dict[str, Any]] = []
    # پاک‌سازی همکاران منقضی شده
    expired = [phone for phone, data in _online_partners.items() if isinstance(data, dict) and (now - data.get('timestamp', 0)) > timeout]
    for phone in expired:
        _online_partners.pop(phone, None)
    # جمع‌آوری همکاران آنلاین
    for phone, data in _online_partners.items():
        if isinstance(data, dict) and (now - data.get('timestamp', 0)) <= timeout:
            online_list.append({
                'phone': phone,
                'name': data.get('name', 'همکار'),
                'ip': data.get('ip', 'نامشخص'),
                'last_activity': data.get('last_activity', ''),
                'timestamp': data.get('timestamp', 0),
            })
    # مرتب‌سازی بر اساس timestamp (جدیدترین اول)
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
        # تنظیمات SMS
        'sms_line_number': '300089930616',  # شماره خط اختصاصی SMS
        # پیام درخواست همکاری (برای همکار)
        'partner_application_sms_message': 'درخواست همکاری شما ثبت شد و در حال بررسی است. وینور',
        # پیام تایید همکاری (برای همکار)
        'partner_approval_sms_message': 'پنل همکاری وینور برای شما فعال شد. وینور',
        # شماره ادمین برای دریافت پیامک درخواست همکاری جدید
        'partner_application_admin_phone': '09121471301',
        # پیامک ارسالی به ادمین هنگام ثبت درخواست همکاری جدید
        'partner_application_admin_sms_message': 'درخواست همکاری جدید همکار در وینور ثبت شد.',
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

# به‌روزرسانی خودکار timestamp کاربران آنلاین در تمام route‌های admin
@admin_bp.before_request
def track_online_user():
    """به‌روزرسانی timestamp آخرین فعالیت کاربر در تمام route‌های admin"""
    if session.get('logged_in'):
        # استفاده از session.sid یا fallback به id(session)
        try:
            session_id = getattr(session, 'sid', None) or session.get('_id') or str(id(session))
        except Exception:
            session_id = str(id(session))
        username = session.get('username') or ADMIN_USERNAME
        ip = request.remote_addr or 'نامشخص'
        _update_online_user(session_id, username, ip)

@admin_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    """
    نکته امنیتی:
    - در تمپلیت admin/login.html حتماً CSRF token بگذارید:
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    - تا قبل از اضافه شدن توکن در فرم، می‌توانید موقتاً این روت را CSRF-exempt کنید.
    """
    # سشن هنوز معتبر است (همان مرورگر/دستگاه، کوکی در مدت PERMANENT_SESSION_LIFETIME)
    if session.get('logged_in'):
        return redirect(url_for('admin.dashboard'))

    now_ts = datetime.utcnow().timestamp()
    last_sent_at = float(session.get('admin_otp_last_sent_at') or 0)
    cooldown_seconds = max(0, ADMIN_OTP_COOLDOWN_SECONDS - int(now_ts - last_sent_at)) if last_sent_at else 0

    def _render_login():
        return render_template(
            'admin/login.html',
            otp_phone=ADMIN_LOGIN_OTP_PHONE,
            otp_cooldown_seconds=max(0, int(cooldown_seconds)),
        )

    # ورود به صفحه لاگین: ارسال خودکار OTP به شماره پیش‌فرض
    if request.method == 'GET':
        if cooldown_seconds == 0:
            code = f"{random.randint(10000, 99999)}"
            sms_result = send_sms_code(ADMIN_LOGIN_OTP_PHONE, code)
            if sms_result.get('ok'):
                session['admin_otp_pending'] = True
                session['admin_otp_code'] = code
                session['admin_otp_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
                session['admin_otp_last_sent_at'] = datetime.utcnow().timestamp()
                cooldown_seconds = ADMIN_OTP_COOLDOWN_SECONDS
                flash('با اشتیاق منتظرتیم', 'info')
            else:
                current_app.logger.error(
                    "Admin login OTP auto-send failed | phone=%s | status=%s | body=%s",
                    ADMIN_LOGIN_OTP_PHONE,
                    sms_result.get('status'),
                    sms_result.get('body'),
                )
                flash('ارسال کد ورود ناموفق بود. صفحه را تازه کنید.', 'danger')
        return _render_login()

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip().lower()
        otp_code = (request.form.get('otp_code') or '').strip()

        if action == 'send':
            if cooldown_seconds > 0:
                flash(f'امکان ارسال مجدد تا {cooldown_seconds} ثانیه دیگر فعال می‌شود.', 'warning')
                return _render_login()
            code = f"{random.randint(10000, 99999)}"
            sms_result = send_sms_code(ADMIN_LOGIN_OTP_PHONE, code)
            if not sms_result.get('ok'):
                flash('ارسال مجدد کد ناموفق بود.', 'danger')
                return _render_login()
            session['admin_otp_pending'] = True
            session['admin_otp_code'] = code
            session['admin_otp_expires_at'] = (datetime.utcnow() + timedelta(hours=1)).timestamp()
            session['admin_otp_last_sent_at'] = datetime.utcnow().timestamp()
            cooldown_seconds = ADMIN_OTP_COOLDOWN_SECONDS
            flash('با اشتیاق منتظرتیم', 'info')
            return _render_login()

        # مرحله ۲: تایید کد پیامکی
        if otp_code:
            expected_code = str(session.get('admin_otp_code') or '')
            expires_at = session.get('admin_otp_expires_at')
            now_ts = datetime.utcnow().timestamp()

            if (not expires_at) or (now_ts > float(expires_at)):
                for k in ('admin_otp_pending', 'admin_otp_code', 'admin_otp_expires_at'):
                    session.pop(k, None)
                flash('کد ورود منقضی شده است. دوباره وارد شوید.', 'warning')
                return _render_login()

            if otp_code == expected_code:
                session['logged_in'] = True
                session['username'] = ADMIN_USERNAME
                session.permanent = True  # ماندگاری session برای PWA
                for k in ('admin_otp_pending', 'admin_otp_code', 'admin_otp_expires_at'):
                    session.pop(k, None)
                flash('خوش آمدید؛ ورود موفق.', 'success')
                return redirect(url_for('admin.dashboard'))

            flash('کد ورود اشتباه است.', 'danger')
            return _render_login()
        flash('کد ورود را وارد کنید.', 'warning')
    return _render_login()

# معافیت موقت CSRF فقط برای لاگین (پس از افزودن توکن، این را حذف کنید)
if csrf is not None:
    admin_bp.view_functions['login'] = csrf.exempt(admin_bp.view_functions['login'])

@admin_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    # فقط کلیدهای ادمین؛ ورود همکار (user_phone) روی همان مرورگر حفظ می‌ماند
    for k in (
        'logged_in',
        'username',
        'admin_otp_pending',
        'admin_otp_code',
        'admin_otp_expires_at',
        'admin_otp_last_sent_at',
    ):
        session.pop(k, None)
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
        return send_from_directory(static_dir, 'admin-manifest.webmanifest', mimetype='application/manifest+json')
    
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
    return Response(json.dumps(fallback, ensure_ascii=False), mimetype='application/manifest+json')

@admin_bp.route('/sw.js')
def admin_service_worker():
    """سرو service worker برای PWA ادمین"""
    from flask import send_from_directory
    import os
    
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    sw_path = os.path.join(static_dir, 'admin-sw.js')
    
    if os.path.exists(sw_path):
        return send_from_directory(static_dir, 'admin-sw.js', mimetype='application/javascript')
    
    return ('// Admin Service Worker not found', 404)

# -----------------------------------------------------------------------------
# داشبورد و صفحات کلی
# -----------------------------------------------------------------------------
@admin_bp.route('/select', endpoint='select_portal')
@login_required
def select_portal():
    """صفحه انتخاب پنل بعد از لاگین: وینور اصلی یا وینور اکسپرس."""
    return render_template('admin/select_portal.html')

@admin_bp.route('', endpoint='admin_root', strict_slashes=False)
@admin_bp.route('/', endpoint='dashboard', strict_slashes=False)
@login_required
def dashboard():
    """داشبورد عملیاتی پنل همکاران."""
    ctx = _admin_dashboard_context()
    return render_template('admin/dashboard.html', **ctx)


def _admin_dashboard_context() -> Dict[str, Any]:
    """آمار و صف اقدام برای داشبورد ادمین."""
    name_map: Dict[str, str] = {}
    try:
        for p in load_express_partners() or []:
            if not isinstance(p, dict):
                continue
            ph = str(p.get('phone') or '').strip()
            if ph:
                name_map[ph] = str(p.get('name') or '').strip()
    except Exception:
        pass

    partners = load_express_partners() or []
    applications = load_express_partner_apps() or []
    assignments = load_express_assignments() or []
    commissions = load_express_commissions() or []
    withdrawals = load_partner_withdrawals() or []
    visits = load_express_visit_requests() or []
    tickets_raw = load_support_tickets() or []

    if not isinstance(partners, list):
        partners = []
    if not isinstance(applications, list):
        applications = []
    if not isinstance(assignments, list):
        assignments = []
    if not isinstance(commissions, list):
        commissions = []
    if not isinstance(withdrawals, list):
        withdrawals = []
    if not isinstance(visits, list):
        visits = []
    if not isinstance(tickets_raw, list):
        tickets_raw = []

    pending_apps = [
        a for a in applications
        if isinstance(a, dict) and str(a.get('status') or '').lower() not in ('approved', 'rejected')
    ]
    pending_commissions = [
        c for c in commissions
        if isinstance(c, dict) and str(c.get('status') or '').lower() == 'pending'
    ]
    pending_withdrawals = [
        w for w in withdrawals
        if isinstance(w, dict) and str(w.get('status') or '').lower() == 'pending'
    ]
    open_withdrawals = [
        w for w in withdrawals
        if isinstance(w, dict) and str(w.get('status') or '').lower() in ('pending', 'approved', 'processing')
    ]
    pending_visits = [
        v for v in visits
        if isinstance(v, dict) and str(v.get('status') or '').lower() == 'pending'
    ]
    open_tickets = [
        t for t in tickets_raw
        if isinstance(t, dict) and str(t.get('status') or '').lower() in ('open', 'in_progress')
    ]
    active_assignments = [
        a for a in assignments
        if isinstance(a, dict)
        and str(a.get('status') or 'active').lower() in ('active', 'assigned', 'open')
    ]

    express_listings_count = 0
    try:
        lands = load_json(_lands_path()) or []
        if isinstance(lands, list):
            express_listings_count = sum(
                1 for l in lands
                if isinstance(l, dict) and l.get('is_express')
            )
    except Exception:
        pass

    online_partners = _get_online_partners_list() or []

    routines_count_month = 0
    try:
        routines = load_partner_routines_cached() or []
        current_month = datetime.now().strftime('%Y-%m')
        routines_count_month = sum(
            1
            for r in routines
            if isinstance(r, dict)
            for d in (r.get('days') or [])
            if isinstance(d, str) and d.startswith(current_month + '-')
        )
    except Exception:
        pass

    def _amount(value: Any) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _ts(row: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            val = str(row.get(key) or '').strip()
            if val:
                return val
        return ''

    action_queue: List[Dict[str, Any]] = []

    for app in pending_apps[:20]:
        ph = str(app.get('phone') or '').strip()
        action_queue.append({
            'kind': 'application',
            'icon': 'fa-user-clock',
            'tone': 'amber',
            'title': (app.get('name') or name_map.get(ph) or ph or 'درخواست همکاری').strip(),
            'meta': 'درخواست همکاری · در انتظار تأیید',
            'url': url_for('admin.express_partners', filter='pending'),
            'ts': _ts(app, 'created_at'),
        })

    for c in pending_commissions[:20]:
        ph = str(c.get('partner_phone') or '').strip()
        action_queue.append({
            'kind': 'commission',
            'icon': 'fa-wallet',
            'tone': 'blue',
            'title': name_map.get(ph) or ph or 'همکار',
            'meta': f"پورسانت {_amount(c.get('commission_amount')):,} ت · کد {c.get('land_code') or '—'}",
            'url': url_for('admin.express_commissions'),
            'ts': _ts(c, 'created_at'),
        })

    for w in pending_withdrawals[:20]:
        ph = str(w.get('phone') or w.get('partner_phone') or '').strip()
        action_queue.append({
            'kind': 'withdrawal',
            'icon': 'fa-money-bill-transfer',
            'tone': 'emerald',
            'title': name_map.get(ph) or ph or 'همکار',
            'meta': f"درخواست برداشت {_amount(w.get('amount')):,} ت",
            'url': url_for('admin.financial_withdrawals', filter='pending'),
            'ts': _ts(w, 'created_at', 'requested_at'),
        })

    for v in pending_visits[:20]:
        ph = str(v.get('partner_phone') or '').strip()
        action_queue.append({
            'kind': 'visit',
            'icon': 'fa-calendar-check',
            'tone': 'indigo',
            'title': (v.get('partner_name') or name_map.get(ph) or ph or 'همکار').strip(),
            'meta': (v.get('land_title') or v.get('land_code') or 'بازدید').strip(),
            'url': url_for('admin.express_visit_requests'),
            'ts': _ts(v, 'visit_date', 'created_at'),
        })

    for t in open_tickets[:20]:
        ph = str(t.get('user_phone') or '').strip()
        subj = (str(t.get('subject') or '')).strip() or 'تیکت پشتیبانی'
        action_queue.append({
            'kind': 'ticket',
            'icon': 'fa-ticket',
            'tone': 'rose',
            'title': (t.get('user_name') or name_map.get(ph) or ph or 'همکار').strip(),
            'meta': subj,
            'url': url_for('admin.support_tickets', filter='open'),
            'ts': _ts(t, 'created_at', 'updated_at'),
        })

    action_queue.sort(key=lambda x: x.get('ts') or '', reverse=True)
    action_queue = action_queue[:12]

    pending_actions_total = (
        len(pending_apps) + len(pending_commissions)
        + len(pending_withdrawals) + len(pending_visits)
        + len(open_tickets)
    )

    online_preview = []
    for o in online_partners[:6]:
        if not isinstance(o, dict):
            continue
        ph = str(o.get('phone') or '').strip()
        online_preview.append({
            'phone': ph,
            'name': (o.get('name') or name_map.get(ph) or ph or 'همکار').strip(),
            'last_activity': o.get('last_activity') or '',
            'url': url_for('admin.express_partner_detail', phone=ph) if ph else url_for('admin.express_partners', filter='online'),
        })

    try:
        _, people_stats = build_admin_people_directory(
            **_admin_people_directory_kwargs(),
            detail_level='summary',
        )
    except Exception:
        people_stats = {'total': 0, 'partners': len(partners), 'online': len(online_partners)}

    return {
        'pending_actions_total': pending_actions_total,
        'pending_apps_count': len(pending_apps),
        'pending_commissions_count': len(pending_commissions),
        'pending_withdrawals_count': len(pending_withdrawals),
        'open_withdrawals_count': len(open_withdrawals),
        'pending_visits_count': len(pending_visits),
        'open_tickets_count': len(open_tickets),
        'pending_commissions_amount': sum(_amount(c.get('commission_amount')) for c in pending_commissions),
        'pending_withdrawals_amount': sum(_amount(w.get('amount')) for w in pending_withdrawals),
        'partners_count': people_stats.get('partners') or len(partners),
        'people_total': people_stats.get('total') or 0,
        'online_partners_count': people_stats.get('online') or len(online_partners),
        'assignments_active_count': len(active_assignments),
        'assignments_total_count': len(assignments),
        'commissions_total_count': len(commissions),
        'express_listings_count': express_listings_count,
        'routines_count_month': routines_count_month,
        'action_queue': action_queue,
        'online_preview': online_preview,
    }


@admin_bp.route('/online-users', endpoint='online_users')
@login_required
def online_users_page():
    """صفحه لیست کاربران آنلاین"""
    online_users = _get_online_users_list()
    return render_template(
        'admin/online_users.html',
        online_users=online_users,
        online_users_count=len(online_users)
    )


@admin_bp.route('/online-partners', endpoint='online_partners')
@login_required
def online_partners_page():
    """صفحه لیست همکاران آنلاین"""
    online_partners = _get_online_partners_list()
    return render_template(
        'admin/online_partners.html',
        online_partners=online_partners,
        online_partners_count=len(online_partners)
    )


@admin_bp.route('/partners/activity', methods=['GET'], endpoint='partners_activity')
@login_required
def partners_activity():
    """فعالیت همکاران → فیلتر آنلاین در لیست یکپارچه."""
    return redirect(url_for('admin.express_partners', filter='online'))

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
    try:
        partners = load_express_partners() or []
    except Exception:
        partners = []
    approved: List[Dict[str, str]] = []
    for p in partners if isinstance(partners, list) else []:
        if not isinstance(p, dict):
            continue
        phone_raw = str(p.get('phone') or '').strip()
        if not phone_raw:
            continue
        phone_normalized = _normalize_phone(phone_raw)
        if phone_normalized and len(phone_normalized) == 11:
            approved.append({
                'phone': phone_normalized,
                'name': str(p.get('name') or p.get('full_name') or phone_normalized).strip(),
            })
    return approved


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

    bid = broadcast_id or str(uuid.uuid4())
    notify_url = '/express/partner/notifications'
    phones = [p['phone'] for p in approved_partners if p.get('phone')]

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

    push_sent = 0
    push_failed = 0
    push_queued = False
    push_targets = 0
    try:
        subs = _load_subs() or []
    except Exception:
        subs = []

    if subs and current_app.config.get('VAPID_PRIVATE_KEY'):
        payload = {
            "title": title,
            "body": body,
            "icon": "/static/icons/icon-192.png",
            "badge": "/static/icons/monochrome-192.png",
            "url": notify_url,
            "sound": "/static/sounds/notify.mp3",
        }
        push_targets = send_push_batch_background(
            payload,
            subs,
            target_phones=phones,
            broadcast_id=bid,
        )
        push_queued = push_targets > 0

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
        source=source,
        broadcast_id=bid,
        admin_user=admin_user,
    )
    if push_queued:
        record['push_queued'] = True
        record['push_targets'] = push_targets

    return {
        'broadcast': record,
        'sent': sent,
        'failed': failed,
        'push_sent': push_sent,
        'push_failed': push_failed,
        'push_queued': push_queued,
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
        subs_for_diag = _load_subs()
    except Exception:
        subs_for_diag = []
    try:
        from app.services.firebase_config import get_firebase_status
        fcm_diag = get_firebase_status()
    except Exception:
        fcm_diag = {}
    push_diag = {
        'has_public': bool(current_app.config.get('VAPID_PUBLIC_KEY')),
        'has_private': bool(current_app.config.get('VAPID_PRIVATE_KEY')),
        'subs_count': len(subs_for_diag or []),
        'tagged_count': sum(1 for s in (subs_for_diag or []) if s.get('user_phone')),
        'fcm_send_ready': bool(fcm_diag.get('send_ready')),
        'fcm_mobile_ready': bool(fcm_diag.get('mobile_ready')),
        'fcm_project_id': fcm_diag.get('project_id'),
    }

    approved_partners = _load_approved_express_partners()

    if request.method == 'POST' and request.form.get('test_action') == 'test':
        from app.services.notifications import (
            get_user_notifications,
            _normalize_user_id,
        )
        test_phone = (request.form.get('test_phone') or '').strip()
        if not test_phone:
            test_error = 'شماره تلفن تست الزامی است.'
        else:
            try:
                normalized = _normalize_user_id(test_phone)
                test_notif = add_notification(
                    user_id=normalized,
                    title="تست اعلان",
                    body="این یک اعلان تستی است برای بررسی سیستم.",
                    ntype="info",
                    source="admin_test",
                )
                notifications = get_user_notifications(normalized, limit=10)
                test_result = {
                    "phone_normalized": normalized,
                    "notification_added": test_notif.get("id") if test_notif else None,
                    "notifications_found": len(notifications),
                }
                test_message = f'تست موفق. اعلان برای {normalized} ثبت شد.'
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
            error = 'هیچ همکاری یافت نشد.'
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
                    message += f' پوش به {result.get("broadcast", {}).get("push_targets", 0)} دستگاه در حال ارسال است.'
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

@admin_bp.route('/sms/colleagues', methods=['GET', 'POST'])
@login_required
def sms_colleagues():
    """ارسال پیامک به تمام همکاران تایید شده"""
    message = None
    error = None
    
    # واکشی همکاران
    try:
        partners = load_express_partners() or []
    except Exception:
        partners = []
    
    # همه همکاران را (به‌جز مواردی که شماره ندارند) فعال در نظر بگیر
    approved_partners = []
    for p in partners if isinstance(partners, list) else []:
        if not isinstance(p, dict):
            continue
        phone_raw = str(p.get('phone') or '').strip()
        if phone_raw:
            phone_normalized = _normalize_for_sms_ir(phone_raw)
            if phone_normalized and len(phone_normalized) == 11:
                approved_partners.append({
                    'phone': phone_normalized,
                    'name': p.get('name') or p.get('full_name') or phone_normalized
                })
    
    if request.method == 'POST':
        send_mode = request.form.get('send_mode', 'template')  # 'template' or 'direct'
        
        if not approved_partners:
            error = 'هیچ همکاری یافت نشد.'
        else:
            sent = 0
            failed = 0
            failed_details = []
            from datetime import datetime
            
            if send_mode == 'direct':
                # حالت ارسال مستقیم
                direct_message = (request.form.get('direct_message') or '').strip()
                line_number_raw = (request.form.get('line_number') or '').strip()
                # استفاده از پیش‌فرض در صورت خالی بودن
                from app.services.sms_config import get_sms_line_number
                line_number = line_number_raw if line_number_raw else get_sms_line_number()
                
                if not direct_message:
                    error = 'متن پیامک الزامی است.'
                else:
                    for partner in approved_partners:
                        try:
                            phone_normalized = partner['phone']
                            if phone_normalized and len(phone_normalized) == 11:
                                current_app.logger.info(f"Sending direct SMS to partner: {partner['name']} ({phone_normalized})")
                                
                                result = send_sms_direct(
                                    mobile=phone_normalized,
                                    message=direct_message,
                                    line_number=line_number
                                )
                                
                                # ذخیره سابقه
                                try:
                                    history = load_sms_history() or []
                                    record = {
                                        'id': len(history) + 1,
                                        'mobile': phone_normalized,
                                        'recipient_name': partner['name'],
                                        'template_id': None,
                                        'message': direct_message,
                                        'parameters': {},
                                        'success': result.get('ok', False),
                                        'status_code': result.get('status', 0),
                                        'response': result.get('body', {}),
                                        'source': 'admin_colleagues_direct',
                                        'created_at': datetime.now().isoformat(),
                                        'error': None if result.get('ok') else str(result.get('body', {}).get('message', 'Unknown error'))
                                    }
                                    history.append(record)
                                    if len(history) > 10000:
                                        history = history[-10000:]
                                    save_sms_history(history)
                                except Exception as hist_err:
                                    current_app.logger.error(f"Failed to save SMS history: {hist_err}")
                                
                                if result.get('ok'):
                                    sent += 1
                                    current_app.logger.info(f"Direct SMS sent successfully to {phone_normalized}")
                                else:
                                    failed += 1
                                    error_msg = result.get('body', {}).get('message', 'Unknown error')
                                    failed_details.append({
                                        'phone': phone_normalized,
                                        'name': partner['name'],
                                        'error': error_msg
                                    })
                                    current_app.logger.error(f"Direct SMS send failed to {phone_normalized}: {error_msg}")
                            else:
                                failed += 1
                                failed_details.append({
                                    'phone': partner.get('phone', 'unknown'),
                                    'name': partner.get('name', 'unknown'),
                                    'error': 'Invalid phone format'
                                })
                        except Exception as e:
                            failed += 1
                            failed_details.append({
                                'phone': partner.get('phone', 'unknown'),
                                'name': partner.get('name', 'unknown'),
                                'error': str(e)
                            })
                            current_app.logger.error(f"Failed to send direct SMS to {partner.get('name', 'unknown')} ({partner.get('phone', 'unknown')}): {e}", exc_info=True)
                    
                    if failed > 0:
                        message = f'پیامک مستقیم به {sent} همکار ارسال شد ({failed} خطا).'
                        if len(failed_details) <= 5:
                            error = 'خطاها: ' + '; '.join([f"{d['name']} ({d['phone']}): {d['error']}" for d in failed_details])
                    else:
                        message = f'پیامک مستقیم با موفقیت به {sent} همکار ارسال شد.'
            
            else:
                # حالت ارسال با قالب
                template_id_raw = (request.form.get('template_id') or '').strip()
                message_text = (request.form.get('message_text') or '').strip()
                
                if not template_id_raw:
                    error = 'شناسه قالب (template_id) الزامی است.'
                else:
                    try:
                        template_id = int(template_id_raw)
                    except ValueError:
                        error = 'شناسه قالب باید یک عدد باشد.'
                        return render_template(
                            'admin/colleagues_sms.html',
                            message=message,
                            error=error,
                            partners_count=len(approved_partners),
                            approved_partners=approved_partners[:10],
                            send_mode=send_mode
                        )
                    
                    # استخراج پارامترها از فرم
                    parameters = {}
                    for k, v in request.form.items():
                        if k.startswith('param_') and k != 'param_key[]' and k != 'param_value[]':
                            param_name = k.replace('param_', '')
                            if param_name and v:
                                parameters[param_name] = v
                    
                    # پشتیبانی از آرایه‌های پارامتر
                    param_keys = request.form.getlist('param_key[]')
                    param_values = request.form.getlist('param_value[]')
                    for i, key in enumerate(param_keys):
                        if key and i < len(param_values):
                            parameters[key.strip()] = param_values[i].strip()
                    
                    # اگر پیام متنی داده شده، از آن به عنوان پارامتر استفاده می‌کنیم
                    if message_text and not parameters:
                        parameters['MESSAGE'] = message_text
                    
                    for partner in approved_partners:
                        try:
                            phone_normalized = partner['phone']
                            if phone_normalized and len(phone_normalized) == 11:
                                current_app.logger.info(f"Sending SMS to partner: {partner['name']} ({phone_normalized})")
                                
                                result = send_sms_template(
                                    mobile=phone_normalized,
                                    template_id=template_id,
                                    parameters=parameters if parameters else None
                                )
                                
                                # ذخیره سابقه
                                try:
                                    history = load_sms_history() or []
                                    record = {
                                        'id': len(history) + 1,
                                        'mobile': phone_normalized,
                                        'recipient_name': partner['name'],
                                        'template_id': template_id,
                                        'parameters': parameters or {},
                                        'success': result.get('ok', False),
                                        'status_code': result.get('status', 0),
                                        'response': result.get('body', {}),
                                        'source': 'admin_colleagues',
                                        'created_at': datetime.now().isoformat(),
                                        'error': None if result.get('ok') else str(result.get('body', {}).get('message', 'Unknown error'))
                                    }
                                    history.append(record)
                                    if len(history) > 10000:
                                        history = history[-10000:]
                                    save_sms_history(history)
                                except Exception as hist_err:
                                    current_app.logger.error(f"Failed to save SMS history: {hist_err}")
                                
                                if result.get('ok'):
                                    sent += 1
                                    current_app.logger.info(f"SMS sent successfully to {phone_normalized}")
                                else:
                                    failed += 1
                                    error_msg = result.get('body', {}).get('message', 'Unknown error')
                                    failed_details.append({
                                        'phone': phone_normalized,
                                        'name': partner['name'],
                                        'error': error_msg
                                    })
                                    current_app.logger.error(f"SMS send failed to {phone_normalized}: {error_msg}")
                            else:
                                failed += 1
                                failed_details.append({
                                    'phone': partner.get('phone', 'unknown'),
                                    'name': partner.get('name', 'unknown'),
                                    'error': 'Invalid phone format'
                                })
                        except Exception as e:
                            failed += 1
                            failed_details.append({
                                'phone': partner.get('phone', 'unknown'),
                                'name': partner.get('name', 'unknown'),
                                'error': str(e)
                            })
                            current_app.logger.error(f"Failed to send SMS to {partner.get('name', 'unknown')} ({partner.get('phone', 'unknown')}): {e}", exc_info=True)
                    
                    if failed > 0:
                        message = f'پیامک به {sent} همکار ارسال شد ({failed} خطا).'
                        if len(failed_details) <= 5:
                            error = 'خطاها: ' + '; '.join([f"{d['name']} ({d['phone']}): {d['error']}" for d in failed_details])
                    else:
                        message = f'پیامک با موفقیت به {sent} همکار ارسال شد.'
    
    # واکشی سابقه ارسال‌ها
    try:
        history = load_sms_history() or []
        # فیلتر سابقه برای همکاران (هم با قالب و هم مستقیم)
        colleagues_history = [h for h in history if h.get('source') in ('admin_colleagues', 'admin_colleagues_direct')]
        # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
        colleagues_history.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination برای سابقه
        history_page = int(request.args.get('history_page', 1))
        history_per_page = 20
        history_total = len(colleagues_history)
        history_start = (history_page - 1) * history_per_page
        history_end = history_start + history_per_page
        paginated_history = colleagues_history[history_start:history_end]
        
        # آمار سابقه
        history_stats = {
            'total': history_total,
            'sent': len([h for h in colleagues_history if h.get('success')]),
            'failed': len([h for h in colleagues_history if not h.get('success')])
        }
    except Exception as e:
        current_app.logger.error(f"Error loading SMS history: {e}")
        paginated_history = []
        history_stats = {'total': 0, 'sent': 0, 'failed': 0}
        history_page = 1
        history_per_page = 20
        history_total = 0
    
    # تعیین حالت پیش‌فرض
    send_mode = request.args.get('mode', 'template')  # 'template' or 'direct'
    if request.method == 'POST':
        send_mode = request.form.get('send_mode', 'template')
    
    return render_template(
        'admin/colleagues_sms.html',
        message=message,
        error=error,
        partners_count=len(approved_partners),
        approved_partners=approved_partners[:10],  # نمایش 10 مورد اول برای پیش‌نمایش
        history=paginated_history,
        history_stats=history_stats,
        history_page=history_page,
        history_per_page=history_per_page,
        history_total=history_total,
        history_total_pages=(history_total + history_per_page - 1) // history_per_page if history_total > 0 else 0,
        send_mode=send_mode
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
        if not test_phone:
            error = 'شماره تلفن تست الزامی است.'
        else:
            try:
                normalized = _normalize_user_id(test_phone)
                
                # افزودن اعلان تست
                test_notif = add_notification(
                    user_id=normalized,
                    title="تست اعلان",
                    body="این یک اعلان تستی است برای بررسی سیستم.",
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

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        defaults = _default_settings()
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

        # تنظیمات SMS
        sms_line_number = (request.form.get('sms_line_number', '').strip()
                           or defaults['sms_line_number'])
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

        # Android APK upload/version
        android_apk_version = (request.form.get('android_apk_version') or '').strip()
        android_apk_url = None
        f = request.files.get('android_apk')
        apk_uploaded = bool(f and f.filename)
        android_apk_size_bytes = None
        android_apk_sha256 = None
        android_apk_original_name = None
        if apk_uploaded:
            try:
                # Validate extension and (approx) size
                fname_lower = f.filename.lower()
                if not fname_lower.endswith('.apk'):
                    raise Exception('BAD_EXT')
                # Max 200MB
                max_bytes = 200 * 1024 * 1024
                content_len = getattr(f, 'content_length', None)
                if content_len and content_len > max_bytes:
                    raise Exception('FILE_TOO_LARGE')
                uploads_root = os.path.join(current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'data', 'uploads'), 'apk')
                os.makedirs(uploads_root, exist_ok=True)
                ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
                safe_name = secure_filename(f"vinor_{ts}.apk")
                dest = os.path.join(uploads_root, safe_name)
                f.save(dest)
                # keep original client filename (sanitized) for download display
                try:
                    android_apk_original_name = secure_filename(f.filename)
                except Exception:
                    android_apk_original_name = None
                # Post-save validations and metadata
                try:
                    android_apk_size_bytes = os.path.getsize(dest)
                except Exception:
                    android_apk_size_bytes = None
                try:
                    import hashlib
                    h = hashlib.sha256()
                    with open(dest, 'rb') as _fp:
                        for chunk in iter(lambda: _fp.read(8192), b''):
                            h.update(chunk)
                    android_apk_sha256 = h.hexdigest()
                except Exception:
                    android_apk_sha256 = None
                # public URL via /uploads/ path
                android_apk_url = f"/uploads/apk/{safe_name}"
            except Exception as e:
                current_app.logger.exception("APK upload failed: %s", e)
                flash('خطا در بارگذاری فایل APK.', 'error')

        # merge with existing settings to preserve APK url when no new file
        current = get_settings()
        if android_apk_url is None:
            android_apk_url = current.get('android_apk_url', '') or ''
        if apk_uploaded and android_apk_url:
            android_apk_updated_at = datetime.utcnow().isoformat() + 'Z'
        else:
            android_apk_updated_at = current.get('android_apk_updated_at') or ''
        if not android_apk_version:
            android_apk_version = current.get('android_apk_version', '') or ''
        if android_apk_original_name is None:
            android_apk_original_name = current.get('android_apk_original_name', '') or ''

        save_settings({
            'approval_method': approval_method,
            'ad_expiry_days': ad_expiry_days,
            'show_submit_button': (request.form.get('show_submit_button') == 'on'),
            'ad_post_price_toman': post_price_toman,
            'sms_line_number': sms_line_number,
            'partner_application_sms_message': partner_application_sms_message,
            'partner_approval_sms_message': partner_approval_sms_message,
            'partner_application_admin_phone': partner_application_admin_phone,
            'partner_application_admin_sms_message': partner_application_admin_sms_message,
            'android_apk_url': android_apk_url,
            'android_apk_version': android_apk_version,
            'android_apk_updated_at': android_apk_updated_at,
            'android_apk_size_bytes': android_apk_size_bytes if android_apk_size_bytes is not None else current.get('android_apk_size_bytes', ''),
            'android_apk_sha256': android_apk_sha256 if android_apk_sha256 is not None else current.get('android_apk_sha256', ''),
            'android_apk_original_name': android_apk_original_name,
        })
        flash('تنظیمات با موفقیت ذخیره شد.', 'success')
        return redirect(url_for('admin.settings'))

    cleanup_expired_ads()
    lands = load_json(_lands_path())
    p, a, r = counts_by_status(lands if isinstance(lands, list) else [])
    settings_data = get_settings()
    return render_template('admin/settings.html',
                           settings=settings_data,
                           pending_count=p, approved_count=a, rejected_count=r)


# -----------------------------------------------------------------------------
# سوالات Vinor AI (ارجاع از چت همکار)
# -----------------------------------------------------------------------------
@admin_bp.route('/ai-questions', methods=['GET', 'POST'], endpoint='ai_questions')
@login_required
def ai_questions():
    from app.ai.escalations import answer_escalation, list_pending_for_admin, list_recent_answered

    if request.method == 'POST':
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
            return render_template('admin/add_land.html',
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
    return render_template('admin/add_land.html',
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
    return render_template('admin/edit_land.html', land=land, land_id=land_index,
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
    pct_raw = extras.get('express_commission_pct', land.get('express_commission_pct'))
    try:
        pct = float(pct_raw) if pct_raw not in (None, '') else 0.0
    except (TypeError, ValueError):
        pct = 0.0
    land['_commission_pct'] = pct

    price_int = _express_land_price_int(land)
    comm_amt = extras.get('express_commission_amount')
    if comm_amt in (None, '') and price_int and pct:
        comm_amt = int(round(price_int * (pct / 100.0)))
    try:
        land['_commission_amount'] = int(comm_amt or 0)
    except (TypeError, ValueError):
        land['_commission_amount'] = 0

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

    express_lands.sort(
        key=lambda l: str(l.get('created_at') or l.get('updated_at') or ''),
        reverse=True,
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
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)

        if cities and city not in cities:
            flash('شهر آگهی باید از بین شهرهای فعال انتخاب شود.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
        
        if len(title) < 10:
            flash('عنوان باید حداقل ۱۰ کاراکتر باشد.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
        
        # تبدیل به عدد
        try:
            size = int(size_clean)
            price_total = int(price_total_clean)
        except (ValueError, TypeError):
            flash('متراژ و قیمت باید عدد معتبر باشند.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
        
        if size <= 0 or price_total <= 0:
            flash('متراژ و قیمت باید بیشتر از صفر باشند.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
        
        # بارگذاری لیست آگهی‌ها برای تولید کد
        lands = load_json(_lands_path())
        if not isinstance(lands, list):
            lands = []
        
        # تولید کد منحصر به فرد
        new_code = form.get("code") or _next_numeric_code(lands)
        
        # ذخیره مدارک
        documents = []
        for key, file in files.items():
            if key.startswith('document_') and file.filename:
                doc_filename = _save_express_document(file, new_code)
                if doc_filename:
                    documents.append(doc_filename)
        
        # پردازش تصاویر (از input multiple)
        images = []
        if 'images' in files:
            from app.utils.images import save_upload_image
            upload_folder = _uploads_root()
            os.makedirs(upload_folder, exist_ok=True)
            for file in files.getlist('images'):
                if file.filename:
                    stored = save_upload_image(file, upload_folder)
                    if stored:
                        images.append(stored)
        
        # کمیسیون همکاران (الزامی)
        pct_raw = (form.get('express_commission_pct') or '').strip()
        if not pct_raw:
            flash('درصد پورسانت الزامی است.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
        try:
            express_commission_pct = float(pct_raw)
            if express_commission_pct <= 0 or express_commission_pct > 100:
                flash('درصد پورسانت باید بین ۰ و ۱۰۰ باشد.', 'error')
                return render_template('admin/add_express_listing.html',
                                      pending_count=0, approved_count=0, rejected_count=0)
        except (ValueError, TypeError):
            flash('درصد پورسانت باید یک عدد معتبر باشد.', 'error')
            return render_template('admin/add_express_listing.html',
                                  pending_count=0, approved_count=0, rejected_count=0,
                                  cities=cities)
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

        # ویدئو (اختیاری)
        video_path = None
        try:
            video_path = _save_video_from_form(files)
        except Exception:
            video_path = None

        # ایجاد آگهی اکسپرس
        payment_method = (form.get('payment_method') or '').strip()
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
            'vinor_contact': form.get('vinor_contact', '09121234567'),
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
    return render_template('admin/add_express_listing.html', cities=cities)

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

    extras = land.get('extras') if isinstance(land.get('extras'), dict) else {}
    commission_pct = extras.get('express_commission_pct', land.get('express_commission_pct', ''))

    def _render_edit(error_category: str = 'error'):
        p, a, r = counts_by_status(lands_list)
        return render_template(
            'admin/edit_express_listing.html',
            land=land,
            pending_count=p,
            approved_count=a,
            rejected_count=r,
            cities=cities,
            commission_pct=commission_pct,
        )

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

        if cities and city not in cities:
            flash('شهر آگهی باید از بین شهرهای فعال انتخاب شود.', 'error')
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
        land['vinor_contact'] = form.get('vinor_contact', '09121234567').strip()
        land['payment_method'] = (form.get('payment_method') or '').strip()

        try:
            if land.get('payment_method') == 'اقساطی':
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

        _apply_express_image_edits(land, form, files)

        for key, file in files.items():
            if key.startswith('document_') and file.filename:
                doc_filename = _save_express_document(file, code)
                if doc_filename:
                    land.setdefault('express_documents', []).append(doc_filename)

        try:
            if (form.get('remove_video') or '').strip():
                old_video = land.get('video')
                if old_video and isinstance(old_video, str):
                    _unlink_stored_upload(old_video)
                land.pop('video', None)
        except Exception:
            pass

        try:
            new_video = _save_video_from_form(files)
            if new_video:
                old_video = land.get('video')
                if old_video and isinstance(old_video, str) and old_video != new_video:
                    _unlink_stored_upload(old_video)
                land['video'] = new_video
        except Exception:
            pass

        apply_category_specs_from_form(land, form)

        save_ads(lands_list)
        flash('آگهی اکسپرس با موفقیت به‌روزرسانی شد.', 'success')
        return redirect(url_for('admin.express_listings'))

    p, a, r = counts_by_status(lands_list)
    return render_template(
        'admin/edit_express_listing.html',
        land=land,
        pending_count=p,
        approved_count=a,
        rejected_count=r,
        cities=cities,
        commission_pct=commission_pct,
    )

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
        people, stats = [], {'total': 0, 'shown': 0, 'partners': 0, 'pending': 0, 'site_users': 0, 'online': 0}
    return render_template(
        'admin/express_partners.html',
        people=people,
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
        if ref_by and (person.get('access') or {}).get('partner_approved'):
            prof['referred_by_phone'] = ref_by
            person['profile'] = prof
            if partner_rec.get('referral_grant_pending'):
                show_referral_retry = True
            else:
                from app.express_partner.referrals import _active_referral_commission_exists
                show_referral_retry = not _active_referral_commission_exists(ref_by, phone)
    except Exception:
        show_referral_retry = False
    return render_template(
        'admin/express_partner_detail.html',
        person=person,
        back_q=back_q,
        back_filter=back_filter,
        page_title=f'پروفایل {display_name}',
        show_referral_retry=show_referral_retry,
    )


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
# Express Assignments (assign lands to partners)
# -----------------------------------------------------------------------------
@admin_bp.route('/express/assignments')
@login_required
def express_assignments():
    try:
        items = load_express_assignments() or []
        if not isinstance(items, list):
            items = []
        items.sort(key=lambda x: x.get('created_at',''), reverse=True)
    except Exception:
        items = []
    # partners list for quick assignment - همه همکاران
    partners = load_express_partners() or []
    # lands pool - همه فایل‌های اکسپرس (بدون فیلتر وضعیت)
    lands = load_json(_lands_path()) or []
    express_pool = [l for l in lands if l.get('is_express', False)]
    return render_template('admin/express_assignments.html', items=items, partners=partners, lands=express_pool)

@admin_bp.post('/express/assignments/new')
@login_required
def express_assignment_new():
    partner_phone = (request.form.get('partner_phone') or '').strip()
    land_code = (request.form.get('land_code') or '').strip()
    commission_pct = (request.form.get('commission_pct') or '').strip()
    try:
        pct = float(commission_pct or '0')
    except Exception:
        pct = 0.0
    
    items = load_express_assignments() or []
    
    # اگر "همه همکاران" انتخاب شده
    if partner_phone == '__ALL__':
        partners = load_express_partners() or []
        count = 0
        for p in partners:
            phone = str(p.get('phone', '')).strip()
            if not phone:
                continue
            # چک کن که قبلاً این فایل به این همکار انتساب نشده باشد
            exists = any(a.get('partner_phone') == phone and a.get('land_code') == land_code for a in items)
            if not exists:
                new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
                items.append({
                    'id': new_id,
                    'partner_phone': phone,
                    'land_code': land_code,
                    'commission_pct': pct,
                    'status': 'active',
                    'created_at': iso_z(utcnow())
                })
                count += 1
        save_express_assignments(items)
        flash(f'فایل به {count} همکار اختصاص یافت.', 'success')
    else:
        new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
        items.append({
            'id': new_id,
            'partner_phone': partner_phone,
            'land_code': land_code,
            'commission_pct': pct,
            'status': 'active',
            'created_at': iso_z(utcnow())
        })
        save_express_assignments(items)
        flash('فایل به همکار اختصاص یافت.', 'success')
    
    return redirect(url_for('admin.express_assignments'))

@admin_bp.post('/express/assignments/<int:aid>/close')
@login_required
def express_assignment_close(aid: int):
    items = load_express_assignments() or []
    changed = False
    for a in items:
        try:
            if int(a.get('id',0) or 0) == int(aid):
                a['status'] = 'closed'
                a['closed_at'] = iso_z(utcnow())
                changed = True
                break
        except Exception:
            continue
    if changed:
        save_express_assignments(items)
        flash('انتساب بسته شد.', 'info')
    return redirect(url_for('admin.express_assignments'))

@admin_bp.post('/express/assignments/clear-all')
@login_required
def express_assignments_clear_all():
    save_express_assignments([])
    flash('همه انتساب‌ها پاک شدند.', 'info')
    return redirect(url_for('admin.express_assignments'))

# -----------------------------------------------------------------------------
# Express Commissions (list/approve/pay)
# -----------------------------------------------------------------------------
def _express_commissions_redirect(filter_hint: str = '') -> str:
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
    )

@admin_bp.post('/express/commissions/new')
@login_required
def express_commission_new():
    partner_phone = (request.form.get('partner_phone') or '').strip()
    land_code = (request.form.get('land_code') or '').strip()
    sale_amount = (request.form.get('sale_amount') or '').strip()
    commission_pct = (request.form.get('commission_pct') or '').strip()
    try:
        sale = int(str(sale_amount).replace(',','').strip() or '0')
    except Exception:
        sale = 0
    try:
        pct = float(commission_pct or '0')
    except Exception:
        pct = 0.0
    commission_amount = int(round(sale * (pct/100.0))) if sale and pct else 0
    items = load_express_commissions() or []
    new_id = (max([int(x.get('id',0) or 0) for x in items if isinstance(x, dict)], default=0) or 0) + 1
    items.append({
        'id': new_id,
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
            reference_id=str(new_id),
        )
    except Exception:
        current_app.logger.exception('commission_pending SMS failed admin new cid=%s', new_id)
    flash('پورسانت ثبت شد (در انتظار تایید).', 'success')
    return redirect(_express_commissions_redirect('pending'))

@admin_bp.post('/express/commissions/<int:cid>/approve')
@login_required
def express_commission_approve(cid: int):
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
        is_referral = str(commission_record.get('commission_type') or '').strip() == 'referral'

        if is_referral:
            try:
                from app.express_partner.referrals import sync_referral_on_commission_status
                sync_referral_on_commission_status(commission_record)
            except Exception as e:
                current_app.logger.error('Referral sync on commission approve: %s', e)

        # تغییر وضعیت فایل به "فروخته شده" در انتساب‌ها (فقط پورسانت فروش ملک)
        if not is_referral:
            try:
                land_code = str(commission_record.get('land_code', ''))
                if land_code and land_code != 'referral':
                    assignments = load_express_assignments() or []
                    for a in assignments:
                        if str(a.get('land_code')) == land_code:
                            a['status'] = 'sold'
                            a['sold_at'] = iso_z(utcnow())
                            a.pop('transaction_holder', None)
                            a.pop('transaction_started_at', None)
                    save_express_assignments(assignments)
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
                        if not is_referral:
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
        else:
            flash('پورسانت تأیید شد، مبلغ به موجودی همکار اضافه شد و فایل فروخته‌شده علامت خورد.', 'success')
    elif not changed:
        flash('پورسانت قبلاً تایید شده است.', 'warning')
    return redirect(_express_commissions_redirect(filter_hint))

@admin_bp.post('/express/commissions/<int:cid>/pay')
@login_required
def express_commission_pay(cid: int):
    flash(
        'واریز پورسانت فقط از مسیر «مالی → درخواست‌های برداشت» انجام می‌شود. '
        'پس از تأیید پورسانت، همکار درخواست برداشت می‌دهد و شما وضعیت را «پرداخت‌شده» می‌کنید.',
        'info',
    )
    return redirect(url_for('admin.financial_withdrawals', filter='pending'))

@admin_bp.post('/express/commissions/<int:cid>/reject')
@login_required
def express_commission_reject(cid: int):
    from app.express_partner.commissions_flow import commission_reject_blocked_reason
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
        is_referral = str(commission_record.get('commission_type') or '').strip() == 'referral'

        if not is_referral and land_code and land_code != 'referral':
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
                            if not is_referral:
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

        flash('پورسانت رد شد.', 'info')
    else:
        flash('فقط پورسانت‌های در انتظار یا تأییدشده قابل رد هستند.', 'warning')
    return redirect(_express_commissions_redirect(filter_hint))

@admin_bp.post('/express/commissions/clear-all')
@login_required
def clear_all_commissions():
    save_express_commissions([])
    flash('همه پورسانت‌ها حذف شدند.', 'info')
    return redirect(url_for('admin.express_commissions'))

@admin_bp.route('/express/commissions/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def express_commission_edit(cid: int):
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
                            
                            # به‌روزرسانی کل فروش‌های تایید شده (تفاوت مبلغ جدید و قدیم)
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


@admin_bp.route('/express/visit-requests', endpoint='express_visit_requests')
@login_required
def express_visit_requests():
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        CANCELLED_STATUS,
        COMPLETED_STATUS,
        PENDING_STATUS,
        admin_row_dict as visit_admin_row,
        admin_visit_status_options,
    )

    flt = (request.args.get('filter') or 'pending').strip().lower()
    items_raw = load_express_visit_requests() or []
    if not isinstance(items_raw, list):
        items_raw = []
    name_map = _partner_name_lookup()
    items = []
    for row in items_raw:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        ph = str(r.get('partner_phone') or '').strip()
        if not (r.get('partner_name') or '').strip() and ph in name_map:
            r['partner_name'] = name_map[ph]
        item = visit_admin_row(r)
        item['status_options'] = admin_visit_status_options(item.get('status'))
        items.append(item)

    pending_count = sum(1 for x in items if x.get('status') == PENDING_STATUS)
    approved_count = sum(1 for x in items if x.get('status') == APPROVED_STATUS)
    done_count = sum(1 for x in items if x.get('status') == COMPLETED_STATUS)
    closed_count = sum(1 for x in items if x.get('status') == CANCELLED_STATUS)
    active_count = pending_count + approved_count

    if flt == 'approved':
        visible = [x for x in items if x.get('status') == APPROVED_STATUS]
    elif flt == 'done':
        visible = [x for x in items if x.get('status') == COMPLETED_STATUS]
    elif flt == 'closed':
        visible = [x for x in items if x.get('status') == CANCELLED_STATUS]
    elif flt == 'active':
        visible = [x for x in items if x.get('status') in (PENDING_STATUS, APPROVED_STATUS)]
    elif flt == 'all':
        visible = items
    else:
        flt = 'pending'
        visible = [x for x in items if x.get('status') == PENDING_STATUS]

    visible.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    visible.sort(key=lambda x: {PENDING_STATUS: 0, APPROVED_STATUS: 1, COMPLETED_STATUS: 2, CANCELLED_STATUS: 3}.get(x.get('status') or '', 9))
    all_count = len(items)

    return render_template(
        'admin/express_visit_requests.html',
        items=visible,
        pending_count=pending_count,
        approved_count=approved_count,
        done_count=done_count,
        closed_count=closed_count,
        active_count=active_count,
        all_count=all_count,
        current_filter=flt,
    )


def _flash_visit_request_status_change(rec: dict, new_status: str) -> None:
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        CANCELLED_STATUS,
        COMPLETED_STATUS,
        PENDING_STATUS,
    )

    name = (rec or {}).get('partner_name') or (rec or {}).get('partner_phone') or 'همکار'
    labels = {
        PENDING_STATUS: 'در انتظار تأیید',
        APPROVED_STATUS: 'تأیید شده',
        COMPLETED_STATUS: 'معامله ثبت شد',
        CANCELLED_STATUS: 'رد شده',
    }
    label = labels.get(new_status, new_status)
    if new_status == APPROVED_STATUS:
        flash(
            f'وضعیت درخواست بازدید {name} به «{label}» تغییر کرد. درخواست معامله برای همکار فعال شد.',
            'success',
        )
    else:
        flash(f'وضعیت درخواست بازدید {name} به «{label}» تغییر کرد.', 'success')


@admin_bp.post('/express/visit-requests/<vid>/status')
@login_required
def express_visit_request_status(vid: str):
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        admin_can_transition_visit,
        admin_update_visit_request_status,
    )
    from app.express_partner.visit_sms import (
        notify_partner_land_tx_sms,
        visit_status_change_event,
    )

    new_status = (request.form.get('status') or '').strip()
    admin_note = (request.form.get('admin_note') or '').strip()
    filter_hint = (request.form.get('filter') or 'pending').strip()
    items = load_express_visit_requests() or []
    if not isinstance(items, list):
        items = []
    prev_status = ''
    for row in items:
        if isinstance(row, dict) and str(row.get('id') or '') == str(vid).strip():
            prev_status = (str(row.get('status') or '')).strip()
            break

    if prev_status and new_status and not admin_can_transition_visit(prev_status, new_status):
        flash('این تغییر وضعیت مجاز نیست. «معامله ثبت شد» فقط پس از درخواست معامله همکار ثبت می‌شود.', 'error')
        return redirect(url_for('admin.express_visit_requests', filter=filter_hint or None))

    rec, err = admin_update_visit_request_status(
        items, vid, new_status, admin_note=admin_note
    )
    if err == 'not_found':
        flash('درخواست بازدید یافت نشد.', 'error')
        return redirect(url_for('admin.express_visit_requests', filter=filter_hint or None))
    if err == 'invalid_status':
        flash('وضعیت انتخاب‌شده نامعتبر است.', 'error')
        return redirect(url_for('admin.express_visit_requests', filter=filter_hint or None))
    if err == 'unchanged':
        flash('تغییری ذخیره نشد. وضعیت یا یادداشت را ویرایش کنید.', 'info')
        return redirect(url_for('admin.express_visit_requests', filter=filter_hint or None))
    try:
        save_express_visit_requests(items)
        if err == 'note_updated':
            flash('یادداشت درخواست بازدید ذخیره شد.', 'success')
        else:
            _flash_visit_request_status_change(rec or {}, new_status)
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
    return redirect(url_for('admin.express_visit_requests', filter=filter_hint or None))


@admin_bp.route('/support/tickets', endpoint='support_tickets')
@login_required
def support_tickets():
    from app.express_partner.support_tickets import (
        OPEN_STATUSES,
        STATUS_LABELS,
        admin_row_dict as ticket_admin_row,
    )

    flt = (request.args.get('filter') or 'open').strip().lower()
    items_raw = load_support_tickets() or []
    if not isinstance(items_raw, list):
        items_raw = []
    name_map = _partner_name_lookup()
    items = []
    for row in items_raw:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        ph = str(r.get('user_phone') or '').strip()
        if not (r.get('user_name') or '').strip() and ph in name_map:
            r['user_name'] = name_map[ph]
        items.append(ticket_admin_row(r))
    items.sort(key=lambda x: (x.get('created_at') or ''), reverse=True)

    if flt == 'open':
        visible = [x for x in items if (x.get('status') or '') in OPEN_STATUSES]
    elif flt == 'closed':
        visible = [x for x in items if (x.get('status') or '') == 'closed']
    elif flt == 'answered':
        visible = [x for x in items if (x.get('status') or '') == 'answered']
    else:
        flt = 'all'
        visible = items

    open_count = sum(1 for x in items if (x.get('status') or '') in OPEN_STATUSES)
    return render_template(
        'admin/support_tickets.html',
        items=visible,
        open_count=open_count,
        current_filter=flt,
        status_labels=STATUS_LABELS,
    )


@admin_bp.post('/support/tickets/<tid>/reply')
@login_required
def support_ticket_reply(tid: str):
    from app.express_partner.support_tickets import (
        STATUS_LABELS,
        admin_update_support_ticket,
    )

    new_status = (request.form.get('status') or '').strip()
    admin_reply = request.form.get('admin_reply')
    filter_hint = (request.form.get('filter') or request.args.get('filter') or 'open').strip()

    items = load_support_tickets() or []
    if not isinstance(items, list):
        items = []
    prev_reply = ''
    for row in items:
        if isinstance(row, dict) and str(row.get('id') or '') == str(tid).strip():
            prev_reply = (str(row.get('admin_reply') or '')).strip()
            break

    rec, err = admin_update_support_ticket(
        items,
        tid,
        new_status=new_status,
        admin_reply=admin_reply,
    )
    if err == 'not_found':
        flash('تیکت یافت نشد.', 'error')
        return redirect(url_for('admin.support_tickets', filter=filter_hint))
    if err == 'invalid_status':
        flash('وضعیت انتخاب‌شده نامعتبر است.', 'error')
        return redirect(url_for('admin.support_tickets', filter=filter_hint))
    if err == 'unchanged':
        flash('تغییری ذخیره نشد. وضعیت یا پاسخ را ویرایش کنید.', 'info')
        return redirect(url_for('admin.support_tickets', filter=filter_hint))

    try:
        save_support_tickets(items)
        st = (str((rec or {}).get('status') or '')).strip()
        label = STATUS_LABELS.get(st, st)
        flash(f'تیکت به‌روزرسانی شد — وضعیت: {label}.', 'success')

        reply_text = (str((rec or {}).get('admin_reply') or '')).strip()
        partner_phone = str((rec or {}).get('user_phone') or '').strip()
        if reply_text and reply_text != prev_reply and partner_phone:
            try:
                add_notification(
                    user_id=partner_phone,
                    title='پاسخ پشتیبانی',
                    body=(reply_text[:200] + '…') if len(reply_text) > 200 else reply_text,
                    ntype='info',
                    action_url=url_for('express_partner.support'),
                    source='support_ticket',
                )
            except Exception:
                current_app.logger.exception('support ticket partner notification failed tid=%s', tid)
    except Exception:
        flash('خطا در ذخیره تیکت.', 'error')
    return redirect(url_for('admin.support_tickets', filter=filter_hint))


def _financial_withdrawals_redirect(filter_hint: str = '') -> str:
    flt = (filter_hint or request.form.get('filter') or request.args.get('filter') or 'active').strip()
    if flt:
        return url_for('admin.financial_withdrawals', filter=flt)
    return url_for('admin.financial_withdrawals')


@admin_bp.post('/financial/withdrawals/<wid>/status')
@login_required
def financial_withdrawal_status(wid: str):
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
    except Exception:
        current_app.logger.exception('save_partner_withdrawals status failed')
        flash('خطا در ذخیره.', 'error')

    return redirect(_financial_withdrawals_redirect(filter_hint))

# -----------------------------------------------------------------------------
# Express Partner Files (upload/list/download/delete by admin)
# -----------------------------------------------------------------------------
@admin_bp.route('/express/partner-files', methods=['GET', 'POST'])
@login_required
def express_partner_files():
    partners = load_express_partners() or []
    # Upload handler
    if request.method == 'POST':
        partner_phone = (request.form.get('partner_phone') or '').strip()
        f = request.files.get('file')
        if partner_phone and f and f.filename:
            base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', partner_phone)
            os.makedirs(base, exist_ok=True)
            tsname = datetime.now().strftime('%Y%m%d%H%M%S%f') + "__" + secure_filename(f.filename)
            path = os.path.join(base, tsname)
            f.save(path)
            metas = load_partner_files_meta() or []
            new_id = (max([int(x.get('id',0) or 0) for x in metas if isinstance(x, dict)], default=0) or 0) + 1
            metas.append({
                'id': new_id,
                'phone': partner_phone,
                'filename': tsname,
                'stored_at': datetime.now().isoformat() + 'Z'
            })
            save_partner_files_meta(metas)
            flash('فایل بارگذاری شد.', 'success')
            return redirect(url_for('admin.express_partner_files', partner=partner_phone))

    # List
    try:
        partner_filter = (request.args.get('partner') or '').strip()
    except Exception:
        partner_filter = ''
    items = load_partner_files_meta() or []
    if partner_filter:
        items = [m for m in items if str(m.get('phone')) == partner_filter]
    try:
        items.sort(key=lambda x: x.get('stored_at',''), reverse=True)
    except Exception:
        pass
    return render_template('admin/express_partner_files.html', partners=partners, items=items, partner_filter=partner_filter)


@admin_bp.get('/express/partner-files/<int:fid>/download')
@login_required
def express_partner_file_download(fid: int):
    metas = load_partner_files_meta() or []
    meta = next((m for m in metas if int(m.get('id',0) or 0) == int(fid)), None)
    if not meta:
        abort(404)
    phone = str(meta.get('phone') or '').strip()
    base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', phone)
    fp = os.path.join(base, meta.get('filename') or '')
    if not os.path.isfile(fp):
        abort(404)
    return send_from_directory(base, os.path.basename(fp), as_attachment=True)


@admin_bp.post('/express/partner-files/<int:fid>/delete')
@login_required
def express_partner_file_delete(fid: int):
    metas = load_partner_files_meta() or []
    kept = []
    removed = None
    for m in metas:
        try:
            if int(m.get('id',0) or 0) == int(fid):
                removed = m
            else:
                kept.append(m)
        except Exception:
            kept.append(m)
    save_partner_files_meta(kept)
    if removed:
        try:
            phone = str(removed.get('phone') or '').strip()
            base = os.path.join(current_app.instance_path, 'data', 'uploads', 'partner', phone)
            fp = os.path.join(base, removed.get('filename') or '')
            if os.path.isfile(fp):
                os.remove(fp)
        except Exception:
            pass
    flash('فایل حذف شد.', 'info')
    return redirect(url_for('admin.express_partner_files', partner=request.args.get('partner') or ''))

@admin_bp.post('/express/partners/applications/<int:aid>/approve')
@login_required
def express_partner_application_approve(aid: int):
    apps = load_express_partner_apps() or []
    partners = load_express_partners() or []
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

    # به فهرست همکاران منتقل و وضعیت را تنظیم کن
    phone = str(target.get('phone') or '').strip()
    name = (target.get('name') or '').strip()
    city = (target.get('city') or '').strip()
    partner = next((p for p in partners if str(p.get('phone')) == phone), None)
    if not partner:
        partner = {
            'id': (max([int(x.get('id',0) or 0) for x in partners], default=0) or 0) + 1,
            'name': name,
            'phone': phone,
            'city': city,
            'status': 'approved',
            'created_at': iso_z(utcnow()),
        }
        partners.append(partner)
    else:
        partner.update({'name': name or partner.get('name'), 'city': city or partner.get('city'), 'status': 'approved'})

    # وضعیت درخواست (برای لاگ‌کردن قبل از حذف)
    target['status'] = 'approved'
    target['approved_at'] = iso_z(utcnow())
    ref_by = (target.get('referred_by_phone') or '').strip()
    if ref_by:
        try:
            from app.express_partner.referrals import _normalize_phone as _ref_norm_phone
            partner['referred_by_phone'] = _ref_norm_phone(ref_by) or ref_by
        except Exception:
            partner['referred_by_phone'] = ref_by
        try:
            partner['referral_application_id'] = int(target.get('id') or 0)
        except Exception:
            pass

    save_express_partners(partners)

    ref_granted = False
    ref_skip_reason = None
    try:
        from app.express_partner.referrals import (
            REFERRAL_GRANT_REASONS_FA,
            grant_referral_commission_for_application,
        )
        ref_granted, ref_skip_reason = grant_referral_commission_for_application(target)
    except Exception as ref_err:
        current_app.logger.error('Referral commission on application approve: %s', ref_err, exc_info=True)
        ref_skip_reason = 'exception'

    if ref_by:
        if ref_granted:
            partner.pop('referral_grant_pending', None)
        else:
            partner['referral_grant_pending'] = True
        save_express_partners(partners)

    # بعد از تایید، خود درخواست از لیست درخواست‌ها حذف شود
    try:
        apps = [a for a in apps if int(a.get('id', 0) or 0) != int(aid)]
    except Exception:
        apps = [a for a in apps if a is not target]
    save_express_partner_apps(apps)

    # انتساب خودکار همه فایل‌های اکسپرس به همکار جدید
    try:
        lands = load_json(_lands_path()) or []
        express_lands = [l for l in lands if l.get('is_express', False)]
        assignments = load_express_assignments() or []
        
        # فایل‌هایی که قبلاً به این همکار انتساب نشده‌اند
        existing_codes = {a.get('land_code') for a in assignments if a.get('partner_phone') == phone}
        new_assignments_count = 0
        
        for land in express_lands:
            land_code = land.get('code')
            if land_code and land_code not in existing_codes:
                new_id = (max([int(x.get('id', 0) or 0) for x in assignments if isinstance(x, dict)], default=0) or 0) + 1
                assignments.append({
                    'id': new_id,
                    'partner_phone': phone,
                    'land_code': land_code,
                    'commission_pct': 2.0,  # درصد پیش‌فرض
                    'status': 'active',
                    'created_at': iso_z(utcnow())
                })
                new_assignments_count += 1
        
        if new_assignments_count > 0:
            save_express_assignments(assignments)
    except Exception as e:
        current_app.logger.error(f"Error auto-assigning lands to partner: {e}")

    # اعلان به کاربر (با normalize کردن شماره تلفن)
    try:
        if phone:
            phone_normalized = _normalize_phone(phone)
            if phone_normalized and len(phone_normalized) == 11:
                add_notification(
                    user_id=phone_normalized,
                    title='تأیید همکاری وینور اکسپرس',
                    body='درخواست شما تأیید شد. اکنون می‌توانید از پنل همکاری استفاده کنید.',
                    ntype='success',
                    action_url=url_for('express_partner.dashboard', _external=True)
                )
    except Exception as e:
        current_app.logger.error(f"Error sending approval notification: {e}", exc_info=True)

    # ارسال پیامک تایید همکاری
    try:
        if phone and len(phone) == 11 and phone.startswith('09'):
            settings = get_settings()
            sms_message = settings.get('partner_approval_sms_message', 'پنل همکاری وینور برای شما فعال شد. وینور')
            sms_line_number = settings.get('sms_line_number', '300089930616')
            
            # اگر پیام خالی است، از پیش‌فرض استفاده کن
            if not sms_message or not sms_message.strip():
                sms_message = 'پنل همکاری وینور برای شما فعال شد. وینور'
            
            current_app.logger.info(f"Sending approval SMS to partner: {name} ({phone})")
            
            sms_result = send_sms_direct(
                mobile=phone,
                message=sms_message,
                line_number=sms_line_number
            )
            
            # ذخیره سابقه ارسال پیامک
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
                    'source': 'admin_partner_approval',
                    'created_at': datetime.now().isoformat(),
                    'error': None if sms_result.get('ok') else str(sms_result.get('body', {}).get('message', 'Unknown error'))
                }
                history.append(record)
                if len(history) > 10000:
                    history = history[-10000:]
                save_sms_history(history)
            except Exception as hist_err:
                current_app.logger.error(f"Failed to save SMS history: {hist_err}")
            
            if sms_result.get('ok'):
                current_app.logger.info(f"✅ Partner approval SMS sent successfully to {phone}")
            else:
                current_app.logger.error(f"❌ Failed to send partner approval SMS to {phone}. Status: {sms_result.get('status')}, Body: {sms_result.get('body')}")
    except Exception as sms_err:
        current_app.logger.error(f"Error sending partner approval SMS: {sms_err}", exc_info=True)

    if (request.headers.get('Accept') or '').lower().find('application/json') >= 0:
        return jsonify({ 'ok': True, 'id': int(aid), 'status': 'approved' })
    msg = f'درخواست تأیید شد و {new_assignments_count} فایل به همکار انتساب یافت.'
    if ref_granted:
        from app.express_partner.referrals import REFERRAL_BONUS_AMOUNT
        msg += f' پورسانت دعوت ({REFERRAL_BONUS_AMOUNT:,} ت) به موجودی معرف اضافه شد.'
    elif target.get('referred_by_phone'):
        from app.express_partner.referrals import REFERRAL_GRANT_REASONS_FA
        reason_fa = REFERRAL_GRANT_REASONS_FA.get(ref_skip_reason or '')
        current_app.logger.warning(
            'Referral commission NOT granted for app id=%s invitee=%s inviter=%s reason=%s',
            aid,
            target.get('phone'),
            target.get('referred_by_phone'),
            ref_skip_reason or 'unknown',
        )
        if reason_fa:
            msg += f' (پورسانت دعوت ثبت نشد: {reason_fa})'
        else:
            msg += ' (پورسانت دعوت ثبت نشد — لاگ سرور را بررسی کنید.)'
    flash(msg, 'success')
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
            new_city = (request.form.get('city') or '').strip()
            if new_city and new_city not in cities:
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
        
        return redirect(url_for('admin.express_cities'))
    
    return render_template('admin/express_cities.html', cities=cities)
