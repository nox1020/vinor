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
    not sold/closed/archived/hidden. The carousel's Garmabsard service-focus
    check stays there; it limits the home strip, not whether the URL is public.
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
