"""مسیریابی پاسخ AI — اولویت آفلاین؛ API فقط پشتیبان."""
from __future__ import annotations

from typing import Any

from .offline_bootstrap import ensure_engine_ready
from .offline_config import offline_enabled, provider_mode
from .offline_engine import generate as offline_generate
from .offline_engine import is_ready as offline_is_ready
from .offline_engine import last_error
from .model_paths import model_is_ready


def _deepseek(messages: list[dict[str, str]]) -> dict[str, Any]:
    from .services import _call_deepseek

    return _call_deepseek(messages)


def _api_usable() -> bool:
    from .config import get_deepseek_api_key
    from .credits import is_api_balance_depleted

    return bool(get_deepseek_api_key()) and not is_api_balance_depleted()


def _try_offline(messages: list[dict[str, str]], *, required: bool = False) -> dict[str, Any]:
    if not offline_enabled():
        if required:
            return {
                "ok": False,
                "error": "AI آفلاین غیرفعال است.",
                "error_code": "offline_disabled",
            }
        return {"ok": False, "error_code": "offline_disabled"}

    if not model_is_ready():
        if required:
            return {
                "ok": False,
                "error": "فایل مدل AI هنوز دانلود نشده است.",
                "error_code": "model_missing",
            }
        return {"ok": False, "error_code": "model_missing"}

    if not offline_is_ready():
        ensure_engine_ready(sync_pip=False)

    if offline_is_ready():
        result = offline_generate(messages)
        if result.get("ok") or required:
            return result
        return result

    err = last_error() or "offline engine not ready"
    if required:
        return {
            "ok": False,
            "error": (
                "موتور AI آفلاین در حال آماده‌سازی است. "
                "لطفاً یک دقیقه دیگر دوباره تلاش کنید."
            ),
            "error_code": "offline_not_ready",
            "offline_error": err,
        }
    return {"ok": False, "error_code": "offline_not_ready", "offline_error": err}


def call_ai(messages: list[dict[str, str]]) -> dict[str, Any]:
    mode = provider_mode()

    if mode == "offline":
        return _try_offline(messages, required=True)

    # auto / deepseek: همیشه اول آفلاین
    if offline_enabled():
        offline = _try_offline(messages)
        if offline.get("ok"):
            return offline

    if mode == "deepseek" or _api_usable():
        api_result = _deepseek(messages)
        if api_result.get("ok"):
            return api_result
        if offline_enabled():
            offline = _try_offline(messages, required=True)
            if offline.get("ok"):
                return offline
        return api_result

    if offline_enabled():
        return _try_offline(messages, required=True)

    return {
        "ok": False,
        "error": "سرویس هوش مصنوعی در دسترس نیست.",
        "error_code": "no_provider",
    }
