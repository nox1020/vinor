"""تنظیمات قابل‌ویرایش Vinor AI از پنل ادمین (settings.json → ai)."""
from __future__ import annotations

import os
from typing import Any

# DeepSeek V4 — Flash پیش‌فرض؛ Pro از پنل ادمین قابل انتخاب (مگر VINOR_AI_FORCE_FLASH=1)
MODEL_ID_FLASH = "deepseek-v4-flash"
MODEL_ID_PRO = "deepseek-v4-pro"
MODEL_CHOICES = ("flash", "pro", "auto")


_AI_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "model_choice": "flash",
    # DeepSeek V4 thinking پیش‌فرض API روشن است — اینجا عمداً خاموش (هزینه/توکن)
    "thinking_enabled": False,
    "min_interval_sec": 4.0,
    "dedup_ttl_sec": 180,
    "max_history": 4,
    "max_msg_chars": 700,
    "max_assistant_history_chars": 300,
    "max_context_chars": 2400,
    "max_tokens": 512,
    "temperature": 0.45,
    "public_ctx_ttl_sec": 300,
    "partner_ctx_ttl_sec": 180,
    "min_message_chars": 1,
    "escalation_sms_enabled": True,
    # شیر اطمینان مصرف — پیش‌فرض روشن
    "spend_fuse_enabled": True,
    "spend_fuse_window_sec": 86400,  # پنجرهٔ غلتان ۲۴ ساعته
    "spend_fuse_max_tokens": 2_500_000,  # سقف توکن در پنجره
    "spend_fuse_max_requests": 600,  # سقف تعداد درخواست API در پنجره
}


def default_ai_settings() -> dict[str, Any]:
    return dict(_AI_DEFAULTS)


def force_flash_enabled() -> bool:
    """قفل اجباری Flash با env — پیش‌فرض خاموش تا ادمین بتواند مدل را انتخاب کند."""
    return (os.environ.get("VINOR_AI_FORCE_FLASH") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def model_choice_options() -> list[dict[str, str]]:
    return [
        {
            "value": "flash",
            "label": "Flash",
            "hint": "سریع و کم‌هزینه — پیشنهاد پیش‌فرض برای تولید",
            "api_id": MODEL_ID_FLASH,
        },
        {
            "value": "pro",
            "label": "Pro",
            "hint": "قوی‌تر و گران‌تر — فقط وقتی لازم است انتخاب کنید",
            "api_id": MODEL_ID_PRO,
        },
    ]


def _normalize_model_choice(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if force_flash_enabled():
        return "flash"
    if v in ("pro", "v4-pro", MODEL_ID_PRO, "reasoner"):
        return "pro"
    if v in ("flash", "auto", "v4-flash", MODEL_ID_FLASH, ""):
        return "flash"
    return "flash"


def resolve_deepseek_model(*, has_tools: bool = False) -> str:
    _ = has_tools
    if force_flash_enabled():
        return MODEL_ID_FLASH
    choice = _normalize_model_choice(get_ai_settings().get("model_choice"))
    return MODEL_ID_PRO if choice == "pro" else MODEL_ID_FLASH


def assert_flash_model(model_id: str) -> str:
    """نرمال‌سازی قبل از ارسال به API — با احترام به انتخاب ادمین مگر قفل env."""
    if force_flash_enabled():
        return MODEL_ID_FLASH
    mid = str(model_id or "").strip().lower()
    if mid == MODEL_ID_PRO or "pro" in mid or "reasoner" in mid:
        return MODEL_ID_PRO
    return MODEL_ID_FLASH


def thinking_enabled() -> bool:
    """Thinking — env اولویت دارد؛ وگرنه مقدار ذخیره‌شده در پنل."""
    env = os.environ.get("VINOR_AI_THINKING")
    if env is not None and str(env).strip() != "":
        return str(env).strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(get_ai_settings().get("thinking_enabled"))
    except Exception:
        return False


def resolve_deepseek_model_label() -> str:
    mid = resolve_deepseek_model()
    if mid == MODEL_ID_PRO:
        return f"Pro ({MODEL_ID_PRO})"
    return f"Flash ({MODEL_ID_FLASH})"


def model_choice_label(choice: str | None = None) -> str:
    c = _normalize_model_choice(choice if choice is not None else get_ai_settings().get("model_choice"))
    return "Pro" if c == "pro" else "Flash"


def _coerce_ai_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_ai_settings()
    if not isinstance(raw, dict):
        return out
    for key in out:
        if key not in raw or raw[key] is None:
            continue
        val = raw[key]
        if key in (
            "enabled",
            "escalation_sms_enabled",
            "thinking_enabled",
            "spend_fuse_enabled",
        ):
            if isinstance(val, bool):
                out[key] = val
            else:
                out[key] = str(val).strip().lower() in ("1", "true", "yes", "on")
        elif key == "model_choice":
            out[key] = _normalize_model_choice(val)
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
        "spend_fuse_window_sec": "VINOR_AI_SPEND_FUSE_WINDOW_SEC",
        "spend_fuse_max_tokens": "VINOR_AI_SPEND_FUSE_MAX_TOKENS",
        "spend_fuse_max_requests": "VINOR_AI_SPEND_FUSE_MAX_REQUESTS",
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

    env_fuse = os.environ.get("VINOR_AI_SPEND_FUSE")
    if env_fuse is not None and str(env_fuse).strip() != "":
        out["spend_fuse_enabled"] = str(env_fuse).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    env_model = os.environ.get("VINOR_AI_MODEL_CHOICE")
    if env_model is not None and str(env_model).strip() != "":
        out["model_choice"] = _normalize_model_choice(env_model)
    elif force_flash_enabled():
        out["model_choice"] = "flash"

    env_thinking = os.environ.get("VINOR_AI_THINKING")
    if env_thinking is not None and str(env_thinking).strip() != "":
        out["thinking_enabled"] = str(env_thinking).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    # سقف سخت هزینه — settings قدیمی (مثلاً max_context=3500) را پایین بکش
    try:
        out["max_history"] = max(1, min(int(out["max_history"]), 4))
        out["max_msg_chars"] = max(120, min(int(out["max_msg_chars"]), 700))
        out["max_assistant_history_chars"] = max(
            80, min(int(out["max_assistant_history_chars"]), 300)
        )
        out["max_context_chars"] = max(400, min(int(out["max_context_chars"]), 2400))
        out["max_tokens"] = max(64, min(int(out["max_tokens"]), 512))
        out["spend_fuse_window_sec"] = max(
            300, min(int(out["spend_fuse_window_sec"]), 7 * 86400)
        )
        out["spend_fuse_max_tokens"] = max(
            50_000, min(int(out["spend_fuse_max_tokens"]), 100_000_000)
        )
        out["spend_fuse_max_requests"] = max(
            20, min(int(out["spend_fuse_max_requests"]), 100_000)
        )
    except Exception:
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
    ai.update(_coerce_ai_settings({**ai, **tunable}))
    if force_flash_enabled():
        ai["model_choice"] = "flash"

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
