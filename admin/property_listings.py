"""نگاشت آگهی‌های lands.json برای تب ادمین «آگهی‌ها - ملک»."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import url_for


def _safe_url(endpoint: str, **kwargs) -> str:
    try:
        return url_for(endpoint, **kwargs)
    except Exception:
        return ""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        raw = str(value or "").replace(",", "").replace("،", "").strip()
        if not raw:
            return default
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _owner_name(land: Dict[str, Any]) -> str:
    return str(
        land.get("owner_name")
        or land.get("seller_name")
        or land.get("name")
        or land.get("owner")
        or "—"
    ).strip() or "—"


def _is_owner_home(land: Dict[str, Any]) -> bool:
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    if land.get("owner_home") or extras.get("owner_home") or extras.get("listed_by_owner"):
        return True
    src = str(land.get("source") or "").strip().lower()
    if src in ("my_property", "owner_home"):
        return True
    return str(land.get("ad_type") or "").strip().lower() == "owner_home"


def _owner_phone(land: Dict[str, Any]) -> str:
    return str(
        land.get("owner")
        or land.get("user_phone")
        or land.get("phone")
        or land.get("owner_phone")
        or ""
    ).strip()


def _created_at(land: Dict[str, Any]) -> str:
    return str(land.get("created_at") or land.get("updated_at") or "").strip()


def _is_today(iso: str) -> bool:
    if not iso:
        return False
    try:
        raw = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return dt.astimezone(timezone.utc).date() == now.date()
    except Exception:
        return iso[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def listing_status(land: Dict[str, Any], expiry: Optional[Dict[str, Any]] = None) -> str:
    status = str(land.get("status") or "pending").strip().lower() or "pending"
    if status in ("expired", "expire"):
        return "expired"
    if expiry and expiry.get("status") == "today":
        return "expired"
    if status not in ("pending", "approved", "rejected"):
        return "pending"
    return status


def to_row(land: Dict[str, Any], expiry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    code = str(land.get("code") or "").strip()
    status = listing_status(land, expiry)
    created = _created_at(land)
    thumb = ""
    try:
        from app.utils.images import partner_card_image_url
        thumb = partner_card_image_url(land) or ""
    except Exception:
        thumb = ""
    return {
        "id": code,
        "code": code,
        "thumbnail": thumb,
        "title": str(land.get("title") or "بدون عنوان").strip() or "بدون عنوان",
        "owner_name": _owner_name(land),
        "owner_phone": _owner_phone(land),
        "city": str(land.get("city") or land.get("location") or "—").strip() or "—",
        "district": str(land.get("location") or land.get("district") or "").strip(),
        "price": _as_int(land.get("price_total") or land.get("price")),
        "sqm": _as_int(land.get("size") or land.get("sqm")),
        "status": status,
        "created_at": created,
        "created_today": _is_today(created),
        "rejection_reason": str(land.get("reject_reason") or land.get("rejection_reason") or "").strip(),
        "owner_home": _is_owner_home(land),
        "view_url": _safe_url("admin.view_land", code=code) if code else "",
        "edit_url": _safe_url("admin.edit_land", code=code) if code else "",
    }


def collect_rows(lands: List[Dict[str, Any]], expiry_fn) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    stats = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "expired": 0, "today": 0}
    for land in lands:
        if not isinstance(land, dict):
            continue
        expiry = expiry_fn(land) if expiry_fn else None
        row = to_row(land, expiry)
        rows.append(row)
        stats["total"] += 1
        key = row["status"] if row["status"] in stats else "pending"
        stats[key] = stats.get(key, 0) + 1
        if row.get("created_today"):
            stats["today"] += 1
    return rows, stats


def filter_rows(rows: List[Dict[str, Any]], status: str, q: str) -> List[Dict[str, Any]]:
    status = (status or "all").strip().lower()
    needle = (q or "").strip().lower()
    out = rows
    if status in ("pending", "approved", "rejected", "expired"):
        out = [r for r in out if r.get("status") == status]
    if needle:
        def _hit(row: Dict[str, Any]) -> bool:
            blob = " ".join([
                str(row.get("title") or ""),
                str(row.get("owner_name") or ""),
                str(row.get("owner_phone") or ""),
                str(row.get("city") or ""),
                str(row.get("district") or ""),
                str(row.get("code") or ""),
                "ملک من" if row.get("owner_home") else "",
            ]).lower()
            return needle in blob
        out = [r for r in out if _hit(r)]
    return out
