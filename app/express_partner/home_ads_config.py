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
DEFAULT_DIVAR_COMMISSION_PCT = 2.0
_FA_TO_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


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
    return False, "پروفایل دیوار را از ملک من اضافه کنید.", get_home_ads_settings()


def remove_divar_profile_url(url: str) -> tuple[bool, str, dict[str, Any]]:
    del url
    return False, "پروفایل دیوار را از ملک من حذف کنید.", get_home_ads_settings()


def _find_plus_partner(phone: str):
    from .partner_roles import partner_is_special
    from .partner_session_sync import find_partner_record
    from ..utils.storage import load_express_partners

    partners = load_express_partners() or []
    rec = find_partner_record(partners, phone)
    if rec is None or not partner_is_special(rec):
        return None, partners
    return rec, partners


def parse_commission_pct(raw: Any) -> tuple[float | None, str]:
    """پارس درصد پورسانت. خالی → (None, '')."""
    if raw is None:
        return None, ""
    text = str(raw).strip().replace("٪", "").replace("%", "")
    if not text:
        return None, ""
    text = text.translate(_FA_TO_EN_DIGITS).replace("٫", ".").replace(",", ".")
    try:
        pct = float(text)
    except (TypeError, ValueError):
        return None, "درصد پورسانت نامعتبر است."
    if pct < 0 or pct > 100:
        return None, "درصد پورسانت باید بین ۰ تا ۱۰۰ باشد."
    return pct, ""


def format_commission_pct(pct: Any) -> str:
    try:
        n = float(pct or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    rounded = round(n, 2)
    if abs(rounded - int(rounded)) < 1e-9:
        return str(int(rounded))
    return f"{rounded:g}"


def parse_divar_price_toman(text: Any) -> int:
    """متن قیمت دیوار → تومان. «توافقی» و مقادیر نامعتبر صفر می‌شوند."""
    raw = str(text or "").strip().translate(_FA_TO_EN_DIGITS)
    if not raw or "توافق" in raw:
        return 0
    compact = raw.replace("٬", ",").replace("،", ",").replace("٫", ".")
    m = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(میلیارد|billion|میلیون|million|هزار|thousand)",
        compact,
        re.I,
    )
    if m:
        num_s = m.group(1).replace(",", ".")
        try:
            num = float(num_s)
        except ValueError:
            num = 0.0
        unit = (m.group(2) or "").lower()
        if unit in ("میلیارد", "billion"):
            return max(0, int(round(num * 1_000_000_000)))
        if unit in ("میلیون", "million"):
            return max(0, int(round(num * 1_000_000)))
        return max(0, int(round(num * 1_000)))
    digits = re.sub(r"[^\d]", "", compact)
    if not digits:
        return 0
    try:
        return max(0, int(digits))
    except ValueError:
        return 0


def _entries_from_partner_rec(rec: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(rec, dict):
        return []
    urls = _normalize_url_list(rec.get("divar_profile_urls"))
    pct_by_url: dict[str, float] = {}
    extra: list[str] = []
    raw_entries = rec.get("divar_profile_entries")
    if isinstance(raw_entries, list):
        for item in raw_entries:
            if isinstance(item, dict):
                url = normalize_divar_profile_url(str(item.get("url") or ""))
                pct, _err = parse_commission_pct(item.get("commission_pct"))
            else:
                url = normalize_divar_profile_url(str(item or ""))
                pct = None
            if not url:
                continue
            extra.append(url)
            if pct is not None:
                pct_by_url[url.lower()] = pct
    seen = {u.lower() for u in urls}
    for url in extra:
        key = url.lower()
        if key in seen:
            continue
        if len(urls) >= _MAX_DIVAR_PROFILES_PER_USER:
            break
        seen.add(key)
        urls.append(url)
    out: list[dict[str, Any]] = []
    for url in urls:
        key = url.lower()
        if key in pct_by_url:
            pct = float(pct_by_url[key])
        else:
            pct = DEFAULT_DIVAR_COMMISSION_PCT
        out.append(
            {
                "url": url,
                "commission_pct": pct,
                "commission_pct_display": format_commission_pct(pct) or "0",
            }
        )
    return out


def _write_partner_divar_entries(rec: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    rec["divar_profile_urls"] = [str(e.get("url") or "") for e in entries if e.get("url")]
    rec["divar_profile_entries"] = [
        {
            "url": str(e.get("url") or ""),
            "commission_pct": float(e.get("commission_pct") or 0.0),
        }
        for e in entries
        if e.get("url")
    ]


def _clear_divar_ads_cache() -> None:
    try:
        from .divar_pro_ads import clear_divar_pro_ads_cache

        clear_divar_pro_ads_cache()
    except Exception:
        pass


def partner_divar_profile_entries(phone: str) -> list[dict[str, Any]]:
    rec, _ = _find_plus_partner(phone)
    if rec is None:
        return []
    return _entries_from_partner_rec(rec)


def partner_divar_profile_urls(phone: str) -> list[str]:
    return [str(e.get("url") or "") for e in partner_divar_profile_entries(phone) if e.get("url")]


def add_partner_divar_profile_url(
    phone: str,
    url: str,
    commission_pct: Any = None,
) -> tuple[bool, str, list[str]]:
    """افزودن پروفایل دیوار برای یک همکار پلاس."""
    from ..utils.storage import save_express_partners

    normalized = normalize_divar_profile_url(url)
    if not normalized:
        return False, "آدرس پروفایل نامعتبر است.", partner_divar_profile_urls(phone)
    pct, err = parse_commission_pct(commission_pct)
    if err:
        return False, err, partner_divar_profile_urls(phone)
    if pct is None:
        pct = DEFAULT_DIVAR_COMMISSION_PCT
    rec, partners = _find_plus_partner(phone)
    if rec is None:
        return False, "فقط همکار پلاس می‌تواند پروفایل اضافه کند.", []
    entries = _entries_from_partner_rec(rec)
    if normalized.lower() in {str(e.get("url") or "").lower() for e in entries}:
        return False, "این پروفایل از قبل اضافه شده است.", [str(e.get("url") or "") for e in entries]
    if len(entries) >= _MAX_DIVAR_PROFILES_PER_USER:
        return False, f"حداکثر {_MAX_DIVAR_PROFILES_PER_USER} پروفایل مجاز است.", [
            str(e.get("url") or "") for e in entries
        ]
    entries.append(
        {
            "url": normalized,
            "commission_pct": pct,
            "commission_pct_display": format_commission_pct(pct),
        }
    )
    _write_partner_divar_entries(rec, entries)
    save_express_partners(partners)
    _clear_divar_ads_cache()
    return True, "پروفایل دیوار اضافه شد.", [str(e.get("url") or "") for e in entries]


def set_partner_divar_profile_commission(
    phone: str,
    url: str,
    commission_pct: Any,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """به‌روزرسانی درصد پورسانت یک پروفایل دیوار."""
    from ..utils.storage import save_express_partners

    target = normalize_divar_profile_url(url) or str(url or "").strip()
    pct, err = parse_commission_pct(commission_pct)
    if err:
        return False, err, partner_divar_profile_entries(phone)
    if pct is None:
        return False, "درصد پورسانت را وارد کنید.", partner_divar_profile_entries(phone)
    rec, partners = _find_plus_partner(phone)
    if rec is None:
        return False, "فقط همکار پلاس می‌تواند پورسانت را تغییر دهد.", []
    entries = _entries_from_partner_rec(rec)
    found = False
    for item in entries:
        if str(item.get("url") or "").lower() == target.lower():
            item["commission_pct"] = pct
            item["commission_pct_display"] = format_commission_pct(pct)
            found = True
            break
    if not found:
        return False, "پروفایل پیدا نشد.", entries
    _write_partner_divar_entries(rec, entries)
    save_express_partners(partners)
    return True, "درصد پورسانت ذخیره شد.", entries


def remove_partner_divar_profile_url(phone: str, url: str) -> tuple[bool, str, list[str]]:
    """حذف پروفایل دیوار یک همکار پلاس."""
    from ..utils.storage import save_express_partners

    target = normalize_divar_profile_url(url) or str(url or "").strip()
    rec, partners = _find_plus_partner(phone)
    if rec is None:
        return False, "فقط همکار پلاس می‌تواند پروفایل حذف کند.", []
    entries = _entries_from_partner_rec(rec)
    filtered = [e for e in entries if str(e.get("url") or "").lower() != target.lower()]
    if len(filtered) == len(entries):
        return False, "پروفایل پیدا نشد.", [str(e.get("url") or "") for e in entries]
    _write_partner_divar_entries(rec, filtered)
    save_express_partners(partners)
    _clear_divar_ads_cache()
    return True, "پروفایل حذف شد.", [str(e.get("url") or "") for e in filtered]


def divar_commission_pct_by_profile_url() -> dict[str, float]:
    """url.lower() → درصد پورسانت پروفایل‌های همکاران پلاس."""
    out: dict[str, float] = {}
    for e in all_plus_divar_profile_entries():
        url = normalize_divar_profile_url(str(e.get("url") or "")).lower()
        if not url or url in out:
            continue
        try:
            out[url] = float(e.get("commission_pct") or 0)
        except (TypeError, ValueError):
            out[url] = 0.0
    return out


def attach_divar_ad_commission(
    ad: dict[str, Any],
    pct_by_url: dict[str, float] | None = None,
) -> dict[str, Any]:
    """محاسبه مبلغ پورسانت آگهی دیوار از درصد پروفایل و متن قیمت."""
    if not isinstance(ad, dict):
        return ad
    mapping = pct_by_url if pct_by_url is not None else divar_commission_pct_by_profile_url()
    profile = str(ad.get("profile_url") or "").strip()
    key = normalize_divar_profile_url(profile).lower() if profile else ""
    pct = float(mapping.get(key) or 0) if key else 0.0
    if pct <= 0 and not key and len(mapping) == 1:
        pct = float(next(iter(mapping.values())) or 0)
    price = parse_divar_price_toman(ad.get("price"))
    amount = int(round(price * (pct / 100.0))) if price and pct else 0
    ad["commission_pct"] = pct
    ad["commission_amount"] = max(0, amount)
    ad["price_toman"] = price
    return ad


def _plus_partner_display_name(rec: dict[str, Any]) -> str:
    return str(
        rec.get("name")
        or rec.get("full_name")
        or rec.get("display_name")
        or rec.get("phone")
        or ""
    ).strip()


def all_plus_divar_profile_entries(*, max_count: int | None = None) -> list[dict[str, Any]]:
    """پروفایل‌های دیوار همهٔ همکاران پلاس با نام/شماره و درصد پورسانت."""
    from .partner_roles import partner_is_special
    from .partner_session_sync import canonical_partner_phone
    from ..utils.storage import load_express_partners

    cap = _MAX_DIVAR_PROFILES if max_count is None else max(0, int(max_count))
    out: list[dict[str, Any]] = []
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
        for item in _entries_from_partner_rec(p):
            url = str(item.get("url") or "").strip()
            key = url.lower()
            if not url or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "url": url,
                    "phone": phone,
                    "name": name,
                    "commission_pct": float(item.get("commission_pct") or 0),
                }
            )
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
