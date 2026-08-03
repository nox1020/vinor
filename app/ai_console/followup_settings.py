# -*- coding: utf-8 -*-
"""ساعت‌های پیگیری خودکار (تهران) — مشترک reach + sales_coach.

اولویت: env VINOR_REACH_HOURS / VINOR_FOLLOWUP_HOURS → settings پنل → پیش‌فرض ۱۰/۱۴/۲۰.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, Sequence

SETTINGS_KEY = "ai_followup_hours"
DEFAULT_HOURS: tuple[int, ...] = (10, 14, 20)
_ENV_KEYS = ("VINOR_REACH_HOURS", "VINOR_FOLLOWUP_HOURS")


def _parse_hours(raw: Any) -> tuple[int, ...] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None
        items = re.split(r"[,;\s]+", text)
    out: list[int] = []
    seen: set[int] = set()
    for item in items:
        try:
            h = int(str(item).strip())
        except Exception:
            continue
        if h < 0 or h > 23:
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    if not out:
        return None
    return tuple(sorted(out))


def followup_hours_env_raw() -> str | None:
    for key in _ENV_KEYS:
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return None


def followup_hours_env_locked() -> bool:
    return followup_hours_env_raw() is not None


def get_followup_hours() -> tuple[int, ...]:
    """نوبت‌های تهران برای رسدکننده و مربی فروش."""
    env = followup_hours_env_raw()
    if env is not None:
        parsed = _parse_hours(env)
        if parsed:
            return parsed
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get(SETTINGS_KEY)
        parsed = _parse_hours(stored)
        if parsed:
            return parsed
    except Exception:
        pass
    return DEFAULT_HOURS


def followup_hours_source() -> str:
    if followup_hours_env_locked():
        return "env"
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get(SETTINGS_KEY)
        if _parse_hours(stored):
            return "settings"
    except Exception:
        pass
    return "default"


def set_followup_hours(hours: Sequence[Any] | str) -> dict[str, Any]:
    """ذخیره نوبت‌ها در settings.json."""
    if followup_hours_env_locked():
        return {
            "ok": False,
            "error": "env_locked",
            "env": followup_hours_env_raw(),
        }
    parsed = _parse_hours(hours)
    if not parsed:
        return {"ok": False, "error": "invalid_hours"}
    if len(parsed) > 12:
        return {"ok": False, "error": "too_many_hours"}

    import json

    from app.utils.storage import _SETTINGS_CACHE, ensure_file, load_settings

    current = dict(load_settings() or {})
    current[SETTINGS_KEY] = list(parsed)
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return {"ok": True, "hours": list(parsed), "source": "settings"}


def hours_for_display(*, selected: Iterable[int] | None = None) -> list[dict[str, Any]]:
    """۲۴ ساعت شبانه‌روز برای UI چک‌باکس."""
    sel = set(int(h) for h in (selected if selected is not None else get_followup_hours()))
    rows = []
    for h in range(24):
        rows.append(
            {
                "hour": h,
                "label": f"{h:02d}:00",
                "selected": h in sel,
            }
        )
    return rows
