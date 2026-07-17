# -*- coding: utf-8 -*-
"""Phase 5 portal hub routes — Buyer / Seller / Owner."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.roles.config import roles_ui_enabled
from app.roles.interfaces import PORTAL_BUYER, PORTAL_OWNER, PORTAL_SELLER
from app.roles.service import require_portal_role, resolve_portals

roles_bp = Blueprint("roles", __name__)


def _ui_or_404():
    if not roles_ui_enabled():
        from flask import abort

        abort(404)


@roles_bp.get("/my", endpoint="buyer_hub")
@require_portal_role(PORTAL_BUYER)
def buyer_hub():
    _ui_or_404()
    me_phone = (session.get("user_phone") or "").strip()
    offers_count = 0
    try:
        from app.commercial.config import commercial_buyer_ui_enabled
        from app.commercial.service import list_buyer_offers

        if commercial_buyer_ui_enabled():
            offers_count = len(list_buyer_offers(me_phone))
    except Exception:
        offers_count = 0
    deals_count = 0
    try:
        from app.closing import store as closing_store

        deals_count = sum(
            1
            for d in closing_store.list_deals(limit=200)
            if (d.buyer_phone or "").strip() == me_phone
        )
    except Exception:
        deals_count = 0
    resolved = resolve_portals(me_phone, session=session)
    return render_template(
        "portals/buyer_hub.html",
        me_phone=me_phone,
        offers_count=offers_count,
        deals_count=deals_count,
        roles=resolved.roles,
        flash_msg=(request.args.get("msg") or "").strip(),
        flash_ok=(request.args.get("ok") or "1").strip() != "0",
    )


@roles_bp.get("/portal/seller", endpoint="seller_hub")
@require_portal_role(PORTAL_SELLER)
def seller_hub():
    _ui_or_404()
    me_phone = (session.get("user_phone") or "").strip()
    resolved = resolve_portals(me_phone, session=session)
    return render_template(
        "portals/seller_hub.html",
        me_phone=me_phone,
        roles=resolved.roles,
        is_owner=resolved.is_owner,
    )


@roles_bp.get("/portal/owner", endpoint="owner_hub")
@require_portal_role(PORTAL_OWNER)
def owner_hub():
    _ui_or_404()
    me_phone = (session.get("user_phone") or "").strip()
    resolved = resolve_portals(me_phone, session=session)
    listings_count = 0
    try:
        from app.express_partner.special_listings import listings_owned_by

        listings_count = len(listings_owned_by(me_phone))
    except Exception:
        listings_count = 0
    return render_template(
        "portals/owner_hub.html",
        me_phone=me_phone,
        roles=resolved.roles,
        listings_count=listings_count,
        is_seller=resolved.is_seller,
    )
