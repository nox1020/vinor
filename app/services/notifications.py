# -*- coding: utf-8 -*-
"""
Express Partner Notifications Service – سیستم مرکزی مدیریت اعلان‌های همکاران اکسپرس
(سیستم اعلان وینور حذف شد - فقط همکاران اکسپرس از این سیستم استفاده می‌کنند)
"""
import time
import uuid
import os
import json
from typing import List, Dict, Any, Optional
from flask import current_app


def _get_notifications_file_path() -> str:
    """مسیر فایل اعلان‌ها"""
    try:
        app = current_app._get_current_object()
        instance_path = app.instance_path
    except Exception:
        instance_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance')
    
    data_dir = os.path.join(instance_path, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'notifications.json')


def _normalize_user_id(user_id: str) -> str:
    """
    Normalize کردن user_id (شماره تلفن) به فرمت استاندارد 09xxxxxxxxx
    این تابع باید در همه جا استفاده شود تا تطابق کامل باشد.
    """
    if not user_id:
        return ""
    
    # تبدیل به string و حذف فاصله‌ها
    user_id = str(user_id).strip()
    
    # حذف همه کاراکترهای غیرعددی
    import re
    normalized = re.sub(r'\D+', '', user_id)
    
    # تبدیل به فرمت استاندارد 09xxxxxxxxx
    if normalized.startswith('0098') and len(normalized) >= 14:
        normalized = '0' + normalized[4:]
    elif normalized.startswith('98') and len(normalized) >= 12:
        normalized = '0' + normalized[2:]
    elif not normalized.startswith('0') and len(normalized) == 10:
        normalized = '0' + normalized
    
    # اطمینان از طول 11 رقم
    if len(normalized) >= 11:
        return normalized[:11]
    elif len(normalized) == 10:
        return '0' + normalized
    else:
        return normalized


def _load_all() -> Dict[str, List[Dict[str, Any]]]:
    """بارگذاری همه اعلان‌ها از فایل"""
    file_path = _get_notifications_file_path()
    
    if not os.path.exists(file_path):
        return {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        try:
            current_app.logger.error(f"Error loading notifications: {e}")
        except Exception:
            pass
        return {}
    
    # تبدیل به ساختار استاندارد
    if isinstance(raw, dict):
        # Normalize کردن کلیدها و merge کردن کلیدهای تکراری
        normalized_data = {}
        needs_save = False
        for key, value in raw.items():
            normalized_key = _normalize_user_id(key)
            if normalized_key and isinstance(value, list):
                # اگر کلید normalize شده از قبل وجود دارد، merge کن
                if normalized_key in normalized_data:
                    # merge کردن لیست‌ها (حذف تکراری‌ها بر اساس id)
                    existing_ids = {n.get('id') for n in normalized_data[normalized_key] if n.get('id')}
                    new_items = [n for n in value if isinstance(n, dict) and n.get('id') not in existing_ids]
                    normalized_data[normalized_key].extend(new_items)
                    # sort بر اساس created_at (جدیدترین اول)
                    normalized_data[normalized_key].sort(key=lambda x: x.get('created_at', 0), reverse=True)
                    needs_save = True  # اگر merge انجام شد، باید ذخیره شود
                else:
                    normalized_data[normalized_key] = [n for n in value if isinstance(n, dict)]
                    # اگر کلید normalize شده با کلید اصلی متفاوت است، باید ذخیره شود
                    if normalized_key != key:
                        needs_save = True
        
        # اگر تغییراتی انجام شد، ذخیره کن
        if needs_save:
            try:
                _save_all(normalized_data)
            except Exception:
                pass
        
        return normalized_data
    
    # حالت قدیمی: لیست تخت
    if isinstance(raw, list):
        grouped = {}
        for n in raw:
            if not isinstance(n, dict):
                continue
            uid = n.get("user_id") or n.get("uid") or ""
            if uid:
                normalized_uid = _normalize_user_id(uid)
                if normalized_uid:
                    if normalized_uid not in grouped:
                        grouped[normalized_uid] = []
                    grouped[normalized_uid].append(n)
        # ذخیره به فرمت جدید
        if grouped:
            try:
                _save_all(grouped)
            except Exception:
                pass
        return grouped
    
    return {}


def _notifications_invalidate_cache() -> None:
    try:
        from flask import g
        for key in ('_notifications_data_cached', '_notifications_user_items'):
            if hasattr(g, key):
                delattr(g, key)
    except Exception:
        pass


def _load_all_cached() -> Dict[str, List[Dict[str, Any]]]:
    try:
        from flask import g
        cached = getattr(g, '_notifications_data_cached', None)
        if cached is not None:
            return cached
    except Exception:
        pass
    data = _load_all()
    try:
        from flask import g
        g._notifications_data_cached = data
    except Exception:
        pass
    return data


def _resolve_user_items(user_id: str) -> List[Dict[str, Any]]:
    """لیست اعلان‌های یک کاربر — یک‌بار در هر درخواست HTTP."""
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        return []
    try:
        from flask import g
        by_user = getattr(g, '_notifications_user_items', None)
        if by_user is None:
            by_user = {}
            g._notifications_user_items = by_user
        if normalized_user_id in by_user:
            return by_user[normalized_user_id]
    except Exception:
        by_user = None

    data = _load_all_cached()
    items = data.get(normalized_user_id, [])
    if not isinstance(items, list):
        items = []

    if not items:
        found_items_list: List[Dict[str, Any]] = []
        keys_to_remove = []
        for key in data.keys():
            normalized_key = _normalize_user_id(key)
            if normalized_key == normalized_user_id:
                found_items = data.get(key, [])
                if found_items and isinstance(found_items, list):
                    found_items_list.extend(found_items)
                    if key != normalized_user_id:
                        keys_to_remove.append(key)
        if found_items_list:
            seen_ids = set()
            unique_items = []
            for item in found_items_list:
                item_id = item.get('id')
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    unique_items.append(item)
            unique_items.sort(key=lambda x: x.get('created_at', 0), reverse=True)
            items = unique_items
            if items:
                data[normalized_user_id] = items
                for old_key in keys_to_remove:
                    data.pop(old_key, None)
                _save_all(data)

    if by_user is not None:
        by_user[normalized_user_id] = items
    return items


def _save_all(data: Dict[str, List[Dict[str, Any]]]) -> bool:
    """ذخیره همه اعلان‌ها در فایل"""
    file_path = _get_notifications_file_path()
    
    try:
        # Normalize کردن همه کلیدها و merge کردن کلیدهای تکراری
        normalized_data = {}
        for key, value in data.items():
            normalized_key = _normalize_user_id(key)
            if normalized_key and isinstance(value, list):
                # اگر کلید normalize شده از قبل وجود دارد، merge کن
                if normalized_key in normalized_data:
                    # merge کردن لیست‌ها (حذف تکراری‌ها بر اساس id)
                    existing_ids = {n.get('id') for n in normalized_data[normalized_key] if n.get('id')}
                    new_items = [n for n in value if isinstance(n, dict) and n.get('id') not in existing_ids]
                    normalized_data[normalized_key].extend(new_items)
                    # sort بر اساس created_at (جدیدترین اول)
                    normalized_data[normalized_key].sort(key=lambda x: x.get('created_at', 0), reverse=True)
                else:
                    normalized_data[normalized_key] = [n for n in value if isinstance(n, dict)]
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(normalized_data, f, ensure_ascii=False, indent=2)

        _notifications_invalidate_cache()
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"Error saving notifications: {e}", exc_info=True)
        except Exception:
            pass
        return False


def add_notification(user_id: str, title: str, body: str, ntype: str = "info",
                     ad_id: Optional[str] = None, action_url: Optional[str] = None,
                     broadcast_id: Optional[str] = None, source: Optional[str] = None) -> Dict[str, Any]:
    """
    افزودن اعلان جدید برای یک کاربر
    """
    if not user_id:
        raise ValueError("user_id is required")
    
    # Normalize کردن user_id
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id or len(normalized_user_id) != 11:
        raise ValueError(f"Invalid user_id format: {user_id} -> {normalized_user_id}")
    
    # بارگذاری داده‌های موجود
    data = _load_all()
    
    # ایجاد اعلان جدید
    notif = {
        "id": str(uuid.uuid4()),
        "title": str(title).strip(),
        "body": str(body).strip(),
        "type": str(ntype).strip() or "info",
        "created_at": int(time.time()),
        "is_read": False,
        "ad_id": ad_id,
        "action_url": action_url,
        "user_id": normalized_user_id,  # ذخیره user_id normalize شده
    }
    if broadcast_id:
        notif["broadcast_id"] = str(broadcast_id)
    if source:
        notif["source"] = str(source)
    
    # افزودن به لیست اعلان‌های کاربر
    if normalized_user_id not in data:
        data[normalized_user_id] = []
    
    # بررسی اینکه آیا اعلان با همین id قبلاً وجود دارد (جلوگیری از duplicate)
    existing_ids = {n.get('id') for n in data[normalized_user_id] if n.get('id')}
    if notif['id'] not in existing_ids:
        data[normalized_user_id].insert(0, notif)
    
    # محدود کردن تعداد اعلان‌ها (حفظ آخرین 100 اعلان)
    if len(data[normalized_user_id]) > 100:
        data[normalized_user_id] = data[normalized_user_id][:100]
    
    # sort بر اساس created_at (جدیدترین اول)
    data[normalized_user_id].sort(key=lambda x: x.get('created_at', 0), reverse=True)
    
    # ذخیره
    if not _save_all(data):
        raise RuntimeError("Failed to save notification")
    
    # Logging
    try:
        current_app.logger.info(
            f"Notification added: user_id={normalized_user_id}, title={title}, "
            f"total_notifications={len(data[normalized_user_id])}"
        )
    except Exception:
        pass
    
    return notif


def add_notifications_batch(
    user_ids: List[str],
    title: str,
    body: str,
    ntype: str = "info",
    ad_id: Optional[str] = None,
    action_url: Optional[str] = None,
    broadcast_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """افزودن یک اعلان برای چند کاربر — یک بار load/save برای سرعت."""
    if not user_ids:
        return {"success_count": 0, "failed_count": 0, "notification_ids": []}

    data = _load_all()
    now = int(time.time())
    title_s = str(title).strip()
    body_s = str(body).strip()
    type_s = str(ntype).strip() or "info"
    success_count = 0
    failed_count = 0
    notification_ids: List[str] = []

    for raw_uid in user_ids:
        normalized_user_id = _normalize_user_id(raw_uid)
        if not normalized_user_id or len(normalized_user_id) != 11:
            failed_count += 1
            continue
        notif = {
            "id": str(uuid.uuid4()),
            "title": title_s,
            "body": body_s,
            "type": type_s,
            "created_at": now,
            "is_read": False,
            "ad_id": ad_id,
            "action_url": action_url,
            "user_id": normalized_user_id,
        }
        if broadcast_id:
            notif["broadcast_id"] = str(broadcast_id)
        if source:
            notif["source"] = str(source)

        if normalized_user_id not in data:
            data[normalized_user_id] = []
        existing_ids = {n.get("id") for n in data[normalized_user_id] if n.get("id")}
        if notif["id"] not in existing_ids:
            data[normalized_user_id].insert(0, notif)
        if len(data[normalized_user_id]) > 100:
            data[normalized_user_id] = data[normalized_user_id][:100]
        data[normalized_user_id].sort(key=lambda x: x.get("created_at", 0), reverse=True)
        notification_ids.append(notif["id"])
        success_count += 1

    if success_count and not _save_all(data):
        raise RuntimeError("Failed to save batch notifications")

    try:
        current_app.logger.info(
            f"Batch notifications: success={success_count}, failed={failed_count}, "
            f"broadcast_id={broadcast_id or '-'}"
        )
    except Exception:
        pass

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "notification_ids": notification_ids,
    }


def get_user_notifications(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """دریافت اعلان‌های یک کاربر (جدیدترین اول)."""
    if not user_id:
        return []
    items = list(_resolve_user_items(user_id))
    items.sort(key=lambda x: x.get('created_at', 0), reverse=True)
    limit = max(1, int(limit or 50))
    return items[:limit]


def unread_count(user_id: str) -> int:
    """شمارش اعلان‌های خوانده‌نشده — بدون بارگذاری مجدد فایل در همان درخواست."""
    if not user_id:
        return 0
    return sum(1 for n in _resolve_user_items(user_id) if not n.get("is_read", False))


def mark_read(user_id: str, notif_id: str) -> bool:
    """علامت‌گذاری یک اعلان به عنوان خوانده شده"""
    if not user_id or not notif_id:
        return False
    
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        return False
    
    data = _load_all()
    items = data.get(normalized_user_id, [])
    
    # اگر با کلید normalize شده پیدا نشد، بررسی همه کلیدها
    if not isinstance(items, list) or not items:
        for key in data.keys():
            normalized_key = _normalize_user_id(key)
            if normalized_key == normalized_user_id:
                items = data.get(key, [])
                if isinstance(items, list) and items:
                    # به‌روزرسانی data با کلید normalize شده
                    data[normalized_user_id] = items
                    if key != normalized_user_id:
                        # حذف کلید قدیمی
                        data.pop(key, None)
                    break
    
    if not isinstance(items, list):
        return False
    
    found = False
    for n in items:
        if n.get("id") == notif_id:
            n["is_read"] = True
            found = True
            break
    
    if found:
        # اطمینان از اینکه items در data با کلید normalize شده ذخیره شده است
        data[normalized_user_id] = items
        _save_all(data)
        try:
            current_app.logger.info(f"Notification marked as read: user_id={normalized_user_id}, notif_id={notif_id}")
        except Exception:
            pass
    
    return found


def mark_all_read(user_id: str) -> int:
    """علامت‌گذاری همه اعلان‌های یک کاربر به عنوان خوانده شده"""
    if not user_id:
        return 0
    
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        return 0
    
    data = _load_all()
    items = data.get(normalized_user_id, [])
    
    # اگر با کلید normalize شده پیدا نشد، بررسی همه کلیدها
    if not isinstance(items, list) or not items:
        for key in data.keys():
            normalized_key = _normalize_user_id(key)
            if normalized_key == normalized_user_id:
                items = data.get(key, [])
                if isinstance(items, list) and items:
                    # به‌روزرسانی data با کلید normalize شده
                    data[normalized_user_id] = items
                    if key != normalized_user_id:
                        # حذف کلید قدیمی
                        data.pop(key, None)
                    break
    
    if not isinstance(items, list):
        return 0
    
    count = 0
    for n in items:
        if not n.get("is_read", False):
            n["is_read"] = True
            count += 1
    
    if count > 0:
        # اطمینان از اینکه items در data با کلید normalize شده ذخیره شده است
        data[normalized_user_id] = items
        _save_all(data)
        try:
            current_app.logger.info(f"Marked {count} notifications as read for user_id={normalized_user_id}")
        except Exception:
            pass
    
    return count


def get_all_notifications_stats() -> Dict[str, Any]:
    """دریافت آمار کلی اعلان‌ها (برای ادمین)"""
    data = _load_all()
    total_users = len(data)
    total_notifications = sum(len(items) for items in data.values() if isinstance(items, list))
    total_unread = 0
    
    for items in data.values():
        if isinstance(items, list):
            total_unread += sum(1 for n in items if not n.get("is_read", False))
    
    return {
        "total_users": total_users,
        "total_notifications": total_notifications,
        "total_unread": total_unread
    }


def merge_duplicate_keys() -> Dict[str, Any]:
    """
    Merge کردن کلیدهای تکراری (که normalize می‌شوند به یک کلید)
    این تابع باید بعد از تغییرات در normalize کردن اجرا شود
    """
    data = _load_all()
    
    # گروه‌بندی کلیدها بر اساس normalize شده
    normalized_groups = {}
    for key in data.keys():
        normalized_key = _normalize_user_id(key)
        if normalized_key:
            if normalized_key not in normalized_groups:
                normalized_groups[normalized_key] = []
            normalized_groups[normalized_key].append(key)
    
    # merge کردن کلیدهای تکراری
    merged_data = {}
    merged_count = 0
    removed_keys = []
    
    for normalized_key, original_keys in normalized_groups.items():
        if len(original_keys) > 1:
            # چند کلید با normalize یکسان - merge کن
            all_items = []
            for orig_key in original_keys:
                items = data.get(orig_key, [])
                if items:
                    all_items.extend(items)
            
            # حذف تکراری‌ها بر اساس id
            seen_ids = set()
            unique_items = []
            for item in all_items:
                item_id = item.get('id')
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    unique_items.append(item)
            
            # sort بر اساس created_at
            unique_items.sort(key=lambda x: x.get('created_at', 0), reverse=True)
            
            merged_data[normalized_key] = unique_items
            removed_keys.extend([k for k in original_keys if k != normalized_key])
            merged_count += len(original_keys) - 1
        else:
            # فقط یک کلید - بدون تغییر
            merged_data[normalized_key] = data.get(original_keys[0], [])
    
    # ذخیره داده‌های merge شده (حتی اگر merged_count = 0 باشد، برای normalize کردن کلیدها)
    # این اطمینان می‌دهد که همه کلیدها normalize شده‌اند
    if merged_count > 0 or len(merged_data) != len(data):
        _save_all(merged_data)
        try:
            if merged_count > 0:
                current_app.logger.info(f"Merged {merged_count} duplicate keys. Removed {len(removed_keys)} keys: {removed_keys}")
            else:
                current_app.logger.info(f"Normalized all notification keys. Total users: {len(merged_data)}")
        except Exception:
            pass
    
    return {
        "merged_count": merged_count,
        "removed_keys": removed_keys,
        "total_users_before": len(data),
        "total_users_after": len(merged_data)
    }
