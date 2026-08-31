# app/__init__.py
# -*- coding: utf-8 -*-
"""
Vinor Express (vinor.ir) – Flask App Factory
- Mobile-first، امن و شفاف
- رجیستر بلوپرینت‌ها: main, admin, webhook, express_partner, uploads_api, push
- سرو sw.js و manifest.webmanifest از ریشه (با fallback)
- گِیت پیمایش مهمان/کاربر
- فقط صفحات همکار اکسپرس و پنل ادمین همکار اکسپرس
"""
import os
import logging
import mimetypes
from datetime import timedelta, datetime
from flask import (
    Flask, request, redirect, url_for, session, current_app, send_from_directory
)
from werkzeug.exceptions import RequestEntityTooLarge
from .utils.storage import load_settings

# CSRF (Flask-WTF)
try:
    from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
except Exception:
    CSRFProtect = None
    CSRFError = None
    def generate_csrf():  # fallback
        return ""

FIRST_VISIT_COOKIE = "vinor_first_visit_done"
SESSION_COOKIE_NAME = "vinor_session"
_STATIC_VERSION_CACHE: dict[str, tuple[int, str]] = {}


def _flask_debug() -> bool:
    return os.environ.get("FLASK_DEBUG", "0").strip().lower() in ("1", "true", "yes")


def _ensure_instance_folder(app: Flask) -> None:
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except Exception as e:
        app.logger.warning("Cannot ensure instance folder: %s", e)


def _setup_logging(app: Flask) -> None:
    class _SafeStreamHandler(logging.StreamHandler):
        """جلوگیری از OSError/BrokenPipe روی stderr بسته‌شدهٔ LSAPI."""

        def emit(self, record: logging.LogRecord) -> None:
            try:
                super().emit(record)
            except (OSError, ValueError, BrokenPipeError):
                pass

    handler = _SafeStreamHandler()
    handler.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    handler.setFormatter(fmt)
    if not any(isinstance(h, logging.StreamHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _register_jinja_filters(app: Flask) -> None:
    """ثبت فیلترهای Jinja موردنیاز پروژه: time_ago، date_ymd، your_time_filter، basename."""
    def _parse_dt(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value)
            except Exception:
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                pass
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt)
                except Exception:
                    continue
        return None

    @app.template_filter("static_version")
    def static_version(filename):
        """افزودن version query parameter به فایل‌های static برای جلوگیری از کش"""
        try:
            from flask import url_for, current_app

            static_path = os.path.join(current_app.static_folder, filename)
            if os.path.exists(static_path):
                mtime = int(os.path.getmtime(static_path))
                cached = _STATIC_VERSION_CACHE.get(filename)
                if cached and cached[0] == mtime:
                    return cached[1]
                base_url = url_for("static", filename=filename)
                result = f"{base_url}?v={mtime}"
                _STATIC_VERSION_CACHE[filename] = (mtime, result)
                return result
            return url_for("static", filename=filename)
        except Exception:
            try:
                return url_for("static", filename=filename)
            except Exception:
                return f"/static/{filename}"

    @app.template_filter("time_ago")
    def time_ago(value):
        dt = _parse_dt(value)
        if dt is None:
            return ""
        now = datetime.now(dt.tzinfo) if getattr(dt, "tzinfo", None) else datetime.now()
        diff = now - dt
        s = int(diff.total_seconds())
        if s < 60:
            return "چند لحظه پیش"
        m = s // 60
        if m < 60:
            return f"{m} دقیقه پیش"
        h = m // 60
        if h < 24:
            return f"{h} ساعت پیش"
        d = h // 24
        if d < 30:
            return f"{d} روز پیش"
        mo = d // 30
        if mo < 12:
            return f"{mo} ماه پیش"
        y = mo // 12
        return f"{y} سال پیش"

    @app.template_filter("date_ymd")
    def date_ymd(value, sep="-"):
        dt = _parse_dt(value)
        if dt is None:
            return ""
        return dt.strftime(f"%Y{sep}%m{sep}%d")

    @app.template_filter("your_time_filter")
    def your_time_filter(value):
        return time_ago(value)

    @app.template_filter("basename")
    def basename_filter(value):
        try:
            return os.path.basename(str(value)) if value is not None else ""
        except Exception:
            return ""

    @app.template_filter("fa_digits")
    def fa_digits_filter(value):
        try:
            return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        except Exception:
            return str(value or '')

    @app.template_filter("toman")
    def toman_filter(value, suffix: bool = True):
        try:
            s = str(value).replace(',', '').strip()
            if s == '' or s.lower() == 'none':
                return ''
            num = int(float(s))
            grouped = f"{num:,}"
            out = grouped.replace(',', '،').translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
            return (out + " تومان") if suffix else out
        except Exception:
            try:
                return (str(value) + (" تومان" if suffix else "")) if value is not None else ''
            except Exception:
                return ''


def _register_land_spec_globals(app: Flask) -> None:
    from .land_category_specs import (
        land_quick_stats,
        land_card_footer_stats,
        land_category_detail_rows,
        category_kind,
        price_basis_area,
        land_expert_verified,
    )

    app.add_template_global(land_quick_stats, "land_quick_stats")
    app.add_template_global(land_card_footer_stats, "land_card_footer_stats")
    app.add_template_global(land_category_detail_rows, "land_category_detail_rows")
    app.add_template_global(category_kind, "category_kind")
    app.add_template_global(price_basis_area, "price_basis_area")
    app.add_template_global(land_expert_verified, "land_expert_verified")


def _flask_instance_path() -> str:
    """مسیر instance مطلق — روی Passenger با INSTANCE_PATH یا پوشهٔ پروژه."""
    envp = os.environ.get("INSTANCE_PATH")
    if envp:
        return os.path.abspath(envp)
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance")
    )


def create_app() -> Flask:
    # اطمینان از MIME صحیح برای فونت‌ها (برخی سرورها پسوند woff2 را نمی‌شناسند)
    try:
        mimetypes.add_type('font/woff2', '.woff2')
        mimetypes.add_type('font/woff', '.woff')
    except Exception:
        pass

    instance_folder = _flask_instance_path()
    os.makedirs(instance_folder, exist_ok=True)
    app = Flask(__name__, instance_path=instance_folder, instance_relative_config=False)

    # ---------- پایه‌های امنیت/پیکربندی ----------
    app.secret_key = os.environ.get("SECRET_KEY") or "super-secret-key-change-this"

    default_upload_folder = os.path.join(app.root_path, "data", "uploads")
    os.makedirs(default_upload_folder, exist_ok=True)

    default_push_store = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data", "push_subs.json")
    )

    trust_proxy = os.environ.get("TRUST_PROXY", "1").strip().lower() in ("1", "true", "yes")
    cookie_secure_env = os.environ.get("SESSION_COOKIE_SECURE", "auto").strip().lower()
    if cookie_secure_env in ("1", "true", "yes"):
        cookie_secure = True
    elif cookie_secure_env in ("0", "false", "no"):
        cookie_secure = False
    else:
        cookie_secure = trust_proxy
    
    # کلیدهای VAPID: اول از environment variables، سپس از config
    from config import Config
    vapid_public = os.environ.get("VAPID_PUBLIC_KEY") or getattr(Config, "VAPID_PUBLIC_KEY", "")
    vapid_private = os.environ.get("VAPID_PRIVATE_KEY") or getattr(Config, "VAPID_PRIVATE_KEY", "")
    vapid_sub = os.environ.get("VAPID_SUB") or getattr(Config, "VAPID_SUB", "mailto:admin@vinor.ir")

    # Database URL (env first, then default to SQLite in instance folder)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass
    db_url = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(app.instance_path, 'vinor.db')}"

    app.config.update(
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
        PREFERRED_URL_SCHEME="https" if cookie_secure else "http",
        TEMPLATES_AUTO_RELOAD=True,
        JSON_AS_ASCII=False,
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER", default_upload_folder),
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Upload limit (برای ویدئو هم استفاده می‌شود)
        MAX_CONTENT_LENGTH=getattr(Config, "MAX_CONTENT_LENGTH", 200 * 1024 * 1024),
        VAPID_PUBLIC_KEY=vapid_public,
        VAPID_PRIVATE_KEY=vapid_private,
        # هر دو کلید برای سازگاری: dict و زیرکلید متنی
        VAPID_CLAIMS={"sub": vapid_sub},
        VAPID_CLAIMS_SUB=vapid_sub,
        PUSH_STORE_PATH=os.environ.get("PUSH_STORE_PATH", default_push_store),
        FCM_SERVICE_ACCOUNT_FILE=os.environ.get("FCM_SERVICE_ACCOUNT_FILE", getattr(Config, "FCM_SERVICE_ACCOUNT_FILE", "")),
        FCM_GOOGLE_SERVICES_FILE=os.environ.get("FCM_GOOGLE_SERVICES_FILE", getattr(Config, "FCM_GOOGLE_SERVICES_FILE", "")),
        FCM_PROJECT_ID=os.environ.get("FCM_PROJECT_ID", getattr(Config, "FCM_PROJECT_ID", "")),
        APP_BRAND_NAME="وینور اکسپرس | Vinor Express",
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_TIME_LIMIT=60 * 60 * 24 * 7,  # ۷ روز — هم‌راستا با کوکی XSRF و اپ موبایل
        WTF_CSRF_CHECK_DEFAULT=True,
        WTF_CSRF_METHODS=("POST", "PUT", "PATCH", "DELETE"),
    )

    _ensure_instance_folder(app)
    _setup_logging(app)
    _register_jinja_filters(app)
    _register_land_spec_globals(app)

    if trust_proxy:
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        except Exception as e:
            app.logger.warning("ProxyFix not applied: %s", e)

    @app.before_request
    def _redirect_admin_to_https():
        """ورود ادمین روی HTTP باعث از دست رفتن کوکی Secure می‌شود."""
        path = request.path or ""
        if not path.startswith("/admin"):
            return None
        if request.is_secure:
            return None
        host = (request.host or "").split(":")[0].lower()
        if host not in ("vinor.ir", "www.vinor.ir"):
            return None
        url = request.url
        if url.startswith("http://"):
            return redirect(url.replace("http://", "https://", 1), code=301)
        return None

    try:
        from .utils.storage import migrate_legacy
        from .ai.paths import ensure_escalations_file

        with app.app_context():
            migrate_legacy(app)
            ensure_escalations_file()
            try:
                from app.services.firebase_config import bootstrap_firebase
                bootstrap_firebase(app)
            except Exception as fb_err:
                app.logger.warning("Firebase bootstrap: %s", fb_err)
    except Exception as e:
        app.logger.warning("Data dir / AI escalations init: %s", e)

    try:
        from app.auth.otp.store import init_schema, purge_old_challenges
        from app.auth.otp.config import log_otp_startup
        with app.app_context():
            init_schema()
            purge_old_challenges()
        log_otp_startup(app.logger)
    except Exception as e:
        app.logger.warning("OTP store init skipped: %s", e)

    # Initialize DB (SQLAlchemy) — فقط وقتی لازم است
    try:
        from .extensions import db
        db.init_app(app)
        with app.app_context():
            if "sqlite" in db_url:
                db_file = db_url.split("///", 1)[-1]
                if not os.path.isfile(db_file) or os.environ.get("VINOR_DB_CREATE_ALL", "").strip() == "1":
                    db.create_all()
            elif os.environ.get("VINOR_DB_CREATE_ALL", "1").strip() not in ("0", "false", "no"):
                db.create_all()
    except Exception as e:
        app.logger.warning(f"DB init/create_all skipped: {e}")

    # Enable CORS for /api/* (mobile app consumption)
    try:
        from flask_cors import CORS  # type: ignore
        CORS(app, resources={r"/api/*": {"origins": "*"}})
    except Exception as e:
        app.logger.warning(f"CORS not enabled: {e}")

    # ---------- Upload too large (413) ----------
    @app.errorhandler(RequestEntityTooLarge)
    def handle_upload_too_large(e):
        from flask import flash
        try:
            max_mb = int(app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024))
        except Exception:
            max_mb = 0
        msg = "حجم فایل زیاد است."
        if max_mb:
            msg = f"حجم فایل زیاد است. حداکثر حجم مجاز: {max_mb}MB"
        flash(msg, "warning")
        return redirect(request.referrer or url_for("admin.express_listings"))

    @app.context_processor
    def inject_vinor_globals():
        is_logged = bool(session.get("user_id") or session.get("user_phone"))
        try:
            settings = load_settings(app)
        except Exception:
            settings = {}
        ep = (request.endpoint or "") if request else ""
        show_ai_fab = ep in (
            "express_partner.home",
        )
        return {
            "VAPID_PUBLIC_KEY": app.config.get("VAPID_PUBLIC_KEY", ""),
            "VINOR_IS_LOGGED_IN": is_logged,
            "APP_BRAND_NAME": app.config.get("APP_BRAND_NAME", "Vinor Express"),
            "csrf_token": generate_csrf,
            "SHOW_SUBMIT_BUTTON": bool(settings.get("show_submit_button", True)),
            "show_ai_fab": show_ai_fab,
        }

    # ---------- رجیستر بلوپرینت‌ها ----------
    from .routes import main_bp

    # Webhook blueprint
    webhook_bp = None
    try:
        from .routes.webhook import webhook_bp as _webhook_bp
        webhook_bp = _webhook_bp
    except Exception as e:
        app.logger.warning(f"Webhook blueprint not available: {e}")

    # Express API (برای پنل همکاران)
    express_api_bp = None
    try:
        from .api.express import express_api_bp as _express_api_bp
        express_api_bp = _express_api_bp
    except Exception as e:
        app.logger.warning(f"Express API disabled: {e}")

    # SMS API (برای ارتباط با sms.ir)
    sms_api_bp = None
    try:
        from .api.sms import sms_api_bp as _sms_api_bp
        sms_api_bp = _sms_api_bp
    except Exception as e:
        app.logger.warning(f"SMS API disabled: {e}")

    # Push API (برای Push Notifications)
    push_api_bp = None
    try:
        from .api.push import api_push_bp as _push_api_bp
        push_api_bp = _push_api_bp
    except Exception as e:
        app.logger.warning(f"Push API disabled: {e}")

    # FCM API (APK push when app closed)
    fcm_api_bp = None
    try:
        from .api.fcm import api_fcm_bp as _fcm_api_bp
        fcm_api_bp = _fcm_api_bp
    except Exception as e:
        app.logger.warning(f"FCM API disabled: {e}")

    # Uploads API (برای سرو فایل‌های /uploads/* و آپلودهای تصویری)
    uploads_bp = None
    try:
        from .api.uploads import uploads_bp as _uploads_bp
        uploads_bp = _uploads_bp
    except Exception as e:
        app.logger.warning(f"Uploads API disabled: {e}")

    # توجه: هیچ url_prefix اضافی نده؛ هر بلوپرینت خودش دارد.
    app.register_blueprint(main_bp)

    # Phase 5 Roles & Portals hubs (/my, /portal/seller, /portal/owner)
    try:
        from .roles.routes import roles_bp
        app.register_blueprint(roles_bp)
    except Exception as e:
        app.logger.warning("Roles portals blueprint not available: %s", e)

    if webhook_bp is not None:
        app.register_blueprint(webhook_bp)
    if express_api_bp is not None:
        app.register_blueprint(express_api_bp)
    try:
        from app.auth.otp.routes import auth_otp_bp
        app.register_blueprint(auth_otp_bp)
    except Exception as e:
        app.logger.warning("Auth OTP blueprint disabled: %s", e)
    try:
        from invest.backend import register_invest_backend
        register_invest_backend(app)
    except Exception as e:
        app.logger.warning("Invest backend disabled: %s", e)
    if sms_api_bp is not None:
        app.register_blueprint(sms_api_bp)
    if push_api_bp is not None:
        app.register_blueprint(push_api_bp)
    if fcm_api_bp is not None:
        app.register_blueprint(fcm_api_bp)
    if uploads_bp is not None:
        app.register_blueprint(uploads_bp)

    # Public REST API v1 (removed)

    # ---------- Caching headers ----------
    @app.after_request
    def add_cache_headers(resp):
        try:
            path = request.path or ""
            # اگر هدر Cache-Control قبلاً ست شده (مثلاً برای واریانت تصاویر)، دست نزن
            if resp.headers.get("Cache-Control"):
                return resp
            # Long cache for static assets and uploads
            if path.startswith("/static/") or path.startswith("/uploads/"):
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp
            # HTML should not be cached aggressively
            if (resp.mimetype or "").startswith("text/html"):
                # Allow revalidation while enabling browser re-fetch
                resp.headers["Cache-Control"] = "no-cache"
                return resp
            return resp
        except Exception:
            return resp

    @app.after_request
    def apply_seo_robots_headers(resp):
        """X-Robots-Tag for private/auth/dashboard pages."""
        try:
            from .utils.seo import apply_x_robots_tag
            logged_in = bool(session.get("user_phone") or session.get("user_id"))
            apply_x_robots_tag(resp, request.path or "", logged_in=logged_in)
        except Exception:
            pass
        return resp

    # Express Partner blueprint
    try:
        from .express_partner import express_partner_bp
        app.register_blueprint(express_partner_bp)
    except Exception as e:
        app.logger.warning(f"Express Partner blueprint not available: {e}")

    # AI blueprint (DeepSeek)
    try:
        from .ai import ai_bp
        app.register_blueprint(ai_bp)
        app.logger.info("AI blueprint registered: /ai")
    except Exception as e:
        app.logger.warning(f"AI blueprint not available: {e}")

    # Admin blueprint
    try:
        from admin import admin_bp
        app.register_blueprint(admin_bp)
        app.logger.info(f"Admin blueprint registered successfully: {admin_bp.name}")
    except Exception as e:
        app.logger.error(f"Admin blueprint registration failed: {e}", exc_info=True)

    # ---------- CSRF ----------
    if CSRFProtect is not None:
        csrf = CSRFProtect()
        csrf.init_app(app)

        # Webhook از CSRF مستثنا است
        if webhook_bp is not None:
            try:
                from .routes.webhook import git_webhook
                csrf.exempt(git_webhook)
            except Exception:
                pass

        # Express API از CSRF مستثنا است
        if express_api_bp is not None:
            try:
                csrf.exempt(express_api_bp)
            except Exception:
                pass

        # SMS API از CSRF مستثنا است
        if sms_api_bp is not None:
            try:
                csrf.exempt(sms_api_bp)
            except Exception:
                pass

        # Push API از CSRF مستثنا است (برای /api/push/subscribe و ...)
        if push_api_bp is not None:
            try:
                csrf.exempt(push_api_bp)
            except Exception:
                pass

        if fcm_api_bp is not None:
            try:
                csrf.exempt(fcm_api_bp)
            except Exception:
                pass

        try:
            from app.auth.otp.routes import auth_otp_bp
            csrf.exempt(auth_otp_bp)
        except Exception:
            pass

        try:
            from invest.backend.routes.api import invest_api_bp
            csrf.exempt(invest_api_bp)
        except Exception:
            pass

        # خروج و به‌روزرسانی پروفایل اپ اندروید (POST با کوکی، بدون CSRF)
        # خروج وب همکار: بدون CSRF تا با توکن کهنه در تب باز طولانی یا PWA خراب نشود
        for endpoint in (
            "express_partner.api_logout",
            "express_partner.api_profile_update",
            "express_partner.api_profile_avatar",
            "express_partner.api_login_request",
            "express_partner.api_verify",
            "auth_otp.request_otp_view",
            "auth_otp.verify_otp_view",
            "express_partner.logout",
            "express_partner.login",
            "express_partner.verify",
            "express_partner.otp_resend",
            "express_partner.ai_chat",
            "express_partner.ai_clear",
            "express_partner.ai_switch_thread",
            "express_partner.ai_delete_thread",
            "express_partner.ai_agent_confirm",
            "express_partner.ai_agent_cancel",
            "express_partner.api_favorites_cards",
            "express_partner.create_visit_request",
            "express_partner.mark_in_transaction",
            "ai.chat",
            "admin.login",
            "admin.logout",
        ):
            try:
                f = app.view_functions.get(endpoint)
                if f is not None:
                    csrf.exempt(f)
            except Exception:
                pass

        # APIهای JSON پرتال همکار — احراز هویت با session؛ CSRF در WebView/APK مشکل‌ساز است
        for rule in app.url_map.iter_rules():
            rule_path = (rule.rule or "").rstrip("/") or "/"
            if not rule_path.startswith("/express/partner/api"):
                continue
            if not rule.methods or not (rule.methods & {"POST", "PUT", "PATCH", "DELETE"}):
                continue
            try:
                view = app.view_functions.get(rule.endpoint)
                if view is not None:
                    csrf.exempt(view)
            except Exception:
                pass

        # API v1 removed



        @app.after_request
        def set_csrf_cookie(resp):
            try:
                ct = (resp.content_type or "").split(";")[0].strip().lower()
                if ct != "text/html":
                    return resp
                token = generate_csrf()
                resp.set_cookie(
                    "XSRF-TOKEN",
                    token,
                    secure=app.config.get("SESSION_COOKIE_SECURE", False),
                    samesite="Lax",
                    httponly=False,
                    path="/",
                    max_age=60 * 60 * 24 * 7,
                )
            except Exception:
                pass
            return resp

        if CSRFError is not None:
            @app.errorhandler(CSRFError)
            def handle_csrf_error(e):
                from flask import flash
                from app.utils.flash_messages import FLASH_AUTH_WARNING

                form = dict(request.form)
                for key in list(form):
                    lk = str(key).lower()
                    if "otp" in lk or lk in ("code", "password"):
                        form[key] = "***"
                current_app.logger.error(
                    "CSRF_ERROR: %s | path=%s | form=%s | headers=%s",
                    getattr(e, "description", str(e)),
                    request.path,
                    form,
                    dict(request.headers),
                )
                path = (request.path or "").rstrip("/")
                auth_paths = {
                    "/express/partner/login",
                    "/express/partner/verify",
                    "/express/partner/otp/resend",
                    "/express/partner/api/login-request",
                    "/auth/request-otp",
                    "/auth/verify-otp",
                    "/admin/login",
                }
                if path in auth_paths or path.startswith("/express/partner/login"):
                    flash(
                        "جلسه منقضی شده است. صفحه را تازه کنید و دوباره شماره موبایل را وارد کنید.",
                        FLASH_AUTH_WARNING,
                    )
                    if path == "/admin/login":
                        flash('لطفاً از آدرس https://vinor.ir/admin/login وارد شوید.', 'warning')
                        try:
                            return redirect(url_for("admin.login"))
                        except Exception:
                            return redirect("https://vinor.ir/admin/login")
                    try:
                        return redirect(url_for("express_partner.login"))
                    except Exception:
                        return redirect("/express/partner/login")
                path_api = (request.path or "").startswith("/express/partner/api/")
                wants_json = (
                    path_api
                    or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                    or "application/json" in (request.headers.get("Accept") or "")
                )
                if wants_json:
                    from flask import jsonify

                    fresh_token = generate_csrf()
                    resp = jsonify(
                        {
                            "ok": False,
                            "error": "csrf_expired",
                            "message": "جلسه منقضی شده؛ صفحه را تازه کنید.",
                            "csrf_token": fresh_token,
                        }
                    )
                    resp.status_code = 400
                    resp.headers["X-CSRF-Token"] = fresh_token
                    try:
                        resp.set_cookie(
                            "XSRF-TOKEN",
                            fresh_token,
                            secure=app.config.get("SESSION_COOKIE_SECURE", False),
                            samesite="Lax",
                            httponly=False,
                            path="/",
                            max_age=60 * 60 * 24 * 7,
                        )
                    except Exception:
                        pass
                    return resp
                flash("لطفاً صفحه را تازه کنید و دوباره تلاش کنید.", "warning")
                try:
                    return redirect(request.referrer or url_for("lands.add_land"))
                except Exception:
                    return redirect(url_for("express_partner.home"))

    # ---------- فایل‌های PWA ----------
    # Service Worker وینور غیرفعال شد - فقط همکاران اکسپرس از Service Worker استفاده می‌کنند
    # اما برای جلوگیری از 404، یک fallback اضافه می‌کنیم
    @app.get("/sw.js")
    def service_worker_fallback():
        """Fallback route for /sw.js - redirects to express partner service worker"""
        from flask import redirect, url_for
        try:
            return redirect(url_for('express_partner.service_worker'), code=302)
        except Exception:
            # اگر route پیدا نشد، یک empty response برگردان
            from flask import Response
            return Response("// Service Worker not available", 
                          mimetype="application/javascript", 
                          status=404)

    @app.get("/manifest.webmanifest")
    def serve_manifest():
        from flask import Response
        static_dir = os.path.join(app.root_path, "static")
        file_path = os.path.join(static_dir, "manifest.webmanifest")
        mimetype = "application/manifest+json"

        if os.path.exists(file_path):
            return send_from_directory(static_dir, "manifest.webmanifest", mimetype=mimetype)

        fallback_json = r'''{
          "id": "/",
          "name": "وینور",
          "short_name": "وینور",
          "description": "وینور؛ تجربه سریع، امن و شفاف برای خرید و فروش زمین، باغ، ویلا و آپارتمان.",
          "dir": "rtl",
          "lang": "fa",
          "start_url": "/express/partner/?source=pwa",
          "scope": "/",
          "display": "standalone",
          "display_override": ["window-controls-overlay", "standalone", "minimal-ui"],
          "orientation": "portrait",
          "background_color": "#ffffff",
          "theme_color": "#16a34a",
          "icons": [
            { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
            { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
          ],
          "shortcuts": [
            { "name": "داشبورد", "short_name": "داشبورد", "url": "/express/partner/home" }
          ],
          "capture_links": "existing-client-navigate",
          "launch_handler": { "client_mode": "auto" }
        }'''
        return Response(fallback_json, status=200, mimetype=mimetype)

    # ---------- Gate ----------
    try:
        from app.express_partner.user_celebration_sms import schedule_daily_celebration_sms
        schedule_daily_celebration_sms(app)
    except Exception as e:
        app.logger.warning("Celebration SMS scheduler not started: %s", e)

    try:
        from app.express_partner.sales_coach import schedule_sales_coach_nudge
        schedule_sales_coach_nudge(app)
    except Exception as e:
        app.logger.warning("Sales coach nudge scheduler not started: %s", e)

    try:
        from app.reach.scheduler import schedule_reach

        schedule_reach(app)
    except Exception as e:
        app.logger.warning("Reach scheduler not started: %s", e)

    try:
        from admin.sms_scheduled import schedule_admin_sms_jobs
        schedule_admin_sms_jobs(app)
    except Exception as e:
        app.logger.warning("Admin SMS scheduler not started: %s", e)

    # Phase 19: Continuous Optimization — background, default ON
    try:
        from app.optimization.scheduler import start_optimization_scheduler

        start_optimization_scheduler(app)
    except Exception as e:
        app.logger.warning("Optimization scheduler not started: %s", e)

    @app.before_request
    def landing_gate():
        debug = app.debug or _flask_debug()
        # Digital Asset Links — must never redirect (Android App Links verification)
        if request.path.startswith("/.well-known/"):
            if debug:
                current_app.logger.debug("PASS (well-known): %s", request.path)
            return

        # مسیری که گیت‌وی اصلاً در آن دخالت نکند (پنل ادمین، خودش لایهٔ امنیتی جدا دارد)
        if request.path.startswith("/admin"):
            if debug:
                current_app.logger.debug("PASS (admin-scope): %s", request.path)
            return

        # دانلود عمومی APK قبل از بقیهٔ گیت — /d، /d/، /d/vinor-{ver}.apk
        # (قبلاً فقط "/d" در safe_paths بود؛ URL نسخه‌دار یا 308 به /d/ → HTML خانه)
        path_now = request.path or ""
        if path_now == "/d" or path_now == "/d/" or path_now.startswith("/d/"):
            if debug:
                current_app.logger.debug("PASS (apk-download): %s", path_now)
            return

        safe_prefixes = ("/static", "/api", "/uploads", "/auth", "/invest")
        if path_now.startswith(safe_prefixes):
            if debug:
                current_app.logger.debug("PASS (prefix): %s", path_now)
            return

        safe_paths = {
            "/", "/start", "/login", "/verify", "/logout",
            "/favicon.ico", "/robots.txt", "/sitemap.xml",
            "/site.webmanifest", "/manifest.webmanifest", "/sw.js",
            "/git-webhook", "/git-webhook/",
            "/healthz", "/diag", "/connection",
            "/d", "/d/",  # belt-and-suspenders با چک بالا
            # Public help pages (accessible بدون لاگین)
            "/help", "/راهنما",
            "/privacy",
            # Public landing pages
            "/partners",
            "/enamad-seal.png",
            # Express Partner auth paths (public)
            "/express/partner/login", "/express/partner/login/otp", "/express/partner/verify", "/express/partner/otp/resend",
            "/express/partner/api/login-request", "/express/partner/api/verify",
            # Express listings (public)
            "/express",
            "/public",  # صفحه اکسپلور عمومی - بدون نیاز به ورود
            "/ai",  # Vinor AI برای کاربر عادی (مهمان با session مهمان)
        }
        # Public dynamic paths (prefix-based)
        public_prefixes = ("/express/", "/uploads/", "/ai/", "/r/", "/property/")
        if request.path.startswith(public_prefixes):
            if debug:
                current_app.logger.debug("PASS (public-prefix): %s", request.path)
            return
        if request.path in safe_paths:
            if debug:
                current_app.logger.debug("PASS (path): %s", request.path)
            return

        user_logged_in = bool(session.get("user_id") or session.get("user_phone"))

        if user_logged_in:
            if debug:
                current_app.logger.debug("PASS (logged-in): %s", request.path)
            return

        if debug:
            current_app.logger.debug("REDIRECT → dashboard (guest): %s", request.path)
        return redirect(url_for("express_partner.home"))

    return app
