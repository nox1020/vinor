"""Secrets and service settings from the environment only.

Required names are enforced by ``require_startup_env`` before the app serves
traffic. Error text lists variable names and never secret values.
"""
from __future__ import annotations

import os

REQUIRED_ENV_VARS = (
    "SECRET_KEY",
    "SMS_API_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_PUBLIC_KEY",
    "DATABASE_URL",
    "VINOR_WEBHOOK_SECRET",
)

_DEEPSEEK_BASE_URL_DEFAULT = "https://api.deepseek.com"
_DEEPSEEK_MODEL_DEFAULT = "deepseek-v4-flash"
_SMS_TEMPLATE_ID_DEFAULT = 878451
_SMS_LINE_NUMBER_DEFAULT = "09981801922"
_SMS_RETRIEVER_HASH_DEFAULT = "4R707/AKLt0"
VAPID_SUB_DEFAULT = "mailto:admin@vinor.ir"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def missing_required_env() -> list[str]:
    return [name for name in REQUIRED_ENV_VARS if not _env(name)]


def require_startup_env() -> None:
    missing = missing_required_env()
    if not missing:
        return
    raise RuntimeError(
        "Refusing to start: missing required environment variable(s): "
        + ", ".join(missing)
    )


def get_sms_api_key() -> str:
    return _env("SMS_API_KEY")


def get_sms_template_id() -> int:
    raw = _env("SMS_TEMPLATE_ID")
    if not raw:
        return _SMS_TEMPLATE_ID_DEFAULT
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _SMS_TEMPLATE_ID_DEFAULT


def get_sms_line_number() -> str:
    return _env("SMS_LINE_NUMBER") or _SMS_LINE_NUMBER_DEFAULT


def get_sms_retriever_hash() -> str:
    return _env("SMS_RETRIEVER_HASH") or _SMS_RETRIEVER_HASH_DEFAULT


def get_deepseek_base_url() -> str:
    return (_env("DEEPSEEK_BASE_URL") or _DEEPSEEK_BASE_URL_DEFAULT).rstrip("/")


def get_deepseek_model() -> str:
    return _env("DEEPSEEK_MODEL") or _DEEPSEEK_MODEL_DEFAULT


def get_vapid_sub() -> str:
    return _env("VAPID_SUB") or VAPID_SUB_DEFAULT


def get_webhook_secret() -> str:
    return _env("VINOR_WEBHOOK_SECRET")


def get_deepseek_api_key() -> str:
    """Precedence: settings.json ``ai.api_key``, then ``DEEPSEEK_API_KEY``."""
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("ai")
        if isinstance(stored, dict):
            key = str(stored.get("api_key") or "").strip()
            if key:
                return key
    except Exception:
        pass
    return _env("DEEPSEEK_API_KEY")
