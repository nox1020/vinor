# -*- coding: utf-8 -*-
"""فهرست شهرهای استان‌ها — منبع واحد برای پنل و همکاری."""
from __future__ import annotations

from typing import Iterable, List

# ۴۸ شهر رسمی استان تهران (بر اساس تقسیمات کشوری)
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


def is_tehran_city(city: str) -> bool:
    return str(city or "").strip() in TEHRAN_CITY_SET


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


def normalize_active_tehran_cities(existing: Iterable[str]) -> List[str]:
    """فقط شهرهای استان تهران — حذف سایر استان‌ها و تکمیل فهرست ۴۸ شهر."""
    tehran_only = [c for c in existing if is_tehran_city(c)]
    return merge_unique_cities(tehran_only, TEHRAN_PROVINCE_CITIES)


def default_active_cities() -> List[str]:
    """شهرهای پیش‌فرض: فقط استان تهران."""
    return list(TEHRAN_PROVINCE_CITIES)
