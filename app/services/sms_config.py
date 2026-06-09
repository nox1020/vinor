"""تنظیمات sms.ir — از api_keys.py در ریشه پروژه."""
from app.keys import (
    get_sms_api_key,
    get_sms_line_number,
    get_sms_retriever_hash,
    get_sms_template_id,
)

__all__ = [
    "get_sms_api_key",
    "get_sms_template_id",
    "get_sms_line_number",
    "get_sms_retriever_hash",
]
