# -*- coding: utf-8 -*-
"""وکیل ملکی — شخصیت جدا از ایجنت فروش."""
from app.lawyer.config import (
    build_lawyer_system_prompt,
    get_lawyer_settings,
    lawyer_enabled,
    lawyer_feature_enabled,
    lawyer_system_enabled,
    lawyer_welcome_text,
    save_lawyer_settings,
)
from app.lawyer.service import (
    LAWYER_THREAD_ID,
    ensure_lawyer_thread,
    is_lawyer_thread,
    lawyer_thread_for_ui,
    threads_with_lawyer,
    threads_with_lawyer_and_postchi,
)

__all__ = [
    "LAWYER_THREAD_ID",
    "build_lawyer_system_prompt",
    "ensure_lawyer_thread",
    "get_lawyer_settings",
    "is_lawyer_thread",
    "lawyer_enabled",
    "lawyer_feature_enabled",
    "lawyer_system_enabled",
    "lawyer_thread_for_ui",
    "lawyer_welcome_text",
    "save_lawyer_settings",
    "threads_with_lawyer",
    "threads_with_lawyer_and_postchi",
]
