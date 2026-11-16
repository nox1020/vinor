"""مسیرها و تنظیمات 1probot داخل وینور.

داده‌های زمان اجرا (bot.db، tokens.json، لاگ‌ها، قفل‌ها، و رونوشت قابل‌نوشتن configs.json)
در «پوشهٔ داده» نگه داشته می‌شوند و در گیت نیستند:

    PROBOT_DATA_DIR            اگر تنظیم شده باشد
    $INSTANCE_PATH/probot      در غیر این صورت (همان instance وینور که deploy دست نمی‌زند)
    <repo>/instance/probot     اگر INSTANCE_PATH هم نباشد

اگر فایل پوشهٔ داده موجود نباشد، مقدار پیش‌فرض بسته‌شده در probot/configs.json خوانده می‌شود.
نوشتن همیشه روی فایل پوشهٔ داده است تا deploy فایل بسته‌شده را بازنویسی نکند و تنظیمات
زمان اجرا از بین نرود. env بر هر دو فایل اولویت دارد.
"""
from __future__ import annotations

import json
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)

# کلید configs.json  ←  نام متغیر محیطی
ENV_OVERRIDES = {
    "token": "PROBOT_BALE_TOKEN",
    "admin": "PROBOT_ADMIN_ID",
    "web_password": "PROBOT_WEB_PASSWORD",
    "divar_relay_url": "PROBOT_DIVAR_RELAY_URL",
    "divar_relay_secret": "PROBOT_DIVAR_RELAY_SECRET",
    "database": "PROBOT_DATABASE",
}

DEFAULT_CONFIG = {
    "database": "bot.db",
    "times": [8, 22],
    "stop_hour": 22,
    "stop_minute": 0,
    "start_hour": 8,
    "start_minute": 0,
    "active_weekdays": [0, 1, 2, 3, 4, 5, 6],
    "repeat_days": 365,
}


def data_dir(create: bool = True) -> str:
    raw = (os.environ.get("PROBOT_DATA_DIR") or "").strip()
    if raw:
        path = os.path.abspath(os.path.expanduser(raw))
    else:
        inst = (os.environ.get("INSTANCE_PATH") or "").strip()
        base = os.path.abspath(inst) if inst else os.path.join(REPO_ROOT, "instance")
        path = os.path.join(base, "probot")
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    return path


def data_path(name: str) -> str:
    if os.path.isabs(name):
        return name
    return os.path.join(data_dir(), name)


def config_file() -> str:
    """مسیر قابل‌نوشتن configs.json در پوشهٔ داده (نه فایل پیش‌فرض بسته‌شده)."""
    return data_path("configs.json")


def packaged_config_file() -> str:
    """پیش‌فرض داخل بسته که در گیت است؛ فقط خواندنی، fallback وقتی فایل پوشهٔ داده نباشد."""
    return os.path.join(PACKAGE_DIR, "configs.json")


def _read_json_dict(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def load_file_config() -> dict:
    """محتوای خام configs.json (بدون env). فایل پوشهٔ داده بر پیش‌فرض بسته اولویت دارد.

    برای بازنویسی، همیشه روی config_file() در پوشهٔ داده بنویسید — نه روی فایل بسته.
    """
    data_cfg = _read_json_dict(config_file())
    if data_cfg is not None:
        return data_cfg
    packed = _read_json_dict(packaged_config_file())
    return packed if packed is not None else {}


def seed_data_config() -> str:
    """اگر فایل پوشهٔ داده نباشد، پیش‌فرض بسته (یا {}) را آنجا کپی می‌کند.

    deploy درخت بسته را عوض می‌کند؛ بعد از اولین نوشتن، فایل پوشهٔ داده برنده است.
    """
    dest = config_file()
    if os.path.isfile(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = _read_json_dict(packaged_config_file()) or {}
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, dest)
    return dest


def load_config() -> dict:
    """پیش‌فرض‌ها + configs.json + env (env برنده است)."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_file_config())
    for key, env_name in ENV_OVERRIDES.items():
        val = (os.environ.get(env_name) or "").strip()
        if val:
            cfg[key] = val
    if not cfg.get("token") and cfg.get("bale_token"):
        cfg["token"] = cfg["bale_token"]
    return cfg


def _admin_ok(value) -> bool:
    try:
        return int(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def is_configured(cfg: dict | None = None) -> bool:
    """ربات فقط وقتی فعال است که توکن بله و شناسهٔ ادمین معتبر داشته باشیم."""
    if (os.environ.get("PROBOT_ENABLED") or "").strip() == "0":
        return False
    cfg = load_config() if cfg is None else cfg
    tok = str(cfg.get("token") or "").strip()
    if not tok or tok.upper().startswith("YOUR_"):
        return False
    return _admin_ok(cfg.get("admin"))
