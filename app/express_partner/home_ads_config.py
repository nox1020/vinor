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
_MAX_DIVAR_PROFILES_PER_USER = 10


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
    """سازگاری قدیمی — پروفایل‌ها دیگر روی همکار پلاس ذخیره می‌شوند."""
    return False, "پروفایل دیوار را از آگهی‌های من اضافه کنید.", get_home_ads_settings()


def remove_divar_profile_url(url: str) -> tuple[bool, str, dict[str, Any]]:
    del url
    return False, "پروفایل دیوار را از آگهی‌های من حذف کنید.", get_home_ads_settings()


def _find_plus_partner(phone: str):
    from .partner_roles import partner_is_special
    from .partner_session_sync import find_partner_record
    from ..utils.storage import load_express_partners

    partners = load_express_partners() or []
    rec = find_partner_record(partners, phone)
    if rec is None or not partner_is_special(rec):
        return None, partners
    return rec, partners


def partner_divar_profile_urls(phone: str) -> list[str]:
    rec, _ = _find_plus_partner(phone)
    if rec is None:
        return []
    return _normalize_url_list(rec.get("divar_profile_urls"))


def add_partner_divar_profile_url(phone: str, url: str) -> tuple[bool, str, list[str]]:
    """افزودن پروفایل دیوار برای یک همکار پلاس."""
    from ..utils.storage import save_express_partners

    normalized = normalize_divar_profile_url(url)
    if not normalized:
        return False, "آدرس پروفایل نامعتبر است.", partner_divar_profile_urls(phone)
    rec, partners = _find_plus_partner(phone)
    if rec is None:
        return False, "فقط همکار پلاس می‌تواند پروفایل اضافه کند.", []
    urls = _normalize_url_list(rec.get("divar_profile_urls"))
    if normalized.lower() in {u.lower() for u in urls}:
        return False, "این پروفایل از قبل اضافه شده است.", urls
    if len(urls) >= _MAX_DIVAR_PROFILES_PER_USER:
        return False, f"حداکثر {_MAX_DIVAR_PROFILES_PER_USER} پروفایل مجاز است.", urls
    urls.append(normalized)
    rec["divar_profile_urls"] = urls
    save_express_partners(partners)
    try:
        from .divar_pro_ads import clear_divar_pro_ads_cache

        clear_divar_pro_ads_cache()
    except Exception:
        pass
    return True, "پروفایل دیوار اضافه شد.", urls


def remove_partner_divar_profile_url(phone: str, url: str) -> tuple[bool, str, list[str]]:
    """حذف پروفایل دیوار یک همکار پلاس."""
    from ..utils.storage import save_express_partners

    target = normalize_divar_profile_url(url) or str(url or "").strip()
    rec, partners = _find_plus_partner(phone)
    if rec is None:
        return False, "فقط همکار پلاس می‌تواند پروفایل حذف کند.", []
    urls = _normalize_url_list(rec.get("divar_profile_urls"))
    filtered = [u for u in urls if u.lower() != target.lower()]
    if len(filtered) == len(urls):
        return False, "پروفایل پیدا نشد.", urls
    rec["divar_profile_urls"] = filtered
    save_express_partners(partners)
    try:
        from .divar_pro_ads import clear_divar_pro_ads_cache

        clear_divar_pro_ads_cache()
    except Exception:
        pass
    return True, "پروفایل حذف شد.", filtered


def _plus_partner_display_name(rec: dict[str, Any]) -> str:
    return str(
        rec.get("name")
        or rec.get("full_name")
        or rec.get("display_name")
        or rec.get("phone")
        or ""
    ).strip()


def all_plus_divar_profile_entries(*, max_count: int | None = None) -> list[dict[str, str]]:
    """پروفایل‌های دیوار همهٔ همکاران پلاس با نام/شماره."""
    from .partner_roles import partner_is_special
    from .partner_session_sync import canonical_partner_phone
    from ..utils.storage import load_express_partners

    cap = _MAX_DIVAR_PROFILES if max_count is None else max(0, int(max_count))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        partners = load_express_partners() or []
    except Exception:
        partners = []
    for p in partners:
        if not isinstance(p, dict) or not partner_is_special(p):
            continue
        phone = ""
        try:
            phone = canonical_partner_phone(str(p.get("phone") or ""))
        except Exception:
            phone = str(p.get("phone") or "").strip()
        name = _plus_partner_display_name(p) or phone
        for url in _normalize_url_list(p.get("divar_profile_urls")):
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"url": url, "phone": phone, "name": name})
            if cap and len(out) >= cap:
                return out
    return out


def all_plus_divar_profile_urls(*, max_count: int | None = None) -> list[str]:
    """ادغام پروفایل‌های همهٔ همکاران پلاس برای نوار خانه."""
    return [e["url"] for e in all_plus_divar_profile_entries(max_count=max_count) if e.get("url")]


def home_ads_divar_profile_urls() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        u = normalize_divar_profile_url(url)
        if not u:
            return
        key = u.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(u)

    env_url = normalize_divar_profile_url(os.environ.get("VINOR_DIVAR_PRO_PROFILE_URL") or "")
    if env_url:
        _add(env_url)
    for url in all_plus_divar_profile_urls(max_count=_MAX_DIVAR_PROFILES):
        _add(url)
        if len(out) >= _MAX_DIVAR_PROFILES:
            return out
    if out:
        return out
    cfg = get_home_ads_settings()
    for url in _normalize_url_list(cfg.get("divar_profile_urls")):
        _add(url)
        if len(out) >= _MAX_DIVAR_PROFILES:
            break
    if not out:
        single = normalize_divar_profile_url(str(cfg.get("divar_profile_url") or ""))
        if single:
            _add(single)
    return out


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
