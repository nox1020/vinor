"""تأیید/انصراف اقدام‌های پیشنهادی — تنها درِ ورودی مسیر «کارت تأیید».

پیاده‌سازی در `agent_tools` است (توکن pending، ثبت واقعی در Backend، به‌روزرسانی
کارت در چت). این ماژول همان را زیر یک نام روشن جمع می‌کند تا routeها و
`assistant.py` به فایل ۵۶۰۰ خطی وابسته نباشند.
"""
from __future__ import annotations

from typing import Any


def confirm_action(*, phone: str, token: str) -> dict[str, Any]:
    """اجرای واقعی اقدام پس از تأیید کاربر."""
    from .agent_tools import confirm_action_from_token

    return confirm_action_from_token(phone=phone, token=token)


def cancel_action(
    *,
    phone: str,
    token: str,
    thread_id: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    from .agent_tools import cancel_pending_action

    return cancel_pending_action(
        phone=phone,
        token=token,
        thread_id=thread_id,
        audience=audience,
    )


def apply_confirm_to_chat(
    *,
    phone: str,
    token: str,
    thread_id: str | None,
    audience: str | None,
    confirm_out: dict[str, Any],
) -> dict[str, Any]:
    """کارت زندهٔ چت را بعد از تأیید به‌روز کن."""
    from .agent_tools import apply_confirm_result_to_chat

    return apply_confirm_result_to_chat(
        phone=phone,
        token=token,
        thread_id=thread_id,
        audience=audience,
        confirm_out=confirm_out,
    )


def has_pending_confirm_card(actions: list[dict[str, Any]] | None) -> bool:
    """آیا در پاسخ همین نوبت کارت تأیید بازی هست؟"""
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        card_type = str(a.get("type") or "")
        state = str(a.get("state") or a.get("status") or "pending").strip().lower()
        if card_type.startswith("confirm_") and state in ("pending", ""):
            return True
    return False
