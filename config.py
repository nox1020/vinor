# app/config.py
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # .../app

def _abs(*parts: str) -> str:
    return os.path.abspath(os.path.join(*parts))

class Config:
    # --- امنیت و سشن ---
    SECRET_KEY = "vinor-dev-keep-it-constant-and-change-in-prod"  # در پروداکشن از متغیر محیطی بگیر
    SESSION_COOKIE_NAME = "vinor_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False         # چون روی HTTP محلی هستی؛ روی سرور HTTPS حتما True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=6)

    # --- CSRF (اگر Flask-WTF داری) ---
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 24 * 7  # ۷ روز
    # اگر از CSRFProtect بدون Flask-WTF استفاده می‌کنی، در تمپلیت <input name="csrf_token" ...> را خودت بگذار

    # --- دیباگ/رندر ---
    TEMPLATES_AUTO_RELOAD = True          # برای توسعه راحت‌تر
    JSON_AS_ASCII = False

    # --- مسیرهای داده و آپلود (یکدست داخل app/data) ---
    DATA_DIR = _abs(BASE_DIR, "data")
    UPLOAD_FOLDER = _abs(DATA_DIR, "uploads")        # app/data/uploads
    LANDS_FILE   = _abs(DATA_DIR, "lands.json")
    CONSULTS_FILE= _abs(DATA_DIR, "consults.json")
    USERS_FILE   = _abs(DATA_DIR, "users.json")
    SETTINGS_FILE= _abs(DATA_DIR, "settings.json")

    # --- محدودیت آپلود ---
    # برای ویدئو، 20MB کافی نیست. پیش‌فرض را 200MB گذاشتیم.
    # در صورت نیاز می‌توانید با env این را تغییر دهید:
    # VINOR_MAX_CONTENT_LENGTH_MB=300
    try:
        MAX_CONTENT_LENGTH = int(os.environ.get("VINOR_MAX_CONTENT_LENGTH_MB", "200")) * 1024 * 1024
    except Exception:
        MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB

    # --- VAPID Keys برای Web Push Notifications ---
    # کلیدهای ثابت برای تست و توسعه (در پروداکشن باید از environment variables استفاده شود)
    # این کلیدها به فرمت base64url هستند و معتبر هستند
    VAPID_PUBLIC_KEY = "BCEikptArx4_523jsZ1e0RedsGx34NonMWYkMSlsUU5vBqseQfHq0mZdI2sdL0h9nTcQQGO_jKMAXjdl1Q15jHQ"
    VAPID_PRIVATE_KEY = "dhvthKpfzxwl73td79EM41VuA6CSpvlg6zjTNQQv__A"
    VAPID_SUB = "mailto:admin@vinor.ir"

    # Firebase Cloud Messaging (APK) — مسیر JSON سرویس‌اکانت Firebase Admin
    FCM_SERVICE_ACCOUNT_FILE = os.environ.get("FCM_SERVICE_ACCOUNT_FILE", "")
    FCM_GOOGLE_SERVICES_FILE = os.environ.get("FCM_GOOGLE_SERVICES_FILE", "")
    FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True          # روی HTTPS
    # SECRET_KEY = os.environ.get("SECRET_KEY")  # حتماً از محیط بگیر

# helper: در app factory بعد از ساخت app، با این اسنیپت پوشه‌ها را مطمئن بساز:
# os.makedirs(app.config["DATA_DIR"], exist_ok=True)
# os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
