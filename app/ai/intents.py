"""نیت چیپ‌های سریع چت — راهنمای کوتاه ابزار برای همان نوبت (بدون پرامپت طولانی در پیام کاربر)."""
from __future__ import annotations

# hintها کوتاه نگه داشته می‌شوند تا توکن هدر نرود
CHIP_INTENT_HINTS: dict[str, str] = {
    "coop_levels": (
        "نیت چیپ: سطوح همکاری. همین الان get_cooperation_info با topic=levels را بزن؛ "
        "۲–۴ جمله؛ لینک نده؛ اگر خواست شروع کند بگو «می‌خواهم همکار شوم»."
    ),
    "coop_terms": (
        "نیت چیپ: شرایط/پورسانت. get_cooperation_info با topic=terms را بزن؛ کوتاه؛ لینک نده."
    ),
    "coop_how": (
        "نیت چیپ: مسیر شروع. get_cooperation_info با topic=how را بزن؛ ۳ قدم؛ لینک نده."
    ),
    "coop_apply": (
        "نیت چیپ: ثبت همکاری. اگر لاگین نیست propose_partner_application را بزن تا need_login بیاید؛ "
        "وگرنه فیلدهای نام، کد ملی، شهر را یکی‌یکی بپرس و در پایان propose_partner_application."
    ),
    "coop_status": (
        "نیت چیپ: وضعیت درخواست. get_application_status را بزن و کوتاه بگو؛ لینک نده."
    ),
    "next_action": (
        "نیت چیپ: کار بعدی. suggest_next_action را بزن؛ یک قدم واضح بگو؛ اگر ثبت لازم است ابزار propose_*."
    ),
    "marketing": (
        "نیت چیپ: بازاریابی. draft_listing_copy را بزن؛ متن‌ها در کارت کپی می‌آیند؛ در پیام تکرار نکن."
    ),
    "visit": (
        "نیت چیپ: ثبت بازدید. اگر نام/شماره نداری بپرس؛ بعد propose_visit_request بدون تاریخ برای لیست تاریخ."
    ),
    "complete_visit": (
        "نیت چیپ: بازدید انجام شد. propose_complete_visit را بزن و کارت تأیید بده."
    ),
    "deal": (
        "نیت چیپ: معامله. propose_deal را بزن و کارت تأیید بده."
    ),
    "release": (
        "نیت چیپ: بستن معامله. propose_release_deal را بزن و کارت تأیید بده."
    ),
    "find_land": (
        "نیت چیپ: پیدا کردن ملک. اگر شهر/بودجه نگفته کوتاه بپرس؛ وگرنه search_lands و [[LAND:کد]]."
    ),
}


def normalize_chip_intent(raw: str | None) -> str:
    key = str(raw or "").strip().lower()
    return key if key in CHIP_INTENT_HINTS else ""


def hint_for_chip_intent(intent: str | None) -> str:
    key = normalize_chip_intent(intent)
    return CHIP_INTENT_HINTS.get(key, "")
