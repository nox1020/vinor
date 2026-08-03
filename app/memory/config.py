from __future__ import annotations

import os

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB per user


def memory_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_MEMORY_ENABLED", default=True)


def memory_budget_chars() -> int:
    try:
        return max(80, min(600, int(os.environ.get("VINOR_MEMORY_BUDGET_CHARS") or 280)))
    except Exception:
        return 280


def system_memory_budget_chars() -> int:
    """Char budget for shared business/system facts in the model prompt."""
    try:
        return max(
            200,
            min(2000, int(os.environ.get("VINOR_SYSTEM_MEMORY_BUDGET_CHARS") or 1200)),
        )
    except Exception:
        return 1200


def memory_top_k() -> int:
    try:
        return max(1, min(16, int(os.environ.get("VINOR_MEMORY_TOP_K") or 8)))
    except Exception:
        return 8


def memory_store_backend() -> str:
    return (os.environ.get("VINOR_MEMORY_STORE") or "file").strip().lower()


def memory_max_bytes() -> int:
    """سقف بایت حافظهٔ اختصاصی هر کاربر (پیش‌فرض ۱۰ مگابایت)."""
    raw = (os.environ.get("VINOR_MEMORY_MAX_BYTES") or "").strip()
    if not raw:
        return _DEFAULT_MAX_BYTES
    try:
        n = int(raw)
    except Exception:
        return _DEFAULT_MAX_BYTES
    # حداقل ۶۴KB؛ حداکثر ۵۱۲MB برای ایمنی دیسک
    return max(64 * 1024, min(512 * 1024 * 1024, n))


def memory_short_ttl_hours() -> int:
    """عمر حافظهٔ کوتاه‌مدت (ساعت). پیش‌فرض ۴۸."""
    try:
        return max(1, min(168, int(os.environ.get("VINOR_MEMORY_SHORT_TTL_HOURS") or 48)))
    except Exception:
        return 48
