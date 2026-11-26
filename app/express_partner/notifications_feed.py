# -*- coding: utf-8 -*-
"""مدل نمایشی صفحهٔ «اعلان‌ها» به سبک دیوار (وب).

هم‌تراز با ``NotificationFeed.kt`` اپ: نوع اعلان (بازدید/کیف پول/آگهی/عمومی)، گروه روز
(امروز/دیروز/قدیمی‌تر به وقت تهران)، زمان کوتاه فارسی، لینک امن داخلی و شمارش خوانده‌نشده.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.utils.dates import gregorian_to_jalali, to_fa_digits

TEHRAN = timezone(timedelta(hours=3, minutes=30))  # ایران از ۱۴۰۱ ساعت تابستانی ندارد
PLUS_VISIT_SOURCE = "visit_plus_user"  # مثل VisitAudience.PLUS_VISIT_SOURCE اپ؛ در فهرست نمایش داده نمی‌شود

KINDS = ("visit", "wallet", "listing", "general")
KIND_LABELS = {"visit": "بازدید", "wallet": "کیف پول", "listing": "آگهی", "general": "اعلان"}
DAY_LABELS = {"today": "امروز", "yesterday": "دیروز", "older": "قدیمی‌تر"}
DAY_ORDER = ("today", "yesterday", "older")
MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")

_WALLET_URL = ("/wallet", "/commissions", "/withdraw")
_WALLET_WORDS = ("کیف پول", "پورسانت", "کمیسیون", "برداشت", "واریز")
_LISTING_URL = ("/lands/", "/divar/", "/listings", "/my-property", "/special-listings", "/special_listings")
_LISTING_WORDS = ("آگهی", "فایل")
_VINOR_HOSTS = ("https://vinor.ir", "https://www.vinor.ir")


def kind_of(n: Dict[str, Any]) -> str:
    t = str(n.get("type") or "").strip().lower()
    s = str(n.get("source") or "").strip().lower()
    u = str(n.get("action_url") or "").strip().lower()
    title = str(n.get("title") or "")
    if t == "visit" or s.startswith("visit") or "tab=visits" in u or "بازدید" in title:
        return "visit"
    if t in ("wallet", "commission", "withdraw", "deposit") or any(x in u for x in _WALLET_URL) \
            or any(w in title for w in _WALLET_WORDS):
        return "wallet"
    if n.get("ad_id") or any(x in u for x in _LISTING_URL) or any(w in title for w in _LISTING_WORDS):
        return "listing"
    return "general"


def safe_link(raw: Any) -> Optional[str]:
    """فقط مسیر داخلی وینور؛ لینک بیرونی یا ``//host`` نادیده گرفته می‌شود."""
    url = str(raw or "").strip()
    if not url:
        return None
    low = url.lower()
    for host in _VINOR_HOSTS:
        if low == host or low.startswith(host + "/"):
            url = url[len(host):] or "/"
            break
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


def epoch_of(raw: Any) -> Optional[int]:
    """created_at سرور ثانیهٔ یونیکس است؛ میلی‌ثانیه و ISO هم پذیرفته می‌شود."""
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
        if v > 1e12:
            v /= 1000.0
        return int(v) if v > 0 else None
    except (TypeError, ValueError):
        pass
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def _tehran_date(ts: int):
    return datetime.fromtimestamp(ts, TEHRAN).date()


def day_bucket(ts: Optional[int], now: int) -> str:
    if ts is None:
        return "older"
    diff = (_tehran_date(now) - _tehran_date(min(ts, now))).days
    if diff <= 0:
        return "today"
    if diff == 1:
        return "yesterday"
    return "older"


def short_time(ts: Optional[int], now: int) -> str:
    if ts is None:
        return ""
    delta = now - ts
    if delta < 60:
        return "همین حالا"
    if delta < 3600:
        return f"{to_fa_digits(delta // 60)} دقیقه پیش"
    bucket = day_bucket(ts, now)
    if bucket == "today":
        return f"{to_fa_digits(delta // 3600)} ساعت پیش"
    if bucket == "yesterday":
        return "دیروز"
    days = (_tehran_date(now) - _tehran_date(ts)).days
    if days < 7:
        return f"{to_fa_digits(days)} روز پیش"
    d = _tehran_date(ts)
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    ny = gregorian_to_jalali(*_tehran_date(now).timetuple()[:3])[0]
    label = f"{to_fa_digits(jd)} {MONTHS[jm - 1]}"
    return label if jy == ny else f"{label} {to_fa_digits(jy)}"


def visible(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [n for n in items if isinstance(n, dict) and str(n.get("source") or "").strip() != PLUS_VISIT_SOURCE]


def row_of(n: Dict[str, Any], now: int) -> Dict[str, Any]:
    ts = epoch_of(n.get("created_at"))
    kind = kind_of(n)
    return {
        "id": str(n.get("id") or ""),
        "title": str(n.get("title") or "").strip() or "اعلان جدید",
        "body": " ".join(str(n.get("body") or "").split()),
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "unread": not bool(n.get("is_read")),
        "link": safe_link(n.get("action_url")),
        "time": short_time(ts, now),
        "ts": ts or 0,
        "day": day_bucket(ts, now),
    }


def build_feed(items: Iterable[Dict[str, Any]], now: Optional[int] = None) -> Dict[str, Any]:
    now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    rows = [row_of(n, now) for n in visible(items)]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    sections = []
    for key in DAY_ORDER:
        part = [r for r in rows if r["day"] == key]
        if part:
            sections.append({"key": key, "label": DAY_LABELS[key], "rows": part})
    unread = sum(1 for r in rows if r["unread"])
    return {"sections": sections, "total": len(rows), "unread": unread, "unread_fa": to_fa_digits(unread)}
