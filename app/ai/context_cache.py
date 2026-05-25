"""کش زمینهٔ system prompt — کاهش بار ساخت مکرر context."""
from __future__ import annotations

import time
from typing import Any

from app.ai.credits import budget_config

_PUBLIC: dict[str, Any] = {"ts": 0.0, "text": ""}
_PARTNER: dict[str, dict[str, Any]] = {}


def get_public_context(build_fn) -> str:
    cfg = budget_config()
    ttl = cfg["public_ctx_ttl_sec"]
    now = time.time()
    if _PUBLIC.get("text") and (now - float(_PUBLIC.get("ts") or 0)) < ttl:
        return str(_PUBLIC["text"])
    text = build_fn()
    _PUBLIC["text"] = text
    _PUBLIC["ts"] = now
    return text


def get_partner_context(phone: str, build_fn) -> str:
    cfg = budget_config()
    ttl = cfg["partner_ctx_ttl_sec"]
    now = time.time()
    entry = _PARTNER.get(phone)
    if entry and entry.get("text") and (now - float(entry.get("ts") or 0)) < ttl:
        return str(entry["text"])
    text = build_fn()
    _PARTNER[phone] = {"text": text, "ts": now}
    if len(_PARTNER) > 200:
        oldest = min(_PARTNER.items(), key=lambda x: float(x[1].get("ts") or 0))[0]
        _PARTNER.pop(oldest, None)
    return text


def invalidate_partner(phone: str) -> None:
    _PARTNER.pop(phone, None)
