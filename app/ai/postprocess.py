"""پس‌پردازش پاسخ چت — سبک پاسخ، مارکر ارجاع، و مونتاژ کارت‌ها.

هیچ HTML‌ای از مدل نمی‌آید: کارت‌ها همیشه در Backend رندر می‌شوند
(`land_cards` / `render_agent_actions_html`). قبلاً این توابع داخل
`services.py` بودند.
"""
from __future__ import annotations

import os
import re
from typing import Any

from .config import ESCALATE_MARKER_RE
from .confirmation import has_pending_confirm_card

_UNCONFIRMED_CLAIM_RE = re.compile(
    r"(مشتری\s*ثبت\s*شد|بازدید\s*ثبت\s*شد|معامله\s*ثبت\s*شد|"
    r"ثبت\s*شد|انجام\s*شد|تکمیل\s*شد|ذخیره\s*شد|معامله\s*شد)",
    re.I,
)


def strip_escalate_marker(text: str) -> tuple[str, str | None]:
    """مارکر ارجاع به ادمین را جدا کن؛ متن قابل‌نمایش را برگردان."""
    if not text:
        return "", None
    m = re.search(ESCALATE_MARKER_RE, text, flags=re.DOTALL)
    if not m:
        return text.strip(), None
    summary = (m.group(1) or "").strip() or None
    cleaned = re.sub(ESCALATE_MARKER_RE, "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, summary


def strip_listing_dump_when_copy_cards(text: str) -> str:
    """وقتی کارت کپی هست، بلاک کد و تکرار متن آگهی را از پیام حذف کن."""
    raw = (text or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"```[\s\S]*?```", "", raw).strip()
    cleaned = re.sub(
        r"(?im)^(?:\*\*)?(?:متن دیوار|کپشن اینستا|متن آگهی(?: دیوار)?|آگهی دیوار)(?:\*\*)?\s*:?\s*$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) < 8:
        return "آماده‌ست — از کارت‌های زیر کپی کن و منتشر کن."
    return cleaned


def style_enforce_enabled() -> bool:
    return (os.environ.get("VINOR_AI_STYLE_ENFORCE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _compact_option_blocks(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    out: list[str] = []
    bucket: list[str] = []

    def flush_bucket() -> None:
        nonlocal bucket
        if len(bucket) >= 2:
            picked = [x for x in bucket if x][:4]
            if picked:
                out.append("گزینه‌ها: " + " / ".join(picked))
            bucket = []
            return
        if len(bucket) == 1:
            out.append(bucket[0])
        bucket = []

    for raw in lines:
        if not raw:
            flush_bucket()
            continue
        m = re.match(r"^\s*(?:[-*•]|\d+[)\.-]|[✅☑️🔹🔸▫️▪️])\s*(.+?)\s*$", raw)
        if m:
            label = re.sub(r"\s+", " ", (m.group(1) or "").strip())
            label = re.sub(r"^گزینه(?:‌)?ها?\s*:\s*", "", label, flags=re.IGNORECASE)
            if label:
                bucket.append(label[:32])
            continue
        if " / " in raw and ("گزینه" in raw or raw.count("/") >= 2):
            flush_bucket()
            out.append(raw)
            continue
        flush_bucket()
        out.append(raw)
    flush_bucket()
    return "\n".join([x for x in out if x]).strip()


def _truncate_lines(text: str, max_lines: int = 8) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines])


def _ensure_next_step(reply: str) -> str:
    text = (reply or "").strip()
    if not text:
        return "قدم بعد: بگو خرید می‌خوای یا فروش؟"
    if re.search(r"(?im)^\s*(?:قدم|مرحله)\s*بعد\s*:", text):
        return text
    # فقط اگر پاسخ خیلی کوتاه و بدون سؤال است، یک قدم کوتاه اضافه کن
    if "؟" in text or len(text) > 180:
        return text
    return text.rstrip() + "\n" + "قدم بعد: بگو چی کار کنیم."


def enforce_response_style(reply: str, *, voice: str, audience: str) -> str:
    """کوتاه و هدف‌محور نگه دار — بدون پد کردن مصنوعی."""
    if not style_enforce_enabled():
        return (reply or "").strip()
    raw = re.sub(r"\r\n?", "\n", str(reply or "")).strip()
    if not raw:
        return "سلام! خرید فایل می‌خوای یا می‌خوای بازاریاب بشی؟"
    text = re.sub(r"\n{3,}", "\n\n", raw)
    text = _compact_option_blocks(text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # فقط یک سؤال روشن نگه‌دار.
    q_seen = False
    one_q: list[str] = []
    for ln in lines:
        if "؟" in ln:
            if q_seen:
                ln = ln.replace("؟", ".")
            q_seen = True
        one_q.append(ln)
    lines = one_q
    lines = [ln for ln in lines if not ln.lower().startswith("cta:")]
    lines = [re.sub(r"(?i)^\s*مرحله بعد\s*:", "قدم بعد:", ln) for ln in lines]
    shaped = "\n".join(lines)
    v = (voice or "").strip().lower()
    max_lines = 3 if v in ("special",) else 5
    shaped = _truncate_lines(shaped, max_lines=max_lines)
    shaped = _ensure_next_step(shaped)
    shaped = _truncate_lines(shaped, max_lines=max_lines)
    return shaped.strip()


def sanitize_unconfirmed_action_claims(
    reply: str,
    *,
    agent_actions: list[dict[str, Any]] | None = None,
    escalated: bool = False,
) -> str:
    """مدل نباید بگوید ثبت شد مگر همین نوبت confirm Backend بوده (مسیر جدا)."""
    if escalated:
        return (reply or "").strip()
    text = (reply or "").strip()
    if not text or not _UNCONFIRMED_CLAIM_RE.search(text):
        return text
    if has_pending_confirm_card(agent_actions):
        return "اطلاعات آماده است. برای ثبت، تأیید کنید."
    parts = re.split(r"(?<=[.؟!])\s+", text)
    kept = [p for p in parts if p and not _UNCONFIRMED_CLAIM_RE.search(p)]
    if kept:
        return " ".join(kept).strip()
    return "هنوز ثبت نشده. اگر بخواهید کارت تأیید می‌آورم."


def build_cards_html(
    *,
    user_key: str,
    audience: str,
    reply: str,
    land_codes: list[str] | None = None,
    agent_actions: list[dict[str, Any]] | None = None,
) -> str:
    """HTML کارت‌ها (فایل + اقدام + تماس پشتیبانی) — همیشه سمت Backend."""
    from .agent_tools import append_support_call_if_needed, render_agent_actions_html

    codes = [str(c).strip() for c in (land_codes or []) if str(c).strip()]
    actions = [a for a in (agent_actions or []) if isinstance(a, dict)]
    parts: list[str] = []
    if codes:
        try:
            from .land_cards import render_land_cards_html

            land_html = render_land_cards_html(user_key, codes, audience=audience) or ""
            if land_html:
                parts.append(land_html)
        except Exception:
            pass
    if actions:
        try:
            actions_html = render_agent_actions_html(
                actions, phone=user_key, audience=audience
            )
            if actions_html:
                parts.append(actions_html)
        except Exception:
            pass
    try:
        return append_support_call_if_needed(
            "".join(parts),
            reply,
            land_codes=codes,
            agent_actions=actions,
            audience=audience,
        )
    except Exception:
        return "".join(parts)
