from __future__ import annotations

import re
from typing import Any

from app.agents.customer_memory.interfaces import CustomerPreferences, PreferenceExtractor

_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_BUDGET_RE = re.compile(
    r"(?:تا|بودجه|زیر|کمتر از|حداکثر)\s*([\d۰-۹]+(?:[.,٫،][\d۰-۹]+)*)\s*(میلیارد|میلیون)?",
    re.I,
)
_CITY_RE = re.compile(r"(دماوند|گرمابسرد|لواسان|رودهن|آبسرد|تهران)", re.I)
_TYPE_RE = re.compile(r"(ویلا|زمین|باغ|آپارتمان)", re.I)
_AVOID_RE = re.compile(r"(نمی.?خوام|نداشته باشد|بدون|اجتناب|نه\s+)([^\n،.]{2,40})", re.I)
_MUST_RE = re.compile(r"(حتما|باید|لازم|می‌خوام|میخوام)\s*([^\n،.]{2,40})", re.I)


def _fa(s: str) -> str:
    return (s or "").translate(_DIGIT)


def _parse_budget(text: str) -> int | None:
    m = _BUDGET_RE.search(text or "")
    if not m:
        return None
    num = re.sub(r"[^\d]", "", _fa(m.group(1)))
    try:
        val = int(num or "0")
    except Exception:
        return None
    unit = (m.group(2) or "").lower()
    if "میلیارد" in unit:
        return val * 1_000_000_000
    if "میلیون" in unit:
        return val * 1_000_000
    if val < 1000:
        return val * 1_000_000_000
    return val


class RulePreferenceExtractor(PreferenceExtractor):
    """Rule-based prefs from existing Memory items + message — no LLM, no new store."""

    def extract(
        self,
        *,
        message: str,
        memory_items: list[Any],
        shared: dict[str, Any],
    ) -> CustomerPreferences:
        prefs = CustomerPreferences()
        blobs: list[str] = [message or ""]

        mem_prefs = shared.get("memory_prefs") if isinstance(shared.get("memory_prefs"), dict) else {}
        for k, v in mem_prefs.items():
            blobs.append(f"{k} {v}")

        for it in memory_items or []:
            key = getattr(it, "key", None) or (it.get("key") if isinstance(it, dict) else "")
            val = getattr(it, "value", None) or (it.get("value") if isinstance(it, dict) else "")
            blobs.append(f"{key} {val}")

        text = "\n".join(blobs)

        budget = _parse_budget(text)
        if budget:
            prefs.budget_max = budget

        for m in _CITY_RE.finditer(text):
            city = m.group(1)
            if city not in prefs.locations:
                prefs.locations.append(city)

        for m in _TYPE_RE.finditer(text):
            t = m.group(1)
            if t not in prefs.property_types:
                prefs.property_types.append(t)

        for m in _MUST_RE.finditer(text):
            bit = (m.group(2) or "").strip()
            if bit and bit not in prefs.must_have and len(prefs.must_have) < 5:
                prefs.must_have.append(bit[:40])

        for m in _AVOID_RE.finditer(text):
            bit = (m.group(2) or "").strip()
            if bit and bit not in prefs.avoid and len(prefs.avoid) < 5:
                prefs.avoid.append(bit[:40])

        # short notes from long-term memory keys
        for it in (memory_items or [])[:8]:
            val = getattr(it, "value", None) or (it.get("value") if isinstance(it, dict) else "")
            if val and str(val).strip() and len(prefs.notes) < 4:
                prefs.notes.append(str(val).strip()[:60])

        return prefs
