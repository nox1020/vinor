# -*- coding: utf-8 -*-
"""فلگ‌های قابلیت AI — ذخیره در settings.json با اولویت env.

قانون: env صریح → kill-switch عملیاتی؛ وگرنه مقدار پنل؛ وگرنه پیش‌فرض روشن.
"""
from __future__ import annotations

import os
from typing import Any

SETTINGS_NS = "ai_feature_flags"

# کلیدهایی که از پنل ادمین قابل تغییرند (پیش‌فرض همه روشن).
MUTABLE_FLAG_KEYS: frozenset[str] = frozenset(
    {
        "VINOR_SUPERVISOR_ENABLED",
        "VINOR_SUPERVISOR_AGENT_ENABLED",
        "VINOR_AGENTS_ENABLED",
        "VINOR_PARALLEL_AGENTS",
        "VINOR_PROPERTY_SEARCH_ENABLED",
        "VINOR_ANALYSIS_ENABLED",
        "VINOR_CUSTOMER_MEMORY_ENABLED",
        "VINOR_RECOMMENDATION_ENABLED",
        "VINOR_NEGOTIATION_ENABLED",
        "VINOR_CUSTOMER_SUCCESS_ENABLED",
        "VINOR_REACH_ENABLED",
        "VINOR_CONVERSATION_ENABLED",
        "VINOR_WORKFLOW_ENGINE_ENABLED",
        "VINOR_MEMORY_ENABLED",
        "VINOR_EVALUATION_ENABLED",
        "VINOR_BI_ENABLED",
        "VINOR_FOUNDATION_ENABLED",
        "VINOR_CRM_AI_TOOLS_ENABLED",
        "VINOR_COMMERCIAL_AI_TOOLS_ENABLED",
        "VINOR_CLOSING_AI_TOOLS_ENABLED",
        "VINOR_INTEGRATION_AI_TOOLS_ENABLED",
        # VINOR_AI_CONSOLE_ENABLED عمداً mutable نیست — جلوگیری از قفل‌شدن پنل
    }
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _parse_bool(raw: Any, *, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in _TRUTHY


def flag_env_raw(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw)


def flag_env_locked(name: str) -> bool:
    """اگر env ست شده باشد، پنل نمی‌تواند override کند."""
    return flag_env_raw(name) is not None


def get_stored_flags() -> dict[str, bool]:
    try:
        from app.utils.storage import load_settings

        raw = (load_settings() or {}).get(SETTINGS_NS)
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, bool] = {}
    for key, val in raw.items():
        name = str(key or "").strip()
        if name not in MUTABLE_FLAG_KEYS:
            continue
        out[name] = _parse_bool(val, default=True)
    return out


def resolve_feature_flag(name: str, *, default: bool = True) -> bool:
    """env صریح > settings پنل > پیش‌فرض روشن."""
    env = flag_env_raw(name)
    if env is not None:
        return env.strip().lower() in _TRUTHY
    stored = get_stored_flags()
    if name in stored:
        return bool(stored[name])
    return default


def set_feature_flag(name: str, enabled: bool) -> dict[str, Any]:
    """ذخیره یک فلگ در settings.json. اگر env قفل باشد خطا برمی‌گرداند."""
    key = str(name or "").strip()
    if key not in MUTABLE_FLAG_KEYS:
        return {"ok": False, "error": "flag_not_mutable"}
    if flag_env_locked(key):
        return {"ok": False, "error": "env_locked", "env": flag_env_raw(key)}

    import json

    from app.utils.storage import _SETTINGS_CACHE, ensure_file, load_settings

    current = dict(load_settings() or {})
    raw = current.get(SETTINGS_NS) if isinstance(current.get(SETTINGS_NS), dict) else {}
    flags = {str(k): _parse_bool(v, default=True) for k, v in raw.items() if str(k) in MUTABLE_FLAG_KEYS}
    flags[key] = bool(enabled)
    current[SETTINGS_NS] = flags
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return {"ok": True, "name": key, "value": bool(enabled), "flags": flags}


def flag_source(name: str) -> str:
    if flag_env_locked(name):
        return "env"
    if name in get_stored_flags():
        return "settings"
    return "default"
