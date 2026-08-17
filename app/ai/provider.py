"""لایهٔ ارائه‌دهندهٔ مدل — تنها نقطهٔ تماس دستیار با API.

پیاده‌سازی HTTP همان `services._call_deepseek` است و مسیریابی/گیت اعتبار در
`provider_router.call_ai`. این ماژول فقط قرارداد را روشن و typed می‌کند تا
`assistant.py` به جزئیات DeepSeek وابسته نباشد.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ProviderReply(TypedDict, total=False):
    ok: bool
    reply: str
    tool_calls: list[dict[str, Any]]
    reasoning_content: str
    meta: dict[str, Any]
    error: str
    error_code: str
    balance_depleted: bool
    spend_fuse: bool


def call_model(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> ProviderReply:
    """یک فراخوان مدل. هرگز استثنا پرتاب نمی‌کند؛ خطا در `ok=False` می‌آید."""
    from .provider_router import call_ai

    try:
        out = call_ai(
            messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception:
        return {
            "ok": False,
            "error": "خطا در دریافت پاسخ از سرویس هوش مصنوعی. لطفاً دوباره تلاش کنید.",
            "error_code": "provider_failed",
        }
    return out if isinstance(out, dict) else {"ok": False, "error": "پاسخی دریافت نشد."}


def provider_status() -> dict[str, Any]:
    """وضعیت کلید/اعتبار/شیر اطمینان — برای گیت‌های قبل از ساخت prompt."""
    from .services import ai_config

    return ai_config()


def is_usable() -> bool:
    from .config import get_deepseek_api_key
    from .credits import is_api_balance_depleted, is_spend_fuse_tripped

    try:
        return (
            bool(get_deepseek_api_key())
            and not is_api_balance_depleted()
            and not is_spend_fuse_tripped()
        )
    except Exception:
        return False
