"""پیام شروع‌کنندهٔ چت — وینور همیشه اول حرف می‌زند."""
from __future__ import annotations

from typing import Any

WELCOME_SOURCE = "welcome"

_OPENING_PARTNER = (
    "سلام بازاریاب فروش 👋\n"
    "چطور کمک کنم؟ از همین چت:\n"
    "۱) مشتری داری — بودجه، متراژ، نوع ملک را بفرست تا فایل مناسب پیدا کنم.\n"
    "۲) فایل برای بازاریابی می‌خواهی — بگو چه نوعی (زمین/باغ/ویلا، متراژ، بودجه)."
)

_OPENING_PENDING = (
    "سلام، چطور کمک کنم؟\n"
    "درخواست بازاریابی‌ات در حال بررسی است — تا تأیید، از همین چت بگو دنبال چه فایلی هستی "
    "یا اگر خرید می‌خواهی معیارت را بفرست."
)

_OPENING_PUBLIC = (
    "سلام، چطور کمک کنم؟\n"
    "۱) خرید فایل در گرمابسرد — معیارت را بفرست.\n"
    "۲) می‌خواهی بازاریاب شوی و بفروشی — بگو تا راهنمایی‌ات کنم."
)

_OPENING_ADMIN = (
    "سلام — دستیار عملیات وینور.\n"
    "از همین چت می‌توانی: پیام همگانی بفرستی، فایل اضافه کنی، "
    "همکار را تأیید کنی، بازدید/مالی را جلو ببری یا به escalation پاسخ بدهی.\n"
    "بگو چه کار کنیم؟"
)


def opening_text(
    *,
    is_approved: bool = False,
    has_pending_app: bool = False,
    audience: str | None = None,
) -> str:
    """متن شروع‌کنندهٔ وینور بر اساس وضعیت مخاطب."""
    if (audience or "").strip().lower() == "admin":
        return _OPENING_ADMIN
    if is_approved:
        return _OPENING_PARTNER
    if has_pending_app:
        return _OPENING_PENDING
    return _OPENING_PUBLIC


def is_welcome_message(msg: Any) -> bool:
    if not isinstance(msg, dict):
        return False
    if str(msg.get("source") or "").strip().lower() == WELCOME_SOURCE:
        return True
    meta = msg.get("meta")
    if isinstance(meta, dict) and meta.get("welcome"):
        return True
    return False


def ensure_vinor_opens_chat(
    user_key: str,
    *,
    audience: str | None = None,
    thread_id: str | None = None,
    text: str | None = None,
    is_approved: bool = False,
    has_pending_app: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """اگر ترد هنوز گفتگوی واقعی ندارد، پیام شروع وینور را به‌عنوان اولین پیام بگذار."""
    from app.ai.chat_store import ensure_vinor_opening

    body = (text or "").strip() or opening_text(
        is_approved=is_approved,
        has_pending_app=has_pending_app,
        audience=audience,
    )
    return ensure_vinor_opening(
        user_key,
        body,
        audience=audience,
        thread_id=thread_id,
    )
