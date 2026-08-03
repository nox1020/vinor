from __future__ import annotations


def agents_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_AGENTS_ENABLED", default=True)


def agents_cache_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_AGENTS_CACHE", default=True)


def property_search_enabled() -> bool:
    """ایجنت جستجوی فایل — پیش‌فرض روشن؛ قابل کنترل از پنل."""
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_PROPERTY_SEARCH_ENABLED", default=True)
