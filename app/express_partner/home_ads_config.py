# -*- coding: utf-8 -*-
"""تنظیمات نوار آگهی خانه (settings.json → home_ads)."""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

DEFAULT_PROFILE_URL = "https://divar.ir/pro/pnMLadIG"
DEFAULT_TITLE = "آگهی‌ها"
DEFAULT_CACHE_TTL_SEC = 1800
DEFAULT_VINOR_LIMIT = 40
_MAX_DIVAR_PROFILES = 20


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def home_ads_feature_enabled() -> bool:
    """فلگ env — پیش‌فرض روشن. قطع اضطراری بدون پنل."""
    return _env_bool("VINOR_HOME_ADS_ENABLED", "1") and _env_bool(
        "VINOR_DIVAR_PRO_ADS_ENABLED", "1"
    )


def normalize_divar_profile_url(raw: str | None) -> str:
    """نرمال‌سازی URL یا توکن پروفایل Pro دیوار."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", text):
        return f"https://divar.ir/pro/{text}"
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text.lstrip("/")
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    host = (parsed.netloc or "").lower()
    if "divar.ir" not in host and "divarcdn.com" not in host:
        # هنوز قبول کن اگر مسیر /pro/ دارد
        if "/pro/" not in (parsed.path or ""):
            return text.rstrip("/")
    path = parsed.path or ""
    m = re.search(r"/pro/([^/?#]+)", path, re.I)
    if m:
        token = (m.group(1) or "").strip()
        if token:
            return f"https://divar.ir/pro/{token}"
    return text.rstrip("/")


def _normalize_url_list(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(values, str):
        values = re.split(r"[\n,]+", values)
    if not isinstance(values, (list, tuple)):
        return out
    for item in values:
        url = normalize_divar_profile_url(str(item or ""))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= _MAX_DIVAR_PROFILES:
            break
    return out


def default_home_ads_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "show_vinor": True,
        "show_divar": True,
        "divar_profile_url": DEFAULT_PROFILE_URL,
        "divar_profile_urls": [DEFAULT_PROFILE_URL],
        "cache_ttl_sec": DEFAULT_CACHE_TTL_SEC,
        "vinor_limit": DEFAULT_VINOR_LIMIT,
        "title": DEFAULT_TITLE,
    }


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _coerce(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_home_ads_settings()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = _as_bool(raw.get("enabled"), out["enabled"])
    if "show_vinor" in raw:
        out["show_vinor"] = _as_bool(raw.get("show_vinor"), out["show_vinor"])
    if "show_divar" in raw:
        out["show_divar"] = _as_bool(raw.get("show_divar"), out["show_divar"])

    urls = _normalize_url_list(raw.get("divar_profile_urls"))
    single = normalize_divar_profile_url(str(raw.get("divar_profile_url") or ""))
    if single and single.lower() not in {u.lower() for u in urls}:
        urls.insert(0, single)
    if not urls and single:
        urls = [single]
    if not urls:
        urls = [DEFAULT_PROFILE_URL]
    out["divar_profile_urls"] = urls
    out["divar_profile_url"] = urls[0]

    title = str(raw.get("title") or "").strip()
    if title:
        out["title"] = title
    try:
        if raw.get("cache_ttl_sec") is not None and str(raw.get("cache_ttl_sec")).strip() != "":
            out["cache_ttl_sec"] = max(60, int(raw["cache_ttl_sec"]))
    except (TypeError, ValueError):
        pass
    try:
        if raw.get("vinor_limit") is not None and str(raw.get("vinor_limit")).strip() != "":
            out["vinor_limit"] = max(0, min(100, int(raw["vinor_limit"])))
    except (TypeError, ValueError):
        pass
    return out


def get_home_ads_settings() -> dict[str, Any]:
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("home_ads")
    except Exception:
        stored = None
    cfg = _coerce(stored if isinstance(stored, dict) else None)
    env_url = normalize_divar_profile_url(os.environ.get("VINOR_DIVAR_PRO_PROFILE_URL") or "")
    if env_url:
        urls = list(cfg.get("divar_profile_urls") or [])
        if env_url.lower() not in {u.lower() for u in urls}:
            urls.insert(0, env_url)
        cfg["divar_profile_urls"] = urls[:_MAX_DIVAR_PROFILES]
        cfg["divar_profile_url"] = cfg["divar_profile_urls"][0]
    if not home_ads_feature_enabled():
        cfg["enabled"] = False
    return cfg


def save_home_ads_settings(patch: dict[str, Any]) -> dict[str, Any]:
    import json

    from app.utils.storage import _SETTINGS_CACHE, ensure_file, load_settings

    current = dict(load_settings() or {})
    merged = _coerce(current.get("home_ads") if isinstance(current.get("home_ads"), dict) else None)
    for key in ("enabled", "show_vinor", "show_divar"):
        if key in patch:
            merged[key] = bool(patch[key])

    if patch.get("divar_profile_urls") is not None:
        urls = _normalize_url_list(patch.get("divar_profile_urls"))
        if urls:
            merged["divar_profile_urls"] = urls
            merged["divar_profile_url"] = urls[0]
    elif patch.get("divar_profile_url") is not None:
        url = normalize_divar_profile_url(str(patch.get("divar_profile_url") or ""))
        if url:
            urls = list(merged.get("divar_profile_urls") or [])
            urls = [u for u in urls if u.lower() != url.lower()]
            urls.insert(0, url)
            merged["divar_profile_urls"] = urls[:_MAX_DIVAR_PROFILES]
            merged["divar_profile_url"] = merged["divar_profile_urls"][0]

    if patch.get("title") is not None:
        title = str(patch.get("title") or "").strip()
        if title:
            merged["title"] = title
    if patch.get("cache_ttl_sec") is not None:
        try:
            merged["cache_ttl_sec"] = max(60, int(patch["cache_ttl_sec"]))
        except (TypeError, ValueError):
            pass
    if patch.get("vinor_limit") is not None:
        try:
            merged["vinor_limit"] = max(0, min(100, int(patch["vinor_limit"])))
        except (TypeError, ValueError):
            pass
    current["home_ads"] = merged
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return merged


def add_divar_profile_url(url: str) -> tuple[bool, str, dict[str, Any]]:
    """افزودن یک پروفایل دیوار. برمی‌گرداند: ok, message, settings."""
    normalized = normalize_divar_profile_url(url)
    if not normalized:
        return False, "آدرس پروفایل نامعتبر است.", get_home_ads_settings()
    cfg = get_home_ads_settings()
    urls = list(cfg.get("divar_profile_urls") or [])
    if normalized.lower() in {u.lower() for u in urls}:
        return False, "این پروفایل از قبل اضافه شده است.", cfg
    if len(urls) >= _MAX_DIVAR_PROFILES:
        return False, f"حداکثر {_MAX_DIVAR_PROFILES} پروفایل مجاز است.", cfg
    urls.append(normalized)
    saved = save_home_ads_settings({"divar_profile_urls": urls})
    return True, "پروفایل دیوار اضافه شد.", saved


def remove_divar_profile_url(url: str) -> tuple[bool, str, dict[str, Any]]:
    """حذف یک پروفایل دیوار."""
    target = normalize_divar_profile_url(url) or str(url or "").strip()
    cfg = get_home_ads_settings()
    urls = list(cfg.get("divar_profile_urls") or [])
    if not urls:
        return False, "لیست پروفایل خالی است.", cfg
    if len(urls) <= 1:
        return False, "حداقل یک پروفایل باید باقی بماند.", cfg
    filtered = [u for u in urls if u.lower() != target.lower()]
    if len(filtered) == len(urls):
        return False, "پروفایل پیدا نشد.", cfg
    if not filtered:
        filtered = [DEFAULT_PROFILE_URL]
    saved = save_home_ads_settings({"divar_profile_urls": filtered})
    return True, "پروفایل حذف شد.", saved


def home_ads_divar_profile_urls() -> list[str]:
    cfg = get_home_ads_settings()
    urls = _normalize_url_list(cfg.get("divar_profile_urls"))
    if urls:
        return urls
    single = normalize_divar_profile_url(str(cfg.get("divar_profile_url") or ""))
    return [single] if single else [DEFAULT_PROFILE_URL]


def home_ads_system_enabled() -> bool:
    """Master نوار آگهی سمت کاربر — env AND settings.enabled."""
    if not home_ads_feature_enabled():
        return False
    try:
        return bool(get_home_ads_settings().get("enabled", True))
    except Exception:
        return False


def home_ads_show_vinor() -> bool:
    if not home_ads_system_enabled():
        return False
    return bool(get_home_ads_settings().get("show_vinor", True))


def home_ads_show_divar() -> bool:
    if not home_ads_system_enabled():
        return False
    return bool(get_home_ads_settings().get("show_divar", True))
