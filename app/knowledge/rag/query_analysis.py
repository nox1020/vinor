from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_CITY_HINTS = ("دماوند", "گرمابسرد", "تهران")
_CATEGORY_HINTS = ("ویلا", "زمین", "باغ", "آپارتمان")
_STATUS_HINTS = {"فروخته": "sold", "فعال": "active", "در حال معامله": "in_transaction"}


@dataclass
class QuerySignals:
    metadata_filter: dict[str, Any] = field(default_factory=dict)


def analyze_query(query: str) -> QuerySignals:
    q = str(query or "").strip().lower()
    filt: dict[str, Any] = {}

    for c in _CITY_HINTS:
        if c in q:
            filt["city"] = c
            break
    for c in _CATEGORY_HINTS:
        if c in q:
            filt["category"] = c
            break
    for key, mapped in _STATUS_HINTS.items():
        if key in q:
            filt["status"] = mapped
            break
    max_price = _extract_price_upper(q)
    if max_price > 0:
        filt["max_price"] = max_price
    min_area = _extract_min_area(q)
    if min_area > 0:
        filt["min_area"] = min_area

    tag_hits = []
    for t in ("سرمایه‌گذاری", "سرمایه گذاری", "لوکس", "خوش نقشه", "دنج"):
        if t in q:
            tag_hits.append(t.replace("‌", " "))
    if tag_hits:
        filt["tags"] = tag_hits

    return QuerySignals(metadata_filter=filt)


def _extract_price_upper(q: str) -> int:
    m = re.search(r"تا\s*([0-9۰-۹,\.]+)\s*(میلیارد|میلیون)?", q)
    if not m:
        return 0
    val = _fa_to_en_digits(m.group(1))
    try:
        n = float(val.replace(",", ""))
    except Exception:
        return 0
    unit = (m.group(2) or "").strip()
    if unit == "میلیارد":
        return int(n * 1_000_000_000)
    if unit == "میلیون":
        return int(n * 1_000_000)
    return int(n)


def _extract_min_area(q: str) -> int:
    m = re.search(r"حداقل\s*([0-9۰-۹]+)\s*متر", q)
    if not m:
        return 0
    try:
        return int(_fa_to_en_digits(m.group(1)))
    except Exception:
        return 0


def _fa_to_en_digits(text: str) -> str:
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    return str(text or "").translate(table)

