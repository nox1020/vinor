# -*- coding: utf-8 -*-
"""درخواست برداشت به سبک دیوار: مبلغ → مقصد (شبا) → تأیید → ثبت.

منبع حقیقت مالی همان partner_withdrawals است:
- قابل برداشت = پورسانت/اعتبار تأییدشده − درخواست‌های برداشت فعال − بلوکهٔ پورسانت آگهی‌ها.
- بلوکهٔ پورسانت (escrow) هرگز قابل برداشت نیست.
- مبلغ از لحظهٔ ثبت درخواست «رزرو» است (وضعیت pending/approved/processing از موجودی کم می‌شود)
  و با رد یا لغو خودبه‌خود آزاد می‌شود.
- واریز همچنان دستی و با تأیید ادمین مالی است؛ این ماژول هیچ پولی جابه‌جا نمی‌کند.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.utils.dates import format_display_jalali_date, to_fa_digits

FLOW_VERSION = 1
HOLDER_MIN = 2
HOLDER_MAX = 80
CHIP_STEPS = (10_000_000, 20_000_000, 50_000_000, 100_000_000)

# شناسهٔ بانک در شبا (رقم‌های ۵ تا ۷) → کلید کاتالوگ بانک
SHEBA_BANK_CODES: Dict[str, str] = {
    "012": "mellat",
    "017": "melli",
    "054": "parsian",
    "019": "saderat",
    "018": "tejarat",
    "057": "pasargad",
    "056": "saman",
    "055": "eghtesad",
}

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

TEXTS: Dict[str, str] = {
    "title": "برداشت از کیف پول",
    "amount_question": "چقدر می‌خواهید برداشت کنید؟",
    "amount_available": "قابل برداشت: {amount}",
    "amount_placeholder": "مبلغ دلخواه",
    "amount_suffix": "تومان",
    "amount_all": "همهٔ موجودی",
    "amount_min": "کمترین مبلغ برداشت {min} است.",
    "blocked_note": "{amount} برای پورسانت آگهی‌هایتان بلوکه است و قابل برداشت نیست.",
    "pending_note": "{amount} در درخواست‌های قبلی در انتظار واریز است.",
    "below_min_title": "فعلاً موجودی کافی برای برداشت ندارید",
    "below_min_body": "کمترین مبلغ برداشت {min} است و موجودی قابل برداشت شما {amount}.",
    "dest_question": "به کدام حساب واریز شود؟",
    "dest_saved": "حساب‌های شما",
    "dest_new": "شبای جدید",
    "dest_new_hint": "شمارهٔ شبا ۲۴ رقم است و با IR شروع می‌شود.",
    "sheba_placeholder": "۲۴ رقم شبا",
    "holder_label": "نام صاحب حساب",
    "holder_placeholder": "مثلاً علی رضایی",
    "holder_hint": "باید با نام صاحب حساب در بانک یکی باشد.",
    "summary_question": "اطلاعات برداشت را بررسی کنید",
    "summary_amount": "مبلغ برداشت",
    "summary_dest": "واریز به",
    "summary_holder": "صاحب حساب",
    "summary_after": "موجودی بعد از برداشت",
    "summary_note": "مبلغ از همین حالا کنار گذاشته می‌شود و بعد از تأیید پشتیبانی وینور به حسابتان واریز می‌شود. تا قبل از بررسی می‌توانید لغوش کنید.",
    "submit": "ثبت درخواست برداشت",
    "submitting": "در حال ثبت…",
    "next": "ادامه",
    "success_title": "درخواست برداشت ثبت شد",
    "success_body": "در انتظار بررسی پشتیبانی وینور است. نتیجه را پیامک می‌کنیم.",
    "success_tracking": "کد پیگیری",
    "success_status": "وضعیت",
    "back_to_wallet": "بازگشت به کیف پول",
    "requests_title": "درخواست‌های برداشت",
    "cancel": "لغو درخواست",
}

ERRORS: Dict[str, str] = {
    "invalid_amount": "مبلغ را درست وارد کنید.",
    "min_amount": "کمترین مبلغ برداشت {min} است.",
    "insufficient_balance": "این مبلغ از موجودی قابل برداشت شما بیشتر است.",
    "missing_bank": "حساب مقصد را انتخاب کنید.",
    "invalid_bank": "این حساب پیدا نشد. دوباره انتخاب کنید.",
    "sheba_required": "برای این حساب شبا ثبت نشده. یک شبای جدید وارد کنید.",
    "sheba_format": "شبا باید IR و ۲۴ رقم باشد.",
    "sheba_checksum": "این شمارهٔ شبا معتبر نیست. دوباره بررسی کنید.",
    "invalid_holder": "نام صاحب حساب را کامل بنویسید.",
    "invalid_request_id": "درخواست نامعتبر است. صفحه را دوباره باز کنید.",
    "save_failed": "ثبت درخواست انجام نشد. دوباره تلاش کنید.",
    "not_found": "این درخواست پیدا نشد.",
    "not_cancellable": "این درخواست دیگر قابل لغو نیست.",
}

STATUS_TONES: Dict[str, str] = {
    "pending": "amber",
    "approved": "blue",
    "processing": "blue",
    "paid": "green",
    "rejected": "red",
    "cancelled": "gray",
}


def _int(value: Any) -> int:
    try:
        return max(0, int(str(value).translate(_FA_DIGITS).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def toman(amount: Any) -> str:
    return to_fa_digits(f"{_int(amount):,}".replace(",", "٬")) + " تومان"


def error_message(code: str, *, min_amount: int = 0) -> str:
    msg = ERRORS.get(code or "", "") or "درخواست انجام نشد. دوباره تلاش کنید."
    return msg.replace("{min}", toman(min_amount))


# ---------------------------------------------------------------- Sheba

def normalize_sheba_input(raw: Any) -> str:
    """ورودی کاربر → «IR» + ۲۴ رقم، یا رشتهٔ خالی. ارقام فارسی، فاصله و خط تیره پذیرفته می‌شوند."""
    s = str(raw or "").translate(_FA_DIGITS).upper()
    s = re.sub(r"[\s\-_.‌]", "", s)
    if s.startswith("IR"):
        s = s[2:]
    if not re.fullmatch(r"\d{24}", s):
        return ""
    return "IR" + s


def sheba_checksum_ok(sheba: str) -> bool:
    """ISO 13616 (mod 97): چهار نویسهٔ اول به آخر، I=18 و R=27، باقیمانده باید ۱ باشد."""
    s = str(sheba or "").upper()
    if not re.fullmatch(r"IR\d{24}", s):
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    return int(digits) % 97 == 1


def validate_sheba(raw: Any) -> Tuple[str, Optional[str]]:
    sheba = normalize_sheba_input(raw)
    if not sheba:
        return "", "sheba_format"
    if not sheba_checksum_ok(sheba):
        return "", "sheba_checksum"
    return sheba, None


def mask_sheba(sheba: str) -> str:
    s = str(sheba or "").upper()
    if len(s) < 8:
        return ""
    return f"{s[:4]} •••• •••• {s[-4:]}"


def bank_key_for_sheba(sheba: str) -> str:
    s = str(sheba or "")
    return SHEBA_BANK_CODES.get(s[4:7], "other") if len(s) == 26 else "other"


def validate_holder(raw: Any) -> Tuple[str, Optional[str]]:
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if len(name) < HOLDER_MIN or len(name) > HOLDER_MAX or re.search(r"[<>{}\d]", name):
        return "", "invalid_holder"
    return name, None


def new_account_record(sheba: str, holder: str, phone: str, created_at: str, is_default: bool) -> Dict[str, Any]:
    """حساب فقط‌شبا (بدون کارت) برای مقصد برداشت."""
    import uuid

    from .partner_bank_accounts import bank_by_key

    bank = bank_by_key(bank_key_for_sheba(sheba)) or bank_by_key("other") or {}
    return {
        "id": uuid.uuid4().hex[:16],
        "phone": phone,
        "bank_key": bank.get("key", "other"),
        "bank_name": bank.get("name", ""),
        "abbr": bank.get("abbr", "بانک"),
        "color": bank.get("color", "#455a64"),
        "holder_name": holder,
        "pan_prefix4": "",
        "pan_last4": "",
        "sheba": sheba,
        "created_at": created_at,
        "is_default": bool(is_default),
        "source": "withdraw_wizard",
    }


# ---------------------------------------------------------------- balances

def earned_commission_total(commissions: List[Dict[str, Any]], phone: str) -> int:
    """پورسانت کسب‌شده از فروش (تأییدشده یا پرداخت‌شده). شارژ، تعدیل و بلوکه حساب نمی‌شوند."""
    return earned_commission_stats(commissions, phone)[0]


def earned_commission_stats(commissions: List[Dict[str, Any]], phone: str) -> Tuple[int, int]:
    """(مبلغ، تعداد) پورسانت‌های واقعی فروش."""
    from .commission_escrow import HOLD_TYPE
    from .partner_withdrawals import partner_phones_match

    total = 0
    count = 0
    for c in commissions or []:
        if not isinstance(c, dict) or not partner_phones_match(c.get("partner_phone"), phone):
            continue
        ctype = str(c.get("commission_type") or "")
        if ctype in ("manual_adjustment", HOLD_TYPE):
            continue
        if str(c.get("status") or "pending").strip() not in ("approved", "paid"):
            continue
        total += _int(c.get("commission_amount")) + _int(c.get("partial_paid_total"))
        count += 1
    return total, count


def balances(commissions: List[Dict[str, Any]], withdrawals: List[Dict[str, Any]], phone: str) -> Dict[str, int]:
    """هر مفهوم یک بار: قابل استفاده، بلوکه، در انتظار برداشت، پورسانت کسب‌شده، پورسانت در انتظار تأیید."""
    from .commission_escrow import held_total
    from .partner_withdrawals import (
        LOCK_RESERVE_STATUSES,
        available_for_new_withdrawal,
        partner_phones_match,
        reserved_withdrawal_total,
    )

    pending_commission = 0
    for c in commissions or []:
        if (isinstance(c, dict) and partner_phones_match(c.get("partner_phone"), phone)
                and str(c.get("commission_type") or "") != "manual_adjustment"
                and str(c.get("status") or "pending").strip() == "pending"):
            pending_commission += _int(c.get("commission_amount"))
    return {
        "available": int(available_for_new_withdrawal(commissions or [], withdrawals or [], phone)),
        "blocked": int(held_total(commissions or [], phone)),
        "pending_withdrawal": int(reserved_withdrawal_total(withdrawals or [], phone)),
        "pending_withdrawal_count": sum(
            1 for w in withdrawals or []
            if isinstance(w, dict) and partner_phones_match(w.get("phone"), phone)
            and str(w.get("status") or "pending").strip().lower() in LOCK_RESERVE_STATUSES
        ),
        "earned": earned_commission_total(commissions or [], phone),
        "pending_commission": pending_commission,
    }


def amount_chips(available: int, min_amount: int) -> List[Dict[str, Any]]:
    avail = _int(available)
    chips: List[Dict[str, Any]] = []
    if avail < min_amount:
        return chips
    for step in CHIP_STEPS:
        if min_amount <= step < avail:
            chips.append({"key": str(step), "amount": step, "label": _short_amount(step), "all": False})
    chips = chips[:3]
    chips.append({"key": "all", "amount": avail, "label": TEXTS["amount_all"], "sub": toman(avail), "all": True})
    return chips


def _short_amount(n: int) -> str:
    if n % 1_000_000 == 0:
        return to_fa_digits(str(n // 1_000_000)) + " میلیون"
    return toman(n)


def resolve_amount(raw: Any, take_all: Any, available: int, min_amount: int) -> Tuple[int, Optional[str]]:
    """«همهٔ موجودی» را سرور در لحظهٔ ثبت حساب می‌کند تا عدد کهنهٔ کلاینت مهم نباشد."""
    from .partner_withdrawals import parse_amount_strict

    if take_all in (True, 1, "1", "true", "on", "all"):
        amount = _int(available)
    else:
        parsed = parse_amount_strict(raw)
        if parsed is None or parsed <= 0:
            return 0, "invalid_amount"
        amount = parsed
    if amount < min_amount:
        return amount, "min_amount"
    if amount > _int(available):
        return amount, "insufficient_balance"
    return amount, None


# ---------------------------------------------------------------- destinations / requests

def saved_destinations(bank_rows: List[Dict[str, Any]], phone: str) -> List[Dict[str, Any]]:
    """فقط حساب‌هایی که شبای معتبر دارند مقصد برداشت‌اند (واریز ادمین با شبا است)."""
    from .partner_bank_accounts import accounts_for_phone

    out: List[Dict[str, Any]] = []
    for r in accounts_for_phone(bank_rows or [], phone):
        sheba = str(r.get("sheba") or "").upper()
        if not sheba_checksum_ok(sheba):
            continue
        out.append({
            "id": str(r.get("id") or ""),
            "bank_name": str(r.get("bank_name") or ""),
            "holder_name": str(r.get("holder_name") or ""),
            "sheba_masked": mask_sheba(sheba),
            "is_default": bool(r.get("is_default")),
            "color": str(r.get("color") or "#455a64"),
        })
    out.sort(key=lambda a: (0 if a["is_default"] else 1))
    return out


def tracking_code(wid: Any) -> str:
    from .partner_withdrawals import _tracking_code

    return _tracking_code(wid)


def destination_label(w: Dict[str, Any]) -> str:
    sheba = str(w.get("sheba") or "")
    if sheba:
        bank = str(w.get("bank_name") or "").strip()
        return (bank + " · " if bank else "") + mask_sheba(sheba)
    return str(w.get("bank_summary") or "حساب بانکی")


def request_row(w: Dict[str, Any]) -> Dict[str, Any]:
    from .partner_withdrawals import PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES, status_label

    st = str(w.get("status") or "pending").strip().lower()
    created = str(w.get("created_at") or "")
    return {
        "id": str(w.get("id") or ""),
        "tracking_code": tracking_code(w.get("id")),
        "amount": _int(w.get("amount")),
        "amount_label": toman(w.get("amount")),
        "status": st,
        "status_label": status_label(st),
        "tone": STATUS_TONES.get(st, "gray"),
        "destination": destination_label(w),
        "date_label": format_display_jalali_date(created[:10]) if created else "",
        "cancellable": st in PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES,
        "admin_note": str(w.get("admin_note") or "") if st == "rejected" else "",
    }


def request_rows(withdrawals: List[Dict[str, Any]], phone: str, limit: int = 20) -> List[Dict[str, Any]]:
    from .partner_withdrawals import partner_phones_match

    mine = [w for w in withdrawals or [] if isinstance(w, dict) and partner_phones_match(w.get("phone"), phone)]
    mine.sort(key=lambda w: str(w.get("created_at") or ""), reverse=True)
    return [request_row(w) for w in mine[:limit]]


def options_payload(
    *,
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    bank_rows: List[Dict[str, Any]],
    phone: str,
    min_amount: int,
) -> Dict[str, Any]:
    b = balances(commissions, withdrawals, phone)
    avail = b["available"]
    texts = dict(TEXTS)
    texts["amount_available"] = TEXTS["amount_available"].replace("{amount}", toman(avail))
    texts["amount_min"] = TEXTS["amount_min"].replace("{min}", toman(min_amount))
    texts["below_min_body"] = (TEXTS["below_min_body"].replace("{min}", toman(min_amount))
                               .replace("{amount}", toman(avail)))
    notes = []
    if b["blocked"] > 0:
        notes.append({"key": "blocked", "text": TEXTS["blocked_note"].replace("{amount}", toman(b["blocked"]))})
    if b["pending_withdrawal"] > 0:
        notes.append({"key": "pending", "text": TEXTS["pending_note"].replace("{amount}", toman(b["pending_withdrawal"]))})
    return {
        "flow_version": FLOW_VERSION,
        "min_amount": int(min_amount),
        "available": avail,
        "available_label": toman(avail),
        "blocked": b["blocked"],
        "pending_withdrawal": b["pending_withdrawal"],
        "can_withdraw": avail >= min_amount,
        "chips": amount_chips(avail, min_amount),
        "notes": notes,
        "destinations": saved_destinations(bank_rows, phone),
        "requests": request_rows(withdrawals, phone),
        "texts": texts,
        "errors": {k: error_message(k, min_amount=min_amount) for k in ERRORS},
    }
