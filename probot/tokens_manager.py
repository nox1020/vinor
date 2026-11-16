# -*- coding: utf-8 -*-
"""
ماژول مدیریت توکن‌ها در فایل JSON
ساختار جدید: هر توکن با وضعیت (pending, success, failed) ذخیره می‌شود
"""

import json
import os
import threading
import copy
from datetime import datetime, timedelta

from .paths import data_path

TOKENS_JSON_FILE = data_path("tokens.json")

# Cache برای JSON - بهبود performance
_tokens_cache = {}
_cache_lock = threading.Lock()
_cache_last_modified = None
_cache_ttl = timedelta(seconds=5)  # Cache برای 5 ثانیه معتبر است
_STATUS_ORDER = ("pending", "success", "failed")
_STATUS_PRIORITY = {"pending": 1, "failed": 2, "success": 3}


def _deepcopy_tokens_data(tokens_data):
    """کپی عمیق امن از داده‌های توکن"""
    return copy.deepcopy(tokens_data)


def _write_json_file(data):
    """نوشتن اتمیک JSON برای کاهش ریسک خراب شدن فایل"""
    temp_file = f"{TOKENS_JSON_FILE}.tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, TOKENS_JSON_FILE)


def _normalize_tokens_data(tokens_data):
    """
    نرمال‌سازی داده‌ها:
    - هر توکن در هر chatid فقط یک‌بار ذخیره شود.
    - اولویت وضعیت: success > failed > pending
    - حذف تکراری‌ها داخل هر لیست.
    """
    normalized = {}
    changed = False

    for chatid, phones in tokens_data.items():
        normalized[chatid] = {}
        token_owner = {}  # token -> (phone, status)

        # مرحله 1: انتخاب مالک نهایی هر توکن با توجه به اولویت وضعیت
        for phone in sorted(phones.keys(), key=lambda x: str(x)):
            status_dict = phones.get(phone, {})
            if not isinstance(status_dict, dict):
                status_dict = {"pending": status_dict if isinstance(status_dict, list) else [], "success": [], "failed": []}
                changed = True

            for status in _STATUS_ORDER:
                seen_local = set()
                for token in status_dict.get(status, []):
                    if not token or token in seen_local:
                        changed = True
                        continue
                    seen_local.add(token)

                    if token not in token_owner:
                        token_owner[token] = (phone, status)
                    else:
                        prev_phone, prev_status = token_owner[token]
                        prev_priority = _STATUS_PRIORITY.get(prev_status, 0)
                        cur_priority = _STATUS_PRIORITY.get(status, 0)
                        if cur_priority > prev_priority:
                            token_owner[token] = (phone, status)
                            changed = True
                        elif cur_priority == prev_priority and prev_phone != phone:
                            # در وضعیت هم‌اولویت، اولین مالک حفظ می‌شود
                            changed = True

        # مرحله 2: بازسازی ساختار نهایی بدون تداخل
        for phone in phones.keys():
            normalized[chatid][phone] = {"pending": [], "success": [], "failed": []}

        for token, (phone, status) in token_owner.items():
            if phone not in normalized[chatid]:
                normalized[chatid][phone] = {"pending": [], "success": [], "failed": []}
            normalized[chatid][phone][status].append(token)

    return normalized, changed

def _create_empty_json_file():
    """ایجاد فایل JSON خالی"""
    try:
        data = {}
        _write_json_file(data)
        print(f"✅ فایل {TOKENS_JSON_FILE} ایجاد شد.")
        return True
    except Exception as e:
        print(f"❌ خطا در ایجاد فایل {TOKENS_JSON_FILE}: {e}")
        import traceback
        traceback.print_exc()
        return False

def _migrate_old_format_to_new(data):
    """تبدیل ساختار قدیمی به ساختار جدید"""
    try:
        migrated = {}
        for chatid_str, phones in data.items():
            chatid_int = int(chatid_str)
            migrated[chatid_int] = {}
            
            for phone_str, tokens in phones.items():
                phone_int = int(phone_str)
                
                # اگر tokens یک لیست ساده است (ساختار قدیمی)
                if isinstance(tokens, list):
                    # همه توکن‌های قدیمی را به pending تبدیل می‌کنیم
                    migrated[chatid_int][phone_int] = {
                        "pending": tokens,
                        "success": [],
                        "failed": []
                    }
                # اگر tokens یک دیکشنری است (ساختار جدید)
                elif isinstance(tokens, dict):
                    # اطمینان از وجود همه کلیدها
                    migrated[chatid_int][phone_int] = {
                        "pending": tokens.get("pending", []),
                        "success": tokens.get("success", []),
                        "failed": tokens.get("failed", [])
                    }
        
        return migrated
    except Exception as e:
        print(f"⚠️ خطا در تبدیل ساختار قدیمی: {e}")
        return data

def load_tokens_json(force_reload=False):
    """بارگذاری توکن‌ها از فایل JSON با cache"""
    global _tokens_cache, _cache_last_modified
    
    with _cache_lock:
        # بررسی cache
        if not force_reload and _tokens_cache and _cache_last_modified:
            # بررسی اینکه آیا فایل تغییر کرده است
            try:
                file_mtime = os.path.getmtime(TOKENS_JSON_FILE) if os.path.exists(TOKENS_JSON_FILE) else 0
                file_modified = datetime.fromtimestamp(file_mtime)
                
                # اگر cache معتبر است و فایل تغییر نکرده
                if datetime.now() - _cache_last_modified < _cache_ttl and file_modified <= _cache_last_modified:
                    return _deepcopy_tokens_data(_tokens_cache)  # برگرداندن کپی عمیق برای جلوگیری از تغییر cache
            except:
                pass  # در صورت خطا، از دیسک بخوان
        
        # بارگذاری از دیسک
        try:
            if os.path.exists(TOKENS_JSON_FILE):
                with open(TOKENS_JSON_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # تبدیل کلیدهای string به int برای سازگاری
                    result = {}
                    for chatid_str, phones in data.items():
                        chatid_int = int(chatid_str)
                        result[chatid_int] = {}
                        for phone_str, tokens in phones.items():
                            phone_int = int(phone_str)
                            result[chatid_int][phone_int] = tokens
                    
                    # تبدیل ساختار قدیمی به جدید (اگر لازم باشد)
                    result = _migrate_old_format_to_new(result)
                    # نرمال‌سازی برای جلوگیری از تداخل وضعیت‌ها/تکراری‌ها
                    result, changed = _normalize_tokens_data(result)
                    if changed:
                        # ذخیرهٔ خودکار نسخهٔ نرمال‌شده روی دیسک
                        serializable = {
                            str(cid): {str(ph): sd for ph, sd in phones.items()}
                            for cid, phones in result.items()
                        }
                        _write_json_file(serializable)
                    
                    # به‌روزرسانی cache
                    _tokens_cache = result
                    _cache_last_modified = datetime.now()
                    
                    return _deepcopy_tokens_data(result)  # برگرداندن کپی عمیق
            else:
                # اگر فایل وجود ندارد، یک فایل خالی ایجاد کن
                print(f"ℹ️ فایل {TOKENS_JSON_FILE} وجود ندارد. فایل خالی ایجاد می‌شود.")
                _create_empty_json_file()
                _tokens_cache = {}
                _cache_last_modified = datetime.now()
                return {}
        except Exception as e:
            print(f"❌ خطا در بارگذاری tokens.json: {e}")
            import traceback
            traceback.print_exc()
            # [audit] قبل از خالی کردن، نسخهٔ خراب را نگه دار (قبلاً همهٔ صف آگهی‌ها بی‌صدا پاک می‌شد)
            try:
                if os.path.exists(TOKENS_JSON_FILE):
                    import shutil
                    bak = f"{TOKENS_JSON_FILE}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    shutil.copy2(TOKENS_JSON_FILE, bak)
                    print(f"⚠️ نسخهٔ خراب tokens.json در {bak} ذخیره شد.")
            except Exception:
                pass
            _create_empty_json_file()
            _tokens_cache = {}
            _cache_last_modified = datetime.now()
            return {}

def save_tokens_json(tokens_data):
    """ذخیره توکن‌ها در فایل JSON - اگر فایل وجود نداشت، ایجاد می‌شود"""
    global _tokens_cache, _cache_last_modified
    
    with _cache_lock:
        try:
            # نرمال‌سازی برای جلوگیری از تداخل وضعیت‌ها قبل از ذخیره
            tokens_data, _ = _normalize_tokens_data(tokens_data)

            # تبدیل کلیدهای int به string برای JSON
            data = {}
            for chatid, phones in tokens_data.items():
                data[str(chatid)] = {}
                for phone, status_dict in phones.items():
                    data[str(chatid)][str(phone)] = status_dict
            
            # اگر data خالی است، یک ساختار خالی ایجاد کن
            if not data:
                data = {}
            
            # ایجاد فایل JSON (حتی اگر خالی باشد) - اگر وجود نداشت، خودکار ایجاد می‌شود
            _write_json_file(data)
            
            # به‌روزرسانی cache
            _tokens_cache = _deepcopy_tokens_data(tokens_data)
            _cache_last_modified = datetime.now()
            
            # بررسی اینکه فایل واقعاً ایجاد شده است
            if os.path.exists(TOKENS_JSON_FILE):
                print(f"✅ فایل {TOKENS_JSON_FILE} با موفقیت ذخیره شد.")
            else:
                print(f"⚠️ فایل {TOKENS_JSON_FILE} ایجاد نشد!")
        except Exception as e:
            print(f"❌ خطا در ذخیره tokens.json: {e}")
            import traceback
            traceback.print_exc()
            # [audit] در خطای ذخیره، فایل موجود را خالی نکن (قبلاً کل صف آگهی‌ها پاک می‌شد)

def invalidate_cache():
    """باطل کردن cache - برای استفاده در صورت نیاز به reload فوری"""
    global _tokens_cache, _cache_last_modified
    with _cache_lock:
        _tokens_cache = {}
        _cache_last_modified = None

def add_tokens_to_json(chatid, phone, tokens):
    """اضافه کردن توکن‌ها به JSON با وضعیت pending"""
    try:
        print(f"📝 [add_tokens_to_json] شروع: chatid={chatid}, phone={phone}, تعداد توکن‌ها={len(tokens)}")
        
        tokens_data = load_tokens_json()
        print(f"📝 [add_tokens_to_json] داده‌های موجود: {len(tokens_data)} chatid")
        
        if chatid not in tokens_data:
            tokens_data[chatid] = {}
            print(f"📝 [add_tokens_to_json] chatid جدید اضافه شد: {chatid}")
        
        if phone not in tokens_data[chatid]:
            tokens_data[chatid][phone] = {
                "pending": [],
                "success": [],
                "failed": []
            }
            print(f"📝 [add_tokens_to_json] phone جدید اضافه شد: {phone}")
        
        # دریافت تمام توکن‌های موجود (از همه وضعیت‌ها)
        all_existing = set(tokens_data[chatid][phone]["pending"] + 
                          tokens_data[chatid][phone]["success"] + 
                          tokens_data[chatid][phone]["failed"])
        
        # اضافه کردن فقط توکن‌های جدید (غیر تکراری) به pending
        new_tokens = [t for t in tokens if t not in all_existing]
        tokens_data[chatid][phone]["pending"].extend(new_tokens)
        
        print(f"📝 [add_tokens_to_json] {len(new_tokens)} توکن جدید اضافه شد (از {len(tokens)} توکن)")
        
        save_tokens_json(tokens_data)
        print(f"✅ [add_tokens_to_json] توکن‌ها با موفقیت ذخیره شدند")
        
        return len(new_tokens)
    except Exception as e:
        print(f"❌ [add_tokens_to_json] خطا: {e}")
        import traceback
        traceback.print_exc()
        return 0

def update_token_status(chatid, phone, token, new_status):
    """به‌روزرسانی وضعیت یک توکن (pending -> success/failed)"""
    try:
        tokens_data = load_tokens_json()
        
        if chatid not in tokens_data or phone not in tokens_data[chatid]:
            print(f"⚠️ توکن {token} یافت نشد برای به‌روزرسانی")
            return False
        
        status_dict = tokens_data[chatid][phone]
        
        # حذف توکن از وضعیت قبلی
        removed = False
        for status in ["pending", "success", "failed"]:
            if token in status_dict[status]:
                status_dict[status].remove(token)
                removed = True
                break
        
        if not removed:
            print(f"⚠️ توکن {token} در هیچ وضعیتی یافت نشد")
            return False
        
        # اضافه کردن توکن به وضعیت جدید
        if new_status in ["pending", "success", "failed"]:
            status_dict[new_status].append(token)
            save_tokens_json(tokens_data)
            print(f"✅ توکن {token} به وضعیت {new_status} تغییر یافت")
            return True
        else:
            print(f"❌ وضعیت نامعتبر: {new_status}")
            return False
            
    except Exception as e:
        print(f"❌ خطا در به‌روزرسانی وضعیت توکن: {e}")
        import traceback
        traceback.print_exc()
        return False

def remove_token_from_json(chatid, phone, token):
    """حذف یک توکن از JSON - DEPRECATED: استفاده از update_token_status به جای این"""
    # برای سازگاری با کد قدیمی، این تابع وضعیت را به success تغییر می‌دهد
    return update_token_status(chatid, phone, token, "success")

def get_tokens_from_json(chatid, phone, status="pending"):
    """دریافت توکن‌ها از JSON با وضعیت مشخص - اگر فایل وجود نداشت، ایجاد می‌شود"""
    tokens_data = load_tokens_json()
    if chatid in tokens_data and phone in tokens_data[chatid]:
        status_dict = tokens_data[chatid][phone]
        if isinstance(status_dict, dict) and status in status_dict:
            return status_dict[status]
        # سازگاری با ساختار قدیمی
        elif isinstance(status_dict, list):
            return status_dict if status == "pending" else []
    return []

def get_all_pending_tokens_from_json(chatid):
    """دریافت تمام توکن‌های pending از JSON - اگر فایل وجود نداشت، ایجاد می‌شود"""
    tokens_data = load_tokens_json()
    if chatid not in tokens_data:
        return []
    
    all_pending = []
    for phone, status_dict in tokens_data[chatid].items():
        if isinstance(status_dict, dict):
            pending_tokens = status_dict.get("pending", [])
        else:
            # سازگاری با ساختار قدیمی
            pending_tokens = status_dict if isinstance(status_dict, list) else []
        
        for token in pending_tokens:
            all_pending.append((phone, token))
    return all_pending

def get_all_tokens_by_status(chatid, status="pending"):
    """دریافت تمام توکن‌ها با وضعیت مشخص از JSON"""
    tokens_data = load_tokens_json()
    if chatid not in tokens_data:
        return []
    
    all_tokens = []
    for phone, status_dict in tokens_data[chatid].items():
        if isinstance(status_dict, dict):
            tokens = status_dict.get(status, [])
        else:
            # سازگاری با ساختار قدیمی
            tokens = status_dict if isinstance(status_dict, list) and status == "pending" else []
        
        for token in tokens:
            all_tokens.append((phone, token))
    return all_tokens

def has_pending_tokens_in_json(chatid):
    """بررسی اینکه آیا توکن pending در JSON وجود دارد - اگر فایل وجود نداشت، ایجاد می‌شود"""
    tokens_data = load_tokens_json()
    if chatid not in tokens_data:
        return False
    
    for phone, status_dict in tokens_data[chatid].items():
        if isinstance(status_dict, dict):
            if status_dict.get("pending", []):
                return True
        else:
            # سازگاری با ساختار قدیمی
            if isinstance(status_dict, list) and status_dict:
                return True
    return False

def get_token_stats(chatid, phone=None):
    """دریافت آمار توکن‌ها برای یک chatid یا phone خاص"""
    tokens_data = load_tokens_json()
    if chatid not in tokens_data:
        return {
            "pending": 0,
            "success": 0,
            "failed": 0,
            "total": 0
        }
    
    stats = {
        "pending": 0,
        "success": 0,
        "failed": 0,
        "total": 0
    }
    
    if phone:
        # آمار برای یک phone خاص
        if phone in tokens_data[chatid]:
            status_dict = tokens_data[chatid][phone]
            if isinstance(status_dict, dict):
                stats["pending"] = len(status_dict.get("pending", []))
                stats["success"] = len(status_dict.get("success", []))
                stats["failed"] = len(status_dict.get("failed", []))
            else:
                # سازگاری با ساختار قدیمی
                stats["pending"] = len(status_dict) if isinstance(status_dict, list) else 0
            stats["total"] = stats["pending"] + stats["success"] + stats["failed"]
    else:
        # آمار برای تمام phone ها
        for phone_key, status_dict in tokens_data[chatid].items():
            if isinstance(status_dict, dict):
                stats["pending"] += len(status_dict.get("pending", []))
                stats["success"] += len(status_dict.get("success", []))
                stats["failed"] += len(status_dict.get("failed", []))
            else:
                # سازگاری با ساختار قدیمی
                stats["pending"] += len(status_dict) if isinstance(status_dict, list) else 0
        
        stats["total"] = stats["pending"] + stats["success"] + stats["failed"]
    
    return stats

def reset_tokens_for_phone(chatid, phone):
    """
    حذف تمام توکن‌های یک شماره برای یک chatid از JSON.
    خروجی: (موفقیت، لیست توکن‌های حذف‌شده) برای پاک‌سازی جدول sents و غیره.
    """
    removed_tokens = []
    try:
        try:
            chatid = int(chatid)
            phone = int(phone)
        except (TypeError, ValueError):
            return False, removed_tokens

        tokens_data = load_tokens_json()
        if chatid not in tokens_data or phone not in tokens_data[chatid]:
            return True, removed_tokens

        status_dict = tokens_data[chatid][phone]
        if isinstance(status_dict, dict):
            for key in ("pending", "success", "failed"):
                removed_tokens.extend(status_dict.get(key, []))
        elif isinstance(status_dict, list):
            removed_tokens.extend(status_dict)

        del tokens_data[chatid][phone]
        if not tokens_data[chatid]:
            del tokens_data[chatid]

        save_tokens_json(tokens_data)
        print(f"♻️ توکن‌های chatid={chatid} phone={phone} از JSON حذف شد ({len(removed_tokens)} توکن).")
        return True, removed_tokens
    except Exception as e:
        print(f"❌ خطا در reset_tokens_for_phone chatid={chatid} phone={phone}: {e}")
        import traceback
        traceback.print_exc()
        return False, removed_tokens


def reset_tokens_for_chat(chatid):
    """حذف کامل تمام توکن‌های مربوط به یک chatid از فایل JSON"""
    try:
        try:
            chatid = int(chatid)
        except (TypeError, ValueError):
            pass
        tokens_data = load_tokens_json()
        if chatid in tokens_data:
            del tokens_data[chatid]
            save_tokens_json(tokens_data)
            print(f"♻️ تمام توکن‌های chatid={chatid} از JSON حذف شد.")
            return True
        # بدون داده هم «ریست موفق» — جلوگیری از گیر کردن auto_reset در حالت JSON خالی/هم‌زمان
        print(f"ℹ️ توکنی برای chatid={chatid} در JSON یافت نشد (ریست بدون تغییر).")
        return True
    except Exception as e:
        print(f"❌ خطا در reset_tokens_for_chat برای chatid={chatid}: {e}")
        import traceback
        traceback.print_exc()
        return False