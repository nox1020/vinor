"""کارت فایل برای چت Vinor AI — پیش‌فرض کارت کامل جزئیات، نه کارت فشردهٔ داشبورد."""
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
    # Partner: کاتالوگ اکسپرس وسیع‌تر تا انتخاب/بازدید از چت محدود به چند نمونه نباشد
    limit = 200 if aud == AUDIENCE_PARTNER else 25
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


def line_is_land_code_ref(line: str, codes: list[str] | None = None) -> bool:
    """خط‌های «فایل: کد/عنوان» که با کارت جایگزین می‌شوند."""
    s = str(line or "").strip()
    if not s:
        return False
    code_set = {str(c).strip() for c in (codes or []) if str(c).strip()}
    if re.match(r"^فایل\s*[:：]", s):
        if not code_set:
            return True
        return any(c in s for c in code_set) or True
    if code_set:
        for c in code_set:
            if not c:
                continue
            if s == c or s == f"فایل {c}" or f"({c})" in s:
                return True
    return False


def filter_lines_without_land_codes(
    lines: list[Any] | None,
    codes: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    for raw in lines or []:
        s = str(raw or "").strip()
        if not s or line_is_land_code_ref(s, codes):
            continue
        out.append(s)
    return out


def strip_visible_land_codes(text: str, codes: list[str] | None) -> str:
    """حذف کد خام از متن قابل‌نمایش وقتی کارت فایل نشان داده می‌شود."""
    out = str(text or "")
    want = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not out or not want:
        return out
    for c in want:
        esc = re.escape(c)
        out = re.sub(rf"\(\s*{esc}\s*\)", "", out)
        out = re.sub(rf"فایل\s*[:：]\s*{esc}\b", "این فایل", out, flags=re.IGNORECASE)
        out = re.sub(rf"فایل\s+{esc}\b", "این فایل", out, flags=re.IGNORECASE)
        out = re.sub(rf"(?<![\w./-]){esc}(?![\w./-])", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" ?، ?،", "،", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


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
    # وقتی کارت می‌آید، کد خام در متن نماند
    if merged:
        cleaned = strip_visible_land_codes(cleaned, merged)
    return cleaned, merged[:2]


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


def _compact_premium_card_html(land: dict[str, Any], *, show_commission: bool) -> str:
    return render_template(
        "express_partner/partials/land_premium_card.html",
        land=land,
        is_approved=show_commission,
        tour_land_card=False,
        for_ai_chat=True,
        card_layout="horizontal",
    )


def _full_land_card_html(code: str) -> str:
    """کارت کامل فایل داخل چت — نه کارت فشردهٔ داشبورد."""
    if not code:
        return ""
    try:
        from app.express_partner.land_chat_detail import render_land_chat_detail_html

        payload = render_land_chat_detail_html(code)
    except Exception:
        payload = None
    if not payload:
        return ""
    return str(payload.get("html") or "").strip()


def _slot_html(inner: str, *, full: bool) -> str:
    slot_cls = "ai-land-cards__slot vinor-dash-card-slot"
    if full:
        slot_cls += " ai-land-cards__slot--full"
    return f'<div class="{slot_cls}" role="listitem">{inner}</div>'


def render_land_cards_html(
    phone: str,
    codes: list[str],
    *,
    audience: str | None = None,
    layout: str = "full",
) -> str:
    """HTML فایل‌ها برای چت: پیش‌فرض کارت کامل (`vn-lcd`). compact فقط برای صفحات جانبی."""
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    full = (layout or "full").strip().lower() != "compact"
    lands = resolve_lands(phone, codes[:2], aud)
    if not lands:
        return ""
    parts: list[str] = []
    show_commission = aud == AUDIENCE_PARTNER and partner_is_approved(phone)
    for land in lands:
        code = str(land.get("code") or "").strip()
        inner = (
            _full_land_card_html(code)
            if full
            else _compact_premium_card_html(land, show_commission=show_commission)
        )
        if not inner:
            continue
        parts.append(_slot_html(inner, full=full))
    if not parts:
        return ""
    wrap_cls = "ai-land-cards no-scrollbar"
    if full:
        wrap_cls += " ai-land-cards--full"
    return (
        f'<div class="{wrap_cls}" role="list" aria-label="فایل‌های پیشنهادی">'
        + "".join(parts)
        + "</div>"
    )


def land_cards_payload(
    phone: str,
    codes: list[str],
    *,
    audience: str | None = None,
    layout: str = "full",
) -> list[dict[str, str]]:
    """برای API JSON: کد + HTML هر کارت."""
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    full = (layout or "full").strip().lower() != "compact"
    lands = resolve_lands(phone, codes[:2], aud)
    if not lands:
        return []
    show_commission = aud == AUDIENCE_PARTNER and partner_is_approved(phone)
    payload: list[dict[str, str]] = []
    for land in lands:
        code = str(land.get("code") or "").strip()
        inner = (
            _full_land_card_html(code)
            if full
            else _compact_premium_card_html(land, show_commission=show_commission)
        )
        if not inner:
            continue
        payload.append({"code": code, "html": _slot_html(inner, full=full)})
    return payload


LAND_CARDS_BATCH_MAX = 10


def parse_land_code_list(raw: str) -> list[str]:
    """Comma-separated codes, order kept, duplicates dropped."""
    out: list[str] = []
    seen: set[str] = set()
    for bit in str(raw or "").replace("،", ",").split(","):
        code = bit.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def land_cards_batch(
    phone: str,
    codes: list[str],
    *,
    audience: str | None = None,
) -> dict[str, Any]:
    """On-demand card HTML for codes the viewer is allowed to see.

    The chat message cap of two cards does not apply here. Callers enforce
    ``LAND_CARDS_BATCH_MAX``. Codes outside ``accessible_lands_map`` are listed
    in ``missing`` and their HTML is not built.
    """
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    lands_map = accessible_lands_map(phone, aud)
    cards: list[dict[str, str]] = []
    missing: list[str] = []
    for code in codes:
        land = lands_map.get(str(code).strip())
        if not land:
            missing.append(code)
            continue
        inner = _full_land_card_html(code)
        if not inner:
            missing.append(code)
            continue
        cards.append({"code": code, "html": _slot_html(inner, full=True)})
    return {"ok": True, "cards": cards, "missing": missing}
