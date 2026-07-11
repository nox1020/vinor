# -*- coding: utf-8 -*-
"""SEO helpers: robots directives, sitemap, land metadata, structured data."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SITE_ORIGIN = "https://vinor.ir"

# Paths that must never be indexed (prefix match unless noted).
_NOINDEX_PREFIXES = (
    "/admin",
    "/api",
    "/app",
    "/my-lands",
    "/settings",
    "/careers",
    "/consultant",
    "/connection",
    "/favorites",
    "/login",
    "/verify",
    "/logout",
    "/start",
    "/express/partner/login",
    "/express/partner/login/otp",
    "/express/partner/verify",
    "/express/partner/otp",
    "/express/partner/apply",
    "/express/partner/thanks",
    "/express/partner/download-app",
    "/express/partner/profile",
    "/express/partner/favorites",
    "/express/partner/commissions",
    "/express/partner/routine",
    "/express/partner/ai",
    "/express/partner/ai",
    "/express/partner/training",
    "/express/partner/invite",
    "/express/partner/my-properties",
    "/express/partner/offline",
    "/express/partner/ai",
)

_NOINDEX_EXACT = frozenset({
    "/express/partner",
    "/express/partner/",
})

# Public express-partner pages (indexable).
_INDEX_PREFIXES = (
    "/express/partner/home",
    "/express/partner/lands/",
    "/express/partner/cooperation-terms",
    "/express/partner/legal/",
    "/express/partner/top-sellers",
)

_PUBLIC_STATIC_PATHS = frozenset({
    "/",
    "/partners",
    "/help",
    "/privacy",
    "/public",
})


def _norm_path(path: str) -> str:
    p = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    return p


def is_public_indexable_path(path: str) -> bool:
    p = _norm_path(path)
    if p in _PUBLIC_STATIC_PATHS:
        return True
    for prefix in _INDEX_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return True
    return False


def should_noindex_path(path: str, *, logged_in: bool = False) -> bool:
    """Return True when crawlers must not index this URL."""
    p = _norm_path(path)
    if p in _NOINDEX_EXACT:
        return True
    for prefix in _NOINDEX_PREFIXES:
        if p == prefix or p.startswith(prefix + "/") or p == prefix:
            return True
    if p.startswith("/express/partner/home") and logged_in:
        return True
    if p.startswith("/express/partner/") and not is_public_indexable_path(p):
        return True
    return False


def robots_meta_content(path: str, *, logged_in: bool = False) -> str:
    if should_noindex_path(path, logged_in=logged_in):
        return "noindex, nofollow"
    if is_public_indexable_path(path) or _norm_path(path) in _PUBLIC_STATIC_PATHS:
        return "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
    return "noindex, nofollow"


def apply_x_robots_tag(response, path: str, *, logged_in: bool = False):
    if should_noindex_path(path, logged_in=logged_in):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _clean_text(val: Any, max_len: int = 320) -> str:
    s = re.sub(r"\s+", " ", str(val or "")).strip()
    if len(s) > max_len:
        return s[: max_len - 1].rstrip() + "…"
    return s


def _format_price_short(land: dict) -> str:
    try:
        total = int(land.get("price_total") or land.get("price") or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        return ""
    if total >= 1_000_000_000:
        return f"{total // 1_000_000_000:,} میلیارد تومان".replace(",", "،")
    if total >= 1_000_000:
        return f"{total // 1_000_000:,} میلیون تومان".replace(",", "،")
    return f"{total:,} تومان".replace(",", "،")


def _land_area_label(land: dict) -> str:
    for key in ("size", "area", "land_area", "built_area"):
        try:
            v = land.get(key)
            if v:
                return f"{int(float(v))} متر"
        except (TypeError, ValueError):
            continue
    return ""


def build_land_seo(land: dict, *, canonical_url: str, site_root: str = SITE_ORIGIN) -> Dict[str, Any]:
    """Unique title, description, OG fields and JSON-LD for a listing."""
    code = str(land.get("code") or "").strip()
    title_base = _clean_text(land.get("title") or f"فایل {code}", 120)
    category = _clean_text(land.get("category"), 40)
    city = _clean_text(land.get("city"), 40)
    location = _clean_text(land.get("location"), 80)
    area = _land_area_label(land)
    price_txt = _format_price_short(land)

    parts = [title_base]
    if category:
        parts.append(category)
    if city:
        parts.append(city)
    seo_title = " | ".join(parts[:3]) + " | وینور اکسپرس"

    desc_body = _clean_text(land.get("description") or land.get("desc"), 400)
    if not desc_body:
        bits = []
        if category:
            bits.append(category)
        if city or location:
            bits.append(city or location)
        if area:
            bits.append(area)
        if price_txt:
            bits.append(f"قیمت {price_txt}")
        bits.append(f"کد {code}")
        desc_body = " — ".join(bits) + ". مشاهده جزئیات و تماس در وینور اکسپرس."
    seo_description = _clean_text(desc_body, 160)

    og_image = _land_og_image(land, site_root)

    json_ld = build_land_json_ld(
        land,
        canonical_url=canonical_url,
        site_root=site_root,
        seo_title=seo_title,
        seo_description=seo_description,
        og_image=og_image,
    )

    keywords = ", ".join(
        x for x in (
            "فایل اکسپرس",
            category,
            city,
            "خرید ملک",
            "فروش ملک",
            "وینور",
            code,
        ) if x
    )

    return {
        "title": seo_title,
        "description": seo_description,
        "canonical": canonical_url,
        "keywords": keywords,
        "og_type": "product",
        "og_image": og_image,
        "price": land.get("price_total") or land.get("price"),
        "currency": "IRR",
        "json_ld": json_ld,
        "is_thin_content": _is_thin_land(land),
    }


def _is_thin_land(land: dict) -> bool:
    desc = _clean_text(land.get("description") or land.get("desc"))
    images = land.get("images") or []
    has_images = bool(images)
    word_count = len(desc.split()) if desc else 0
    return (not has_images and word_count < 20) or word_count < 8


def _land_og_image(land: dict, site_root: str) -> str:
    root = site_root.rstrip("/")
    imgs = land.get("images") or []
    if imgs:
        from app.utils.images import normalize_upload_url
        return _abs_url(normalize_upload_url(str(imgs[0])), root)
    return f"{root}/static/icons/icon-512.png"


def _abs_url(src: str, site_root: str) -> str:
    s = (src or "").strip()
    if not s:
        return f"{site_root.rstrip('/')}/static/icons/icon-512.png"
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("/"):
        return f"{site_root.rstrip('/')}{s}"
    return f"{site_root.rstrip('/')}/uploads/{s.lstrip('/')}"


def build_land_json_ld(
    land: dict,
    *,
    canonical_url: str,
    site_root: str,
    seo_title: str,
    seo_description: str,
    og_image: str,
) -> dict:
    images = []
    for img in land.get("images") or []:
        images.append(_abs_url(str(img), site_root))
    if not images and og_image:
        images = [og_image]

    address_parts = [land.get("city"), land.get("location")]
    address_text = "، ".join(_clean_text(p, 80) for p in address_parts if p)

    data: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": _clean_text(land.get("title") or seo_title, 120),
        "description": seo_description,
        "url": canonical_url,
        "datePosted": _land_iso_date(land),
    }
    if images:
        data["image"] = images
    if address_text:
        data["address"] = {
            "@type": "PostalAddress",
            "addressLocality": _clean_text(land.get("city"), 60),
            "streetAddress": _clean_text(land.get("location"), 120),
            "addressCountry": "IR",
        }
    lat, lng = land.get("latitude"), land.get("longitude")
    try:
        if lat is not None and lng is not None:
            data["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": float(lat),
                "longitude": float(lng),
            }
    except (TypeError, ValueError):
        pass

    price = land.get("price_total") or land.get("price")
    try:
        price_num = int(price) if price else 0
    except (TypeError, ValueError):
        price_num = 0
    if price_num > 0:
        data["offers"] = {
            "@type": "Offer",
            "price": price_num,
            "priceCurrency": "IRR",
            "availability": "https://schema.org/InStock",
            "url": canonical_url,
        }

    area = _land_area_label(land)
    if area:
        data["floorSize"] = {
            "@type": "QuantitativeValue",
            "value": re.sub(r"[^\d.]", "", area) or area,
            "unitText": "m²",
        }

    data["category"] = _clean_text(land.get("category") or "املاک", 40)
    return data


def json_ld_script_tag(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _land_iso_date(land: dict) -> str:
    for key in ("updated_at", "modified_at", "created_at"):
        raw = land.get(key)
        if not raw:
            continue
        try:
            s = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        except (TypeError, ValueError):
            continue
    return datetime.now(timezone.utc).date().isoformat()


def land_lastmod(land: dict) -> str:
    return _land_iso_date(land)


def similar_lands(land: dict, all_lands: List[dict], *, limit: int = 6) -> List[dict]:
    code = str(land.get("code") or "")
    city = _clean_text(land.get("city"), 40).lower()
    category = _clean_text(land.get("category"), 40).lower()

    scored: List[tuple] = []
    for item in all_lands or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "") == code:
            continue
        if not item.get("is_express") or item.get("express_status") == "sold":
            continue
        score = 0
        ic = _clean_text(item.get("city"), 40).lower()
        ik = _clean_text(item.get("category"), 40).lower()
        if city and ic == city:
            score += 3
        if category and ik == category:
            score += 2
        if score <= 0:
            continue
        scored.append((score, item.get("created_at") or "", item))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if len(scored) < limit:
        for item in all_lands or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("code") or "") == code:
                continue
            if not item.get("is_express") or item.get("express_status") == "sold":
                continue
            if any(str(x[2].get("code")) == str(item.get("code")) for x in scored):
                continue
            scored.append((0, item.get("created_at") or "", item))
            if len(scored) >= limit:
                break

    return [x[2] for x in scored[:limit]]


def build_robots_txt() -> str:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /app",
        "Disallow: /settings",
        "Disallow: /my-lands",
        "Disallow: /careers/",
        "Disallow: /consultant/",
        "Disallow: /express/partner/login",
        "Disallow: /express/partner/apply",
        "Disallow: /express/partner/profile",
        "Disallow: /express/partner/favorites",
        "Disallow: /express/partner/commissions",
        "Disallow: /express/partner/routine",
        "Disallow: /express/partner/ai",
        "Disallow: /express/partner/my-properties",
        "Disallow: /express/partner/ai",
        "",
        f"Sitemap: {SITE_ORIGIN}/sitemap.xml",
        "",
    ]
    return "\n".join(lines)


def _production_loc(url: str) -> str:
    """Force sitemap URLs to use the public production origin."""
    try:
        path = urlparse(url).path or "/"
    except Exception:
        path = url if url.startswith("/") else "/"
    if not path.startswith("/"):
        path = "/" + path
    return SITE_ORIGIN.rstrip("/") + path


def build_sitemap_entries(app) -> List[Dict[str, str]]:
    """Public indexable URLs with lastmod for sitemap.xml."""
    from flask import url_for

    entries: List[Dict[str, str]] = []
    today = datetime.now(timezone.utc).date().isoformat()

    static_pages = [
        ("main.partners", {}),
        ("main.help", {}),
        ("main.privacy", {}),
        ("express_partner.home", {}),
        ("express_partner.cooperation_terms", {}),
    ]
    with app.app_context():
        entries.append({"loc": SITE_ORIGIN + "/", "lastmod": today})
        for endpoint, kwargs in static_pages:
            try:
                loc = url_for(endpoint, _external=True, **kwargs)
            except Exception:
                continue
            entries.append({"loc": _production_loc(loc), "lastmod": today})

        try:
            from ..utils.storage import load_express_lands_cached

            for land in load_express_lands_cached(app) or []:
                code = str(land.get("code") or "").strip()
                if not code:
                    continue
                try:
                    loc = url_for("express_partner.land_detail", code=code, _external=True)
                except Exception:
                    loc = f"{SITE_ORIGIN}/express/partner/lands/{code}"
                entries.append({"loc": _production_loc(loc), "lastmod": land_lastmod(land)})
        except Exception:
            pass

    # de-dupe by loc
    seen = set()
    unique: List[Dict[str, str]] = []
    for e in entries:
        loc = e["loc"]
        if loc in seen:
            continue
        seen.add(loc)
        unique.append(e)
    return unique


def render_sitemap_xml(entries: List[Dict[str, str]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for item in entries:
        loc = item["loc"].replace("&", "&amp;")
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{item.get('lastmod', '')}</lastmod>")
        lines.append("    <changefreq>weekly</changefreq>")
        if loc.rstrip("/") == SITE_ORIGIN or loc.rstrip("/") == SITE_ORIGIN + "/":
            priority = "1.0"
        elif "/lands/" in loc:
            priority = "0.8"
        else:
            priority = "0.9"
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)
