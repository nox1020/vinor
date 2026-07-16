from __future__ import annotations

import re
from typing import Callable

from app.workflow.interfaces import ValidationResult

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _normalize_digits(text: str) -> str:
    return (text or "").translate(_DIGIT_MAP)


def validate_non_empty(value: str) -> ValidationResult:
    v = (value or "").strip()
    if not v:
        return ValidationResult(ok=False, error="لطفاً یک پاسخ وارد کنید.")
    return ValidationResult(ok=True, normalized=v)


def validate_price(value: str) -> ValidationResult:
    raw = _normalize_digits(value or "")
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return ValidationResult(ok=False, error="قیمت معتبر نیست. عدد وارد کنید.")
    amount = int(digits)
    if amount <= 0:
        return ValidationResult(ok=False, error="قیمت باید بزرگ‌تر از صفر باشد.")
    return ValidationResult(ok=True, normalized=str(amount))


def validate_area(value: str) -> ValidationResult:
    raw = _normalize_digits(value or "")
    m = re.search(r"(\d+(?:\.\d+)?)", raw.replace(",", ""))
    if not m:
        return ValidationResult(ok=False, error="متراژ معتبر نیست. عدد متر را بگویید.")
    area = float(m.group(1))
    if area <= 0 or area > 1_000_000:
        return ValidationResult(ok=False, error="متراژ خارج از بازه معقول است.")
    return ValidationResult(ok=True, normalized=str(area))


def validate_phone(value: str) -> ValidationResult:
    raw = _normalize_digits(value or "")
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    if not re.fullmatch(r"09\d{9}", digits):
        return ValidationResult(ok=False, error="شماره موبایل معتبر نیست (مثال: 09121234567).")
    return ValidationResult(ok=True, normalized=digits)


def validate_national_id(value: str) -> ValidationResult:
    digits = re.sub(r"\D", "", _normalize_digits(value or ""))
    if len(digits) != 10:
        return ValidationResult(ok=False, error="کد ملی باید ۱۰ رقم باشد.")
    if digits == digits[0] * 10:
        return ValidationResult(ok=False, error="کد ملی نامعتبر است.")
    return ValidationResult(ok=True, normalized=digits)


def validate_photos(value: str) -> ValidationResult:
    v = (value or "").strip().lower()
    if not v:
        return ValidationResult(ok=False, error="وضعیت تصاویر را بگویید (بله/خیر یا لینک).")
    # Accept yes/no or any descriptive text / url
    return ValidationResult(ok=True, normalized=(value or "").strip())


def validate_yes_no(value: str) -> ValidationResult:
    v = (value or "").strip()
    if re.match(r"^(بله|آره|بلی|yes|ok|باشه|ثبت|تأیید|تایید)([\s!.]*)$", v, re.I):
        return ValidationResult(ok=True, normalized="yes")
    if re.match(r"^(خیر|نه|no|انصراف|لغو)([\s!.]*)$", v, re.I):
        return ValidationResult(ok=True, normalized="no")
    return ValidationResult(ok=False, error="لطفاً «بله» یا «خیر» بگویید.")


def validate_land_code(value: str) -> ValidationResult:
    raw = _normalize_digits(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 4:
        return ValidationResult(ok=False, error="کد فایل معتبر نیست.")
    return ValidationResult(ok=True, normalized=digits)


def validate_deal_type(value: str) -> ValidationResult:
    v = (value or "").strip()
    if re.search(r"(پیش.?فروش|پیشفروش)", v, re.I):
        return ValidationResult(ok=True, normalized="pre_sale")
    if re.search(r"(فروش|قطعی|نهایی)", v, re.I):
        return ValidationResult(ok=True, normalized="sale")
    return ValidationResult(ok=False, error="نوع معامله را بگویید: فروش یا پیش‌فروش.")


VALIDATORS: dict[str, Callable[[str], ValidationResult]] = {
    "non_empty": validate_non_empty,
    "price": validate_price,
    "area": validate_area,
    "phone": validate_phone,
    "national_id": validate_national_id,
    "photos": validate_photos,
    "yes_no": validate_yes_no,
    "land_code": validate_land_code,
    "deal_type": validate_deal_type,
}


def validate_step(validator_key: str, value: str) -> ValidationResult:
    fn = VALIDATORS.get(validator_key or "non_empty", validate_non_empty)
    return fn(value)
