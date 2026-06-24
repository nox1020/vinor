# -*- coding: utf-8 -*-
"""اعتبارسنجی کد ملی ایران."""
from __future__ import annotations

_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_digits(value: str) -> str:
    """تبدیل ارقام فارسی/عربی به لاتین و حذف غیرعدد."""
    s = str(value or "").strip().translate(_DIGIT_MAP)
    return "".join(c for c in s if c.isdigit())


def is_valid_iran_national_id(value: str) -> bool:
    """بررسی ۱۰ رقمی بودن و رقم کنترل کد ملی."""
    s = normalize_digits(value)
    if len(s) != 10 or not s.isdigit():
        return False
    if len(set(s)) == 1:
        return False
    check = int(s[9])
    total = sum(int(s[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    if remainder < 2:
        return check == remainder
    return check == 11 - remainder
