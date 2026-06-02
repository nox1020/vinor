# app/utils/storage.py
import os, json, shutil, logging
from flask import current_app

_log = logging.getLogger(__name__)


def _package_app_root() -> str:
    """مسیر پکیج Flask روی دیسک (…/project/app)."""
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _standalone_instance_path() -> str:
    """
    پوشهٔ instance وقتی هنوز به Flask app متصل نیستیم.
    Passenger معمولاً INSTANCE_PATH را ست می‌کند؛ در غیر این صورت ../instance کنار پروژه.
    """
    envp = os.environ.get("INSTANCE_PATH")
    if envp:
        return os.path.abspath(envp)
    project_root = os.path.dirname(_package_app_root())
    return os.path.abspath(os.path.join(project_root, "instance"))


def _resolve_app(app):
    """برگرداندن app صریح یا current_app؛ در نبود context مقدار None."""
    if app is not None:
        return app
    try:
        return current_app._get_current_object()
    except RuntimeError:
        return None


# -------- مسیرهای داده --------
def data_dir(app=None):
    """
    مسیر امن و قابل‌نوشتن: <instance>/data  (داخل instance_path)
    """
    app = _resolve_app(app)
    if app is not None:
        base = app.instance_path
    else:
        base = _standalone_instance_path()
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, 'data')
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, 'uploads'), exist_ok=True)
    return path

def legacy_dir(app=None):
    """مسیر قدیمی کنار کد: <root>/data"""
    app = _resolve_app(app)
    if app is not None:
        return os.path.join(app.root_path, 'data')
    return os.path.join(_package_app_root(), 'data')

# -------- اطمینان از وجود فایل و مهاجرت --------
def ensure_file(config_key: str, filename: str, default_content, app=None):
    """
    اگر فایل کانفیگ‌شده وجود نداشته باشد:
      1) تلاش برای کپی از مسیر قدیمی (root/data)
      2) در غیر این صورت ایجاد فایل با محتوای پیش‌فرض
    همچنین مسیر به app.config[config_key] ست می‌شود.
    """
    app = _resolve_app(app)
    d = data_dir(app)
    if app is not None:
        fpath = app.config.get(config_key) or os.path.join(d, filename)
        app.config[config_key] = fpath
    else:
        fpath = os.path.join(d, filename)

    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    if not os.path.exists(fpath):
        old = os.path.join(legacy_dir(app), filename)
        if os.path.exists(old):
            try:
                shutil.copy2(old, fpath)
            except Exception:
                pass
        if not os.path.exists(fpath):
            with open(fpath, 'w', encoding='utf-8') as f:
                if isinstance(default_content, (dict, list)):
                    json.dump(default_content, f, ensure_ascii=False, indent=2)
                else:
                    f.write(str(default_content or ""))
    return fpath

def migrate_legacy(app=None):
    """
    کپی فایل‌های قدیمی از <root>/data به <instance>/data در اولین اجرا
    """
    app = _resolve_app(app)
    inst = data_dir(app)
    marker = os.path.join(inst, ".legacy_migrated")
    if os.path.isfile(marker):
        return
    legacy = legacy_dir(app)
    try:
        for name in ('lands.json','users.json','consults.json','settings.json','notifications.json','reports.json'):
            old, new = os.path.join(legacy, name), os.path.join(inst, name)
            if os.path.exists(old) and not os.path.exists(new):
                try: shutil.copy2(old, new)
                except Exception: pass

        old_up, new_up = os.path.join(legacy, 'uploads'), os.path.join(inst, 'uploads')
        if os.path.isdir(old_up):
            if not os.path.exists(new_up) or (os.path.exists(new_up) and not os.listdir(new_up)):
                try: shutil.copytree(old_up, new_up, dirs_exist_ok=True)
                except Exception: pass
    except Exception as e:
        try:
            if app is not None:
                app.logger.warning("Legacy migration issue: %s", e)
            else:
                _log.warning("Legacy migration issue: %s", e)
        except Exception:
            pass
    else:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("ok")
        except Exception:
            pass

# -------- IO ساده JSON --------
def _load(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:    return json.load(f)
            except: return []
    return []

def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# فایل‌های دامنه
_ADS_CACHE = {"path": None, "mtime": None, "size": None, "data": None}
_EXPRESS_LANDS_CACHE = {"path": None, "mtime": None, "size": None, "data": None}
_SETTINGS_CACHE = {"path": None, "mtime": None, "size": None, "data": None}
_PARTNERS_CACHE = {"path": None, "mtime": None, "size": None, "data": None}


def _file_cache_load(cache: dict, path: str, loader):
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, "st_mtime_ns") else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None
    if cache["path"] == path and cache["mtime"] == mtime and cache["size"] == size and cache["data"] is not None:
        return cache["data"]
    data = loader(path)
    cache.update({"path": path, "mtime": mtime, "size": size, "data": data})
    return data

def load_ads(app=None):        return _load(ensure_file('LANDS_FILE','lands.json',[],app))

def load_ads_cached(app=None):
    """لود آگهی‌ها با کش ساده مبتنی بر mtime/size فایل."""
    app = _resolve_app(app)
    path = ensure_file('LANDS_FILE','lands.json',[],app)
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None

    c = _ADS_CACHE
    if c["path"] == path and c["mtime"] == mtime and c["size"] == size and c["data"] is not None:
        return c["data"]

    data = _load(path)
    _ADS_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": data})
    # پاک کردن کش اکسپرس هنگام تغییر فایل اصلی
    _EXPRESS_LANDS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return data

def load_express_lands_cached(app=None):
    """لود فایل‌های اکسپرس فیلتر شده با کش جداگانه برای سرعت بیشتر."""
    app = _resolve_app(app)
    path = ensure_file('LANDS_FILE','lands.json',[],app)
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None

    c = _EXPRESS_LANDS_CACHE
    if c["path"] == path and c["mtime"] == mtime and c["size"] == size and c["data"] is not None:
        return c["data"]

    # بارگذاری و فیلتر کردن فایل‌های اکسپرس
    all_lands = load_ads_cached(app)
    express_lands = [
        l for l in all_lands 
        if l.get('is_express', False) and l.get('express_status') != 'sold'
    ]
    # مرتب‌سازی بر اساس تاریخ ایجاد (جدیدترین اول)
    express_lands.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    _EXPRESS_LANDS_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": express_lands})
    return express_lands

def get_lands_file_stats(app=None):
    """
    آمار فایل آگهی‌ها برای ساخت ETag/Last-Modified سریع.
    خروجی: {"path": str, "mtime": int|None, "size": int|None, "etag": str}
    """
    app = _resolve_app(app)
    path = ensure_file('LANDS_FILE','lands.json',[],app)
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None
    etag = f'W/"lands-{mtime}-{size}"'
    return {"path": path, "mtime": mtime, "size": size, "etag": etag}

def _update_ads_cache_after_save(path, items):
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None
    _ADS_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": items})
    # به‌روزرسانی کش اکسپرس
    express_lands = [
        l for l in items 
        if l.get('is_express', False) and l.get('express_status') != 'sold'
    ]
    express_lands.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    _EXPRESS_LANDS_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": express_lands})

def save_ads(items, app=None):
    path = ensure_file('LANDS_FILE','lands.json',[],app)
    _save(path, items)
    _update_ads_cache_after_save(path, items)

def load_users(app=None):        return _load(ensure_file('USERS_FILE','users.json',[],app))
def save_users(items, app=None): return _save(ensure_file('USERS_FILE','users.json',[],app), items)

def load_consults(app=None):        return _load(ensure_file('CONSULTS_FILE','consults.json',[],app))
def save_consults(items, app=None): return _save(ensure_file('CONSULTS_FILE','consults.json',[],app), items)

def load_settings(app=None):
    default_settings = {
        "approval_method": "manual",
        "show_submit_button": True,
        "ad_expiry_days": 30,
        "android_apk_url": "",
        "android_apk_version": "",
        "android_apk_updated_at": "",
        "android_apk_size_bytes": "",
        "android_apk_sha256": "",
        "android_apk_original_name": "",
        "sms_line_number": "300089930616",
        "partner_application_sms_message": "درخواست همکاری شما ثبت شد و در حال بررسی است. وینور",
        "partner_approval_sms_message": "پنل همکاری وینور برای شما فعال شد. وینور",
        "partner_application_admin_phone": "09121471301",
        "partner_application_admin_sms_message": "درخواست همکاری جدید همکار در وینور ثبت شد.",
        "visit_approval_sms_message": "",
    }
    return load_settings_cached(app, default_settings=default_settings)


def load_settings_cached(app=None, default_settings=None):
    if default_settings is None:
        default_settings = {
            "approval_method": "manual",
            "show_submit_button": True,
            "ad_expiry_days": 30,
            "android_apk_url": "",
            "android_apk_version": "",
            "android_apk_updated_at": "",
            "android_apk_size_bytes": "",
            "android_apk_sha256": "",
            "android_apk_original_name": "",
            "sms_line_number": "300089930616",
            "partner_application_sms_message": "درخواست همکاری شما ثبت شد و در حال بررسی است. وینور",
            "partner_approval_sms_message": "پنل همکاری وینور برای شما فعال شد. وینور",
            "partner_application_admin_phone": "09121471301",
            "partner_application_admin_sms_message": "درخواست همکاری جدید همکار در وینور ثبت شد.",
            "visit_approval_sms_message": "",
        }
    app = _resolve_app(app)
    path = ensure_file("SETTINGS_FILE", "settings.json", default_settings, app)
    return _file_cache_load(_SETTINGS_CACHE, path, _load)


def load_express_partners_cached(app=None):
    app = _resolve_app(app)
    path = ensure_file("EXPRESS_PARTNERS_FILE", "express_partners.json", [], app)
    return _file_cache_load(_PARTNERS_CACHE, path, _load)

# شهرهای فعال برای همکاری
def load_active_cities(app=None):        return _load(ensure_file('ACTIVE_CITIES_FILE','active_cities.json',["تهران", "کرج", "اصفهان", "شیراز", "مشهد", "تبریز"],app))
def save_active_cities(items, app=None): return _save(ensure_file('ACTIVE_CITIES_FILE','active_cities.json',[],app), items)

def load_notifications(app=None):        return _load(ensure_file('NOTIFICATIONS_FILE','notifications.json',[],app))
def save_notifications(items, app=None): return _save(ensure_file('NOTIFICATIONS_FILE','notifications.json',[],app), items)

# Reports (user-reported ads)
def load_reports(app=None):        return _load(ensure_file('REPORTS_FILE','reports.json',[],app))
def save_reports(items, app=None): return _save(ensure_file('REPORTS_FILE','reports.json',[],app), items)

# Consultants & Applications
def load_consultant_apps(app=None):        return _load(ensure_file('CONSULTANT_APPS_FILE','consultant_applications.json',[],app))
def save_consultant_apps(items, app=None): return _save(ensure_file('CONSULTANT_APPS_FILE','consultant_applications.json',[],app), items)
def load_consultants(app=None):           return _load(ensure_file('CONSULTANTS_FILE','consultants.json',[],app))
def save_consultants(items, app=None):    return _save(ensure_file('CONSULTANTS_FILE','consultants.json',[],app), items)

# Express Partners & Applications
def load_express_partner_apps(app=None):   return _load(ensure_file('EXPRESS_PARTNER_APPS_FILE','express_partner_applications.json',[],app))
def save_express_partner_apps(items, app=None): return _save(ensure_file('EXPRESS_PARTNER_APPS_FILE','express_partner_applications.json',[],app), items)
def load_express_partners(app=None):       return load_express_partners_cached(app)
def save_express_partners(items, app=None):
    path = ensure_file('EXPRESS_PARTNERS_FILE','express_partners.json',[],app)
    _save(path, items)
    _PARTNERS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
def load_express_reposts(app=None):        return _load(ensure_file('EXPRESS_REPOSTS_FILE','express_reposts.json',[],app))
def save_express_reposts(items, app=None): return _save(ensure_file('EXPRESS_REPOSTS_FILE','express_reposts.json',[],app), items)

# Express Partner: Notes, Sales, Files (metadata)
def load_partner_notes(app=None):          return _load(ensure_file('EXPRESS_PARTNER_NOTES_FILE','express_partner_notes.json',[],app))
def save_partner_notes(items, app=None):   return _save(ensure_file('EXPRESS_PARTNER_NOTES_FILE','express_partner_notes.json',[],app), items)
def load_partner_sales(app=None):          return _load(ensure_file('EXPRESS_PARTNER_SALES_FILE','express_partner_sales.json',[],app))
def save_partner_sales(items, app=None):   return _save(ensure_file('EXPRESS_PARTNER_SALES_FILE','express_partner_sales.json',[],app), items)
def load_partner_files_meta(app=None):     return _load(ensure_file('EXPRESS_PARTNER_FILES_META_FILE','express_partner_files.json',[],app))
def save_partner_files_meta(items, app=None): return _save(ensure_file('EXPRESS_PARTNER_FILES_META_FILE','express_partner_files.json',[],app), items)

# Express Assignments & Commissions
def load_express_assignments(app=None):    return _load(ensure_file('EXPRESS_ASSIGNMENTS_FILE','express_assignments.json',[],app))
def save_express_assignments(items, app=None): return _save(ensure_file('EXPRESS_ASSIGNMENTS_FILE','express_assignments.json',[],app), items)
_COMMISSIONS_CACHE = {"path": None, "mtime": None, "size": None, "data": None}

def load_express_commissions(app=None):    return _load(ensure_file('EXPRESS_COMMISSIONS_FILE','express_commissions.json',[],app))

def load_express_commissions_cached(app=None):
    """پورسانت‌ها با کش mtime — برای ناوبری سریع‌تر بین تب‌ها."""
    app = _resolve_app(app)
    path = ensure_file('EXPRESS_COMMISSIONS_FILE', 'express_commissions.json', [], app)
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None
    c = _COMMISSIONS_CACHE
    if c["path"] == path and c["mtime"] == mtime and c["size"] == size and c["data"] is not None:
        return c["data"]
    data = _load(path)
    _COMMISSIONS_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": data})
    return data

def save_express_commissions(items, app=None):
    data = _save(ensure_file('EXPRESS_COMMISSIONS_FILE','express_commissions.json',[],app), items)
    _COMMISSIONS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return data

def load_express_referrals(app=None):
    return _load(ensure_file('EXPRESS_REFERRALS_FILE', 'express_referrals.json', [], app))

def save_express_referrals(items, app=None):
    return _save(ensure_file('EXPRESS_REFERRALS_FILE', 'express_referrals.json', [], app), items)

# کارت‌های بانکی همکار اکسپرس (فقط متادیتا؛ شمارهٔ کامل ذخیره نمی‌شود)
def load_partner_bank_accounts(app=None):
    return _load(ensure_file('EXPRESS_PARTNER_BANK_ACCOUNTS_FILE', 'express_partner_bank_accounts.json', [], app))


def save_partner_bank_accounts(items, app=None):
    return _save(ensure_file('EXPRESS_PARTNER_BANK_ACCOUNTS_FILE', 'express_partner_bank_accounts.json', [], app), items)

# درخواست‌های برداشت پورسانت همکار
def load_partner_withdrawals(app=None):
    return _load(ensure_file('EXPRESS_PARTNER_WITHDRAWALS_FILE', 'express_partner_withdrawals.json', [], app))


def save_partner_withdrawals(items, app=None):
    return _save(ensure_file('EXPRESS_PARTNER_WITHDRAWALS_FILE', 'express_partner_withdrawals.json', [], app), items)

# درخواست بازدید فایل اکسپرس
def load_express_visit_requests(app=None):
    return _load(ensure_file('EXPRESS_VISIT_REQUESTS_FILE', 'express_visit_requests.json', [], app))


def save_express_visit_requests(items, app=None):
    return _save(ensure_file('EXPRESS_VISIT_REQUESTS_FILE', 'express_visit_requests.json', [], app), items)

# SMS History
def load_sms_history(app=None):    return _load(ensure_file('SMS_HISTORY_FILE','sms_history.json',[],app))
def save_sms_history(items, app=None): return _save(ensure_file('SMS_HISTORY_FILE','sms_history.json',[],app), items)

# Landing Page Views Statistics
def load_landing_views(app=None):    return _load(ensure_file('LANDING_VIEWS_FILE','landing_views.json',[],app))
def save_landing_views(items, app=None): return _save(ensure_file('LANDING_VIEWS_FILE','landing_views.json',[],app), items)

# Express Listing Views Statistics (tracking views per listing code)
# Public views: بازدیدهای صفحه عمومی
def load_express_views(app=None):    return _load(ensure_file('EXPRESS_VIEWS_FILE','express_views.json',[],app))
def save_express_views(items, app=None): return _save(ensure_file('EXPRESS_VIEWS_FILE','express_views.json',[],app), items)
# Partner views: بازدیدهای صفحه همکاران
def load_express_partner_views(app=None):    return _load(ensure_file('EXPRESS_PARTNER_VIEWS_FILE','express_partner_views.json',[],app))
def save_express_partner_views(items, app=None): return _save(ensure_file('EXPRESS_PARTNER_VIEWS_FILE','express_partner_views.json',[],app), items)

# Express Partner: Routine tracking (days done per partner)
_ROUTINES_CACHE = {"path": None, "mtime": None, "size": None, "data": None}

def load_partner_routines(app=None):
    return _load(ensure_file('EXPRESS_PARTNER_ROUTINES_FILE','express_partner_routines.json',[],app))

def load_partner_routines_cached(app=None):
    """Load partner routines with a small in-memory cache based on file mtime/size."""
    app = _resolve_app(app)
    path = ensure_file('EXPRESS_PARTNER_ROUTINES_FILE','express_partner_routines.json',[],app)
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None

    c = _ROUTINES_CACHE
    if c["path"] == path and c["mtime"] == mtime and c["size"] == size and c["data"] is not None:
        return c["data"]

    data = _load(path)
    _ROUTINES_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": data})
    return data

def _update_routines_cache_after_save(path, items):
    try:
        st = os.stat(path)
        mtime = st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else int(st.st_mtime * 1e9)
        size = st.st_size
    except Exception:
        mtime = None
        size = None
    _ROUTINES_CACHE.update({"path": path, "mtime": mtime, "size": size, "data": items})

def save_partner_routines(items, app=None):
    path = ensure_file('EXPRESS_PARTNER_ROUTINES_FILE','express_partner_routines.json',[],app)
    _save(path, items)
    _update_routines_cache_after_save(path, items)