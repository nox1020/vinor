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
    "VINOR_WEBHOOK_SECRET",
    "get_deepseek_api_key",
    "get_sms_api_key",
    "get_sms_template_id",
    "get_sms_line_number",
]


def get_deepseek_api_key() -> str:
    return (DEEPSEEK_API_KEY or "").strip()


def get_sms_api_key() -> str:
    return (SMS_API_KEY or "").strip()


def get_sms_template_id() -> int:
    try:
        return int(SMS_TEMPLATE_ID)
    except (TypeError, ValueError):
        return 878451


def get_sms_line_number() -> str:
    return (SMS_LINE_NUMBER or "300089930616").strip()
