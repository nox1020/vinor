"""بارگذاری کلیدها از api_keys.py در ریشه پروژه."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api_keys import (  # noqa: E402
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    SMS_API_KEY,
    SMS_LINE_NUMBER,
    SMS_RETRIEVER_HASH,
    SMS_TEMPLATE_ID,
    VINOR_WEBHOOK_SECRET,
)

__all__ = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "SMS_API_KEY",
    "SMS_TEMPLATE_ID",
    "SMS_LINE_NUMBER",
    "SMS_RETRIEVER_HASH",
    "VINOR_WEBHOOK_SECRET",
    "get_deepseek_api_key",
    "get_sms_api_key",
    "get_sms_template_id",
    "get_sms_line_number",
    "get_sms_retriever_hash",
]


def get_deepseek_api_key() -> str:
    """اولویت: settings.json → متغیر محیطی → api_keys.py"""
    import os

    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("ai")
        if isinstance(stored, dict):
            key = str(stored.get("api_key") or "").strip()
            if key:
                return key
    except Exception:
        pass
    env_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if env_key:
        return env_key
    return (DEEPSEEK_API_KEY or "").strip()


def get_sms_api_key() -> str:
    return (SMS_API_KEY or "").strip()


def get_sms_template_id() -> int:
    try:
        return int(SMS_TEMPLATE_ID)
    except (TypeError, ValueError):
        return 878451


def get_sms_line_number() -> str:
    return (SMS_LINE_NUMBER or "09981801922").strip()


def get_sms_retriever_hash() -> str:
    return (SMS_RETRIEVER_HASH or "").strip()
