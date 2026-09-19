# app/routes/public.py
import os
from urllib.parse import quote

from flask import (
    render_template, send_from_directory, request, abort,
    redirect, url_for, session, make_response, current_app,
    has_app_context, has_request_context, jsonify,
)

from . import main_bp
from ..utils.storage import data_dir, legacy_dir
from ..utils.storage import load_express_partners_cached, load_landing_views, save_landing_views
from ..utils.short_urls import apk_public_download_filename, public_apk_download_url
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
ENAMAD_SEAL_ID = "747402"
ENAMAD_SEAL_CODE = "RezEMiH776DbFMbxMMPxhhAeTgqLfytW"
ENAMAD_TRUST_URL = (
    f"https://trustseal.enamad.ir/?id={ENAMAD_SEAL_ID}&Code={ENAMAD_SEAL_CODE}"
)
ENAMAD_LOGO_URL = (
    f"https://trustseal.enamad.ir/logo.aspx?id={ENAMAD_SEAL_ID}&Code={ENAMAD_SEAL_CODE}"
)

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
        "VINOR_HOME_URL": url_for("express_partner.home"),
        "VINOR_BRAND": "وینور اکسپرس",
        "VINOR_DOMAIN": "vinor.ir",
        "enamad_trust_url": ENAMAD_TRUST_URL,
        "enamad_seal_code": ENAMAD_SEAL_CODE,
        # نقش‌ها
        "VINOR_IS_EXPRESS_PARTNER": is_express_partner,
    }

# -------------------------
# Routes
# -------------------------

def _apk_size_label(settings) -> str:
    try:
        n = int((settings or {}).get("android_apk_size_bytes") or 0)
        if n >= 1_048_576:
            return f"{max(1, round(n / 1_048_576))} مگابایت"
        if n >= 1024:
            return f"{max(1, round(n / 1024))} کیلوبایت"
    except Exception:
        pass
    return ""


def _android_apk_page_vars() -> dict:
    settings = _get_cached_settings() or {}
    raw = str((settings or {}).get("android_apk_url") or "").strip()
    url = public_apk_download_url(settings, external=False) if raw else ""
    version = str((settings or {}).get("android_apk_version") or "").strip()
    return {
        "android_apk_url": url,
        "android_apk_version": version,
        "android_apk_size_label": _apk_size_label(settings),
        "android_apk_filename": apk_public_download_filename(settings) if url else "vinor.apk",
    }


def _guest_index_redirect_headers(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Vary"] = "Cookie"
    return resp


@main_bp.route("/", endpoint="index")
def index():
    """صفحهٔ اصلی vinor.ir — مهمان: لندینگ دانلود APK؛ واردشده: داشبورد."""
    nxt = request.args.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return _guest_index_redirect_headers(redirect(nxt))
    if session.get("logged_in"):
        return _guest_index_redirect_headers(redirect(url_for("admin.dashboard")))
    if session.get("user_phone"):
        from ..express_partner.routes import _redirect_after_login
        return _guest_index_redirect_headers(redirect(_redirect_after_login()))

    web = (request.args.get("web") or "").strip().lower()
    if web in ("1", "true", "yes", "on"):
        return _guest_index_redirect_headers(redirect(url_for("express_partner.home")))

    q = (request.args.get("q") or "").strip() or None
    city = (request.args.get("city") or "").strip() or None
    if q or city:
        return _guest_index_redirect_headers(
            redirect(url_for("express_partner.home", q=q, city=city))
        )

    try:
        from ..utils.apk_version import is_vinor_apk_request
        if is_vinor_apk_request(request):
            return _guest_index_redirect_headers(redirect(url_for("express_partner.home")))
    except Exception:
        pass

    cached = _mc_get("page:apk-landing")
    if cached:
        resp = make_response(cached)
        resp.headers["Cache-Control"] = "private, no-cache"
        resp.headers["Vary"] = "Cookie"
        return resp

    html = render_template("home/apk_download.html", **_android_apk_page_vars())
    try:
        _mc_set("page:apk-landing", html, ttl=15)
    except Exception:
        pass
    resp = make_response(html)
    resp.headers["Cache-Control"] = "private, no-cache"
    resp.headers["Vary"] = "Cookie"
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
        if session.get("user_phone"):
            from ..express_partner.routes import _redirect_after_login
            return redirect(_redirect_after_login())
        return redirect(url_for("express_partner.home"))

    # اول کش مهمان — ثبت بازدید نباید مسیر پاسخ کش‌شده را کند کند
    guest = not (session.get("user_phone") or session.get("user_id") or is_admin)
    if guest:
        cached = _mc_get("page:partners")
        if cached:
            resp = make_response(cached)
            resp.headers["Cache-Control"] = "no-cache"
            return resp

    # ثبت بازدید لندینگ (فقط برای کاربران غیرلاگین و غیرادمین و درخواست‌های مستقیم)
    # اگر referer از admin یا express/partner باشد، tracking نمی‌کنیم
    if '/admin' not in referer and '/express/partner' not in referer:
        try:
            views = load_landing_views() or []
            if not isinstance(views, list):
                views = []

            visitor_ip = request.remote_addr or ''
            now = datetime.utcnow()
            today_str = now.strftime('%Y-%m-%d')

            already_viewed_today = False
            # پیمایش از آخر + مقایسه سریع timestamp[:10] (بدون fromisoformat)
            for v in reversed(views):
                try:
                    if (v.get('ip') or '') != visitor_ip:
                        continue
                    if (v.get('timestamp') or '')[:10] == today_str:
                        already_viewed_today = True
                        break
                except Exception:
                    continue

            if not already_viewed_today and visitor_ip:
                views.append({
                    'timestamp': now.isoformat(),
                    'ip': visitor_ip,
                    'user_agent': request.headers.get('User-Agent', '')[:200]
                })
                if len(views) > 10000:
                    views = views[-10000:]
                save_landing_views(views)
        except Exception as e:
            current_app.logger.error(f"Error tracking landing view: {e}", exc_info=True)

    apk = _android_apk_page_vars()
    html = render_template(
        "home/partners.html",
        brand="وینور",
        domain="vinor.ir",
        android_apk_url=apk["android_apk_url"],
        android_apk_version=apk["android_apk_version"],
        android_apk_size_label=(
            f"حدود {apk['android_apk_size_label']}" if apk["android_apk_size_label"] else ""
        ),
    )
    if guest:
        try:
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
    target = url_for("express_partner.home")
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
    target = url_for('express_partner.home', q=q or None, city=city or None)
    return redirect(target, code=301)

@main_bp.route("/express/<code>", endpoint="express_detail")
def express_detail(code):
    """
    صفحه عمومی جزئیات فایل حذف شده است.
    لینک‌های قدیمی به صفحه جزئیات داخل پنل همکار هدایت می‌شوند.
    """
    return redirect(url_for('express_partner.land_detail', code=code), code=302)


@main_bp.route("/property/<code>", endpoint="property_deep_link")
def property_deep_link(code: str):
    """
    Deep Link عمومی فایل: https://vinor.ir/property/{id}
    در مرورگر → جزئیات پنل؛ در اپ با App Links باز می‌شود.
    """
    code_s = (code or "").strip()
    if not code_s:
        return redirect(url_for("express_partner.home"), code=302)
    return redirect(url_for("express_partner.land_detail", code=code_s), code=302)


@main_bp.route("/.well-known/assetlinks.json", endpoint="android_assetlinks")
def android_assetlinks():
    """Digital Asset Links برای Android App Links (package ir.vinor.app)."""
    from flask import Response, current_app
    import os

    candidates = [
        os.path.join(current_app.root_path, "static", ".well-known", "assetlinks.json"),
        os.path.join(current_app.static_folder or "", ".well-known", "assetlinks.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                body = f.read().strip()
            resp = Response(body, status=200, mimetype="application/json")
            resp.headers["Content-Type"] = "application/json"
            resp.headers["Cache-Control"] = "public, max-age=300"
            resp.headers["X-Content-Type-Options"] = "nosniff"
            return resp
    return Response("[]", status=404, mimetype="application/json")


@main_bp.route("/r/<ref>", endpoint="short_referral")
def short_referral(ref: str):
    """لینک کوتاه دعوت → فرم همکاری با ref در session/cookie."""
    from flask import make_response

    from ..utils.share_tokens import decode_partner_ref

    token = (ref or "").strip()
    if not token or not decode_partner_ref(token):
        return redirect(url_for("express_partner.apply"))

    from app.express_partner.referrals import (
        set_ref_cookie_on_response,
        store_referral_ref_token,
    )

    store_referral_ref_token(token)
    resp = make_response(redirect(url_for("express_partner.apply")))
    set_ref_cookie_on_response(resp, token)
    return resp


# strict_slashes=False: جلوگیری از 308 روی /d → /d/ (پروکسی/Werkzeug) که با گیت قدیمی
# به HTML لاگین ختم می‌شد و دانلود داخل اپ را می‌شکست.
@main_bp.route("/d", defaults={"download_name": None}, endpoint="short_apk_download", strict_slashes=False)
@main_bp.route("/d/<path:download_name>", endpoint="short_apk_download", strict_slashes=False)
def short_apk_download(download_name=None):
    """لینک کوتاه دانلود APK — نام فایل کاربر: vinor-{version}.apk"""
    from flask import send_file

    from ..utils.short_urls import (
        apk_file_url_from_settings,
        apk_public_download_filename,
        resolve_apk_filesystem_path,
    )
    from ..utils.storage import load_settings

    settings = load_settings() or {}
    target = apk_file_url_from_settings(settings)
    if not target:
        abort(404)

    download_as = apk_public_download_filename(settings)
    # اگر کلاینت نام دیگری در URL گذاشته بود، فقط الگوی vinor-*.apk امن را بپذیر
    if download_name:
        base = os.path.basename(str(download_name).replace("\\", "/")).strip()
        if base.lower().endswith(".apk") and base.lower().startswith("vinor"):
            download_as = base

    # از ریدایرکت به خود /d جلوگیری کن (حلقه)
    def _is_self_or_d_url(url: str) -> bool:
        u = (url or "").strip().lower()
        if not u:
            return True
        if u == "/d" or u.startswith("/d/") or u.startswith("/d?"):
            return True
        if "vinor.ir/d" in u.replace("www.", ""):
            return True
        return False

    if target.startswith(("http://", "https://")):
        if _is_self_or_d_url(target):
            abort(404)
        return redirect(target, code=302)

    fp, _ = resolve_apk_filesystem_path(settings)
    if fp and os.path.isfile(fp):
        resp = send_file(
            fp,
            mimetype="application/vnd.android.package-archive",
            as_attachment=True,
            download_name=download_as,
            conditional=False,
            max_age=300,
        )
        resp.headers["Cache-Control"] = "public, max-age=300"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Content-Type"] = "application/vnd.android.package-archive"
        return resp

    # مسیر ذخیره‌شده روی دیسک پیدا نشد — redirect به URL نسبی (نه دوباره /d)
    if _is_self_or_d_url(target):
        abort(404)
    return redirect(target, code=302)


@main_bp.route("/enamad-seal.png", endpoint="enamad_seal")
def enamad_seal():
    """
    پروکسی لوگوی اینماد — سرور trustseal فقط با Referer دامنهٔ ثبت‌شده تصویر می‌دهد.
    """
    cache_key = "enamad_seal_png"
    cached = _mc_get(cache_key)
    if cached:
        resp = make_response(cached)
        resp.headers["Content-Type"] = "image/png"
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp

    try:
        import requests

        upstream = requests.get(
            ENAMAD_LOGO_URL,
            headers={"Referer": "https://vinor.ir/"},
            timeout=12,
        )
        if upstream.status_code != 200 or not upstream.content:
            current_app.logger.warning(
                "enamad seal upstream %s (len=%s)",
                upstream.status_code,
                len(upstream.content or b""),
            )
            abort(404)
        body = upstream.content
        _mc_set(cache_key, body, ttl=300)
        resp = make_response(body)
        resp.headers["Content-Type"] = "image/png"
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
    except Exception as exc:
        current_app.logger.warning("enamad seal proxy failed: %s", exc)
        abort(502)


@main_bp.route("/healthz", methods=("GET", "HEAD"), endpoint="healthz")
def healthz():
    """پین سلامت برای تشخیص آنلاین/آفلاین در کلاینت.

    Default: 204 (کلاینت‌های فعلی فقط status را چک می‌کنند).
    GET /healthz?detail=1 → JSON غیرمحرمانه شامل وضعیت SMS OTP.
    """
    if request.method == "HEAD":
        resp = make_response("", 204)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    want_detail = (request.args.get("detail") or "").strip() == "1"
    if want_detail:
        try:
            from app.auth.otp.config import sms_health
            payload = {"ok": True, "sms": sms_health()}
        except Exception:
            payload = {"ok": True, "sms": {"enabled": False, "configured": False}}
        resp = jsonify(payload)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    resp = make_response("", 204)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@main_bp.route("/connection", endpoint="connection_check")
def connection_check():
    """صفحهٔ بررسی اتصال اینترنت."""
    resp = make_response(render_template("system/connection.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@main_bp.route("/uploads/<path:filename>", endpoint="uploaded_file")
def uploaded_file(filename):
    """سرو فایل‌های آپلود — با پشتیبانی resize اختیاری (?w=&q=)."""
    from ..utils.images import (
        make_resized_upload_response,
        parse_resize_request_args,
        redirect_if_legacy_variant_request,
    )

    legacy_redirect = redirect_if_legacy_variant_request()
    if legacy_redirect is not None:
        return legacy_redirect

    resize = parse_resize_request_args(request.args)
    cache_hdr = "public, max-age=86400, stale-while-revalidate=86400"
    safe_path = os.path.normpath(filename).replace("\\", "/")

    def _try_resized(fp: str):
        if resize and fp and os.path.isfile(fp):
            max_w, quality = resize
            resp = make_resized_upload_response(fp, max_w, quality)
            if resp is not None:
                return resp
        return None

    def _maybe_set_apk_download_name(resp):
        try:
            fn_norm = (filename or '').replace('\\', '/')
            if fn_norm.lower().endswith('.apk') and fn_norm.startswith('apk/'):
                try:
                    from ..utils.short_urls import apk_public_download_filename
                    from ..utils.storage import load_settings
                    settings = load_settings() or {}
                except Exception:
                    settings = {}
                wanted_url = str(settings.get('android_apk_url') or '')
                download_as = apk_public_download_filename(settings)
                if wanted_url and download_as:
                    try:
                        wanted_base = os.path.basename(wanted_url)
                    except Exception:
                        wanted_base = ''
                    if wanted_base and wanted_base == os.path.basename(fn_norm):
                        try:
                            disp = (
                                "attachment; filename*=UTF-8''"
                                + quote(download_as)
                                + '; filename="'
                                + download_as
                                + '"'
                            )
                            resp.headers['Content-Disposition'] = disp
                        except Exception:
                            resp.headers['Content-Disposition'] = (
                                'attachment; filename="' + download_as + '"'
                            )
                        resp.headers['Content-Type'] = (
                            'application/vnd.android.package-archive'
                        )
                        resp.headers['X-Content-Type-Options'] = 'nosniff'
        except Exception:
            pass
        return resp

    try:
        base_cfg = current_app.config.get("UPLOAD_FOLDER")
        if base_cfg:
            fp_cfg = os.path.join(base_cfg, safe_path)
            resized = _try_resized(fp_cfg)
            if resized is not None:
                return resized
            if os.path.isfile(fp_cfg):
                resp = send_from_directory(base_cfg, safe_path)
                resp = _maybe_set_apk_download_name(resp)
                resp.headers["Cache-Control"] = cache_hdr
                return resp
    except Exception:
        pass

    for folder in (
        os.path.join(data_dir(), "uploads"),
        os.path.join(legacy_dir(), "uploads"),
    ):
        fp = os.path.join(folder, safe_path)
        resized = _try_resized(fp)
        if resized is not None:
            return resized
        if os.path.isfile(fp):
            resp = send_from_directory(folder, safe_path)
            resp = _maybe_set_apk_download_name(resp)
            resp.headers["Cache-Control"] = cache_hdr
            return resp

    try:
        static_root = current_app.static_folder
        candidates = []
        if filename.startswith('uploads/'):
            candidates.append(os.path.join(static_root, filename))
            candidates.append(os.path.join(static_root, filename.lstrip('/')))
        else:
            candidates.append(os.path.join(static_root, 'uploads', filename))
        for cand in candidates:
            resized = _try_resized(cand)
            if resized is not None:
                return resized
            if os.path.isfile(cand):
                rel_dir = os.path.dirname(os.path.relpath(cand, static_root))
                fn = os.path.basename(cand)
                resp = send_from_directory(os.path.join(static_root, rel_dir), fn)
                resp = _maybe_set_apk_download_name(resp)
                resp.headers["Cache-Control"] = cache_hdr
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


def _commercial_buyer_ui_or_404():
    try:
        from app.commercial.config import commercial_buyer_ui_enabled
        if commercial_buyer_ui_enabled():
            return None
    except Exception:
        pass
    from flask import abort
    abort(404)


@main_bp.route("/my/offers", methods=["GET"], endpoint="my_offers")
def my_offers_page():
    """Phase 3 — پیشنهادهای خریدار (User OTP). فلگ BUYER_UI پیش‌فرض خاموش."""
    _commercial_buyer_ui_or_404()
    me_phone = (session.get("user_phone") or "").strip()
    if not me_phone:
        nxt = request.args.get("next") or url_for("main.my_offers")
        return redirect(url_for("express_partner.login", next=nxt))
    from app.commercial.service import list_buyer_offers

    offers = list_buyer_offers(me_phone)
    items = [
        {
            "id": o.id,
            "land_code": o.land_code,
            "amount": o.amount,
            "status": o.status,
            "terms": o.terms,
        }
        for o in offers
    ]
    return render_template(
        "my_offers.html",
        items=items,
        flash_msg=(request.args.get("msg") or "").strip(),
        flash_ok=(request.args.get("ok") or "1").strip() != "0",
    )


@main_bp.route("/my/offers/<offer_id>/respond", methods=["POST"], endpoint="my_offer_respond")
def my_offer_respond(offer_id: str):
    _commercial_buyer_ui_or_404()
    me_phone = (session.get("user_phone") or "").strip()
    if not me_phone:
        return redirect(url_for("express_partner.login", next=url_for("main.my_offers")))
    from app.commercial.service import get_offer, respond_offer
    from app.services.sms import normalize_iran_mobile as _norm

    offer = get_offer(offer_id)
    if not offer or _norm(offer.buyer_phone) != (_norm(me_phone) or me_phone):
        return redirect(url_for("main.my_offers", ok=0, msg="پیشنهاد یافت نشد."))
    action = (request.form.get("action") or "").strip().lower()
    out = respond_offer(offer_id, action=action, actor_key=me_phone)
    if not out:
        return redirect(url_for("main.my_offers", ok=0, msg="پاسخ نامعتبر بود."))
    return redirect(url_for("main.my_offers", ok=1, msg="وضعیت به‌روز شد."))


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
    return _legacy_redirect("express_partner.home")


@main_bp.route("/my-lands")
@main_bp.route("/my-lands/")
def legacy_my_lands():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.home")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.home"))


@main_bp.route("/settings")
@main_bp.route("/settings/")
def legacy_settings():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.home", menu=1)
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.home", menu=1))


@main_bp.route("/careers/consultant/apply")
@main_bp.route("/careers/consultant/apply/")
def legacy_careers_apply():
    return _legacy_redirect("express_partner.apply")


@main_bp.route("/consultant/dashboard")
@main_bp.route("/consultant/dashboard/")
def legacy_consultant_dashboard():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.home")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.home"))


@main_bp.route("/express/partner/my-properties")
@main_bp.route("/express/partner/my-properties/")
def legacy_partner_my_properties():
    if session.get("user_phone"):
        return _legacy_redirect("express_partner.home")
    return _legacy_redirect("express_partner.login", next=url_for("express_partner.home"))

