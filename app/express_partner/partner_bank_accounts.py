# -*- coding: utf-8 -*-
"""کاتالوگ بانک و اعتبارسنجی/ماسک برای حساب‌های بانکی همکار اکسپرس."""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

PARTNER_BANK_CATALOG: List[Dict[str, str]] = [
    {"key": "mellat", "name": "بانک ملت", "abbr": "ملت", "color": "#c62828"},
    {"key": "melli", "name": "بانک ملی ایران", "abbr": "ملی", "color": "#1565c0"},
    {"key": "parsian", "name": "بانک پارسیان", "abbr": "پارس", "color": "#6a1b9a"},
    {"key": "saderat", "name": "بانک صادرات ایران", "abbr": "صادرات", "color": "#2e7d32"},
    {"key": "tejarat", "name": "بانک تجارت", "abbr": "تجارت", "color": "#0277bd"},
    {"key": "pasargad", "name": "بانک پاسارگاد", "abbr": "پاسارگاد", "color": "#37474f"},
    {"key": "saman", "name": "بانک سامان", "abbr": "سامان", "color": "#00838f"},
    {"key": "eghtesad", "name": "بانک اقتصاد نوین", "abbr": "نوین", "color": "#6d4c41"},
    {"key": "other", "name": "سایر بانک‌ها", "abbr": "بانک", "color": "#455a64"},
]


def bank_by_key(key: str) -> Optional[Dict[str, str]]:
    k = (key or "").strip().lower()
    for b in PARTNER_BANK_CATALOG:
        if b["key"] == k:
            return dict(b)
    return None


def _digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def luhn_ok(num: str) -> bool:
    d = _digits(num)
    if len(d) < 13 or len(d) > 19:
        return False
    arr = [int(x) for x in d]
    s = 0
    parity = len(arr) % 2
    for i, n in enumerate(arr):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return s % 10 == 0


def normalize_sheba(raw: str) -> str:
    s = (raw or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    if not s.startswith("IR"):
        s = "IR" + s
    body = "IR" + re.sub(r"\D+", "", s[2:])
    if len(body) != 26:
        return ""
    return body


def mask_pan_display(prefix4: str, last4: str) -> str:
    p = _digits(prefix4)[:4].ljust(4, "0") if prefix4 else "0000"
    l = _digits(last4)[-4:].rjust(4, "0") if last4 else "0000"
    return f"{p[:4]} **** **** {l[-4:]}"


def format_pan_display(pan: str) -> str:
    """نمایش ۱۶ رقم کارت به‌صورت ۴×۴ (فقط پنل ادمین)."""
    d = _digits(pan)
    if len(d) != 16:
        return d
    return f"{d[0:4]} {d[4:8]} {d[8:12]} {d[12:16]}"


def validate_new_account(
    bank_key: str,
    pan16: str,
    holder_name: str,
    sheba_raw: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    bk = bank_by_key(bank_key)
    if not bk:
        return None, "invalid_bank"

    name = (holder_name or "").strip()
    if len(name) < 2 or len(name) > 80:
        return None, "invalid_holder"

    pan = _digits(pan16)
    if len(pan) != 16:
        return None, "invalid_pan"

    prefix4, last4 = pan[:4], pan[-4:]
    sheba = normalize_sheba(sheba_raw) if (sheba_raw or "").strip() else ""
    if (sheba_raw or "").strip() and not sheba:
        return None, "invalid_sheba"

    rec: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "bank_key": bk["key"],
        "bank_name": bk["name"],
        "abbr": bk["abbr"],
        "color": bk["color"],
        "holder_name": name,
        "pan": pan,
        "pan_prefix4": prefix4,
        "pan_last4": last4,
        "sheba": sheba,
        "created_at": None,
        "is_default": False,
    }
    return rec, None


def public_account_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """فیلدهای امن برای JSON و UI (بدون شماره کامل)."""
    pfx = str(row.get("pan_prefix4") or "")[:4]
    lst = str(row.get("pan_last4") or "")[-4:]
    masked = mask_pan_display(pfx, lst)
    summary = f"{row.get('bank_name') or ''} · {masked}".strip(" ·")
    return {
        "id": row.get("id"),
        "bank_key": row.get("bank_key"),
        "bank_name": row.get("bank_name"),
        "abbr": row.get("abbr") or (bank_by_key(str(row.get("bank_key") or "")) or {}).get("abbr", "بانک"),
        "color": row.get("color") or (bank_by_key(str(row.get("bank_key") or "")) or {}).get("color", "#455a64"),
        "holder_name": row.get("holder_name") or "",
        "masked_pan": masked,
        "summary": summary,
        "is_default": bool(row.get("is_default")),
        "created_at": row.get("created_at") or "",
    }


def admin_account_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """فیلدهای حساب بانکی برای پنل ادمین — شامل شماره کارت کامل."""
    out = public_account_dict(row)
    out["sheba"] = str(row.get("sheba") or "").strip()
    pan = _digits(str(row.get("pan") or ""))
    if len(pan) == 16:
        out["display_pan"] = format_pan_display(pan)
    else:
        out["display_pan"] = out.get("masked_pan") or ""
    return out


def accounts_for_phone(all_rows: List[Dict[str, Any]], phone: str) -> List[Dict[str, Any]]:
    from .partner_withdrawals import partner_phones_match

    return [r for r in all_rows if isinstance(r, dict) and partner_phones_match(r.get("phone"), phone)]


def catalog_public() -> List[Dict[str, str]]:
    return [{"key": b["key"], "name": b["name"]} for b in PARTNER_BANK_CATALOG]
