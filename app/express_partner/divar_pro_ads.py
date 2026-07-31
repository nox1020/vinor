# -*- coding: utf-8 -*-
"""آگهی‌های پروفایل Divar Pro — واکشی سمت سرور با کش فایل."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from app.utils.storage import data_dir

_log = logging.getLogger(__name__)

DEFAULT_PROFILE_URL = "https://divar.ir/pro/pnMLadIG"
DEFAULT_CACHE_TTL_SEC = 1800  # 30 دقیقه
DEFAULT_HTTP_TIMEOUT_SEC = 12
_MAX_PAGES = 25

_CACHE_LOCK = threading.Lock()
_MEM_CACHE: dict[str, Any] = {
    "key": None,
    "fetched_at": 0.0,
    "ads": [],
    "title": "",
    "profile_url": "",
    "error": "",
}


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def divar_pro_ads_enabled() -> bool:
    """فلگ قابلیت دیوار — پیش‌فرض روشن؛ پنل ادمین (home_ads) هم اعمال می‌شود."""
    try:
        from .home_ads_config import home_ads_show_divar

        return home_ads_show_divar()
    except Exception:
        return _env_bool("VINOR_DIVAR_PRO_ADS_ENABLED", "1")


def divar_pro_profile_url() -> str:
    try:
        from .home_ads_config import home_ads_divar_profile_urls

        urls = home_ads_divar_profile_urls()
        if urls:
            return str(urls[0] or "").strip()
    except Exception:
        pass
    try:
        from .home_ads_config import get_home_ads_settings

        cfg_url = str((get_home_ads_settings() or {}).get("divar_profile_url") or "").strip()
        if cfg_url:
            return cfg_url
    except Exception:
        pass
    raw = (os.environ.get("VINOR_DIVAR_PRO_PROFILE_URL") or DEFAULT_PROFILE_URL).strip()
    return raw or DEFAULT_PROFILE_URL


def divar_pro_profile_urls() -> list[str]:
    try:
        from .home_ads_config import home_ads_divar_profile_urls

        urls = home_ads_divar_profile_urls()
        if urls:
            return list(urls)
    except Exception:
        pass
    one = divar_pro_profile_url()
    return [one] if one else [DEFAULT_PROFILE_URL]


def divar_pro_cache_ttl_sec() -> int:
    try:
        from .home_ads_config import get_home_ads_settings

        ttl = int((get_home_ads_settings() or {}).get("cache_ttl_sec") or 0)
        if ttl >= 60:
            return ttl
    except Exception:
        pass
    try:
        return max(60, int(os.environ.get("VINOR_DIVAR_PRO_ADS_CACHE_TTL") or DEFAULT_CACHE_TTL_SEC))
    except Exception:
        return DEFAULT_CACHE_TTL_SEC


def extract_brand_token(profile_url: str | None = None) -> str:
    """استخراج توکن برند از URL پروفایل Pro."""
    url = (profile_url or divar_pro_profile_url()).strip()
    if not url:
        return ""
    try:
        path = urlparse(url).path or ""
    except Exception:
        path = url
    m = re.search(r"/pro/([^/?#]+)", path, re.I)
    if m:
        return (m.group(1) or "").strip()
    # اگر فقط توکن داده شده باشد
    token = url.strip().strip("/")
    if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", token):
        return token
    return ""


def _cache_path() -> str:
    return os.path.join(data_dir(), "divar_pro_ads_cache.json")


def _read_disk_cache(brand_token: str) -> dict[str, Any] | None:
    path = _cache_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    stored_key = str(raw.get("brand_token") or raw.get("cache_key") or "")
    if stored_key != brand_token:
        return None
    return raw


def _write_disk_cache(payload: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        _log.exception("divar_pro_ads: failed to write cache")


def _warmup_cookies(opener: urllib.request.OpenerDirector, profile_url: str) -> None:
    try:
        req = urllib.request.Request(
            profile_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fa-IR,fa;q=0.9",
            },
        )
        with opener.open(req, timeout=DEFAULT_HTTP_TIMEOUT_SEC) as resp:
            resp.read(2048)
    except Exception:
        _log.debug("divar_pro_ads: cookie warmup failed", exc_info=True)


def _post_json_opener(
    opener: urllib.request.OpenerDirector,
    url: str,
    data: dict | None,
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SEC,
) -> dict[str, Any]:
    body = json.dumps(data if data is not None else {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Referer": divar_pro_profile_url(),
            "Origin": "https://divar.ir",
        },
    )
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _normalize_ad(row: dict[str, Any]) -> dict[str, Any] | None:
    data = row.get("data") if isinstance(row.get("data"), dict) else row
    if not isinstance(data, dict):
        return None
    token = str(data.get("token") or "").strip()
    if not token:
        action = data.get("action") if isinstance(data.get("action"), dict) else {}
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        token = str(payload.get("token") or "").strip()
    if not token:
        return None
    title = str(data.get("title") or "").strip()
    price = str(data.get("middle_description_text") or "").strip()
    location = str(data.get("bottom_description_text") or "").strip()
    image_url = str(data.get("image_url") or "").strip()
    badge = str(data.get("red_text") or "").strip()
    try:
        image_count = int(data.get("image_count") or 0)
    except Exception:
        image_count = 0
    return {
        "token": token,
        "title": title or "آگهی دیوار",
        "price": price,
        "location": location,
        "image_url": image_url,
        "badge": badge,
        "image_count": image_count,
        "url": f"https://divar.ir/v/{token}",
    }


def _extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, str, str]:
    """برمی‌گرداند: ads, has_next, last_item_identifier, page_title."""
    title = str(payload.get("title") or "").strip()
    widgets = payload.get("post_row_widget_list")
    if not isinstance(widgets, list):
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        widgets = page.get("widget_list") if isinstance(page.get("widget_list"), list) else []
        if not title:
            title = str(page.get("title") or "").strip()
    ads: list[dict[str, Any]] = []
    for w in widgets:
        if not isinstance(w, dict):
            continue
        if str(w.get("widget_type") or "") not in ("POST_ROW", ""):
            # فقط ردیف آگهی
            if "POST_ROW" not in str(w.get("widget_type") or "") and not (
                isinstance(w.get("data"), dict) and (w["data"].get("token") or "")
            ):
                continue
        ad = _normalize_ad(w)
        if ad:
            ads.append(ad)
    scroll = payload.get("infinite_scroll_response")
    if not isinstance(scroll, dict):
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        scroll = page.get("infinite_scroll_response") if isinstance(page.get("infinite_scroll_response"), dict) else {}
    has_next = bool(scroll.get("has_next"))
    last_id = str(scroll.get("last_item_identifier") or "").strip()
    return ads, has_next, last_id, title


def fetch_divar_pro_ads(brand_token: str | None = None, profile_url: str | None = None) -> dict[str, Any]:
    """
    واکشی همهٔ آگهی‌های پروفایل Pro از API دیوار.
    خروجی: {ok, ads, title, profile_url, brand_token, error, fetched_at}
    """
    profile = (profile_url or divar_pro_profile_url()).strip() or DEFAULT_PROFILE_URL
    token = (brand_token or extract_brand_token(profile)).strip()
    out: dict[str, Any] = {
        "ok": False,
        "ads": [],
        "title": "",
        "profile_url": profile,
        "brand_token": token,
        "error": "",
        "fetched_at": time.time(),
    }
    if not token:
        out["error"] = "missing_brand_token"
        return out

    jar = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(jar)
    _warmup_cookies(opener, profile)

    api = f"https://api.divar.ir/v8/premium-user/web/business/brand-landing/{token}"
    all_ads: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_title = ""
    last_id = ""
    try:
        for page_idx in range(_MAX_PAGES):
            if page_idx == 0:
                payload: dict[str, Any] = {}
            else:
                payload = {
                    "request_data": {},
                    "specification": {"last_item_identifier": last_id},
                }
            data = _post_json_opener(opener, api, payload)
            ads, has_next, next_id, title = _extract_page(data)
            if title and not page_title:
                page_title = title
            new_count = 0
            for ad in ads:
                tok = ad["token"]
                if tok in seen:
                    continue
                seen.add(tok)
                all_ads.append(ad)
                new_count += 1
            if not has_next or not next_id or new_count == 0:
                break
            last_id = next_id
    except urllib.error.HTTPError as e:
        out["error"] = f"http_{e.code}"
        _log.warning("divar_pro_ads: HTTP %s for %s", e.code, token)
        return out
    except Exception as e:
        out["error"] = type(e).__name__
        _log.warning("divar_pro_ads: fetch failed: %s", e)
        return out

    out["ok"] = True
    out["ads"] = all_ads
    out["title"] = page_title or "آگهی‌های دیوار"
    return out


def get_divar_pro_ads(*, force_refresh: bool = False, ignore_disabled: bool = False) -> dict[str, Any]:
    """
    آگهی‌ها از همهٔ پروفایل‌های تنظیم‌شده — با کش حافظه + فایل.
    اگر واکشی تازه شکست بخورد و کش قدیمی باشد، همان را برمی‌گرداند.
    """
    profiles = divar_pro_profile_urls()
    primary = profiles[0] if profiles else divar_pro_profile_url()
    if not ignore_disabled and not divar_pro_ads_enabled():
        return {
            "ok": False,
            "ads": [],
            "title": "",
            "profile_url": primary,
            "profile_urls": profiles,
            "brand_token": extract_brand_token(primary),
            "error": "disabled",
            "fetched_at": 0.0,
            "from_cache": False,
        }

    ttl = divar_pro_cache_ttl_sec()
    now = time.time()
    tokens = [extract_brand_token(u) for u in profiles]
    cache_key = "|".join(t or u for t, u in zip(tokens, profiles))
    disk: dict[str, Any] | None = None

    with _CACHE_LOCK:
        mem_ok = (
            _MEM_CACHE.get("key") == cache_key
            and isinstance(_MEM_CACHE.get("ads"), list)
            and (now - float(_MEM_CACHE.get("fetched_at") or 0)) < ttl
            and not force_refresh
        )
        if mem_ok:
            return {
                "ok": True,
                "ads": list(_MEM_CACHE.get("ads") or []),
                "title": str(_MEM_CACHE.get("title") or ""),
                "profile_url": str(_MEM_CACHE.get("profile_url") or primary),
                "profile_urls": profiles,
                "brand_token": extract_brand_token(primary),
                "error": "",
                "fetched_at": float(_MEM_CACHE.get("fetched_at") or 0),
                "from_cache": True,
            }

        disk = _read_disk_cache(cache_key)
        if (
            disk
            and not force_refresh
            and (now - float(disk.get("fetched_at") or 0)) < ttl
            and isinstance(disk.get("ads"), list)
        ):
            _MEM_CACHE.update(
                {
                    "key": cache_key,
                    "fetched_at": float(disk.get("fetched_at") or now),
                    "ads": list(disk.get("ads") or []),
                    "title": str(disk.get("title") or ""),
                    "profile_url": str(disk.get("profile_url") or primary),
                    "error": "",
                }
            )
            return {
                "ok": True,
                "ads": list(disk.get("ads") or []),
                "title": str(disk.get("title") or ""),
                "profile_url": str(disk.get("profile_url") or primary),
                "profile_urls": profiles,
                "brand_token": extract_brand_token(primary),
                "error": "",
                "fetched_at": float(disk.get("fetched_at") or 0),
                "from_cache": True,
            }

    all_ads: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_title = ""
    errors: list[str] = []
    any_ok = False
    for profile in profiles:
        token = extract_brand_token(profile)
        fresh = fetch_divar_pro_ads(brand_token=token, profile_url=profile)
        if fresh.get("ok"):
            any_ok = True
            if not page_title:
                page_title = str(fresh.get("title") or "").strip()
            for ad in fresh.get("ads") or []:
                if not isinstance(ad, dict):
                    continue
                tok = str(ad.get("token") or "").strip()
                if not tok or tok in seen:
                    continue
                seen.add(tok)
                ad2 = dict(ad)
                ad2.setdefault("source", "divar")
                ad2.setdefault("external", True)
                ad2.setdefault("badge", "دیوار")
                ad2["profile_url"] = profile
                all_ads.append(ad2)
        else:
            err = str(fresh.get("error") or "fetch_failed")
            errors.append(f"{token or profile}:{err}")

    if any_ok:
        payload = {
            "brand_token": cache_key,
            "profile_url": primary,
            "profile_urls": profiles,
            "title": page_title or "آگهی‌های دیوار",
            "ads": all_ads,
            "fetched_at": now,
        }
        _write_disk_cache(payload)
        with _CACHE_LOCK:
            _MEM_CACHE.update(
                {
                    "key": cache_key,
                    "fetched_at": now,
                    "ads": list(all_ads),
                    "title": payload["title"],
                    "profile_url": primary,
                    "error": "",
                }
            )
        return {
            "ok": True,
            "ads": all_ads,
            "title": payload["title"],
            "profile_url": primary,
            "profile_urls": profiles,
            "brand_token": extract_brand_token(primary),
            "error": "; ".join(errors) if errors else "",
            "fetched_at": now,
            "from_cache": False,
        }

    stale = disk if disk else _read_disk_cache(cache_key)
    if stale and isinstance(stale.get("ads"), list) and stale["ads"]:
        with _CACHE_LOCK:
            _MEM_CACHE.update(
                {
                    "key": cache_key,
                    "fetched_at": float(stale.get("fetched_at") or 0),
                    "ads": list(stale.get("ads") or []),
                    "title": str(stale.get("title") or ""),
                    "profile_url": str(stale.get("profile_url") or primary),
                    "error": "; ".join(errors) or "stale",
                }
            )
        return {
            "ok": True,
            "ads": list(stale.get("ads") or []),
            "title": str(stale.get("title") or ""),
            "profile_url": str(stale.get("profile_url") or primary),
            "profile_urls": profiles,
            "brand_token": extract_brand_token(primary),
            "error": "; ".join(errors),
            "fetched_at": float(stale.get("fetched_at") or 0),
            "from_cache": True,
            "stale": True,
        }

    return {
        "ok": False,
        "ads": [],
        "title": "",
        "profile_url": primary,
        "profile_urls": profiles,
        "brand_token": extract_brand_token(primary),
        "error": "; ".join(errors) or "fetch_failed",
        "fetched_at": now,
        "from_cache": False,
    }


def clear_divar_pro_ads_cache() -> None:
    """پاک کردن کش حافظه + فایل آگهی‌های دیوار."""
    with _CACHE_LOCK:
        _MEM_CACHE.update(
            {
                "key": None,
                "fetched_at": 0.0,
                "ads": [],
                "title": "",
                "profile_url": "",
                "error": "",
            }
        )
    path = _cache_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        _log.debug("divar_pro_ads: cache file remove failed", exc_info=True)


def home_divar_ads_context() -> dict[str, Any]:
    """کانتکست قالب خانه — اگر خاموش/خالی باشد ads=[]."""
    empty = {
        "divar_pro_ads_enabled": False,
        "divar_pro_ads": [],
        "divar_pro_ads_title": "",
        "divar_pro_profile_url": divar_pro_profile_url(),
    }
    try:
        from .home_ads_config import get_home_ads_settings, home_ads_system_enabled

        if not home_ads_system_enabled():
            return empty
        title = str((get_home_ads_settings() or {}).get("title") or "آگهی‌ها").strip() or "آگهی‌ها"
    except Exception:
        title = "آگهی‌ها"
    if not divar_pro_ads_enabled():
        # دیوار خاموش است؛ وینور ممکن است جداگانه در routes ادغام شود
        return {
            "divar_pro_ads_enabled": False,
            "divar_pro_ads": [],
            "divar_pro_ads_title": title,
            "divar_pro_profile_url": divar_pro_profile_url(),
        }
    try:
        result = get_divar_pro_ads()
    except Exception:
        _log.exception("divar_pro_ads: home context failed")
        return empty
    ads = result.get("ads") if isinstance(result.get("ads"), list) else []
    if not ads:
        return {
            "divar_pro_ads_enabled": False,
            "divar_pro_ads": [],
            "divar_pro_ads_title": title,
            "divar_pro_profile_url": str(result.get("profile_url") or divar_pro_profile_url()),
        }
    return {
        "divar_pro_ads_enabled": True,
        "divar_pro_ads": ads,
        "divar_pro_ads_title": title or str(result.get("title") or "آگهی‌های دیوار"),
        "divar_pro_profile_url": str(result.get("profile_url") or divar_pro_profile_url()),
    }
