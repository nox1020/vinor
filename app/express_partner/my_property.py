"""ملک من — داشبورد مالک به‌سبک Redfin My Home."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from flask import url_for

from .apk_native import json_ready


def feature_enabled() -> bool:
    return (os.environ.get("VINOR_MY_PROPERTY_ENABLED") or "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value: Any) -> str:
    return str(value).translate(_FA_DIGITS)


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


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    raw = str(value).replace(",", "").replace("،", "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _unknown_market() -> Dict[str, Any]:
    """کلیدهای قدیمی نمودار قیمت می‌مانند، ولی دیگر عدد ساختگی ندارند."""
    return {
        "monthly_change_pct": None,
        "monthly_change_label": None,
        "yearly_change_pct": None,
        "yearly_change_label": None,
        "neighborhood_avg": None,
        "equity": {"total": None, "paid_off_pct": None},
        "price_history": [],
    }


def _activity_from_stats(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    published_at = stats.get("published_at")
    if published_at:
        rows.append({
            "type": "publish",
            "text": "برای فروش منتشر شد",
            "date": published_at,
        })
    weekly = int(stats.get("weekly_views") or 0)
    if weekly:
        rows.append({
            "type": "view",
            "text": f"{fa_digits(weekly)} بازدید همکار در ۷ روز اخیر",
            "date": "",
        })
    week_visits = int(stats.get("visit_requests_7d") or 0)
    total_visits = int(stats.get("visit_requests_total") or 0)
    if week_visits:
        rows.append({
            "type": "visit",
            "text": f"{fa_digits(week_visits)} درخواست بازدید در ۷ روز اخیر",
            "date": "",
        })
    elif total_visits:
        rows.append({
            "type": "visit",
            "text": f"{fa_digits(total_visits)} درخواست بازدید از زمان انتشار",
            "date": "",
        })
    return rows


def _sale_publish_fields(land: Dict[str, Any] | None) -> Dict[str, Any]:
    try:
        from app.listings.sale_publish_window import sale_publish_fields

        return sale_publish_fields(land if isinstance(land, dict) else None)
    except Exception:
        return {
            "sale_publish_expires_at": None,
            "sale_publish_remaining_seconds": None,
        }


def _performance(land: Dict[str, Any] | None) -> Dict[str, Any]:
    try:
        from app.listings.performance import listing_performance

        stats = listing_performance(land if isinstance(land, dict) else None)
    except Exception:
        stats = {
            "weekly_views": 0,
            "views_since_publish": 0,
            "visit_requests_7d": 0,
            "visit_requests_total": 0,
            "published_at": None,
            "first_published_at": None,
            "days_since_publish": None,
        }
    return stats


def demo_property() -> Dict[str, Any]:
    stats = _performance(None)
    card = {
        "id": "demo-home",
        "is_demo": True,
        "cover_image": "",
        "gallery_count": 0,
        "address": "",
        "city": "",
        "state": "",
        "zip": "",
        "beds": None,
        "baths": None,
        "sqm": None,
        "built_year": None,
        "beds_label": "",
        "baths_label": "",
        "sqm_label": "",
        "built_year_label": "",
        "zip_label": "",
        "gallery_label": fa_digits(0),
        "estimated_value": None,
        "price_per_sqm": None,
        "weekly_views": stats["weekly_views"],
        "views_since_publish": stats["views_since_publish"],
        "visit_requests_7d": stats["visit_requests_7d"],
        "visit_requests_total": stats["visit_requests_total"],
        "published_at": stats["published_at"],
        "first_published_at": stats["first_published_at"],
        "days_since_publish": stats["days_since_publish"],
        "is_claimed": False,
        "badge_label": "خصوصی",
        "privacy_note": "بعد از ثبت ملک، آمار واقعی انتشار اینجا می‌آید",
        "published_for_sale": False,
        "sale_publish_expires_at": None,
        "sale_publish_remaining_seconds": None,
        "nearby_listings": [],
        "activity": [],
        "edit_url": "",
        "photos_url": "",
        "settings_url": "",
        "sell_url": "",
    }
    card.update(_unknown_market())
    return card


def _from_land(land: Dict[str, Any], nearby: List[Dict[str, Any]]) -> Dict[str, Any]:
    price = _optional_int(land.get("price_total") if land.get("price_total") not in (None, "") else land.get("price"))
    sqm = _optional_int(land.get("size") if land.get("size") not in (None, "") else land.get("sqm"))
    ppm = int(round(price / sqm)) if price and sqm else None
    beds = _optional_int(land.get("beds") if land.get("beds") not in (None, "") else land.get("rooms"))
    baths = _optional_int(land.get("baths"))
    built_year = _optional_int(
        land.get("built_year") if land.get("built_year") not in (None, "") else land.get("year_built")
    )
    code = str(land.get("code") or "").strip()
    stats = _performance(land)
    gallery = _gallery_count(land)
    try:
        from .special_listings import is_published_for_sale
        published = is_published_for_sale(land)
    except Exception:
        published = False
    try:
        edit_url = url_for("express_partner.my_property")
    except Exception:
        edit_url = ""
    try:
        detail_url = url_for("express_partner.land_detail", code=code) if published and code else ""
    except Exception:
        detail_url = f"/express/partner/lands/{code}" if published and code else ""
    card = {
        "id": code or "claimed-home",
        "is_demo": False,
        "cover_image": _cover_url(land),
        "gallery_count": gallery,
        "gallery_label": fa_digits(gallery),
        "address": str(land.get("title") or land.get("location") or "").strip(),
        "city": str(land.get("city") or "").strip(),
        "state": str(land.get("province") or land.get("state") or "").strip(),
        "zip": str(land.get("zip") or land.get("postal_code") or "").strip(),
        "zip_label": fa_digits(str(land.get("zip") or land.get("postal_code") or "").strip()),
        "beds": beds,
        "baths": baths,
        "sqm": sqm,
        "built_year": built_year,
        "beds_label": fa_digits(beds) if beds is not None else "",
        "baths_label": fa_digits(baths) if baths is not None else "",
        "sqm_label": fa_digits(sqm) if sqm is not None else "",
        "built_year_label": fa_digits(built_year) if built_year is not None else "",
        "estimated_value": price,
        "price_per_sqm": ppm,
        "weekly_views": stats["weekly_views"],
        "views_since_publish": stats["views_since_publish"],
        "visit_requests_7d": stats["visit_requests_7d"],
        "visit_requests_total": stats["visit_requests_total"],
        "published_at": stats["published_at"],
        "first_published_at": stats["first_published_at"],
        "days_since_publish": stats["days_since_publish"],
        "is_claimed": True,
        "badge_label": "منتشرشده" if published else "خصوصی",
        "privacy_note": (
            "این ملک برای فروش در آگهی‌های وینور منتشر شده است"
            if published else
            "فقط شما این ملک را می‌بینید · برای فروش هنوز منتشر نشده"
        ),
        "published_for_sale": published,
        **_sale_publish_fields(land),
        "nearby_listings": list(nearby or []),
        "activity": _activity_from_stats(stats),
        "edit_url": edit_url,
        "photos_url": edit_url,
        "settings_url": "",
        "sell_url": "",
        "detail_url": detail_url,
        "code": code,
    }
    card.update(_unknown_market())
    return card


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


def property_cards(me_phone: str) -> List[Dict[str, Any]]:
    """همهٔ ملک‌ها و آگهی‌های این شماره برای لیست کارت دیوار."""
    from .apk_native import land_card
    from .special_listings import (
        detail_sale_flag,
        ensure_unique_land_codes,
        listings_owned_by,
        listings_owned_home,
    )

    try:
        ensure_unique_land_codes()
    except Exception:
        pass

    seen = set()
    out: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    try:
        rows.extend(listings_owned_home(me_phone) if me_phone else [])
    except Exception:
        pass
    try:
        rows.extend(listings_owned_by(me_phone) if me_phone else [])
    except Exception:
        pass
    for land in rows:
        if not isinstance(land, dict):
            continue
        code = str(land.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        card = land_card(land)
        published = False
        try:
            published = detail_sale_flag(land)
        except Exception:
            published = False
        img = str(card.get("image_url") or "").strip()
        images = [img] if img else []
        try:
            detail_url = url_for("express_partner.land_detail", code=code)
        except Exception:
            detail_url = f"/express/partner/lands/{code}"
        stats = _performance(land)
        card.update({
            "images": images,
            "image_count": len(images),
            "published_for_sale": published,
            **_sale_publish_fields(land),
            "badge_label": "منتشرشده" if published else "خصوصی",
            "_status_label": "منتشرشده" if published else "خصوصی",
            "_status_class": "text-emerald-400" if published else "text-slate-400",
            "_detail_url": detail_url,
            "detail_url": detail_url,
            "video": land.get("video") or "",
            "_commission_amount": int(card.get("commission_amount") or 0),
            "weekly_views": stats["weekly_views"],
            "views_since_publish": stats["views_since_publish"],
            "visit_requests_7d": stats["visit_requests_7d"],
            "visit_requests_total": stats["visit_requests_total"],
            "published_at": stats["published_at"],
            "first_published_at": stats["first_published_at"],
            "days_since_publish": stats["days_since_publish"],
            "monthly_change_pct": None,
            "monthly_change_label": None,
            "yearly_change_pct": None,
            "yearly_change_label": None,
            "neighborhood_avg": None,
            "equity": {"total": None, "paid_off_pct": None},
            "price_history": [],
            "activity": _activity_from_stats(stats),
        })
        try:
            from app.listings.service import archive_payload

            card.update(archive_payload(land))
        except Exception:
            card.update({
                "archived": False,
                "is_archived": False,
                "archived_at": "",
                "archived_reason": "",
            })
        out.append(card)
    return out


def page_payload(me_phone: str, status: str = "active") -> Dict[str, Any]:
    try:
        from app.listings.service import sweep_inactive_listings

        if me_phone:
            sweep_inactive_listings()
    except Exception:
        pass
    items = property_cards(me_phone) if me_phone else []
    want_archived = str(status or "").strip().lower() == "archived"
    active_items = [item for item in items if not item.get("archived")]
    archived_items = [item for item in items if item.get("archived")]
    shown = archived_items if want_archived else active_items
    shown_codes = {str(item.get("code") or "") for item in shown}
    prop = property_for_user(me_phone)
    if not isinstance(prop, dict) or str(prop.get("code") or "") not in shown_codes:
        prop = shown[0] if shown else None
    divar: List[Dict[str, Any]] = []
    try:
        from .home_ads_config import partner_divar_profile_entries

        for entry in partner_divar_profile_entries(me_phone) or []:
            if not isinstance(entry, dict):
                continue
            divar.append(entry)
    except Exception:
        divar = []
    try:
        form_url = url_for("express_partner.my_property")
    except Exception:
        form_url = "/express/partner/my-property"
    try:
        publish_url = url_for("express_partner.apk_my_property_publish")
    except Exception:
        publish_url = "/express/partner/api/my-property/publish"
    stats = prop or _performance(None)
    return json_ready({
        "ok": True,
        "logged_in": bool(me_phone),
        "has_property": bool(items),
        "status": "archived" if want_archived else "active",
        "counts": {"active": len(active_items), "archived": len(archived_items)},
        "form_url": form_url,
        "publish_url": publish_url,
        "published_for_sale": bool(prop and prop.get("published_for_sale")),
        "sale_publish_expires_at": None if not prop else prop.get("sale_publish_expires_at"),
        "sale_publish_remaining_seconds": None if not prop else prop.get("sale_publish_remaining_seconds"),
        "payment_methods": ["نقدی", "توافقی", "معاوضه"],
        "default_commission_pct": "2",
        "weekly_views": stats.get("weekly_views", 0),
        "views_since_publish": stats.get("views_since_publish", 0),
        "visit_requests_7d": stats.get("visit_requests_7d", 0),
        "visit_requests_total": stats.get("visit_requests_total", 0),
        "published_at": stats.get("published_at"),
        "first_published_at": stats.get("first_published_at"),
        "days_since_publish": stats.get("days_since_publish"),
        "items": shown,
        "listings": shown,
        "divar_profiles": divar,
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
        page_subtitle = "ابتدا ملک را برای خودتان ثبت کنید؛ بعد از ثبت می‌توانید برای فروش منتشر کنید"
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
