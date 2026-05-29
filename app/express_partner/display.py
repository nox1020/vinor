"""نمایش پروفایل همکار — حروف اولیه آواتار و غیره."""
from __future__ import annotations


def partner_avatar_initials(name: str | None) -> str:
    """حرف اول (یا دو حرف از نام و نام‌خانوادگی) — نه رقم موبایل."""
    raw = (name or "").strip().replace("\u200c", " ")
    if not raw:
        return "؟"
    parts = [p for p in raw.split() if p]
    if len(parts) >= 2:
        first = parts[0][:1]
        last = parts[-1][:1] if parts[-1] != parts[0] else ""
        out = (first + last).strip()
        return out or first or "؟"
    if len(raw) >= 2:
        return raw[:2]
    return raw[:1] or "؟"


def phone_last4(phone: str | None) -> str:
    """۴ رقم آخر شماره موبایل (فقط ارقام) برای تأیید حذف حساب."""
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    if len(digits) >= 4:
        return digits[-4:]
    return digits
