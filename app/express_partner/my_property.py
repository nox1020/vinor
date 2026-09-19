"""ملک من — داشبورد مالک به‌سبک Redfin My Home."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

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
        "weekly_views": 45,
        "is_claimed": True,
        "neighborhood_avg": 11_750_000_000,
        "equity": {"total": 7_800_000_000, "paid_off_pct": 62},
        "price_history": history,
        "nearby_listings": [
            {"address": "کاوه، پلاک ۱۸", "price": 11_200_000_000, "distance_km": 0.3},
            {"address": "جردن، خیابان چهارم", "price": 13_400_000_000, "distance_km": 0.8},
            {"address": "زعفرانیه، کوچهٔ گل", "price": 15_900_000_000, "distance_km": 1.4},
        ],
        "activity": [
            {"type": "price", "text": "قیمت تخمینی به‌روز شد", "date": "۳ روز پیش"},
            {"type": "view", "text": "۴۵ نفر ملک شما را دیدند", "date": "۱ هفته پیش"},
            {"type": "photo", "text": "عکس جدید اضافه شد", "date": "۲ هفته پیش"},
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
    for item in nearby[:3]:
        nearby_rows.append({
            "address": str(item.get("title") or item.get("location") or "ملک نزدیک").strip() or "ملک نزدیک",
            "price": _as_int(item.get("price_total") or item.get("price")),
            "distance_km": round(0.4 + 0.5 * len(nearby_rows), 1),
            "code": str(item.get("code") or "").strip(),
        })
    if not nearby_rows:
        nearby_rows = demo_property()["nearby_listings"]
    views = _as_int(land.get("_public_views_count") or land.get("views") or 45, 45)
    try:
        edit_url = url_for("express_partner.special_listings") if code else ""
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
        "weekly_views": views or 45,
        "is_claimed": True,
        "neighborhood_avg": int(round(price * 0.94)),
        "equity": {"total": int(round(price * equity_pct / 100.0)), "paid_off_pct": equity_pct},
        "price_history": history,
        "nearby_listings": nearby_rows,
        "activity": [
            {"type": "price", "text": "قیمت تخمینی به‌روز شد", "date": "۳ روز پیش"},
            {"type": "view", "text": f"{fa_digits(views or 45)} نفر ملک شما را دیدند", "date": "۱ هفته پیش"},
            {"type": "photo", "text": "عکس جدید اضافه شد", "date": "۲ هفته پیش"},
        ],
        "edit_url": edit_url,
        "photos_url": edit_url,
        "settings_url": url_for("express_partner.settings") if edit_url else "",
        "sell_url": edit_url,
    }


def property_for_user(me_phone: str) -> Dict[str, Any]:
    owned: List[Dict[str, Any]] = []
    try:
        from .special_listings import listings_owned_by
        owned = listings_owned_by(me_phone) if me_phone else []
    except Exception:
        owned = []
    city = ""
    land = owned[0] if owned else None
    if land:
        city = str(land.get("city") or "").strip()
    nearby: List[Dict[str, Any]] = []
    if city:
        try:
            from ..utils.storage import load_ads_cached
            ads = load_ads_cached() or []
        except Exception:
            ads = []
        for item in ads:
            if not isinstance(item, dict):
                continue
            if land and str(item.get("code") or "") == str(land.get("code") or ""):
                continue
            if str(item.get("status") or "").lower() not in ("", "approved", "active"):
                continue
            if str(item.get("city") or "").strip() != city:
                continue
            nearby.append(item)
            if len(nearby) >= 6:
                break
    if land:
        return _from_land(land, nearby)
    return demo_property()


def page_payload(me_phone: str) -> Dict[str, Any]:
    prop = property_for_user(me_phone)
    return json_ready({
        "ok": True,
        "logged_in": bool(me_phone),
        "property": prop,
    })
