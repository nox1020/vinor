# -*- coding: utf-8 -*-
"""شارژ کیف پول به سبک دیوار: زمینهٔ کمبود، مقصد بازگشت، نتیجهٔ پرداخت، و فهرست تراکنش‌ها.

امنیت پرداخت در wallet_topup می‌ماند: مبلغ از رکورد سرور، تأیید زرین‌پال پیش از واریز،
و یک‌بار واریز برای هر authority. این ماژول فقط نمایش و مسیر را می‌سازد.

- زمینهٔ کمبود (shortfall + دلیل + کد آگهی) با امضای سرور در ``ctx`` می‌آید؛ کلاینت
  نمی‌تواند دلیل یا آگهی یا مبلغ دلخواه را جا بزند.
- مقصد «بازگشت به جایی که بودید» فقط از ``RETURN_TARGETS`` ساخته می‌شود؛ هیچ URL
  از کاربر گرفته نمی‌شود.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.dates import format_display_jalali_date, to_fa_digits

CTX_SALT = "vinor-wallet-charge-ctx-v1"
RESULT_SALT = "vinor-wallet-charge-result-v1"
CTX_MAX_AGE = 24 * 3600
RESULT_MAX_AGE = 14 * 24 * 3600
GATEWAY_LABEL = "زرین‌پال"

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# دلیل کمبود → جملهٔ «برای … X تومان کم دارید» و مقصد بازگشت.
REASONS: Dict[str, Dict[str, str]] = {
    "publish": {"phrase": "برای انتشار این آگهی", "return": "listing"},
    "restore": {"phrase": "برای برگرداندن این آگهی به فهرست فعال", "return": "listing"},
    "sold": {"phrase": "برای ثبت فروش این آگهی", "return": "listing"},
    "deal": {"phrase": "برای تأیید نهایی این معامله", "return": "deal"},
    "generic": {"phrase": "برای ادامه", "return": "commissions"},
}

# مقصدهای مجاز بازگشت. کلید را APK هم می‌شناسد؛ آدرس وب فقط با url_for ساخته می‌شود.
RETURN_TARGETS: Dict[str, Dict[str, Any]] = {
    "commissions": {"endpoint": "express_partner.commissions", "label": "بازگشت به کیف پول", "needs_code": False},
    "wallet": {"endpoint": "express_partner.wallet_home", "label": "بازگشت به کیف پول", "needs_code": False},
    "listing": {"endpoint": "express_partner.land_detail", "label": "بازگشت به آگهی", "needs_code": True},
    "deal": {"endpoint": "express_partner.special_visit_inbox", "label": "بازگشت به معامله", "needs_code": False},
}
DEFAULT_RETURN = "wallet"
# فقط این کلیدها بی‌امضا از query پذیرفته می‌شوند (آگهی و معامله باید از سرور امضا شوند).
PLAIN_RETURN_KEYS = frozenset({"commissions", "wallet"})

TEXTS: Dict[str, str] = {
    "wallet_title": "کیف پول",
    "available_label": "موجودی قابل استفاده",
    "available_hint": "برای انتشار آگهی، پرداخت پورسانت و برداشت در دسترس است.",
    "blocked_label": "بلوکه برای پورسانت",
    "blocked_hint": "پورسانت آگهی‌های منتشرشده کنار گذاشته شده و با فروش یا لغو آگهی تکلیفش روشن می‌شود.",
    "pending_withdrawal_label": "در انتظار برداشت",
    "pending_withdrawal_hint": "درخواست‌های برداشتی که هنوز واریز نشده‌اند.",
    "topup_button": "افزایش اعتبار",
    "withdraw_button": "برداشت",
    "requests_title": "درخواست‌های برداشت",
    "cancel_request": "لغو",
    "amount_title": "افزایش اعتبار",
    "amount_question": "چقدر می‌خواهید کیف پولتان را شارژ کنید؟",
    "amount_placeholder": "مبلغ دلخواه",
    "amount_suffix": "تومان",
    "amount_min": "کمترین مبلغ شارژ {min} است.",
    "amount_too_low": "مبلغ باید دست‌کم {min} باشد.",
    "amount_too_high": "این مبلغ بیش از حد مجاز است.",
    "next": "ادامه",
    "summary_title": "تأیید و پرداخت",
    "summary_question": "اطلاعات پرداخت را بررسی کنید",
    "summary_amount": "مبلغ شارژ",
    "summary_gateway": "درگاه پرداخت",
    "summary_after": "موجودی بعد از شارژ",
    "summary_note": "مبلغ فقط بعد از تأیید پرداخت از طرف بانک به کیف پولتان اضافه می‌شود.",
    "pay": "پرداخت",
    "paying": "در حال انتقال به درگاه…",
    "success_title": "کیف پولتان شارژ شد",
    "success_amount": "مبلغ شارژ",
    "success_balance": "موجودی قابل استفاده",
    "success_ref": "کد پیگیری",
    "cancelled_title": "پرداخت لغو شد",
    "cancelled_body": "پرداخت را در درگاه لغو کردید و پولی از حسابتان کم نشد.",
    "failed_title": "پرداخت انجام نشد",
    "failed_body": "بانک پرداخت را تأیید نکرد و مبلغی به کیف پول اضافه نشد.",
    "refund_note": "اگر پولی از حسابتان کم شده، بانک حداکثر تا ۷۲ ساعت آن را برمی‌گرداند.",
    "pending_title": "نتیجهٔ پرداخت هنوز مشخص نیست",
    "pending_body": "هنوز تأیید بانک به ما نرسیده و تا وقتی تأیید نشود مبلغی به کیف پول اضافه نمی‌شود.",
    "pending_note": "اگر پولی از حسابتان کم شده، یا چند دقیقهٔ دیگر تأیید می‌شود یا بانک حداکثر تا ۷۲ ساعت برمی‌گرداند.",
    "retry": "تلاش دوباره",
    "recheck": "بررسی دوباره",
    "not_found_title": "این پرداخت پیدا نشد",
    "not_found_body": "مبلغی به کیف پول اضافه نشد. اگر پولی از حسابتان کم شده، بانک حداکثر تا ۷۲ ساعت آن را برمی‌گرداند.",
    "back_to_app": "بازگشت به وینور",
    "transactions_title": "تراکنش‌ها",
    "transactions_empty": "هنوز تراکنشی ندارید.",
}


# ------------------------------------------------------------------ helpers

def _int(value: Any) -> int:
    try:
        return max(0, int(str(value).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def toman(amount: Any) -> str:
    return to_fa_digits(f"{_int(amount):,}".replace(",", "٬")) + " تومان"


_SCALES = ("", "هزار", "میلیون", "میلیارد", "هزار میلیارد")


def amount_words(amount: Any) -> str:
    """۲٬۵۰۰٬۰۰۰ → «۲ میلیون و ۵۰۰ هزار تومان» (مثل دیوار: رقم + مقیاس)."""
    n = _int(amount)
    if n <= 0:
        return ""
    parts: List[str] = []
    scale = 0
    while n > 0 and scale < len(_SCALES):
        chunk = n % 1000
        n //= 1000
        if chunk:
            label = to_fa_digits(str(chunk))
            if _SCALES[scale]:
                label += " " + _SCALES[scale]
            parts.append(label)
        scale += 1
    if n > 0:  # بیش از مقیاس‌ها؛ رقمی نشان بده
        return toman(amount)
    return " و ".join(reversed(parts)) + " تومان"


def _serializer(salt: str):
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def _same_phone(a: Any, b: Any) -> bool:
    from .partner_withdrawals import partner_phones_match

    return bool(str(a or "").strip()) and partner_phones_match(a, b)


def clean_code(value: Any) -> str:
    code = str(value or "").strip()
    return code if _CODE_RE.match(code) else ""


# ------------------------------------------------------------------ context (shortfall)

def make_context(*, phone: str, shortfall: int, reason: str, code: str = "") -> str:
    """زمینهٔ امضاشدهٔ کمبود برای پاسخ‌های wallet_insufficient."""
    why = reason if reason in REASONS else "generic"
    return _serializer(CTX_SALT).dumps({
        "p": str(phone or "").strip(),
        "s": _int(shortfall),
        "r": why,
        "c": clean_code(code),
    })


def charge_path_for(*, phone: str, shortfall: int, reason: str, code: str = "") -> str:
    from flask import url_for

    if _int(shortfall) <= 0:
        return url_for("express_partner.wallet_charge")
    return url_for("express_partner.wallet_charge",
                   ctx=make_context(phone=phone, shortfall=shortfall, reason=reason, code=code))


def read_context(token: Any, phone: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "").strip()
    if not raw or len(raw) > 600:
        return None
    try:
        data = _serializer(CTX_SALT).loads(raw, max_age=CTX_MAX_AGE)
    except Exception:
        return None
    if not isinstance(data, dict) or not _same_phone(data.get("p"), phone):
        return None
    reason = str(data.get("r") or "")
    if reason not in REASONS:
        return None
    code = clean_code(data.get("c"))
    target = REASONS[reason]["return"]
    if RETURN_TARGETS[target]["needs_code"] and not code:
        target = DEFAULT_RETURN
    return {"shortfall": _int(data.get("s")), "reason": reason, "code": code, "return": target, "ctx": raw}


def return_target(key: str, code: str = "") -> Dict[str, Any]:
    """مقصد بازگشت فقط از فهرست مجاز. ورودی ناشناخته به کیف پول برمی‌گردد."""
    from flask import url_for

    k = key if key in RETURN_TARGETS else DEFAULT_RETURN
    spec = RETURN_TARGETS[k]
    c = clean_code(code) if spec["needs_code"] else ""
    if spec["needs_code"] and not c:
        k, spec, c = DEFAULT_RETURN, RETURN_TARGETS[DEFAULT_RETURN], ""
    url = url_for(spec["endpoint"], code=c) if spec["needs_code"] else url_for(spec["endpoint"])
    return {"key": k, "code": c, "label": spec["label"], "url": url}


def context_from_request(values, phone: str, *, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """زمینهٔ صفحهٔ مبلغ از ctx امضاشده، از نتیجهٔ قبلی (تلاش دوباره)، یا shortfall قدیمی."""
    from .wallet_topup import MAX_TOPUP, MIN_TOPUP

    ctx = read_context(values.get("ctx"), phone)
    out: Dict[str, Any] = {"shortfall": 0, "reason": "", "code": "", "return": DEFAULT_RETURN, "ctx": "", "retry_amount": 0}
    if ctx:
        out.update(ctx)
    else:
        retry = read_result_token(values.get("from"))
        row = find_topup_row(retry, rows) if retry else None
        if row is not None and _same_phone(row.get("partner_phone"), phone):
            out["retry_amount"] = _int(row.get("commission_amount"))
            out["reason"] = str(row.get("charge_reason") or "")
            out["code"] = clean_code(row.get("return_code"))
            out["return"] = str(row.get("return_target") or DEFAULT_RETURN)
            out["shortfall"] = _int(row.get("charge_shortfall"))
            out["ctx"] = str(row.get("charge_ctx") or "")
            if out["ctx"] and not read_context(out["ctx"], phone):
                out["ctx"] = ""
        else:
            # APK و لینک‌های قدیمی: ?shortfall=N فقط پیش‌پر می‌کند، دلیل عمومی.
            legacy = _int(values.get("shortfall"))
            if legacy:
                out.update({"shortfall": legacy, "reason": "generic"})
            plain = str(values.get("return") or "").strip()
            if plain in PLAIN_RETURN_KEYS:
                out["return"] = plain
    if out["shortfall"] > MAX_TOPUP:
        out["shortfall"] = 0
        out["reason"] = ""
    if out["return"] not in RETURN_TARGETS:
        out["return"] = DEFAULT_RETURN
    return out


def reason_line(ctx: Dict[str, Any]) -> str:
    short = _int(ctx.get("shortfall"))
    why = str(ctx.get("reason") or "")
    if not short or why not in REASONS:
        return ""
    return f"{REASONS[why]['phrase']} {toman(short)} کم دارید."


def prefill_amount(ctx: Dict[str, Any]) -> int:
    from .wallet_topup import MIN_TOPUP

    if _int(ctx.get("retry_amount")):
        return _int(ctx.get("retry_amount"))
    short = _int(ctx.get("shortfall"))
    if not short:
        return 0
    return max(short, MIN_TOPUP)


def charge_options(header: Dict[str, int], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .wallet_topup import MAX_TOPUP, MIN_TOPUP, TOPUP_PRESETS

    prefill = prefill_amount(ctx)
    presets = list(TOPUP_PRESETS)
    if prefill and prefill not in presets:
        presets = [prefill] + presets
    target = return_target(str(ctx.get("return") or ""), str(ctx.get("code") or ""))
    texts = dict(TEXTS)
    texts["amount_min"] = TEXTS["amount_min"].format(min=toman(MIN_TOPUP))
    texts["amount_too_low"] = TEXTS["amount_too_low"].format(min=toman(MIN_TOPUP))
    return {
        "flow_version": 1,
        "min_amount": MIN_TOPUP,
        "max_amount": MAX_TOPUP,
        "presets": [{"amount": p, "label": toman(p), "words": amount_words(p)} for p in presets],
        "prefill": prefill,
        "shortfall": _int(ctx.get("shortfall")),
        "reason": str(ctx.get("reason") or ""),
        "reason_line": reason_line(ctx),
        "ctx": str(ctx.get("ctx") or ""),
        "return": {"key": target["key"], "code": target["code"], "label": target["label"], "url": target["url"]},
        "gateway": {"key": "zarinpal", "label": GATEWAY_LABEL},
        "wallet": header_payload(header),
        "texts": texts,
    }


def header_payload(header: Dict[str, int]) -> Dict[str, Any]:
    """هر مفهوم موجودی یک بار: قابل استفاده (بزرگ)، بلوکه، در انتظار برداشت.

    «کل موجودی» (قابل استفاده + بلوکه) دیگر نمایش داده نمی‌شود چون تکرار همان دو عدد بود؛
    کلید ``total`` فقط برای سازگاری نسخه‌های قدیمی اپ در JSON می‌ماند.
    """
    available = _int(header.get("available"))
    blocked = _int(header.get("blocked"))
    pending_wd = _int(header.get("pending_withdrawal"))
    total = _int(header.get("total")) or available + blocked
    return {
        "available": available,
        "blocked": blocked,
        "pending_withdrawal": pending_wd,
        "total": total,
        "available_label": toman(available),
        "blocked_label": toman(blocked),
        "pending_withdrawal_label": toman(pending_wd),
        "total_label": toman(total),
        "lines": [
            {"key": "blocked", "label": TEXTS["blocked_label"], "value": toman(blocked), "hint": TEXTS["blocked_hint"]},
            {"key": "pending_withdrawal", "label": TEXTS["pending_withdrawal_label"], "value": toman(pending_wd),
             "hint": TEXTS["pending_withdrawal_hint"]},
        ],
    }


def charge_meta(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """آنچه روی رکورد شارژ ذخیره می‌شود تا صفحهٔ نتیجه بداند کاربر به کجا برگردد."""
    target = return_target(str(ctx.get("return") or ""), str(ctx.get("code") or ""))
    return {
        "return_target": target["key"],
        "return_code": target["code"],
        "charge_reason": str(ctx.get("reason") or "") if ctx.get("reason") in REASONS else "",
        "charge_shortfall": _int(ctx.get("shortfall")),
        "charge_ctx": str(ctx.get("ctx") or ""),
    }


# ------------------------------------------------------------------ result

def result_token(txn_id: Any) -> str:
    return _serializer(RESULT_SALT).dumps({"t": _int(txn_id)})


def read_result_token(token: Any) -> int:
    raw = str(token or "").strip()
    if not raw or len(raw) > 300:
        return 0
    try:
        data = _serializer(RESULT_SALT).loads(raw, max_age=RESULT_MAX_AGE)
    except Exception:
        return 0
    return _int((data or {}).get("t")) if isinstance(data, dict) else 0


def find_topup_row(txn_id: int, rows: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    from .commission_escrow import TOPUP_SOURCE

    if not txn_id:
        return None
    if rows is None:
        from app.utils.storage import load_express_commissions

        rows = load_express_commissions() or []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("source") or "") != TOPUP_SOURCE:
            continue
        if _int(row.get("id")) == int(txn_id):
            return row
    return None


def topup_state(row: Optional[Dict[str, Any]]) -> str:
    """success فقط وقتی درگاه با ref_id تأیید کرده است."""
    from .wallet_topup import topup_verified_paid

    if not isinstance(row, dict):
        return "not_found"
    if topup_verified_paid(row):
        return "success"
    if str(row.get("status") or "") == "rejected":
        reason = str(row.get("result_reason") or row.get("reject_reason") or "")
        return "cancelled" if reason == "cancelled" else "failed"
    return "pending"


def result_payload(row: Optional[Dict[str, Any]], *, viewer_phone: str, available: Optional[int],
                   token: str = "") -> Dict[str, Any]:
    from flask import url_for

    state = topup_state(row)
    owner = isinstance(row, dict) and _same_phone(row.get("partner_phone"), viewer_phone)
    amount = _int((row or {}).get("commission_amount"))
    target = return_target(str((row or {}).get("return_target") or ""), str((row or {}).get("return_code") or ""))
    body: Dict[str, Any] = {
        "ok": True,
        "state": state,
        "txn_id": _int((row or {}).get("id")),
        "amount": amount,
        "amount_label": toman(amount) if amount else "",
        "gateway": GATEWAY_LABEL,
        "owner": bool(owner),
        "return": {"key": target["key"], "code": target["code"], "label": target["label"], "url": target["url"]},
    }
    if state == "success":
        body.update({
            "title": TEXTS["success_title"],
            "message": "",
            "note": "",
            "ref_id": str((row or {}).get("ref_id") or ""),
        })
        if owner and available is not None:
            body["balance"] = _int(available)
            body["balance_label"] = toman(available)
    elif state == "cancelled":
        body.update({"title": TEXTS["cancelled_title"], "message": TEXTS["cancelled_body"], "note": ""})
    elif state == "failed":
        body.update({"title": TEXTS["failed_title"], "message": TEXTS["failed_body"], "note": TEXTS["refund_note"]})
    elif state == "pending":
        body.update({"title": TEXTS["pending_title"], "message": TEXTS["pending_body"], "note": TEXTS["pending_note"],
                     "can_recheck": bool(owner and str((row or {}).get("authority") or "").strip())})
    else:
        body.update({"title": TEXTS["not_found_title"], "message": TEXTS["not_found_body"], "note": ""})
    if state in ("cancelled", "failed") and token:
        body["retry_url"] = url_for("express_partner.wallet_charge", **{"from": token})
    elif state in ("cancelled", "failed", "not_found"):
        body["retry_url"] = url_for("express_partner.wallet_charge")
    return body


# ------------------------------------------------------------------ transactions feed

_KINDS = {
    "topup": {"icon": "fa-arrow-down", "title": "افزایش اعتبار"},
    "hold": {"icon": "fa-lock", "title": "بلوکه برای پورسانت"},
    "release": {"icon": "fa-lock-open", "title": "آزاد شدن بلوکه"},
    "commission_paid": {"icon": "fa-handshake", "title": "پرداخت پورسانت"},
    "commission": {"icon": "fa-coins", "title": "پورسانت"},
    "withdrawal": {"icon": "fa-arrow-up", "title": "برداشت"},
    "adjustment": {"icon": "fa-sliders", "title": "تعدیل موجودی"},
}

_CHIPS = {
    "success": "green",
    "pending": "amber",
    "failed": "red",
    "neutral": "gray",
}


def _tehran(dt_raw: str) -> Optional[datetime]:
    from app.utils.dates import parse_iso_to_naive_utc

    utc = parse_iso_to_naive_utc(str(dt_raw or ""))
    if utc is None:
        return None
    return utc.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=3, minutes=30)))


def _classify(row: Dict[str, Any]) -> Dict[str, Any]:
    from .commission_escrow import HOLD_TYPE, STATUS_HELD, STATUS_RELEASED, STATUS_SETTLED, TOPUP_SOURCE

    detail = row.get("_txn_detail") or {}
    ctype = str(row.get("commission_type") or "")
    source = str(row.get("source") or "")
    status = str(row.get("status") or "")
    txn_type = str(row.get("txn_type") or "commission")
    amount = _int(detail.get("amount", row.get("commission_amount")))
    sign = str(detail.get("amount_sign") or "+")
    meta = str(row.get("_txn_meta") or detail.get("description") or "").strip()
    if ctype == HOLD_TYPE:
        code = str(row.get("land_code") or "")
        sub = f"آگهی {to_fa_digits(code)}" if code else ""
        if status == STATUS_RELEASED:
            return {"kind": "release", "sign": "+", "amount": amount, "chip": ("آزاد شد", "success"), "subtitle": sub}
        if status == STATUS_SETTLED:
            return {"kind": "commission_paid", "sign": "-", "amount": amount, "chip": ("پرداخت شد", "neutral"), "subtitle": sub}
        if status == STATUS_HELD:
            return {"kind": "hold", "sign": "-", "amount": amount, "chip": ("بلوکه", "pending"), "subtitle": sub}
    if source == TOPUP_SOURCE:
        state = topup_state(row)
        chip = {
            "success": ("موفق", "success"),
            "pending": ("در انتظار تأیید بانک", "pending"),
            "cancelled": ("لغو شد", "failed"),
            "failed": ("ناموفق", "failed"),
        }.get(state, ("ناموفق", "failed"))
        ref = str(row.get("ref_id") or "")
        sub = f"{GATEWAY_LABEL}" + (f" · کد پیگیری {to_fa_digits(ref)}" if ref else "")
        return {"kind": "topup", "sign": "+", "amount": amount, "chip": chip, "subtitle": sub,
                "muted": state != "success"}
    if txn_type in ("withdrawal", "withdrawal_request"):
        label = str(detail.get("status_label") or "")
        tone = "success" if txn_type == "withdrawal" else ("failed" if status in ("rejected", "cancelled") else "pending")
        return {"kind": "withdrawal", "sign": "-", "amount": amount, "chip": (label or "در جریان", tone),
                "subtitle": str(row.get("bank_summary") or "")}
    if ctype == "manual_adjustment":
        return {"kind": "adjustment", "sign": sign, "amount": amount,
                "chip": (str(detail.get("status_label") or "تأیید شده"), "success" if status in ("approved", "paid") else "pending"),
                "subtitle": meta}
    tone = "success" if status in ("approved", "paid") else ("failed" if status == "rejected" else "pending")
    return {"kind": "commission", "sign": sign, "amount": amount,
            "chip": (str(detail.get("status_label") or ""), tone), "subtitle": meta,
            "title": str(detail.get("title") or "")}


def feed_groups(rows: List[Dict[str, Any]], *, limit: int = 60) -> List[Dict[str, Any]]:
    """تراکنش‌ها گروه‌بندی‌شده بر اساس روز (وقت تهران)، جدیدترین اول."""
    from app.utils.dates import tehran_today

    today = tehran_today()
    groups: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in (rows or [])[: max(1, limit)]:
        if not isinstance(row, dict):
            continue
        try:
            c = _classify(row)
        except Exception:
            continue
        kind = c["kind"]
        spec = _KINDS.get(kind, _KINDS["commission"])
        when = _tehran(row.get("created_at") or "")
        if when is not None:
            key = when.date().isoformat()
            if when.date() == today:
                label = "امروز"
            elif when.date() == today - timedelta(days=1):
                label = "دیروز"
            else:
                label = format_display_jalali_date(key, with_weekday=True)
            time_label = to_fa_digits(when.strftime("%H:%M"))
        else:
            key, label, time_label = "unknown", "بدون تاریخ", ""
        sign = "-" if c["sign"] == "-" else "+"
        tone = "muted" if c.get("muted") else ("green" if sign == "+" else "red")
        if kind in ("hold", "release"):
            tone = "muted" if c.get("muted") else "amber"
        chip_label, chip_tone = c["chip"]
        item = {
            "id": row.get("id"),
            "kind": kind,
            "icon": spec["icon"],
            "title": c.get("title") or spec["title"],
            "subtitle": c.get("subtitle") or "",
            "amount": c["amount"],
            "sign": sign,
            "amount_label": ("+" if sign == "+" else "−") + to_fa_digits(f"{c['amount']:,}".replace(",", "٬")),
            "tone": tone,
            "chip": {"label": chip_label, "tone": _CHIPS.get(chip_tone, "gray")} if chip_label else None,
            "time_label": time_label,
            "created_at": str(row.get("created_at") or ""),
        }
        g = by_key.get(key)
        if g is None:
            g = {"key": key, "label": label, "entries": []}
            by_key[key] = g
            groups.append(g)
        g["entries"].append(item)
    return groups


def recheck_topup(txn_id: int, phone: str) -> Dict[str, Any]:
    """«بررسی دوباره» برای شارژ در انتظار: فقط صاحب رکورد، فقط با تأیید خود زرین‌پال."""
    from .wallet_topup import complete_wallet_topup

    row = find_topup_row(txn_id)
    if row is None or not _same_phone(row.get("partner_phone"), phone):
        return {"ok": False, "reason": "not_found"}
    if topup_state(row) != "pending":
        return {"ok": True, "reason": "settled"}
    authority = str(row.get("authority") or "").strip()
    if not authority:
        return {"ok": False, "reason": "no_authority"}
    return complete_wallet_topup(authority, "OK")
