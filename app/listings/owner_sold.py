# -*- coding: utf-8 -*-
"""«فروخته شد» از طرف مالک آگهی.

دو مسیر، هر دو روی منطق موجود:

* ``vinor``: فروش از طریق بازدید یک بازاریاب وینور. همان مسیر پیگیری مالک اجرا
  می‌شود: «تأیید معامله» (confirm_deal) و بعد «بستن پرونده» (close_deal). پورسانت از
  بلوکهٔ انتشار به بازاریاب می‌رسد و آگهی فروخته‌شده و بایگانی می‌شود.
* ``outside``: مالک خودش بیرون از وینور فروخته. آگهی فروخته‌شده و بایگانی می‌شود.
  اگر هیچ بازدید انجام‌شده یا معاملهٔ بازی روی آگهی نباشد، بلوکه مثل لغو آگهی آزاد
  می‌شود. اگر بازاریابی بازدید انجام‌شده داشته باشد، بلوکه آزاد نمی‌شود و برای
  تصمیم ادمین علامت می‌خورد تا «فروخته شد» راه فرار از پورسانت نشود.

مالکیت روی سرور چک می‌شود. تکرار روی آگهی فروخته‌شده همان نتیجه را می‌دهد.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

CHANNEL_VINOR = "vinor"
CHANNEL_OUTSIDE = "outside"
CHANNELS = (CHANNEL_VINOR, CHANNEL_OUTSIDE)
# «هنوز قطعی نشده / منصرف شدم»: هیچ تغییری روی آگهی، بلوکه یا پرونده نمی‌دهد.
CHANNEL_NOT_FINAL = "not_final"

# پرسش‌نامهٔ بعد از «فروخته شد» (سبک دیوار). همه اختیاری و فقط برای آمار/اطلاع؛
# پورسانت و بلوکه از این پاسخ‌ها اثر نمی‌گیرند.
WIZARD_VERSION = 1
SOLD_SOURCES = (
    ("agency", "مشاور املاک"),
    ("acquaintance", "آشنا و همسایه"),
    ("other_platform", "سایت یا اپ دیگر"),
    ("other", "سایر"),
)
SOLD_SOURCE_LABELS = dict(SOLD_SOURCES)
FINAL_PRICE_MAX = 10 ** 13  # ده هزار میلیارد تومان
COMMENT_MAX = 300
RATING_LABELS = {1: "خیلی بد", 2: "بد", 3: "معمولی", 4: "خوب", 5: "عالی"}

WIZARD_COPY = {
    "channel_question": "ملک‌تان از چه راهی فروخته شد؟",
    "channel_vinor": "با بازدیدی که در وینور هماهنگ شد",
    "channel_vinor_hint": "بازاریاب وینور مشتری را آورد",
    "channel_vinor_disabled": "هنوز بازدید انجام‌شده‌ای برای این ملک ثبت نشده است",
    "channel_outside": "خودم بیرون از وینور فروختم",
    "channel_not_final": "هنوز قطعی نشده / منصرف شدم",
    "channel_not_final_hint": "چیزی ثبت نمی‌شود و آگهی همین‌طور می‌ماند",
    "visit_question": "کدام بازدید به فروش رسید؟",
    "visit_hint": "پورسانت به بازاریاب همین بازدید می‌رسد.",
    "source_question": "از چه طریقی فروختید؟",
    "source_hint": "اختیاری؛ فقط برای بهتر شدن وینور می‌پرسیم.",
    "price_question": "قیمت نهایی فروش چقدر بود؟",
    "price_hint": "اختیاری و فقط برای اطلاع است؛ روی پورسانت اثری ندارد.",
    "price_placeholder": "مثلاً ۲٬۵۰۰٬۰۰۰٬۰۰۰",
    "rating_question": "از بازاریاب راضی بودید؟",
    "rating_hint": "اختیاری؛ نظر شما فقط برای پشتیبانی وینور دیده می‌شود.",
    "comment_placeholder": "اگر نکته‌ای دارید بنویسید (اختیاری)",
    "summary_title": "مرور و ثبت فروش",
    "summary_hint": "بعد از ثبت، آگهی بسته می‌شود و دیگر قابل بازگرداندن نیست.",
    "submit": "ثبت فروش",
    "next": "ادامه",
    "skip": "رد شدن",
    "not_final_message": "تغییری ثبت نشد. هر وقت فروش قطعی شد، دوباره «فروخته شد» را بزنید.",
}

LABEL = "فروخته شد"
CONFIRM_VINOR = (
    "فروش از طریق بازدید {name} ثبت شود؟ پورسانت اعلام‌شده از مبلغ بلوکه‌شده به کیف پول "
    "بازاریاب منتقل و آگهی بسته می‌شود."
)
CONFIRM_OUTSIDE = (
    "ملک را خودتان بیرون از وینور فروخته‌اید؟ آگهی بسته و از فهرست عمومی برداشته می‌شود "
    "و پورسانت بلوکه‌شده آزاد می‌شود."
)
CONFIRM_OUTSIDE_REVIEW = (
    "ملک را خودتان بیرون از وینور فروخته‌اید؟ آگهی بسته و از فهرست عمومی برداشته می‌شود. "
    "چون بازاریاب وینور برای این ملک بازدید ثبت‌شده دارد، پورسانت بلوکه‌شده تا بررسی "
    "پشتیبانی وینور آزاد نمی‌شود."
)

REVIEW_WARNING = (
    "بازاریاب وینور برای این ملک بازدید ثبت‌شده دارد؛ اگر از طریق او فروخته‌اید، همان بازدید را انتخاب کنید. "
    "با «بیرون از وینور» پورسانت بلوکه‌شده تا بررسی پشتیبانی آزاد نمی‌شود."
)

ERRORS_FA = {
    "forbidden": "فقط مالک آگهی می‌تواند آن را فروخته‌شده اعلام کند.",
    "not_found": "این آگهی پیدا نشد.",
    "invalid_channel": "روش فروش را انتخاب کنید.",
    "visit_required": "بازدیدی را که به فروش رسید انتخاب کنید.",
    "visit_not_found": "این بازدید برای این آگهی پیدا نشد یا هنوز انجام نشده است.",
    "failed": "ثبت فروش ممکن نشد. دوباره تلاش کنید.",
    "csrf_failed": "نشست صفحه منقضی شده است. صفحه را تازه کنید و دوباره تلاش کنید.",
    "invalid_sold_source": "روش فروش انتخاب‌شده معتبر نیست.",
    "invalid_final_price": "قیمت نهایی را فقط با عدد و به تومان وارد کنید.",
    "invalid_rating": "امتیاز بازاریاب باید عددی بین ۱ تا ۵ باشد.",
    "comment_too_long": "توضیح حداکثر ۳۰۰ نویسه می‌تواند باشد.",
    "rating_vinor_only": "امتیاز بازاریاب فقط برای فروش با بازدید وینور ثبت می‌شود.",
    "source_outside_only": "«از چه طریقی فروختید» فقط برای فروش بیرون از وینور است.",
}

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = (",", "٬", "،", " ", "\u00a0", "\u200c", "_", "'")


def parse_final_price(raw: Any) -> Tuple[Optional[int], Optional[str]]:
    """«۲٬۵۰۰٬۰۰۰٬۰۰۰» یا 2500000000 → عدد تومان. خالی یعنی پاسخ نداده."""
    if raw is None or isinstance(raw, bool):
        return (None, None) if raw is None else (None, "invalid_final_price")
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and not raw.is_integer():
            return None, "invalid_final_price"
        value = int(raw)
    else:
        text = str(raw).strip().translate(_DIGITS)
        for sep in _SEPARATORS:
            text = text.replace(sep, "")
        if text.endswith("تومان"):
            text = text[: -len("تومان")].strip()
        if not text:
            return None, None
        if not text.isdigit():
            return None, "invalid_final_price"
        value = int(text)
    if value <= 0 or value > FINAL_PRICE_MAX:
        return None, "invalid_final_price"
    return value, None


def parse_details(channel: str, data: Dict[str, Any] | None) -> Tuple[Dict[str, Any], Optional[str]]:
    """پاسخ‌های اختیاری پرسش‌نامه. قبل از هر تغییر روی آگهی یا بلوکه اعتبارسنجی می‌شود.

    کلاینت قدیمی هیچ‌کدام را نمی‌فرستد و همان رفتار قبلی را می‌گیرد.
    """
    data = data if isinstance(data, dict) else {}
    out: Dict[str, Any] = {}
    source = _clean(data.get("sold_source")).lower()
    if source:
        if channel != CHANNEL_OUTSIDE:
            return {}, "source_outside_only"
        if source not in SOLD_SOURCE_LABELS:
            return {}, "invalid_sold_source"
        out["sold_source"] = source
    price, err = parse_final_price(data.get("final_price"))
    if err:
        return {}, err
    if price is not None:
        out["final_price"] = price
    raw_rating = data.get("marketer_rating")
    comment = str(data.get("comment") if data.get("comment") is not None else (data.get("marketer_comment") or "")).strip()
    if raw_rating not in (None, "", 0, "0"):
        if channel != CHANNEL_VINOR:
            return {}, "rating_vinor_only"
        try:
            text = str(raw_rating).strip().translate(_DIGITS)
            if isinstance(raw_rating, bool) or not text.isdigit():
                raise ValueError
            rating = int(text)
        except (TypeError, ValueError):
            return {}, "invalid_rating"
        if rating < 1 or rating > 5:
            return {}, "invalid_rating"
        out["marketer_rating"] = rating
    if comment:
        if channel != CHANNEL_VINOR:
            return {}, "rating_vinor_only"
        if len(comment) > COMMENT_MAX:
            return {}, "comment_too_long"
        out["marketer_comment"] = comment
    return out, None


def details_from_extras(extras: Dict[str, Any] | None) -> Dict[str, Any]:
    """پاسخ‌های ثبت‌شده روی آگهی، برای ادمین و صفحهٔ موفقیت."""
    extras = extras if isinstance(extras, dict) else {}
    source = _clean(extras.get("sold_source"))
    out: Dict[str, Any] = {
        "sold_source": source,
        "sold_source_label": SOLD_SOURCE_LABELS.get(source, ""),
        "final_price": int(extras.get("sold_final_price") or 0) or None,
        "marketer_rating": int(extras.get("sold_marketer_rating") or 0) or None,
        "marketer_comment": _clean(extras.get("sold_marketer_comment")),
    }
    out["final_price_label"] = _toman(out["final_price"]) if out["final_price"] else ""
    return out


def _toman(amount: Any) -> str:
    try:
        from app.express_partner.deal_wallet import toman_fa

        return toman_fa(int(amount or 0))
    except Exception:
        return f"{int(amount or 0):,} تومان"

DEAL_STARTED_RETRY = (
    "معامله با بازاریاب ثبت شد ولی پرداخت پورسانت انجام نشد ({reason}). "
    "{hint}سپس دوباره «فروخته شد» را بزنید و همین بازدید را انتخاب کنید؛ معامله از همین‌جا ادامه می‌یابد."
)
WALLET_TOPUP_HINT = "کیف پول را به اندازهٔ پورسانت شارژ کنید، "


def _clean(value: Any) -> str:
    return str(value or "").strip()


def is_sold(land: Dict[str, Any] | None) -> bool:
    return isinstance(land, dict) and _clean(land.get("express_status")).lower() == "sold"


def can_mark_sold(land: Dict[str, Any] | None, phone: str) -> bool:
    """دکمه فقط برای مالک همان آگهی و فقط وقتی هنوز فروخته نشده."""
    from app.listings.service import owner_phone, same_owner

    if not isinstance(land, dict) or not _clean(phone):
        return False
    if not same_owner(owner_phone(land), phone):
        return False
    return not is_sold(land)


def _resolve_owned(code: str, phone: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from app.listings.service import _listing_for_code, listings_path, _read_json

    items = _read_json(listings_path())
    return _listing_for_code(items, code, phone, require_owner=True)


# وضعیت‌هایی که «فروش با بازدید» در آن‌ها مستقیم ممکن است. done_pending اول با تأیید
# مالک completed می‌شود (همان «تأیید انجام بازدید») و بعد معامله ثبت می‌شود.
SELLABLE_STATUSES = ("completed", "done_pending")


def _has_dispute(row: Dict[str, Any]) -> bool:
    return bool(_clean(row.get("dispute_reason")) or _clean(row.get("dispute_at")) or row.get("disputed"))


def visit_triggers_review(row: Dict[str, Any]) -> bool:
    """بازدیدی که با وجودش «فروش بیرون از وینور» نباید بلوکه را خودکار آزاد کند.

    done_pending، disputed، completed، no_show با اعتراض، و approved که وقتش گذشته.
    """
    from app.express_partner.visit_requests import (
        APPROVED_STATUS,
        COMPLETED_STATUS,
        DISPUTED_STATUS,
        DONE_PENDING_STATUS,
        NO_SHOW_STATUS,
        visit_slot_has_passed,
    )

    status = _clean(row.get("status"))
    if status in (COMPLETED_STATUS, DONE_PENDING_STATUS, DISPUTED_STATUS):
        return True
    if status == NO_SHOW_STATUS:
        return _has_dispute(row)
    if status == APPROVED_STATUS:
        try:
            return bool(visit_slot_has_passed(row))
        except Exception:
            return False
    return False


def _listing_visits(code: str, owner: str, rows: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    """بازدیدهای بازاریاب‌ها (نه خود مالک) روی همین آگهی؛ کد قبلی هم حساب می‌شود."""
    from app.express_partner.visit_requests import canonical_land_code, load_visit_requests_fresh
    from app.listings.service import same_owner

    want = canonical_land_code(code)
    if not want:
        return []
    if rows is None:
        rows = load_visit_requests_fresh() or []
    out: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if canonical_land_code(_clean(row.get("land_code"))) != want:
            continue
        partner = _clean(row.get("partner_phone"))
        if not partner or (owner and same_owner(partner, owner)):
            continue
        out.append(row)
    return out


def review_visits(code: str, owner: str = "", rows: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """همهٔ بازدیدهایی که فروش بیرون از وینور را به بازبینی ادمین می‌برند."""
    return [row for row in _listing_visits(code, owner, rows) if visit_triggers_review(row)]


def sellable_visits(code: str, owner: str = "", rows: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """بازدیدهایی که مالک می‌تواند «فروش از طریق این بازدید» را رویشان بزند."""
    return [row for row in _listing_visits(code, owner, rows) if _clean(row.get("status")) in SELLABLE_STATUSES]


def completed_visits(code: str, owner: str = "", rows: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """سازگاری: فقط بازدیدهای completed."""
    return [row for row in _listing_visits(code, owner, rows) if _clean(row.get("status")) == "completed"]


def _visit_option(row: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean(row.get("partner_name")) or "بازاریاب وینور"
    day = _clean(row.get("visit_date"))
    label = f"{name} · بازدید {day}" if day else name
    if _clean(row.get("status")) == "done_pending":
        label = f"{label} (تأیید انجام بازدید هم ثبت می‌شود)"
    try:
        from app.express_partner.visit_requests import visit_card_when

        when = visit_card_when(row)
        day_fa = _clean(when.get("visit_date_label")) or _clean(when.get("visit_date_jalali")) or day
    except Exception:
        day_fa = day
    status_label = {
        "completed": "بازدید انجام شد",
        "done_pending": "منتظر تأیید انجام بازدید",
    }.get(_clean(row.get("status")), "")
    return {
        "visit_id": _clean(row.get("id")),
        "partner_name": name,
        "visit_date": day,
        "deal_decision": _clean(row.get("deal_decision")),
        "status": _clean(row.get("status")),
        "label": label,
        "visit_date_label": day_fa,
        "status_label": status_label,
        "confirm_message": CONFIRM_VINOR.format(name=name),
    }


def _held_amount(code: str) -> int:
    try:
        from app.express_partner.commission_escrow import find_hold
        from app.utils.storage import load_express_commissions

        row = find_hold(load_express_commissions() or [], code)
        return int((row or {}).get("commission_amount") or 0)
    except Exception:
        return 0


def _open_deal(code: str) -> bool:
    try:
        from app.express_partner.commission_escrow import listing_has_open_deal

        if listing_has_open_deal(code):
            return True
        from app.utils.storage import load_express_commissions

        for row in load_express_commissions() or []:
            if not isinstance(row, dict):
                continue
            if _clean(row.get("commission_type")) != "deal":
                continue
            if _clean(row.get("land_code")) == code and _clean(row.get("status")).lower() == "pending":
                return True
    except Exception:
        return False
    return False


def sold_options(phone: str, code: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """گزینه‌های صفحهٔ «فروخته شد». فقط مالک."""
    from app.listings.service import code_key

    land, err = _resolve_owned(code, phone)
    if err or land is None:
        return None, err or "not_found"
    key = code_key(land)
    visits = [_visit_option(row) for row in sellable_visits(key, phone)]
    review = bool(review_visits(key, phone)) or _open_deal(key)
    held = _held_amount(key)
    for visit in visits:
        visit["summary"] = summary_vinor(visit["partner_name"], held)
    return {
        "ok": True,
        "code": key,
        "title": _clean(land.get("title")),
        "sold": is_sold(land),
        "can_mark_sold": can_mark_sold(land, phone),
        "label": LABEL,
        "visits": visits,
        "has_completed_visits": bool(visits),
        "review_required_if_outside": review,
        "review_warning": REVIEW_WARNING if review else "",
        "held_amount": _held_amount(key),
        "outside_confirm_message": CONFIRM_OUTSIDE_REVIEW if review else CONFIRM_OUTSIDE,
        "outside_label": "خودم بیرون از وینور فروختم",
        "question": "ملک از طریق بازدید بازاریاب وینور فروخته شد؟",
        # پرسش‌نامهٔ مرحله‌ای (نسخهٔ جدید). کلیدهای بالا برای کلاینت قدیمی ثابت مانده‌اند.
        "wizard_version": WIZARD_VERSION,
        "texts": dict(WIZARD_COPY),
        "channels": [
            {"value": CHANNEL_VINOR, "label": WIZARD_COPY["channel_vinor"],
             "hint": WIZARD_COPY["channel_vinor_hint"] if visits else WIZARD_COPY["channel_vinor_disabled"],
             "enabled": bool(visits)},
            {"value": CHANNEL_OUTSIDE, "label": WIZARD_COPY["channel_outside"], "hint": "", "enabled": True},
            {"value": CHANNEL_NOT_FINAL, "label": WIZARD_COPY["channel_not_final"],
             "hint": WIZARD_COPY["channel_not_final_hint"], "enabled": True},
        ],
        "sources": [{"value": value, "label": label} for value, label in SOLD_SOURCES],
        "rating_labels": {str(k): v for k, v in RATING_LABELS.items()},
        "held_amount_label": _toman(held) if held else "",
        "outside_summary": summary_outside(held, review),
        "comment_max": COMMENT_MAX,
        "final_price_max": FINAL_PRICE_MAX,
    }, None


def summary_vinor(name: str, held: int) -> str:
    if held > 0:
        return (f"پورسانت اعلام‌شده ({_toman(held)}) از مبلغ بلوکه‌شده به کیف پول {name} منتقل می‌شود "
                "و آگهی بسته می‌شود.")
    return f"پورسانت اعلام‌شده به {name} پرداخت می‌شود و آگهی بسته می‌شود."


def summary_outside(held: int, review: bool) -> str:
    if review:
        return ("آگهی بسته می‌شود. چون بازاریاب وینور برای این ملک بازدید ثبت‌شده دارد، "
                "مبلغ بلوکه‌شده تا بررسی پشتیبانی وینور آزاد نمی‌شود.")
    if held > 0:
        return f"آگهی بسته می‌شود و مبلغ بلوکه‌شده ({_toman(held)}) به کیف پول شما برمی‌گردد."
    return "آگهی بسته و از فهرست عمومی برداشته می‌شود. برای این آگهی مبلغی بلوکه نشده است."


def success_payload(land: Dict[str, Any] | None, *, hold_released: Optional[bool] = None) -> Dict[str, Any]:
    """متن صفحهٔ موفقیت (تیک سبز) از روی وضعیت ثبت‌شدهٔ آگهی."""
    extras = (land or {}).get("extras") if isinstance((land or {}).get("extras"), dict) else {}
    channel = _clean(extras.get("sold_channel"))
    review = bool(extras.get("sold_review_required"))
    steps: List[str] = []
    if channel == CHANNEL_VINOR:
        steps.append("پورسانت به کیف پول بازاریاب منتقل شد.")
    elif review:
        steps.append("پشتیبانی وینور پرونده را بررسی می‌کند و نتیجه را به شما خبر می‌دهد.")
        steps.append("تا پایان بررسی، مبلغ بلوکه‌شده آزاد نمی‌شود.")
    elif hold_released:
        steps.append("مبلغ بلوکه‌شده به کیف پول شما برگشت.")
    steps.append("آگهی بسته شد و دیگر در فهرست عمومی دیده نمی‌شود.")
    steps.append("سابقهٔ این فروش در بایگانی «ملک من» می‌ماند.")
    return {"success_title": "فروش ثبت شد", "next_steps": steps}


def _audit(action: str, *, phone: str, code: str, payload: Dict[str, Any]) -> None:
    try:
        from app.foundation.activity_store import append_activity

        append_activity(
            action=action,
            actor_key=_clean(phone),
            actor_role="owner",
            entity_type="listing",
            entity_id=code,
            land_code=code,
            object_type="listing",
            summary=f"Owner marked listing {code} sold ({payload.get('channel')})",
            payload=dict(payload),
            source="owner_mark_sold",
        )
    except Exception:
        pass


def _stamp_sold(
    code: str,
    phone: str,
    *,
    channel: str,
    visit_id: str,
    review: bool,
    details: Dict[str, Any] | None = None,
) -> Optional[Dict[str, Any]]:
    """آگهی را sold و با دلیل «بسته» بایگانی کن. بلوکه اینجا لمس نمی‌شود."""
    from app.listings.service import (
        ARCHIVE_CLOSED,
        _archive_now,
        _listing_for_code,
        _read_json,
        _stamp_archive,
        code_key,
        listings_lock,
        listings_path,
        save_listings,
    )

    with listings_lock():
        items = _read_json(listings_path())
        target, err = _listing_for_code(items, code, phone, require_owner=True)
        if err or target is None:
            return None
        stamp = _archive_now()
        target["express_status"] = "sold"
        extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
        if not extras.get("sold_at"):
            extras["sold_at"] = stamp
            extras["sold_by_owner"] = True
            extras["sold_channel"] = channel
            extras["sold_visit_id"] = visit_id
            extras["sold_review_required"] = bool(review)
            info = details or {}
            if info.get("sold_source"):
                extras["sold_source"] = info["sold_source"]
            if info.get("final_price"):
                extras["sold_final_price"] = int(info["final_price"])
            if info.get("marketer_rating"):
                extras["sold_marketer_rating"] = int(info["marketer_rating"])
            if info.get("marketer_comment"):
                extras["sold_marketer_comment"] = str(info["marketer_comment"])
            extras["sold_wizard_version"] = WIZARD_VERSION if info else 0
        target["extras"] = extras
        target["sold_at"] = extras["sold_at"]
        _stamp_archive(target, ARCHIVE_CLOSED)
        written = save_listings(items)
        want = code_key(target)
        for land in written:
            if isinstance(land, dict) and code_key(land) == want:
                return land
        return target


def _sync_followups(land: Dict[str, Any]) -> None:
    from app.listings.service import _sync_archived_followups, code_key

    _sync_archived_followups(
        code_key(land),
        _clean(land.get("archived_reason")) or "closed",
        _clean(land.get("archived_at")),
    )


def _result(land: Dict[str, Any], *, already: bool, channel: str, review: bool, message: str) -> Dict[str, Any]:
    from app.listings.service import archive_payload, code_key

    body = archive_payload(land)
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    body.update({
        "ok": True,
        "code": code_key(land),
        "sold": True,
        "already": already,
        "can_mark_sold": False,
        "channel": _clean(extras.get("sold_channel")) or channel,
        "review_required": bool(extras.get("sold_review_required", review)),
        "message": message,
        "details": details_from_extras(extras),
    })
    body.update(success_payload(land))
    return body


def _sell_via_visit(phone: str, code: str, visit_id: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """همان دو قدم پیگیری مالک: تأیید معامله و بستن پرونده (پرداخت از بلوکه)."""
    from app.express_partner.special_visit_inbox import apply_special_visit_action, inject_visit_deal_chat
    from app.express_partner.visit_requests import (
        DEAL_DECISION_APPROVED,
        DEAL_DECISION_CLOSED,
        locked_mutate_visit_requests,
        visit_deal_decision,
    )

    held: Dict[str, Any] = {"steps": []}

    def _mutate(rows):
        rec = next((r for r in rows if isinstance(r, dict) and _clean(r.get("id")) == visit_id), None)
        if rec is None or rec not in sellable_visits(code, phone, rows):
            held["err"] = "visit_not_found"
            return False
        saved = False
        if _clean(rec.get("status")) == "done_pending":
            out, err = apply_special_visit_action(
                rows, owner_phone=phone, visit_id=visit_id, action="complete",
            )
            if err:
                held["err"] = err
                return False
            saved = True
            held["steps"].append("complete")
            rec = out or rec
        decision = visit_deal_decision(rec)
        if decision == DEAL_DECISION_CLOSED:
            held["rec"] = rec
            return False
        if decision != DEAL_DECISION_APPROVED:
            out, err = apply_special_visit_action(
                rows, owner_phone=phone, visit_id=visit_id, action="confirm_deal",
            )
            if err:
                held["err"] = err
                return False
            saved = True
            held["steps"].append("confirm_deal")
            held["rec"] = out
        out, err = apply_special_visit_action(
            rows, owner_phone=phone, visit_id=visit_id, action="close_deal",
        )
        if err:
            held["err"] = err
            # تأیید معامله ثبت شد (حالا یا قبلاً) ولی بستن/پرداخت نشد: تلاش دوباره از close_deal ادامه می‌دهد.
            held["deal_started"] = True
            return saved
        held["steps"].append("close_deal")
        held["rec"] = out
        return True

    locked_mutate_visit_requests(_mutate)
    rec = held.get("rec")
    chat = {"confirm_deal": "approved", "close_deal": "closed"}
    for step in held["steps"]:
        if step not in chat:
            continue
        try:
            inject_visit_deal_chat(rec, decision=chat[step])
        except Exception:
            pass
    return held.get("err"), held


def mark_sold(
    phone: str,
    code: str,
    *,
    channel: str,
    visit_id: str = "",
    answers: Dict[str, Any] | None = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """(body, error_code, detail). error_code=None یعنی موفق یا تکراری.

    answers: پاسخ‌های اختیاری پرسش‌نامه (sold_source، final_price، marketer_rating، comment).
    """
    from app.listings.service import code_key

    land, err = _resolve_owned(code, phone)
    if err or land is None:
        return None, err or "not_found", {}
    key = code_key(land)
    if is_sold(land):
        return _result(land, already=True, channel=channel, review=False,
                       message="این آگهی از قبل فروخته‌شده ثبت شده است."), None, {}
    chan = _clean(channel).lower()
    if chan == CHANNEL_NOT_FINAL:
        # «هنوز قطعی نشده»: هیچ نوشتنی روی آگهی، بلوکه، بازدید یا گزارش.
        return {
            "ok": True,
            "code": key,
            "sold": False,
            "noop": True,
            "can_mark_sold": can_mark_sold(land, phone),
            "message": WIZARD_COPY["not_final_message"],
        }, None, {}
    if chan not in CHANNELS:
        return None, "invalid_channel", {}
    details, detail_err = parse_details(chan, answers)
    if detail_err:
        return None, detail_err, {}

    if chan == CHANNEL_VINOR:
        vid = _clean(visit_id)
        if not vid:
            return None, "visit_required", {}
        if vid not in {_clean(row.get("id")) for row in sellable_visits(key, phone)}:
            return None, "visit_not_found", {}
        deal_err, detail = _sell_via_visit(phone, key, vid)
        if deal_err:
            if detail.get("deal_started"):
                hint = WALLET_TOPUP_HINT if deal_err == "wallet_insufficient" else ""
                detail["message"] = DEAL_STARTED_RETRY.format(reason=error_message(deal_err), hint=hint)
                _audit("owner_mark_sold_deal_pending", phone=phone, code=key,
                       payload={"channel": chan, "visit_id": vid, "error": deal_err,
                                "steps": detail.get("steps") or []})
            return None, deal_err, detail
        sold_land = _stamp_sold(key, phone, channel=chan, visit_id=vid, review=False, details=details)
        if sold_land is None:
            return None, "failed", detail
        _sync_followups(sold_land)
        _audit("owner_mark_sold", phone=phone, code=key,
               payload={"channel": chan, "visit_id": vid, "steps": detail.get("steps") or [],
                        "answers": details})
        return _result(sold_land, already=False, channel=chan, review=False,
                       message="فروش ثبت شد. پورسانت به بازاریاب رسید و آگهی بسته شد."), None, detail

    visits = review_visits(key, phone)
    review = bool(visits) or _open_deal(key)
    if review:
        # Flag before closing the listing, so no auto-release can slip in between.
        # A legacy listing with no hold still gets a review case so it shows on the admin page.
        try:
            from app.express_partner.commission_escrow import (
                REVIEW_OWNER_SOLD_OUTSIDE,
                flag_hold_for_review,
                open_review_case,
            )

            visit_ids = [_clean(row.get("id")) for row in visits]
            flagged = flag_hold_for_review(
                key,
                reason=REVIEW_OWNER_SOLD_OUTSIDE,
                actor_phone=phone,
                visit_ids=visit_ids,
            )
            if flagged is None:
                open_review_case(
                    key,
                    owner_phone=phone,
                    reason=REVIEW_OWNER_SOLD_OUTSIDE,
                    visit_ids=visit_ids,
                    title=_clean(land.get("title")),
                )
        except Exception:
            return None, "failed", {}
    sold_land = _stamp_sold(key, phone, channel=chan, visit_id="", review=review, details=details)
    if sold_land is None:
        return None, "failed", {}
    _sync_followups(sold_land)
    released = False
    if not review:
        try:
            from app.express_partner.commission_escrow import release_publish_hold

            released = release_publish_hold(key, reason="owner_sold_outside")
        except Exception:
            released = False
    _audit("owner_mark_sold", phone=phone, code=key,
           payload={"channel": chan, "review_required": review, "hold_released": released,
                    "visit_ids": [_clean(row.get("id")) for row in visits], "answers": details})
    if review:
        message = ("آگهی فروخته‌شده ثبت و بسته شد. چون بازاریاب وینور بازدید ثبت‌شده داشت، "
                   "پورسانت بلوکه‌شده تا بررسی پشتیبانی وینور آزاد نمی‌شود.")
    else:
        message = "آگهی فروخته‌شده ثبت و بسته شد. پورسانت بلوکه‌شده آزاد شد."
    body = _result(sold_land, already=False, channel=chan, review=review, message=message)
    body["hold_released"] = released
    body.update(success_payload(sold_land, hold_released=released))
    return body, None, {}


def error_message(err: str) -> str:
    if err == "wallet_insufficient":
        try:
            from app.express_partner.special_visit_inbox import listing_deal_error_fa

            return listing_deal_error_fa(err)
        except Exception:
            pass
    if err in ERRORS_FA:
        return ERRORS_FA[err]
    try:
        from app.express_partner.special_visit_inbox import LISTING_DEAL_ERROR_FA

        if err in LISTING_DEAL_ERROR_FA:
            return LISTING_DEAL_ERROR_FA[err]
    except Exception:
        pass
    return ERRORS_FA["failed"]
