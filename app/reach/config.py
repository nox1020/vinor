"""رسدکننده — پیگیری خودکار SMS/FCM بدون تأیید ادمین."""
from __future__ import annotations

import os


def reach_enabled() -> bool:
    return (os.environ.get("VINOR_REACH_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def reach_scheduler_enabled() -> bool:
    if not reach_enabled():
        return False
    if (os.environ.get("VINOR_DISABLE_REACH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    return (os.environ.get("VINOR_REACH_SCHEDULER") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def reach_sms_enabled() -> bool:
    return (os.environ.get("VINOR_REACH_SMS") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def reach_notif_enabled() -> bool:
    return (os.environ.get("VINOR_REACH_NOTIF") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# نوبت‌های تهران — هم‌تراز مربی فروش همکار
REACH_HOURS = (10, 14, 20)
