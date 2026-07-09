"""کش زمینهٔ system prompt — کاهش بار ساخت مکرر context."""
from __future__ import annotations

import time
from typing import Any

from app.ai.credits import budget_config

_PUBLIC_BASE: dict[str, Any] = {"ts": 0.0, "text": ""}
_PARTNER_BASE: dict[str, dict[str, Any]] = {}


def get_public_context_base(build_fn) -> str:
    cfg = budget_config()
    ttl = cfg["public_ctx_ttl_sec"]
    now = time.time()
    if _PUBLIC_BASE.get("text") and (now - float(_PUBLIC_BASE.get("ts") or 0)) < ttl:
        return str(_PUBLIC_BASE["text"])
    text = build_fn()
    _PUBLIC_BASE["text"] = text
    _PUBLIC_BASE["ts"] = now
    return text


def get_partner_context_base(phone: str, build_fn) -> str:
    cfg = budget_config()
    ttl = cfg["partner_ctx_ttl_sec"]
    now = time.time()
    entry = _PARTNER_BASE.get(phone)
    if entry and entry.get("text") and (now - float(entry.get("ts") or 0)) < ttl:
        return str(entry["text"])
    text = build_fn()
    _PARTNER_BASE[phone] = {"text": text, "ts": now}
    if len(_PARTNER_BASE) > 200:
        oldest = min(_PARTNER_BASE.items(), key=lambda x: float(x[1].get("ts") or 0))[0]
        _PARTNER_BASE.pop(oldest, None)
    return text


def invalidate_partner(phone: str) -> None:
    _PARTNER_BASE.pop(phone, None)


# سازگاری با importهای قدیمی
def get_public_context(build_fn) -> str:
    return get_public_context_base(build_fn)


def get_partner_context(phone: str, build_fn) -> str:
    return get_partner_context_base(phone, build_fn)
