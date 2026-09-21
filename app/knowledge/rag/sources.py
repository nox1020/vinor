from __future__ import annotations

import re
from typing import Any

from app.utils.storage import load_ads_cached

from .models import LandDocument


def _to_int(value: Any) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _status_of(land: dict[str, Any]) -> str:
    st = str(land.get("_assignment_status") or land.get("status") or "active").strip().lower()
    if st in ("in-transaction", "in transaction"):
        return "in_transaction"
    return st or "active"


def _collect_tags(land: dict[str, Any]) -> list[str]:
    raw = land.get("tags")
    tags: list[str] = []
    if isinstance(raw, list):
        tags.extend(str(x).strip() for x in raw if str(x).strip())
    elif isinstance(raw, str):
        tags.extend(t.strip() for t in re.split(r"[,\u060c|/]+", raw) if t.strip())
    for key in ("amenities", "features"):
        extra = land.get(key)
        if isinstance(extra, list):
            tags.extend(str(x).strip() for x in extra if str(x).strip())
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out[:24]


def _build_land_text(land: dict[str, Any]) -> str:
    # Keeps embedding source strictly tied to lands.json fields.
    fields = [
        _clean_text(land.get("title")),
        _clean_text(land.get("description") or land.get("desc")),
        _clean_text(land.get("category")),
        _clean_text(land.get("city")),
        _clean_text(land.get("location")),
        _clean_text(land.get("type")),
        _clean_text(land.get("status")),
        " ".join(_collect_tags(land)),
        _clean_text(land.get("price_total") or land.get("price")),
        _clean_text(
            land.get("villa_land_area")
            or land.get("villa_built_area")
            or land.get("land_area")
            or land.get("built_area")
            or land.get("size")
        ),
    ]
    return "\n".join(x for x in fields if x)


def load_land_documents() -> list[LandDocument]:
    rows = load_ads_cached() or []
    if not isinstance(rows, list):
        return []
    docs: list[LandDocument] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("public") is False:
            continue
        src = str(row.get("source") or "").strip().lower()
        if src in ("my_property", "owner_home"):
            continue
        if row.get("owner_home") and row.get("public") is not True:
            continue
        if str(row.get("ad_type") or "").strip().lower() == "owner_home":
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        docs.append(
            LandDocument(
                code=code,
                text=_build_land_text(row),
                city=_clean_text(row.get("city")).lower(),
                location=_clean_text(row.get("location")).lower(),
                category=_clean_text(row.get("category")).lower(),
                status=_status_of(row),
                tags=[x.lower() for x in _collect_tags(row)],
                price_total=_to_int(row.get("price_total") or row.get("price")),
                area_total=_to_int(
                    row.get("villa_land_area")
                    or row.get("villa_built_area")
                    or row.get("land_area")
                    or row.get("built_area")
                    or row.get("size")
                ),
            )
        )
    return docs

