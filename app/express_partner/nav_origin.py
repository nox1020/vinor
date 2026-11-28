# -*- coding: utf-8 -*-
"""مبدأ بازگشت زیرصفحات «وینور من».

وقتی لینک از پروفایل (یا تنظیمات) باز می‌شود، ?from=profile (یا settings)
روی آدرس می‌ماند تا دکمهٔ برگشت هدر همان‌جا برگردد؛ اگر صفحه از خانه یا
جای دیگری باز شده باشد، رفتار قبلی (معمولاً خانه) حفظ می‌شود.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import request, url_for

FROM_ARG = "from"
FROM_PROFILE = "profile"
FROM_SETTINGS = "settings"

# کلیدهای مجاز — فقط endpoint داخلی، نه آدرس آزاد کاربر.
FROM_ENDPOINTS: Dict[str, str] = {
    FROM_PROFILE: "express_partner.profile",
    FROM_SETTINGS: "express_partner.settings",
}


def origin_token() -> str:
    try:
        raw = str(request.args.get(FROM_ARG) or "").strip().lower()
    except Exception:
        return ""
    return raw if raw in FROM_ENDPOINTS else ""


def came_from_profile() -> bool:
    return origin_token() == FROM_PROFILE


def with_from(url: str, origin: str = FROM_PROFILE) -> str:
    """from را به query یک مسیر نسبی/داخلی اضافه می‌کند (یا روی next می‌گذارد)."""
    origin = (origin or "").strip().lower()
    if origin not in FROM_ENDPOINTS or not url:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    # صفحهٔ ورود: مبدأ را روی مقصدِ next بگذار تا بعد از ورود هم برگردد.
    nxt = query.get("next")
    if parts.path.rstrip("/").endswith("/login") and nxt:
        query["next"] = with_from(nxt, origin)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    login_next = query.get("login_next")
    if login_next:
        query["login_next"] = with_from(login_next, origin)
    query[FROM_ARG] = origin
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def carry_from_kwargs(kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = dict(kwargs or {})
    token = origin_token()
    if token:
        out.setdefault(FROM_ARG, token)
    return out


def subpage_back_url(default_endpoint: str = "express_partner.home", **kwargs: Any) -> str:
    token = origin_token()
    if token:
        return url_for(FROM_ENDPOINTS[token])
    return url_for(default_endpoint, **kwargs)
