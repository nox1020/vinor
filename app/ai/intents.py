"""نیت چیپ‌های سریع — فقط مسیر فروش فایل / استخدام بازاریاب."""
from __future__ import annotations

from .goal import VISIT_COORD_PHONE, wrap_internal_hint

CHIP_INTENT_HINTS: dict[str, str] = {
    "coop_levels": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=levels؛ کوتاه؛ لینک نده."
    ),
    "coop_terms": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=terms؛ کوتاه؛ لینک نده."
    ),
    "coop_how": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=how؛ ۳ قدم؛ لینک نده."
    ),
    "coop_apply": (
        "هدف: استخدام بازاریاب. propose_partner_application؛ "
        "نام→کدملی→شهر گرمابسرد یکی‌یکی؛ need_login→منوی راست."
    ),
    "coop_status": (
        "هدف: وضعیت استخدام. get_application_status؛ کوتاه؛ لینک نده."
    ),
    "next_action": (
        "هدف: فروش امروز. suggest_next_action؛ یک قدم واضح برای بستن فروش."
    ),
    "marketing": (
        "هدف: فروش فایل. draft_listing_copy؛ متن در کارت؛ در پیام تکرار نکن."
    ),
    "visit": (
        f"هدف: رساندن به بازدید/فروش. propose_visit_request با land_code خالی؛ "
        f"نام مشتری→موبایل→تاریخ یکی‌یکی. تماس کسب‌وکار: {VISIT_COORD_PHONE}."
    ),
    "complete_visit": (
        "هدف: بستن قیف. propose_complete_visit + کارت تأیید."
    ),
    "deal": (
        "هدف: معامله نهایی. propose_deal + کارت تأیید."
    ),
    "release": (
        "هدف: آزادسازی فایل برای فروش دوباره. propose_release_deal + کارت."
    ),
    "find_land": (
        "هدف: پیشنهاد بهترین فایل سیستم (فقط گرمابسرد). "
        "معیار کوتاه→search_lands→[[LAND:کد]]→هل به بازدید."
    ),
    "log_call": (
        "هدف: پیگیری فروش. propose_log_call با موبایل مشتری."
    ),
    "followup": (
        "هدف: پیگیری روزانه فروش. propose_followup با موبایل و due_at."
    ),
}


def normalize_chip_intent(raw: str | None) -> str:
    key = str(raw or "").strip().lower()
    return key if key in CHIP_INTENT_HINTS else ""


def hint_for_chip_intent(intent: str | None) -> str:
    key = normalize_chip_intent(intent)
    raw = CHIP_INTENT_HINTS.get(key, "")
    return wrap_internal_hint(raw) if raw else ""
