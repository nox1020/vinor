# app/routes/public.py
import os
from urllib.parse import quote

from flask import (
    render_template, send_from_directory, request, abort,
    redirect, url_for, session, make_response, current_app,
    has_app_context, has_request_context,
)

from . import main_bp
from ..utils.storage import data_dir, legacy_dir
from ..utils.storage import load_express_partners_cached, load_landing_views, save_landing_views
from ..utils.images import (
    variant_headers_for_width,
)
from datetime import datetime
from time import time as _now

# --- very small in-memory microcache (5-20s) for public pages ---
_MICROCACHE: dict = {}  # key -> (expires_at, payload)
_SETTINGS_CACHE: dict = {}  # Cache for settings
def _mc_get(key: str):
    try:
        exp, val = _MICROCACHE.get(key, (0, None))
        if exp and exp > _now():
            return val
    except Exception:
        return None
    return None
def _mc_set(key: str, val, ttl: int = 10):
    try:
        _MICROCACHE[key] = (_now() + max(1, int(ttl)), val)
    except Exception:
        pass
def _get_cached_settings():
    """Cache settings برای 60 ثانیه"""
    cache_key = "settings"
    cached = _mc_get(cache_key)
    if cached is not None:
        return cached
    try:
        from ..utils.storage import load_settings_cached
        settings = load_settings_cached()
        _mc_set(cache_key, settings, ttl=60)
        return settings
    except Exception:
        return {}
# ثابت‌ها
FIRST_VISIT_COOKIE = "vinor_first_visit_done"

# -------------------------
# Context (برای استفادهٔ ساده در تمام قالب‌ها)
# -------------------------
@main_bp.app_context_processor
def inject_vinor_globals():
    """
    متغیرهای عمومیِ وینور برای استفاده در تمپلیت‌ها
    """
    if not has_app_context() or not has_request_context():
        return {}
    # همکار اکسپرس تأییدشده — بدون خواندن کل فایل partners روی هر درخواست
    try:
        me = str(session.get("user_phone") or "").strip()
        if me and "VINOR_IS_EXPRESS_PARTNER" in session:
            is_express_partner = bool(session.get("VINOR_IS_EXPRESS_PARTNER"))
        elif me:
            partners = load_express_partners_cached(current_app._get_current_object())
            is_express_partner = any(
                isinstance(p, dict)
                and str(p.get("phone") or "").strip() == me
                and (str(p.get("status") or "").lower() == "approved" or p.get("status") is True)
                for p in (partners or [])
            )
            session["VINOR_IS_EXPRESS_PARTNER"] = is_express_partner
        else:
            is_express_partner = False
    except Exception:
        is_express_partner = False

    return {
        "VINOR_IS_LOGGED_IN": bool(session.get("user_id")),
        "VINOR_HOME_URL": url_for("express_partner.dashboard"),
        "VINOR_BRAND": "وینور اکسپرس",
        "VINOR_DOMAIN": "vinor.ir",
        # نقش‌ها
        "VINOR_IS_EXPRESS_PARTNER": is_express_partner,
    }

# -------------------------
# Routes
# -------------------------

@main_bp.route("/", endpoint="index")
def index():
    """
    صفحهٔ اصلی vinor.ir — همیشه داشبورد همکار (مهمان یا واردشده).
    لندینگ معرفی همکاری فقط در /partners است.
    """
    nxt = request.args.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        resp = redirect(nxt)
    elif session.get('logged_in'):
        resp = redirect(url_for('admin.dashboard'))
    else:
        q = (request.args.get('q') or '').strip() or None
        city = (request.args.get('city') or '').strip() or None
        resp = redirect(url_for('express_partner.dashboard', q=q, city=city))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['Vary'] = 'Cookie'
    return resp

@main_bp.route("/partners", endpoint="partners")
def partners():
    """
    لندینگ همکاران وینور – معرفی فرصت‌های همکاری
    اگر کاربر وارد شده باشد، مستقیم به داشبورد می‌رود.
    """
    # بررسی اینکه آیا کاربر در پنل ادمین است یا نه
    referer = request.headers.get('Referer', '') or ''
    is_admin = (
        session.get('logged_in') or 
        request.path.startswith('/admin') or
        '/admin' in referer
    )
    
    if session.get("user_phone") or session.get("user_id") or is_admin:
        nxt = request.args.get('next')
        if nxt and nxt.startswith('/'):
            return redirect(nxt)
        if is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("express_partner.dashboard"))
    
    # ثبت بازدید لندینگ (فقط برای کاربران غیرلاگین و غیرادمین و درخواست‌های مستقیم)
    # اگر referer از admin یا express/partner باشد، tracking نمی‌کنیم
    if '/admin' not in referer and '/express/partner' not in referer:
        try:
            views = load_landing_views() or []
            if not isinstance(views, list):
                views = []
            
            # بررسی اینکه آیا این IP در امروز قبلاً بازدید داشته یا نه
            visitor_ip = request.remote_addr or ''
            now = datetime.utcnow()
            today_str = now.strftime('%Y-%m-%d')
            
            # بررسی بازدیدهای امروز برای این IP
            already_viewed_today = False
            for v in views:
                try:
                    v_ip = v.get('ip', '')
                    v_ts_str = v.get('timestamp', '')
                    if v_ip == visitor_ip and v_ts_str:
                        v_dt = datetime.fromisoformat(v_ts_str.replace('Z', '+00:00'))
                        if v_dt.tzinfo:
                            v_dt = v_dt.replace(tzinfo=None)
                        v_date_str = v_dt.strftime('%Y-%m-%d')
                        if v_date_str == today_str:
                            already_viewed_today = True
                            break
                except Exception:
                    continue
            
            # اگر این IP امروز بازدید نداشته، ثبت کن
            if not already_viewed_today and visitor_ip:
                views.append({
                    'timestamp': now.isoformat(),
                    'ip': visitor_ip,
                    'user_agent': request.headers.get('User-Agent', '')[:200]
                })
                # نگه داشتن فقط 10000 بازدید اخیر
                if len(views) > 10000:
                    views = views[-10000:]
                save_landing_views(views)
        except Exception as e:
            current_app.logger.error(f"Error tracking landing view: {e}", exc_info=True)
    
    try:
        from ..utils.storage import load_settings
        _settings = load_settings()
    except Exception:
        _settings = {}
    # Microcache only for guests
    if not (session.get("user_phone") or session.get("user_id") or is_admin):
        k = f"page:partners"
        cached = _mc_get(k)
        if cached:
            resp = make_response(cached)
            resp.headers["Cache-Control"] = "no-cache"
            return resp
    html = render_template("home/partners.html",
                           brand="وینور",
                           domain="vinor.ir",
                           android_apk_url=_settings.get('android_apk_url') or '',
                           android_apk_version=_settings.get('android_apk_version') or '')
    try:
        if not (session.get("user_phone") or session.get("user_id") or is_admin):
            _mc_set("page:partners", html, ttl=15)
    except Exception:
        pass
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@main_bp.route("/start", endpoint="start")
def start():
    """
    CTA لندینگ → ست‌کردن کوکی «اولین بازدید انجام شد»
    سپس به داشبورد همکار می‌رویم.
    """
    target = url_for("express_partner.dashboard")
    resp = make_response(redirect(target))
    resp.set_cookie(FIRST_VISIT_COOKIE, "1", max_age=60 * 60 * 24 * 365, samesite="Lax")
    session.permanent = True
    return resp

@main_bp.route("/public", endpoint="express_public_list")
def express_public_list():
    """
    صفحه عمومی (اکسپلور) حذف شده؛ همه فایل‌ها در داشبورد نمایش داده می‌شوند.
    برای حفظ لینک‌های قدیمی، ریدایرکت دائمی (301) به داشبورد.
    """
    q = (request.args.get('q', '') or '').strip()
    city = (request.args.get('city', '') or '').strip()
    target = url_for('express_partner.dashboard', q=q or None, city=city or None)
    return redirect(target, code=301)

@main_bp.route("/express/<code>", endpoint="express_detail")
def express_detail(code):
    """
    صفحه عمومی جزئیات فایل حذف شده است.
    لینک‌های قدیمی به صفحه جزئیات داخل پنل همکار هدایت می‌شوند.
    """
    return redirect(url_for('express_partner.land_detail', code=code), code=302)

@main_bp.route("/uploads/<path:filename>", endpoint="uploaded_file")
def uploaded_file(filename):
    """
    سرو فایل‌های آپلود:
      1) ابتدا از UPLOAD_FOLDER (مسیر جدید تاریخ‌محور)
      2) سپس از instance/data/uploads
      3) سپس از <root>/data/uploads (legacy)
    """
    try:
        width = int(request.args.get("w", 0) or 0)
        quality = int(request.args.get("q", 0) or 0) or 80
        fmt = (request.args.get("fmt") or "webp").lower()
    except Exception:
        width = 0
        quality = 80
        fmt = "webp"

    def _generate_variant(root: str, safe_name: str):
        if width <= 0:
            return None
        try:
            from app.utils.images import generate_variant  # محلی برای جلوگیری از چرخه

            variant_rel = generate_variant(root, safe_name, width, quality, f"w{width}_q{quality}", fmt.upper())
            if not variant_rel:
                return None
            abs_path = os.path.join(root, variant_rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            if os.path.isfile(abs_path):
                vdir, vfile = os.path.split(abs_path)
                resp = send_from_directory(vdir, vfile)
                resp.headers["Cache-Control"] = variant_headers_for_width(width)
                resp.headers["Content-Type"] = "image/webp"
                return resp
        except Exception as e:
            current_app.logger.debug("Variant generation failed: %s", e, exc_info=True)
        return None

    def _maybe_set_apk_download_name(resp):
        try:
            fn_norm = (filename or '').replace('\\', '/')
            if fn_norm.lower().endswith('.apk') and fn_norm.startswith('apk/'):
                try:
                    from ..utils.storage import load_settings
                    settings = load_settings()
                except Exception:
                    settings = {}
                wanted_url = str(settings.get('android_apk_url') or '')
                orig_name = str(settings.get('android_apk_original_name') or '').strip()
                if wanted_url and orig_name:
                    # match by basename to ensure we are serving the configured APK
                    try:
                        wanted_base = os.path.basename(wanted_url)
                    except Exception:
                        wanted_base = ''
                    if wanted_base and wanted_base == os.path.basename(fn_norm):
                        # Force download with the original client filename
                        try:
                            disp = "attachment; filename*=UTF-8''" + quote(orig_name) + f"; filename=\"{orig_name}\""
                            resp.headers['Content-Disposition'] = disp
                        except Exception:
                            resp.headers['Content-Disposition'] = f'attachment; filename=\"{orig_name}\"'
        except Exception:
            pass
        return resp
    # اول مسیر تنظیم‌شده در کانفیگ
    try:
        base_cfg = current_app.config.get("UPLOAD_FOLDER")
        if base_cfg:
            fp_cfg = os.path.join(base_cfg, filename)
            if os.path.isfile(fp_cfg):
                # تلاش برای سرو واریانت
                variant_resp = _generate_variant(base_cfg, filename)
                if variant_resp:
                    return variant_resp
                resp = send_from_directory(base_cfg, filename)
                resp = _maybe_set_apk_download_name(resp)
                try:
                    if width > 0:
                        resp.headers["Cache-Control"] = variant_headers_for_width(width)
                    else:
                        resp.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=86400"
                except Exception:
                    pass
                return resp
    except Exception:
        pass

    # سپس مسیر instance/data/uploads و legacy data/uploads
    upload_roots = (
        os.path.join(data_dir(), "uploads"),
        os.path.join(legacy_dir(), "uploads"),
    )
    for folder in upload_roots:
        fp = os.path.join(folder, filename)
        if os.path.isfile(fp):
            variant_resp = _generate_variant(folder, filename)
            if variant_resp:
                return variant_resp
            resp = send_from_directory(folder, filename)
            resp = _maybe_set_apk_download_name(resp)
            try:
                resp.headers["Cache-Control"] = variant_headers_for_width(width) if width > 0 else "public, max-age=86400, stale-while-revalidate=86400"
            except Exception:
                pass
            return resp
    # در نهایت: static/uploads (تصاویر ذخیره‌شده در static)
    try:
        static_root = current_app.static_folder
        # پشتیبانی از هر دو ورودی: 'uploads/...' یا فقط '...'
        candidates = []
        if filename.startswith('uploads/'):
            candidates.append(os.path.join(static_root, filename))
            candidates.append(os.path.join(static_root, filename.lstrip('/')))
        else:
            candidates.append(os.path.join(static_root, 'uploads', filename))
        for cand in candidates:
            if os.path.isfile(cand):
                rel_dir = os.path.dirname(os.path.relpath(cand, static_root))
                fn = os.path.basename(cand)
                resp = send_from_directory(os.path.join(static_root, rel_dir), fn)
                resp = _maybe_set_apk_download_name(resp)
                try:
                    resp.headers["Cache-Control"] = variant_headers_for_width(width) if width > 0 else "public, max-age=86400, stale-while-revalidate=86400"
                except Exception:
                    pass
                return resp
    except Exception:
        pass
    abort(404, description="File not found")


@main_bp.route("/express-docs/<filename>")
def serve_express_document(filename):
    """سرو کردن مدارک اکسپرس برای کاربران"""
    try:
        docs_dir = os.path.join(current_app.instance_path, 'data', 'express_docs')
        return send_from_directory(docs_dir, filename)
    except Exception as e:
        current_app.logger.error(f"Error serving express document {filename}: {e}")
        abort(404)

@main_bp.route("/help", endpoint="help")
def help_page():
    """صفحه راهنمای عمومی - فقط برای Express Partner"""
    base_url = request.url_root.rstrip('/')
    return render_template(
        'public/help.html',
        seo={
            'title': 'راهنما | وینور اکسپرس',
            'description': 'راهنمای استفاده از پلتفرم وینور اکسپرس و اطلاعات تماس پشتیبانی',
            'keywords': 'راهنما, پشتیبانی, وینور اکسپرس',
            'canonical': f"{base_url}/help",
            'og_type': 'website',
            'og_image': f"{base_url}/static/icons/icon-512.png"
        }
    )


@main_bp.route("/privacy", endpoint="privacy")
def privacy_page():
    """حریم خصوصی عمومی — آدرس canonical برای فروشگاه‌ها و vinor.ir/privacy"""
    base_url = request.url_root.rstrip('/')
    return render_template(
        'public/privacy.html',
        seo={
            'title': 'حریم خصوصی | وینور',
            'description': 'سیاست حریم خصوصی وینور اکسپرس: وب، پنل همکار و اپ اندروید',
            'canonical': f"{base_url}/privacy",
            'og_type': 'website',
            'og_image': f"{base_url}/static/icons/icon-512.png",
        },
    )


@main_bp.route("/profile", methods=["GET"], endpoint="profile")
def profile():
    """
    پروفایل عمومی کاربر (نقش کاربر عادی).
    - اگر وارد نشده باشد → صفحه ورود همکار (OTP) برای احراز شماره
    - اگر وارد شده باشد:
        - وضعیت همکاری (تایید/درحال بررسی/غیرفعال) نمایش داده می‌شود
        - دکمه «درخواست همکاری» برای شروع فرآیند apply
    """
    me_phone = (session.get("user_phone") or "").strip()
    if not me_phone:
        nxt = request.args.get("next") or url_for("main.profile")
        return redirect(url_for("express_partner.login", next=nxt))

    # وضعیت همکاری
    try:
        partners = load_express_partners() or []
    except Exception:
        partners = []
    prof = next((p for p in partners if str(p.get("phone") or "").strip() == me_phone), None)
    status = str((prof or {}).get("status") or "").lower() if prof else ""
    is_approved = (status == "approved") or ((prof or {}).get("status") is True)
    is_pending = status in ("pending", "waiting", "review")

    html = render_template(
        "account/profile.html",
        me_phone=me_phone,
        partner_status=("approved" if is_approved else ("pending" if is_pending else "none")),
        profile=prof or {},
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Vary"] = "Cookie"
    return resp


# -------------------------
# SEO: robots.txt, sitemap, legacy private URLs
# -------------------------
from ..utils.seo import (
    apply_x_robots_tag,
    build_robots_txt,
    build_sitemap_entries,
    render_sitemap_xml,
)


@main_bp.route("/robots.txt", endpoint="robots_txt")
def robots_txt():
    body = build_robots_txt()
    resp = make_response(body, 200)
    resp.mimetype = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@main_bp.route("/sitemap.xml", endpoint="sitemap_xml")
def sitemap_xml():
    entries = build_sitemap_entries(current_app._get_current_object())
    body = render_sitemap_xml(entries)
    resp = make_response(body, 200)
    resp.mimetype = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=600"
    return resp


def _legacy_redirect(endpoint: str, **kwargs):
    """Redirect legacy private/app URLs to current express partner routes."""
    from flask import session as _session

    resp = redirect(url_for(endpoint, **kwargs), code=302)
    return apply_x_robots_tag(resp, request.path, logged_in=bool(_session.get("user_phone")))


@main_bp.route("/app")
@main_bp.route("/app/")
def legacy_app_shell():
    return _legacy_redirect("express_partner.dashboard")


@main_bp.route("/my-lands")
@main_bp.route("/my-lands/")
def legacy_my_lands():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.dashboard")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.dashboard"))


@main_bp.route("/settings")
@main_bp.route("/settings/")
def legacy_settings():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.profile")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.profile"))


@main_bp.route("/careers/consultant/apply")
@main_bp.route("/careers/consultant/apply/")
def legacy_careers_apply():
    return _legacy_redirect("express_partner.apply")


@main_bp.route("/consultant/dashboard")
@main_bp.route("/consultant/dashboard/")
def legacy_consultant_dashboard():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.dashboard")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.dashboard"))


@main_bp.route("/express/partner/my-properties")
@main_bp.route("/express/partner/my-properties/")
def legacy_partner_my_properties():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.dashboard")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.dashboard"))

