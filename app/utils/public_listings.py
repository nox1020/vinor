# -*- coding: utf-8 -*-
"""Which express listings are publicly visible.

The home carousel and the sitemap share this predicate so a listing that
visitors cannot see in the public feed is not advertised to crawlers.
"""
from __future__ import annotations

from typing import Any

# ``express_status`` values ``_home_public_carousel_lands`` drops.
# Sold is stored on ``express_status`` (not a separate flag). ``status`` is the
# moderation field (approved/pending) and is not a visibility switch.
_NONPUBLIC_EXPRESS_STATUSES = frozenset({
    "sold",
    "closed",
    "archived",
    "hidden",
})


def is_publicly_visible_listing(land: Any) -> bool:
    """True when a listing belongs on the public feed and in the sitemap.

    Same rules as ``_home_public_carousel_lands``: express listing with a code,
    not ``public=False``, not an unpublished owner-home, not admin-created, and
    not sold/closed/archived/hidden. A sale publish older than 30 days is not
    public even before the stop sweep writes the unpublished flags. City does
    not decide visibility.
    """
    if not isinstance(land, dict):
        return False
    try:
        from app.listings.sale_publish_window import sale_publish_expired

        if sale_publish_expired(land):
            return False
    except Exception:
        pass
    try:
        from app.listings.service import is_archived

        if is_archived(land):
            return False
    except Exception:
        if land.get("archived") is True:
            return False
    if not land.get("is_express"):
        return False
    if not str(land.get("code") or "").strip():
        return False
    if land.get("public") is False:
        return False
    express_status = str(land.get("express_status") or "").strip().lower()
    if express_status in _NONPUBLIC_EXPRESS_STATUSES:
        return False
    try:
        from app.express_partner.special_listings import (
            is_admin_created_express_listing,
            is_owner_home,
        )

        if is_admin_created_express_listing(land):
            return False
        if is_owner_home(land):
            return False
    except Exception:
        if land.get("owner_home") and land.get("public") is not True:
            return False
    return True


def is_partner_assignment_land(land: Any) -> bool:
    """فهرست اختصاص همکار فقط آگهی اکسپرسِ عمومی را نشان می‌دهد.

    ملک خصوصی «ملک من» و آگهی با ``public=False`` نمی‌آید. فروخته‌شدهٔ
    اکسپرس می‌ماند چون داشبورد همکار آن را در انتهای لیست نشان می‌دهد.
    """
    if not isinstance(land, dict):
        return False
    try:
        from app.listings.service import is_archived

        if is_archived(land):
            return False
    except Exception:
        if land.get("archived") is True:
            return False
    if not land.get("is_express"):
        return False
    if land.get("public") is False:
        return False
    try:
        from app.express_partner.special_listings import is_owner_home

        if is_owner_home(land):
            return False
    except Exception:
        extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
        if land.get("owner_home") or extras.get("owner_home"):
            return False
    return True


# Fields a visitor or the Android chat card may see.
# Listing.kt and the home-card builders read the publish flags. Phones,
# contact numbers, names, and national ids never leave this list.
PUBLIC_LISTING_FIELDS = (
    "id",
    "code",
    "title",
    "price_total",
    "price",
    "city",
    "location",
    "district",
    "category",
    "size",
    "rooms",
    "floor",
    "year_built",
    "description",
    "features",
    "docs_status",
    "latitude",
    "longitude",
    "land_area",
    "built_area",
    "villa_built_area",
    "area",
    "street_width",
    "created_at",
    "updated_at",
    "image_url",
    "public",
    "source",
    "is_express",
    "ad_type",
    "badge_label",
    "owner_home",
    "published_for_sale",
    "listed_by_owner",
    "listed_by_special",
    "previous_code",
    "status",
    "express_status",
)

# Flags Listing.kt copies out of extras. Nothing else in extras is public.
PUBLIC_EXTRAS_FIELDS = (
    "previous_code",
    "published_for_sale",
    "listed_by_owner",
    "owner_home",
    "public",
    "listed_by_special",
)


def public_image_urls(land: Any) -> list[str]:
    if not isinstance(land, dict):
        return []
    images = land.get("images")
    if not isinstance(images, list):
        return []
    urls: list[str] = []
    for image in images:
        if isinstance(image, str) and image.strip():
            urls.append(image.strip())
    return urls


def _public_value(value: Any) -> bool:
    """False and 0 are real flags. Only missing and blank strings are dropped."""
    return value is not None and value != ""


def public_extras(land: Any) -> dict[str, Any]:
    """Safe publish flags from extras. Phones, notes, and names are dropped."""
    if not isinstance(land, dict):
        return {}
    extras = land.get("extras")
    if not isinstance(extras, dict):
        return {}
    out: dict[str, Any] = {}
    for key in PUBLIC_EXTRAS_FIELDS:
        if key not in extras:
            continue
        value = extras.get(key)
        if not _public_value(value):
            continue
        out[key] = value
    return out


def public_listing_view(land: Any, *, cover: tuple[str, str, str] | None = None) -> dict[str, Any]:
    """Allow-listed listing card. Drops owner phones, contact numbers, and private extras."""
    if not isinstance(land, dict):
        return {}
    out: dict[str, Any] = {}
    for key in PUBLIC_LISTING_FIELDS:
        if key not in land:
            continue
        value = land.get(key)
        if not _public_value(value):
            continue
        out[key] = value
    images = public_image_urls(land)
    if images:
        out["images"] = images
    extras = public_extras(land)
    if extras:
        out["extras"] = extras
    if cover:
        thumb, full, raw = cover
        if thumb:
            out["image_thumb"] = thumb
        if full:
            out["image_full"] = full
        if raw:
            out["image_raw"] = raw
    return out
