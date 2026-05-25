"""کارت فایل داشبورد — برای نمایش در چت Vinor AI."""
from __future__ import annotations

import re
from typing import Any

from flask import render_template, url_for

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


def accessible_lands_map(phone: str) -> dict[str, dict[str, Any]]:
    """همه فایل‌های قابل نمایش برای همکار: اختصاصی + عمومی."""
    out: dict[str, dict[str, Any]] = {}
    for land in _assigned_lands(phone):
        code = str(land.get("code") or "").strip()
        if not code:
            continue
        item = dict(land)
        item["_is_public"] = False
        out[code] = item
    for land in _public_lands_sample(80):
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


def _prepare_land_item(land: dict[str, Any]) -> dict[str, Any]:
    item = dict(land)
    code = str(item.get("code") or "").strip()
    try:
        item["_detail_url"] = url_for("express_partner.land_detail", code=code)
    except Exception:
        item["_detail_url"] = f"/express/partner/land/{code}" if code else ""
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


def infer_codes_from_text(text: str, lands_map: dict[str, dict[str, Any]]) -> list[str]:
    """اگر کد فایل در متن آمده (بدون مارکر)، همان را پیدا کن."""
    if not text or not lands_map:
        return []
    found: list[str] = []
    for code in lands_map:
        if not code:
            continue
        if re.search(r"(?<!\w)" + re.escape(code) + r"(?!\w)", text):
            if code not in found:
                found.append(code)
    return found


def collect_land_codes(
    reply_text: str,
    *,
    user_text: str = "",
    phone: str = "",
) -> tuple[str, list[str]]:
    """متن تمیز + لیست یکتا کدهای فایل برای کارت."""
    cleaned, from_markers = strip_land_markers(reply_text)
    lands_map = accessible_lands_map(phone) if phone else {}
    merged: list[str] = []
    for c in from_markers:
        if c in lands_map and c not in merged:
            merged.append(c)
    for c in infer_codes_from_text(cleaned, lands_map):
        if c not in merged:
            merged.append(c)
    for c in infer_codes_from_text(user_text or "", lands_map):
        if c not in merged:
            merged.append(c)
    return cleaned, merged[:5]


def resolve_lands(phone: str, codes: list[str]) -> list[dict[str, Any]]:
    if not codes:
        return []
    lands_map = accessible_lands_map(phone)
    out: list[dict[str, Any]] = []
    for code in codes:
        land = lands_map.get(str(code).strip())
        if land:
            out.append(_prepare_land_item(land))
    return out


def render_land_cards_html(phone: str, codes: list[str]) -> str:
    """HTML کارت‌های داشبورد (همان partial)."""
    lands = resolve_lands(phone, codes)
    if not lands:
        return ""
    parts: list[str] = []
    approved = partner_is_approved(phone)
    for land in lands:
        parts.append(
            render_template(
                "express_partner/partials/land_premium_card.html",
                land=land,
                is_approved=approved,
                tour_land_card=False,
                for_ai_chat=True,
            )
        )
    wrapper = (
        '<div class="ai-land-cards mt-2.5 flex w-full max-w-full flex-col gap-2.5">'
        + "".join(
            '<div class="vinor-dash-card-slot w-full max-w-full shrink-0">'
            + p
            + "</div>"
            for p in parts
        )
        + "</div>"
    )
    return wrapper


def land_cards_payload(phone: str, codes: list[str]) -> list[dict[str, str]]:
    """برای API JSON: کد + HTML هر کارت."""
    lands = resolve_lands(phone, codes)
    if not lands:
        return []
    approved = partner_is_approved(phone)
    payload: list[dict[str, str]] = []
    for land in lands:
        code = str(land.get("code") or "").strip()
        html = render_template(
            "express_partner/partials/land_premium_card.html",
            land=land,
            is_approved=approved,
            tour_land_card=False,
            for_ai_chat=True,
        )
        payload.append(
            {
                "code": code,
                "html": (
                    '<div class="vinor-dash-card-slot w-full max-w-full shrink-0">'
                    + html
                    + "</div>"
                ),
            }
        )
    return payload
