"""کارت فایل داشبورد — برای نمایش در چت Vinor AI."""
from __future__ import annotations

import re
from typing import Any

from flask import render_template, url_for

from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from app.ai.context import _assigned_lands, _public_lands_sample
from app.utils.storage import load_express_partners

LAND_MARKER_RE = r"\[\[LAND:([^\]]+)\]\]"


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def partner_is_approved(phone: str) -> bool:
    me = _norm_phone(phone)
    if not me:
        return False
    partners = load_express_partners() or []
    prof = next((p for p in partners if _norm_phone(str(p.get("phone") or "")) == me), None)
    if not prof:
        return False
    return prof.get("status") in ("approved", True)


def accessible_lands_map(phone: str, audience: str | None = None) -> dict[str, dict[str, Any]]:
    """فایل‌های قابل نمایش بر اساس مخاطب."""
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    out: dict[str, dict[str, Any]] = {}
    if aud == AUDIENCE_PARTNER:
        for land in _assigned_lands(phone):
            code = str(land.get("code") or "").strip()
            if not code:
                continue
            item = dict(land)
            item["_is_public"] = False
            out[code] = item
    limit = 80 if aud == AUDIENCE_PARTNER else 25
    for land in _public_lands_sample(limit):
        code = str(land.get("code") or "").strip()
        if not code or code in out:
            continue
        item = dict(land)
        item["_assignment_status"] = "public"
        item["_commission_pct"] = item.get("_commission_pct") or 0
        item["_commission_amount"] = item.get("_commission_amount") or 0
        item["_is_public"] = True
        out[code] = item
    return out


def _prepare_land_item(land: dict[str, Any], audience: str | None = None) -> dict[str, Any]:
    item = dict(land)
    code = str(item.get("code") or "").strip()
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    try:
        if aud == AUDIENCE_PUBLIC:
            item["_detail_url"] = url_for("main.express_detail", code=code)
        else:
            item["_detail_url"] = url_for("express_partner.land_detail", code=code)
    except Exception:
        if aud == AUDIENCE_PUBLIC:
            item["_detail_url"] = f"/express/{code}" if code else ""
        else:
            item["_detail_url"] = f"/express/partner/lands/{code}" if code else ""
    return item


def strip_land_markers(text: str) -> tuple[str, list[str]]:
    """حذف مارکرها از متن؛ استخراج کدها به ترتیب."""
    if not text:
        return "", []
    codes: list[str] = []
    for m in re.finditer(LAND_MARKER_RE, text, flags=re.IGNORECASE):
        c = (m.group(1) or "").strip()
        if c and c not in codes:
            codes.append(c)
    cleaned = re.sub(LAND_MARKER_RE, "", text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, codes


def collect_land_codes(
    reply_text: str,
    *,
    user_text: str = "",
    phone: str = "",
    audience: str | None = None,
) -> tuple[str, list[str]]:
    """متن تمیز + کدهای فایل فقط از مارکر صریح [[LAND:کد]].

    کارت فایل فقط وقتی مدل عمداً پیشنهاد می‌کند نشان داده می‌شود؛
    ذکر معمولی کد در متن کاربر/پاسخ کارت نمی‌سازد.
    """
    del user_text  # عمداً برای استنباط خودکار استفاده نمی‌شود
    cleaned, from_markers = strip_land_markers(reply_text)
    if not from_markers:
        return cleaned, []
    lands_map = accessible_lands_map(phone, audience) if phone else accessible_lands_map("", audience)
    merged: list[str] = []
    for c in from_markers:
        if c in lands_map and c not in merged:
            merged.append(c)
    return cleaned, merged[:5]


def resolve_lands(phone: str, codes: list[str], audience: str | None = None) -> list[dict[str, Any]]:
    if not codes:
        return []
    lands_map = accessible_lands_map(phone, audience)
    out: list[dict[str, Any]] = []
    for code in codes:
        land = lands_map.get(str(code).strip())
        if land:
            out.append(_prepare_land_item(land, audience))
    return out


def render_land_cards_html(
    phone: str,
    codes: list[str],
    *,
    audience: str | None = None,
) -> str:
    """HTML کارت‌های داشبورد (همان partial)."""
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    lands = resolve_lands(phone, codes, aud)
    if not lands:
        return ""
    parts: list[str] = []
    show_commission = aud == AUDIENCE_PARTNER and partner_is_approved(phone)
    for land in lands:
        parts.append(
            render_template(
                "express_partner/partials/land_premium_card.html",
                land=land,
                is_approved=show_commission,
                tour_land_card=False,
                for_ai_chat=True,
                card_layout="horizontal",
            )
        )
    wrapper = (
        '<div class="ai-land-cards no-scrollbar" role="list" aria-label="فایل‌های پیشنهادی">'
        + "".join(
            '<div class="ai-land-cards__slot vinor-dash-card-slot" role="listitem">'
            + p
            + "</div>"
            for p in parts
        )
        + "</div>"
    )
    return wrapper


def land_cards_payload(
    phone: str,
    codes: list[str],
    *,
    audience: str | None = None,
) -> list[dict[str, str]]:
    """برای API JSON: کد + HTML هر کارت."""
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    lands = resolve_lands(phone, codes, aud)
    if not lands:
        return []
    show_commission = aud == AUDIENCE_PARTNER and partner_is_approved(phone)
    payload: list[dict[str, str]] = []
    for land in lands:
        code = str(land.get("code") or "").strip()
        html = render_template(
            "express_partner/partials/land_premium_card.html",
            land=land,
            is_approved=show_commission,
            tour_land_card=False,
            for_ai_chat=True,
            card_layout="horizontal",
        )
        payload.append(
            {
                "code": code,
                "html": (
                    '<div class="ai-land-cards__slot vinor-dash-card-slot" role="listitem">'
                    + html
                    + "</div>"
                ),
            }
        )
    return payload
