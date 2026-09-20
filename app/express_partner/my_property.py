"""ملک من — داشبورد مالک به‌سبک Redfin My Home."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import url_for

from .apk_native import json_ready


def feature_enabled() -> bool:
    return (os.environ.get("VINOR_MY_PROPERTY_ENABLED") or "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_MONTHS_FA = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)


def fa_digits(value: Any) -> str:
    return str(value).translate(_FA_DIGITS)


def fa_pct(value: Any, digits: int = 1) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = 0.0
    text = f"{n:.{digits}f}".rstrip("0").rstrip(".")
    return fa_digits(text.replace(".", "٫"))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        raw = str(value or "").replace(",", "").replace("،", "").strip()
        if not raw:
            return default
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _cover_url(land: Dict[str, Any] | None) -> str:
    if not isinstance(land, dict):
        return ""
    try:
        from ..utils.images import partner_card_image_url
        return partner_card_image_url(land) or ""
    except Exception:
        return ""


def _gallery_count(land: Dict[str, Any] | None) -> int:
    if not isinstance(land, dict):
        return 0
    images = land.get("images") or []
    if isinstance(images, str):
        return 1 if images.strip() else 0
    if isinstance(images, list):
        return len([i for i in images if i])
    return 0


def _price_history(current: int, months: int = 60, monthly_pct: float = 0.42) -> List[Dict[str, Any]]:
    now = datetime.now()
    series: List[Dict[str, Any]] = []
    for i in range(months):
        age = months - 1 - i
        factor = (1.0 - (monthly_pct / 100.0)) ** age
        month_i = (now.month - 1 - (months - 1 - i)) % 12
        label = _MONTHS_FA[month_i]
        v = max(1, int(round(current * factor)))
        n = max(1, int(round(current * 0.94 * factor)))
        series.append({"month": label, "value": v, "neighborhood": n})
    if series:
        series[-1]["value"] = current
        series[-1]["neighborhood"] = int(round(current * 0.94))
    return series


def demo_property() -> Dict[str, Any]:
    value = 12_500_000_000
    history = _price_history(value, 60, 0.35)
    return {
        "id": "demo-home",
        "is_demo": True,
        "cover_image": "",
        "gallery_count": 8,
        "address": "بلوار کاوه، کوچهٔ نرگس، پلاک ۲۴",
        "city": "تهران",
        "state": "تهران",
        "zip": "19197",
        "beds": 3,
        "baths": 2,
        "sqm": 120,
        "built_year": 1395,
        "beds_label": fa_digits(3),
        "baths_label": fa_digits(2),
        "sqm_label": fa_digits(120),
        "built_year_label": fa_digits(1395),
        "zip_label": fa_digits("19197"),
        "gallery_label": fa_digits(8),
        "estimated_value": value,
        "price_per_sqm": 104_166_667,
        "monthly_change_pct": 4.2,
        "monthly_change_label": fa_pct(4.2),
        "yearly_change_pct": 11.8,
        "yearly_change_label": fa_pct(11.8),
        "weekly_views": 0,
        "is_claimed": True,
        "badge_label": "خصوصی",
        "privacy_note": "فقط شما این قیمت را می‌بینید",
        "neighborhood_avg": 11_750_000_000,
        "equity": {"total": 7_800_000_000, "paid_off_pct": 62},
        "price_history": history,
        "nearby_listings": [],
        "activity": [
            {"type": "price", "text": "قیمت تخمینی به‌روز شد", "date": "۳ روز پیش"},
            {"type": "price", "text": "تغییر ماهانه محاسبه شد", "date": "۱ هفته پیش"},
        ],
        "edit_url": "",
        "photos_url": "",
        "settings_url": "",
        "sell_url": "",
    }


def _from_land(land: Dict[str, Any], nearby: List[Dict[str, Any]]) -> Dict[str, Any]:
    price = _as_int(land.get("price_total") or land.get("price"))
    sqm = _as_int(land.get("size") or land.get("sqm") or 120, 120) or 120
    if price <= 0:
        price = 12_500_000_000
    ppm = int(round(price / max(sqm, 1)))
    monthly = 4.2
    yearly = 11.8
    history = _price_history(price, 60, 0.35)
    equity_pct = 62
    code = str(land.get("code") or "").strip()
    nearby_rows = []
    try:
        edit_url = url_for("express_partner.my_property")
    except Exception:
        edit_url = ""
    return {
        "id": code or "claimed-home",
        "is_demo": False,
        "cover_image": _cover_url(land),
        "gallery_count": _gallery_count(land) or 1,
        "gallery_label": fa_digits(_gallery_count(land) or 1),
        "address": str(land.get("title") or land.get("location") or "ملک شما").strip() or "ملک شما",
        "city": str(land.get("city") or "تهران").strip() or "تهران",
        "state": str(land.get("province") or land.get("state") or land.get("city") or "تهران").strip(),
        "zip": str(land.get("zip") or land.get("postal_code") or "").strip(),
        "zip_label": fa_digits(str(land.get("zip") or land.get("postal_code") or "").strip()),
        "beds": _as_int(land.get("beds") or land.get("rooms") or 3, 3),
        "baths": _as_int(land.get("baths") or 2, 2),
        "sqm": sqm,
        "built_year": _as_int(land.get("built_year") or land.get("year_built") or 1395, 1395),
        "beds_label": fa_digits(_as_int(land.get("beds") or land.get("rooms") or 3, 3)),
        "baths_label": fa_digits(_as_int(land.get("baths") or 2, 2)),
        "sqm_label": fa_digits(sqm),
        "built_year_label": fa_digits(_as_int(land.get("built_year") or land.get("year_built") or 1395, 1395)),
        "estimated_value": price,
        "price_per_sqm": ppm,
        "monthly_change_pct": monthly,
        "monthly_change_label": fa_pct(monthly),
        "yearly_change_pct": yearly,
        "yearly_change_label": fa_pct(yearly),
        "weekly_views": 0,
        "is_claimed": True,
        "badge_label": "خصوصی",
        "privacy_note": "فقط شما این قیمت را می‌بینید",
        "neighborhood_avg": int(round(price * 0.94)),
        "equity": {"total": int(round(price * equity_pct / 100.0)), "paid_off_pct": equity_pct},
        "price_history": history,
        "nearby_listings": nearby_rows,
        "activity": [
            {"type": "price", "text": "قیمت تخمینی به‌روز شد", "date": "۳ روز پیش"},
            {"type": "price", "text": f"تغییر ماهانه {fa_pct(monthly)}٪ ثبت شد", "date": "۱ هفته پیش"},
        ],
        "edit_url": edit_url,
        "photos_url": edit_url,
        "settings_url": "",
        "sell_url": "",
    }


def property_for_user(me_phone: str) -> Optional[Dict[str, Any]]:
    owned: List[Dict[str, Any]] = []
    try:
        from .special_listings import listings_owned_home
        owned = listings_owned_home(me_phone) if me_phone else []
    except Exception:
        owned = []
    land = owned[0] if owned else None
    if land:
        return _from_land(land, [])
    return None


def page_payload(me_phone: str) -> Dict[str, Any]:
    prop = property_for_user(me_phone)
    try:
        form_url = url_for("express_partner.my_property")
    except Exception:
        form_url = "/express/partner/my-property"
    return json_ready({
        "ok": True,
        "logged_in": bool(me_phone),
        "has_property": bool(prop),
        "form_url": form_url,
        "property": prop or {},
    })


CATEGORIES = ["زمین", "باغ", "باغچه", "ویلا", "آپارتمان", "تجاری"]

CAT_KIND = {
    "زمین": "land",
    "باغ": "garden",
    "باغچه": "garden",
    "ویلا": "villa",
    "آپارتمان": "apartment",
    "تجاری": "commercial",
}

SIZE_LABELS = {
    "land": "متراژ زمین (متر)",
    "garden": "متراژ زمین (متر)",
    "villa": "متراژ کل / زمین (متر)",
    "apartment": "متراژ (متر)",
    "commercial": "متراژ (متر)",
    "other": "متراژ",
}

_OPT = lambda value, label=None: {"value": value, "label": label or value}

SPEC_SCHEMA: Dict[str, List[Dict[str, Any]]] = {
    "land": [
        {"key": "frontage", "label": "عرض بر (متر)", "type": "text"},
        {"key": "length", "label": "طول (متر)", "type": "text"},
        {"key": "street_width", "label": "عرض گذر (متر)", "type": "text"},
        {"key": "land_shape", "label": "شکل زمین", "type": "select", "options": [
            _OPT("مستطیل"), _OPT("مربع"), _OPT("هندسی", "دیگر"),
        ]},
        {"key": "land_use", "label": "کاربری", "type": "select", "options": [
            _OPT("مسکونی"), _OPT("کشاورزی"), _OPT("باغ/ویلایی"), _OPT("تجاری"),
        ]},
        {"key": "has_fence", "label": "دیوارکشی", "type": "checkbox"},
        {"key": "has_corner", "label": "نبش", "type": "checkbox"},
        {"key": "has_well", "label": "چاه", "type": "checkbox"},
        {"key": "has_guardroom", "label": "سرایداری", "type": "checkbox"},
    ],
    "garden": [
        {"key": "tree_count", "label": "تعداد درخت", "type": "text"},
        {"key": "irrigation", "label": "سیستم آبیاری", "type": "select", "options": [
            _OPT("قطره‌ای"), _OPT("غرقابی"), _OPT("آبیاری سنتی", "سنتی"),
        ]},
        {"key": "land_shape", "label": "شکل زمین", "type": "select", "options": [
            _OPT("مستطیل"), _OPT("مربع"), _OPT("هندسی", "دیگر"),
        ]},
        {"key": "land_use", "label": "کاربری", "type": "select", "options": [
            _OPT("مسکونی"), _OPT("کشاورزی"), _OPT("باغ/ویلایی"),
        ]},
        {"key": "frontage", "label": "عرض بر (متر)", "type": "text"},
    ],
    "villa": [
        {"key": "villa_land_area", "label": "متراژ زمین (متر)", "type": "text"},
        {"key": "villa_built_area", "label": "متراژ بنا (متر)", "type": "text"},
        {"key": "villa_bedrooms", "label": "اتاق خواب", "type": "text"},
        {"key": "villa_bathrooms", "label": "سرویس", "type": "text"},
        {"key": "villa_terrace", "label": "تراس", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
        {"key": "villa_pool", "label": "استخر", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
        {"key": "villa_direction", "label": "جهت", "type": "text"},
        {"key": "year_built", "label": "سال ساخت", "type": "text"},
    ],
    "apartment": [
        {"key": "year_built", "label": "سال ساخت", "type": "text"},
        {"key": "floor", "label": "طبقه", "type": "text"},
        {"key": "rooms", "label": "تعداد اتاق", "type": "text"},
        {"key": "elevator", "label": "آسانسور", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
        {"key": "parking", "label": "پارکینگ", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
        {"key": "warehouse", "label": "انباری", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
    ],
    "commercial": [
        {"key": "front_width", "label": "ویترین/بر (متر)", "type": "text"},
        {"key": "commercial_floor", "label": "طبقه", "type": "text"},
        {"key": "has_license", "label": "مجوز کسب", "type": "select", "options": [
            _OPT("1", "دارد"), _OPT("0", "ندارد"),
        ]},
        {"key": "commercial_type", "label": "نوع کاربری تجاری", "type": "text",
         "placeholder": "مثلاً پوشاک، رستوران"},
    ],
}


def form_meta(
    me_phone: str,
    *,
    is_special: bool = False,
    public_listing: bool = False,
) -> Dict[str, Any]:
    """متادیتای فرم ثبت برای اپ نیتیو — همان فیلدهای فرم وب."""
    from app.utils.storage import load_active_cities

    payload = page_payload(me_phone)
    public = bool(is_special and public_listing)
    if public:
        page_title = "ثبت آگهی"
        page_subtitle = "اطلاعات ملک را وارد و منتشر کنید"
        submit_label = "ثبت و انتشار آگهی"
    else:
        page_title = "ثبت ملک من"
        page_subtitle = "قیمت‌گذاری شخصی — منتشر نمی‌شود و فقط تغییرات قیمت را برای شما نشان می‌دهد"
        submit_label = "ثبت ملک من"
    return json_ready({
        "ok": True,
        "logged_in": bool(me_phone),
        "me_phone": me_phone or "",
        "has_property": bool(payload.get("has_property")),
        "is_special": bool(is_special),
        "public_listing": public,
        "owner_home": not public,
        "hide_commission": not public,
        "hide_payment": not public,
        "hide_broadcast": not public,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "submit_label": submit_label,
        "default_commission_pct": "2" if public else "0",
        "payment_methods": ["نقدی", "اقساطی", "معاوضه", "توافقی"],
        "cities": load_active_cities() or [],
        "categories": CATEGORIES,
        "cat_kind": CAT_KIND,
        "size_labels": SIZE_LABELS,
        "spec_schema": SPEC_SCHEMA,
        "property": payload.get("property") or {},
    })
