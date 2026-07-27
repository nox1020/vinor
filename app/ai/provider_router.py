"""مسیریابی پاسخ AI — DeepSeek API."""
from __future__ import annotations

from typing import Any


def _deepseek(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    from .services import _call_deepseek

    return _call_deepseek(
        messages,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _api_usable() -> bool:
    from .config import get_deepseek_api_key
    from .credits import is_api_balance_depleted, is_spend_fuse_tripped

    return (
        bool(get_deepseek_api_key())
        and not is_api_balance_depleted()
        and not is_spend_fuse_tripped()
    )


def call_ai(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    if _api_usable():
        return _deepseek(
            messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    from .config import get_deepseek_api_key
    from .credits import SPEND_FUSE_ERROR, is_spend_fuse_tripped

    if not get_deepseek_api_key():
        return {
            "ok": False,
            "error": "کلید API هوش مصنوعی تنظیم نشده است.",
            "error_code": "no_api_key",
        }

    if is_spend_fuse_tripped():
        return {
            "ok": False,
            "error": SPEND_FUSE_ERROR,
            "error_code": "spend_fuse",
            "spend_fuse": True,
        }

    return {
        "ok": False,
        "error": "اعتبار API هوش مصنوعی کافی نیست.",
        "error_code": "balance_depleted",
        "balance_depleted": True,
    }
