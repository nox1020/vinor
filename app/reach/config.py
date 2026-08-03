"""رسدکننده — پیگیری خودکار SMS/FCM بدون تأیید ادمین."""
from __future__ import annotations

import os


def reach_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_REACH_ENABLED", default=True)


def reach_scheduler_enabled() -> bool:
    if not reach_enabled():
        return False
    if (os.environ.get("VINOR_DISABLE_REACH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_REACH_SCHEDULER", default=True)


def reach_sms_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_REACH_SMS", default=True)


def reach_notif_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_REACH_NOTIF", default=True)


def reach_hours() -> tuple[int, ...]:
    """نوبت‌های تهران — از پنل/env قابل تنظیم؛ پیش‌فرض ۱۰/۱۴/۲۰."""
    from app.ai_console.followup_settings import get_followup_hours

    return get_followup_hours()


# سازگاری با importهای قدیمی — مقدار پیش‌فرض؛ کد زنده باید reach_hours() را صدا بزند
REACH_HOURS = (10, 14, 20)
