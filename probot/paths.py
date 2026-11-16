"""مسیرها و تنظیمات 1probot داخل وینور.

داده‌های زمان اجرا (configs.json، bot.db، tokens.json، لاگ‌ها، قفل‌ها) هرگز داخل
گیت نیستند و در «پوشهٔ داده» نگه داشته می‌شوند:

    PROBOT_DATA_DIR            اگر تنظیم شده باشد
    $INSTANCE_PATH/probot      در غیر این صورت (همان instance وینور که deploy دست نمی‌زند)
    <repo>/instance/probot     اگر INSTANCE_PATH هم نباشد

مقادیر حساس را می‌توان با env هم داد؛ env بر configs.json اولویت دارد.
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
    return data_path("configs.json")


def load_file_config() -> dict:
    """فقط محتوای خام configs.json (بدون env). برای نوشتن دوباره در فایل همین را بخوانید."""
    try:
        with open(config_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


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
