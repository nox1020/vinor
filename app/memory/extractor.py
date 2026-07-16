from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from app.memory.interfaces import (
    MEMORY_LONG,
    MEMORY_RELATIONSHIP,
    MEMORY_SEMANTIC,
    MEMORY_SHORT,
    MemoryExtractRequest,
    MemoryExtractor,
    MemoryItem,
)

_BUDGET_RE = re.compile(
    r"(?:بودجه|تا|حداکثر)\s*([0-9۰-۹,\.]+)\s*(میلیارد|میلیون)?",
    re.I,
)
_CITY_HINTS = ("گرمابسرد", "دماوند", "تهران", "لواسان")
_CATEGORY_HINTS = ("ویلا", "زمین", "باغ", "آپارتمان")
_PREF_HINTS = (
    ("سرمایه", "سرمایه‌گذاری"),
    ("لوکس", "لوکس"),
    ("دنج", "دنج"),
    ("خوش نقشه", "خوش‌نقشه"),
)
_REJECT_HINTS = ("نمیخوام", "نمی‌خوام", "رد", "منتفی", "نه این")
_LIKE_HINTS = ("علاقه", "دوست دارم", "همین خوبه", "همین رو", "پسند")
_NOISE = (
    "سلام",
    "خوبی",
    "ممنون",
    "مرسی",
    "چطور",
    "کمکم کن",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fa_to_en(text: str) -> str:
    return str(text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


class RuleMemoryExtractor(MemoryExtractor):
    """Rule-based extractor — no LLM cost; only valuable facts."""

    def extract(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        user_msg = (req.user_message or "").strip()
        reply = (req.assistant_reply or "").strip()
        if not user_msg and not reply:
            return []
        if _is_noise(user_msg):
            # still allow relationship from land_codes
            return self._relationship_only(req)

        out: list[MemoryItem] = []
        blob = f"{user_msg}\n{reply}".lower()

        # Long-term preferences
        budget = _extract_budget(user_msg)
        if budget:
            out.append(
                _item(
                    req,
                    MEMORY_LONG,
                    "budget",
                    f"بودجه تقریبی تا {budget}",
                    score=0.95,
                )
            )
        for city in _CITY_HINTS:
            if city in blob:
                out.append(
                    _item(
                        req,
                        MEMORY_LONG,
                        f"city:{city}",
                        f"علاقه به منطقه {city}",
                        score=0.9,
                        metadata={"city": city},
                    )
                )
                break
        for cat in _CATEGORY_HINTS:
            if cat in blob:
                out.append(
                    _item(
                        req,
                        MEMORY_LONG,
                        f"category:{cat}",
                        f"ترجیح نوع ملک: {cat}",
                        score=0.9,
                        metadata={"category": cat},
                    )
                )
                break
        for needle, label in _PREF_HINTS:
            if needle in blob:
                out.append(
                    _item(
                        req,
                        MEMORY_LONG,
                        f"pref:{label}",
                        f"ترجیح: {label}",
                        score=0.8,
                    )
                )

        # Semantic: only concise useful facts from user
        if len(user_msg) >= 12 and not _is_noise(user_msg):
            if any(x in user_msg for x in ("میخوام", "می‌خوام", "دنبال", "بودجه", "منطقه", "ویلا", "زمین")):
                out.append(
                    _item(
                        req,
                        MEMORY_SEMANTIC,
                        f"fact:{_hash8(user_msg)}",
                        user_msg[:120],
                        score=0.7,
                    )
                )

        # Short-term conversation state
        if user_msg:
            out.append(
                _item(
                    req,
                    MEMORY_SHORT,
                    "last_user_intent",
                    user_msg[:100],
                    score=0.6,
                    metadata={"thread_id": req.thread_id or ""},
                )
            )

        # Relationship memory from land codes / like-reject hints
        out.extend(self._relationship_only(req))
        if any(h in blob for h in _LIKE_HINTS) and req.land_codes:
            for code in req.land_codes[:3]:
                out.append(
                    _item(
                        req,
                        MEMORY_RELATIONSHIP,
                        f"liked:{code}",
                        f"علاقه‌مند به فایل {code}",
                        score=0.85,
                        metadata={"land_code": code, "relation": "liked"},
                    )
                )
        if any(h in blob for h in _REJECT_HINTS) and req.land_codes:
            for code in req.land_codes[:3]:
                out.append(
                    _item(
                        req,
                        MEMORY_RELATIONSHIP,
                        f"rejected:{code}",
                        f"رد شده: فایل {code}",
                        score=0.85,
                        metadata={"land_code": code, "relation": "rejected"},
                    )
                )
        return _dedup_items(out)

    def _relationship_only(self, req: MemoryExtractRequest) -> list[MemoryItem]:
        out: list[MemoryItem] = []
        for code in (req.land_codes or [])[:5]:
            c = str(code).strip()
            if not c:
                continue
            out.append(
                _item(
                    req,
                    MEMORY_RELATIONSHIP,
                    f"viewed:{c}",
                    f"مشاهده فایل {c}",
                    score=0.75,
                    metadata={"land_code": c, "relation": "viewed"},
                )
            )
        return out


def _item(
    req: MemoryExtractRequest,
    memory_type: str,
    key: str,
    value: str,
    *,
    score: float,
    metadata: dict | None = None,
) -> MemoryItem:
    meta = dict(metadata or {})
    meta.setdefault("audience", req.audience)
    meta.setdefault("thread_id", req.thread_id or "")
    return MemoryItem(
        id=str(uuid.uuid4()),
        user_key=req.user_key,
        memory_type=memory_type,
        key=key,
        value=value,
        score=score,
        metadata=meta,
        version=1,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )


def _extract_budget(text: str) -> str:
    m = _BUDGET_RE.search(text or "")
    if not m:
        return ""
    n = _fa_to_en(m.group(1)).replace(",", "")
    unit = (m.group(2) or "").strip()
    if not n:
        return ""
    return f"{n} {unit}".strip()


def _is_noise(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not t:
        return True
    if len(t) <= 2:
        return True
    return any(t == n or t.startswith(n + " ") for n in _NOISE)


def _hash8(text: str) -> str:
    import hashlib

    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:8]


def _dedup_items(items: list[MemoryItem]) -> list[MemoryItem]:
    seen: set[str] = set()
    out: list[MemoryItem] = []
    for it in items:
        k = f"{it.memory_type}:{it.key}:{it.value}".lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out
