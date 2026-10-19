"""نیت گفتگو — یک matcher مشترک برای انتخاب ابزار و seed برنامه‌ریز.

`CHIP_INTENT_HINTS` نیت چیپ‌های سریع است (مسیر فروش فایل / استخدام بازاریاب).
`detect_intent` تنها تشخیص‌دهندهٔ متن است؛ هم `tools/selection.py` و هم
`assistant.py` از همین استفاده می‌کنند تا سیگنال‌ها یک‌جا بمانند.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .goal import VISIT_COORD_PHONE, wrap_internal_hint

CHIP_INTENT_HINTS: dict[str, str] = {
    "coop_levels": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=levels؛ خودمونی و کوتاه؛ لینک نده."
    ),
    "coop_terms": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=terms؛ خودمونی و کوتاه؛ لینک نده."
    ),
    "coop_how": (
        "هدف: استخدام بازاریاب. get_cooperation_info topic=how؛ ۳ قدم کوتاه؛ لینک نده."
    ),
    "coop_apply": (
        "هدف: استخدام بازاریاب. "
        "۱) اول get_cooperation_info با topic=all — شرایط همکاری و نحوه ارتقا به بازاریاب را کوتاه و خودمونی بگو (لینک نده). "
        "۲) بعد در همان پاسخ ثبت را شروع کن: فقط نام کوچک را بپرس. "
        "نام→نام‌خانوادگی→کدملی یکی‌یکی؛ وقتی هر سه را داشتی propose_partner_application. "
        "مهمان بدون ورود→need_login / منوی راست. شهر نپرس."
    ),
    "coop_status": (
        "هدف: وضعیت استخدام. get_application_status؛ کوتاه؛ لینک نده."
    ),
    "next_action": (
        "هدف: فروش امروز. suggest_next_action؛ فقط یک قدم واضح."
    ),
    "marketing": (
        "هدف: فروش فایل. draft_listing_copy؛ متن در کارت؛ در پیام تکرار نکن."
    ),
    "visit": (
        f"هدف: رساندن به بازدید/فروش. propose_visit_request با land_code خالی؛ "
        f"نام مشتری→موبایل→تاریخ یکی‌یکی. تماس: {VISIT_COORD_PHONE}."
    ),
    "complete_visit": (
        "هدف: بستن قیف. اگر بازدید هنوز اعلام نشده propose_complete_visit؛ "
        "اگر انجام شده propose_visit_result (علاقه‌مند/پیگیری/بی‌علاقه) یا propose_no_show."
    ),
    "visit_result": (
        "هدف: ثبت نتیجه بازدید از همین چت. "
        "اگر outcome در پیام هست propose_visit_result؛ اگر نیومد/عدم حضور propose_no_show؛ "
        "وگرنه فقط یکی بپرس: علاقه‌مند / پیگیری دوباره / بی‌علاقه / نیومد. لینک صفحه نده."
    ),
    "no_show": (
        "هدف: عدم حضور مشتری. propose_no_show + کارت تأیید. لینک صفحه نده."
    ),
    "deal": (
        "هدف: معامله نهایی. propose_deal + کارت تأیید."
    ),
    "release": (
        "هدف: آزادسازی فایل. propose_release_deal + کارت."
    ),
    "find_land": (
        "هدف: بهترین فایل منتشرشدهٔ سیستم. "
        "معیار کوتاه→search_lands→[[LAND:کد]]→هل به بازدید."
    ),
    "have_customer": (
        "هدف: قیف مشتری. اول فقط نام را بپرس، بعد فقط موبایل. "
        "وقتی هر دو را داشتی propose_lead بزن و کارت «آماده ثبت» نشان بده. "
        "تا کاربر تأیید نکرده و Backend موفق نشده نگو ثبت شد. "
        "بعد از تأیید واقعی: search_lands؛ بعد از انتخاب فایل propose_visit_request "
        "(نام/موبایل از پیش‌نویس؛ فقط تاریخ)."
    ),
    "log_call": (
        "هدف: پیگیری فروش. propose_log_call با موبایل مشتری."
    ),
    "followup": (
        "هدف: پیگیری روزانه. propose_followup با موبایل و due_at."
    ),
}


def normalize_chip_intent(raw: str | None) -> str:
    key = str(raw or "").strip().lower()
    return key if key in CHIP_INTENT_HINTS else ""


def hint_for_chip_intent(intent: str | None) -> str:
    key = normalize_chip_intent(intent)
    raw = CHIP_INTENT_HINTS.get(key, "")
    return wrap_internal_hint(raw) if raw else ""


# --- matcher مشترک ---------------------------------------------------------

# چیپ‌هایی که فرم مرحله‌ای دارند؛ برنامه‌ریز نباید روی آن‌ها جستجوی اضافه بزند
PLANNING_SKIP_CHIPS = frozenset(
    {
        "visit",
        "complete_visit",
        "visit_result",
        "no_show",
        "deal",
        "release",
        "coop_apply",
    }
)

_GREETING_RE = re.compile(
    r"^(سلام|درود|صبح بخیر|عصر بخیر|شب بخیر|hello|hi|hey|خوبی|چطوری)[\s!.؟?]*$",
    re.I,
)

# «زمین» عمداً در سیگنال جستجو هست: «زمین گرمابسرد» باید search_lands بزند.
_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "search": (
        "جستجو",
        "search",
        "زمین",
        "قطعه",
        "ویلا",
        "ملک",
        "فایل",
        "land",
        "خرید",
        "پیشنهاد",
        "گزینه",
    ),
    "visit": ("بازدید", "visit", "رزرو"),
    "visit_result": (
        "نتیجه بازدید",
        "علاقه‌مند",
        "بی‌علاقه",
        "نپسندید",
        "پیگیری دوباره",
    ),
    "no_show": ("نیومد", "نیامد", "عدم حضور", "نرسید", "no_show"),
    "deal": ("معامله", "deal", "فروش", "release", "آزاد"),
    "listing": ("آگهی", "listing", "متن آگهی", "مارکتینگ"),
    "crm": ("تماس", "فالوآپ", "follow", "call", "crm", "ثبت تماس", "یادآوری تماس"),
    "pipeline": ("پیگیری", "کار بعدی", "قدم بعدی"),
    "lead": ("مشتری دارم", "ثبت مشتری", "customer", "lead"),
    "coop": ("همکاری", "بازاریاب", "coop", "apply", "ثبت نام"),
    "admin_partner": ("همکار", "partner", "درخواست همکاری"),
    "admin_msg": ("پیام", "sms", "اعلان", "push", "همگانی"),
    "admin_visit": ("بازدید", "visit"),
    "admin_money": ("پورسانت", "commission", "برداشت"),
    "admin_esc": ("سوال", "escalation", "پاسخ"),
    "admin_queue": ("صف", "queue", "عملیات", "خلاصه"),
    "forget": ("فراموش", "حذف حافظه", "forget"),
}


def message_signals(msg: str) -> dict[str, bool]:
    """سیگنال‌های کلیدواژه‌ای پیام — منبع واحد انتخاب ابزار."""
    m = (msg or "").strip().lower()
    return {name: any(k in m for k in keys) for name, keys in _SIGNAL_KEYWORDS.items()}


def is_guidance_only(user_message: str, chip_intent: str = "") -> bool:
    """پیام بدون درخواست عملی (سلام/تک‌حرف) — ابزار لازم نیست."""
    if str(chip_intent or "").strip():
        return False
    m = (user_message or "").strip()
    if not m or len(m) <= 2:
        return True
    return bool(_GREETING_RE.match(m))


@dataclass(frozen=True)
class ChatIntent:
    """نتیجهٔ یک بار تشخیص نیت برای کل درخواست."""

    chip: str = ""
    raw_chip: str = ""
    signals: dict[str, bool] = field(default_factory=dict)
    guidance_only: bool = False

    @property
    def wants_search(self) -> bool:
        return bool(self.signals.get("search")) or self.chip == "find_land"

    @property
    def skip_planning(self) -> bool:
        return self.chip in PLANNING_SKIP_CHIPS


def detect_intent(message: str, chip_intent: str | None = "") -> ChatIntent:
    """یک بار تشخیص نیت؛ selection و assistant هر دو از همین می‌خوانند."""
    raw_chip = str(chip_intent or "").strip()
    chip = normalize_chip_intent(raw_chip)
    blob = f"{message or ''} {raw_chip}".strip()
    return ChatIntent(
        chip=chip,
        raw_chip=raw_chip,
        signals=message_signals(blob),
        guidance_only=is_guidance_only(message or "", raw_chip),
    )
