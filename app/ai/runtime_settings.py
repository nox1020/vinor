"""تنظیمات قابل‌ویرایش Vinor AI از پنل ادمین (settings.json → ai)."""
from __future__ import annotations

import os
from typing import Any

_AI_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "min_interval_sec": 4.0,
    "dedup_ttl_sec": 180,
    "max_history": 5,
    "max_msg_chars": 700,
    "max_assistant_history_chars": 300,
    "max_context_chars": 3000,
    "max_tokens": 512,
    "temperature": 0.45,
    "public_ctx_ttl_sec": 300,
    "partner_ctx_ttl_sec": 180,
    "min_message_chars": 1,
    "escalation_sms_enabled": True,
}


def default_ai_settings() -> dict[str, Any]:
    return dict(_AI_DEFAULTS)


def _coerce_ai_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_ai_settings()
    if not isinstance(raw, dict):
        return out
    for key in out:
        if key not in raw or raw[key] is None:
            continue
        val = raw[key]
        if key == "enabled" or key == "escalation_sms_enabled":
            if isinstance(val, bool):
                out[key] = val
            else:
                out[key] = str(val).strip().lower() in ("1", "true", "yes", "on")
        elif key in ("min_interval_sec", "temperature"):
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                pass
        else:
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                pass
    return out


def get_stored_ai_api_key() -> str:
    """کلید ذخیره‌شده در settings.json (بدون fallback)."""
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("ai")
        if isinstance(stored, dict):
            return str(stored.get("api_key") or "").strip()
    except Exception:
        pass
    return ""


def mask_api_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "••••"
    return k[:4] + "••••" + k[-4:]


def get_ai_settings() -> dict[str, Any]:
    """ادغام پیش‌فرض + settings.json + متغیر محیطی (env برای enabled اولویت دارد)."""
    try:
        from app.utils.storage import load_settings

        stored = (load_settings() or {}).get("ai")
    except Exception:
        stored = None
    out = _coerce_ai_settings(stored if isinstance(stored, dict) else None)

    env_enabled = os.environ.get("VINOR_AI_ENABLED")
    if env_enabled is not None:
        out["enabled"] = str(env_enabled).strip().lower() not in ("0", "false", "no")

    env_map = {
        "min_interval_sec": "VINOR_AI_MIN_INTERVAL_SEC",
        "dedup_ttl_sec": "VINOR_AI_DEDUP_TTL_SEC",
        "max_history": "VINOR_AI_MAX_HISTORY",
        "max_msg_chars": "VINOR_AI_MAX_MSG_CHARS",
        "max_assistant_history_chars": "VINOR_AI_MAX_ASSISTANT_HISTORY_CHARS",
        "max_context_chars": "VINOR_AI_MAX_CONTEXT_CHARS",
        "max_tokens": "VINOR_AI_MAX_TOKENS",
        "temperature": "VINOR_AI_TEMPERATURE",
        "public_ctx_ttl_sec": "VINOR_AI_PUBLIC_CTX_TTL",
        "partner_ctx_ttl_sec": "VINOR_AI_PARTNER_CTX_TTL",
        "min_message_chars": "VINOR_AI_MIN_MESSAGE_CHARS",
    }
    for key, env_key in env_map.items():
        raw = os.environ.get(env_key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            if key in ("min_interval_sec", "temperature"):
                out[key] = float(raw)
            else:
                out[key] = int(raw)
        except (TypeError, ValueError):
            pass
    return out


def save_ai_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """ذخیره در settings.json — فقط از پنل ادمین."""
    import json

    from app.utils.storage import ensure_file, load_settings, _SETTINGS_CACHE

    current = dict(load_settings() or {})
    raw_ai = current.get("ai") if isinstance(current.get("ai"), dict) else {}
    ai = _coerce_ai_settings(raw_ai)
    tunable = {k: v for k, v in (patch or {}).items() if k not in ("api_key", "clear_api_key")}
    ai.update(_coerce_ai_settings(tunable))

    if patch.get("clear_api_key"):
        ai.pop("api_key", None)
    elif "api_key" in patch:
        new_key = str(patch.get("api_key") or "").strip()
        if new_key:
            ai["api_key"] = new_key
        elif isinstance(raw_ai.get("api_key"), str) and raw_ai.get("api_key").strip():
            ai["api_key"] = str(raw_ai["api_key"]).strip()
    elif isinstance(raw_ai.get("api_key"), str) and raw_ai.get("api_key").strip():
        ai["api_key"] = str(raw_ai["api_key"]).strip()

    current["ai"] = ai
    path = ensure_file("SETTINGS_FILE", "settings.json", {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _SETTINGS_CACHE.update({"path": None, "mtime": None, "size": None, "data": None})
    return ai
