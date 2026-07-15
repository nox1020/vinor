# -*- coding: utf-8 -*-
"""فهرست شهرها و محدودهٔ تمرکز سرویس وینور."""
from __future__ import annotations

from typing import Any, Iterable, List

# ── محدودهٔ فعلی سرویس (همه پیشنهادها فقط اینجا) ──────────────────────────
SERVICE_PROVINCE = "تهران"
SERVICE_COUNTY = "دماوند"
SERVICE_VILLAGE = "گرمابسرد"

# برچسب انتخاب در فرم‌ها / شهر فعال
FOCUS_SERVICE_CITY = SERVICE_VILLAGE
FOCUS_SERVICE_CITIES: List[str] = [FOCUS_SERVICE_CITY]

# نام‌ها/عبارت‌هایی که همان محدودهٔ تمرکز محسوب می‌شوند
FOCUS_CITY_ALIASES = frozenset(
    {
        "گرمابسرد",
        "گرمابسرد دماوند",
        "روستای گرمابسرد",
        "روستا گرمابسرد",
        "دشت اول گرمابسرد",
        "دشت اول",
    }
)

FOCUS_TEXT_MARKERS = (
    "گرمابسرد",
    "دشت اول",
)


def focus_location_label() -> str:
    return f"استان {SERVICE_PROVINCE} · شهرستان {SERVICE_COUNTY} · روستای {SERVICE_VILLAGE}"


def focus_location_block() -> str:
    """متن ثابت برای system / زمینهٔ AI."""
    return (
        f"محدوده ثابت سرویس: {focus_location_label()}.\n"
        f"همه پیشنهادها، جستجوها و فایل‌ها فقط حول روستای {SERVICE_VILLAGE} "
        f"(شهرستان {SERVICE_COUNTY}، استان {SERVICE_PROVINCE}) باشد.\n"
        f"اگر کاربر جای دیگری خواست: مودبانه بگو فعلا فقط {SERVICE_VILLAGE} پوشش داده می‌شود "
        f"و فایل‌های همین روستا را پیشنهاد بده؛ خارج از {SERVICE_VILLAGE} پیشنهاد نده.\n"
        f"برای ثبت همکاری شهر را فقط «{FOCUS_SERVICE_CITY}» بپذیر/پیشنهاد بده."
    )


def normalize_to_focus_city(city: str) -> str:
    name = str(city or "").strip()
    if not name:
        return ""
    if name in FOCUS_CITY_ALIASES or SERVICE_VILLAGE in name:
        return FOCUS_SERVICE_CITY
    return name


def land_in_service_focus(land: dict[str, Any] | None) -> bool:
    """آیا فایل متعلق به محدودهٔ گرمابسرد است؟"""
    if not isinstance(land, dict):
        return False
    city = str(land.get("city") or "").strip()
    if city in FOCUS_CITY_ALIASES or SERVICE_VILLAGE in city:
        return True
    blob = " ".join(
        [
            city,
            str(land.get("title") or ""),
            str(land.get("address") or ""),
            str(land.get("location") or ""),
            str(land.get("region") or ""),
            str(land.get("area_name") or ""),
            str(land.get("village") or ""),
        ]
    )
    return any(m in blob for m in FOCUS_TEXT_MARKERS)


# ۴۸ شهر رسمی استان تهران — فقط برای افزودن دستی در ادمین
TEHRAN_PROVINCE_CITIES: List[str] = [
    "تهران",
    "اسلام‌شهر",
    "شهریار",
    "قدس",
    "ملارد",
    "صالحیه",
    "پاکدشت",
    "قرچک",
    "ورامین",
    "گلستان",
    "ری",
    "اندیشه",
    "رباط‌کریم",
    "پرند",
    "باغستان",
    "پردیس",
    "بومهن",
    "باقرشهر",
    "پیشوا",
    "نسیم‌شهر",
    "صباشهر",
    "چهاردانگه",
    "دماوند",
    "حسن‌آباد",
    "وحیدیه",
    "نصیرشهر",
    "فردوسیه",
    "رودهن",
    "شاهدشهر",
    "صفادشت",
    "فیروزکوه",
    "لواسان",
    "آبسرد",
    "شریف‌آباد",
    "کهریزک",
    "فشم",
    "جوادآباد",
    "فرون‌آباد",
    "آبعلی",
    "کیلان",
    "شمشک",
    "احمدآباد مستوفی",
    "ارجمند",
    "قلعه‌نو",
    "قیام‌دشت",
    "سعیدآباد",
    "خسروآباد",
    "جلیل‌آباد",
]


TEHRAN_CITY_SET: set[str] = set(TEHRAN_PROVINCE_CITIES)
ALLOWED_SERVICE_CITY_SET: set[str] = (
    TEHRAN_CITY_SET | set(FOCUS_SERVICE_CITIES) | set(FOCUS_CITY_ALIASES)
)


def is_tehran_city(city: str) -> bool:
    return str(city or "").strip() in TEHRAN_CITY_SET


def is_allowed_service_city(city: str) -> bool:
    name = str(city or "").strip()
    if name in ALLOWED_SERVICE_CITY_SET:
        return True
    return SERVICE_VILLAGE in name


def merge_unique_cities(existing: Iterable[str], extra: Iterable[str]) -> List[str]:
    """ادغام بدون تکرار — ترتیب: موجودها اول، سپس جدیدها."""
    seen: set[str] = set()
    out: List[str] = []
    for city in list(existing) + list(extra):
        name = str(city or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def sanitize_active_cities(existing: Iterable[str]) -> List[str]:
    """پاکسازی لیست فعال — نام‌های معادل گرمابسرد را یکی می‌کند."""
    seen: set[str] = set()
    out: List[str] = []
    for city in existing:
        name = normalize_to_focus_city(city) if city else ""
        name = name or str(city or "").strip()
        if not name or name in seen:
            continue
        if not is_allowed_service_city(name):
            continue
        # اگر معادل تمرکز است همیشه با نام رسمی روستا ذخیره شود
        if name in FOCUS_CITY_ALIASES or SERVICE_VILLAGE in name:
            name = FOCUS_SERVICE_CITY
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def normalize_active_tehran_cities(existing: Iterable[str]) -> List[str]:
    """ادمین: افزودن همهٔ شهرهای استان تهران به لیست فعلی."""
    kept = sanitize_active_cities(existing)
    return merge_unique_cities(kept, TEHRAN_PROVINCE_CITIES)


def default_active_cities() -> List[str]:
    """پیش‌فرض: فقط روستای گرمابسرد."""
    return list(FOCUS_SERVICE_CITIES)
