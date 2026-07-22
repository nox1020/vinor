# -*- coding: utf-8 -*-
"""دسته‌بندی گزارش‌های Supervisor Agent."""
from __future__ import annotations

REPORT_FOLLOWUP = "followup"
REPORT_DEAL = "deal"
REPORT_VISIT = "visit"
REPORT_PARTNER = "partner"
REPORT_CUSTOMER = "customer"
REPORT_SYSTEM = "system"

ALL_REPORT_CATEGORIES = frozenset(
    {
        REPORT_FOLLOWUP,
        REPORT_DEAL,
        REPORT_VISIT,
        REPORT_PARTNER,
        REPORT_CUSTOMER,
        REPORT_SYSTEM,
    }
)

REPORT_CATEGORY_LABELS: dict[str, str] = {
    REPORT_FOLLOWUP: "پیگیری",
    REPORT_DEAL: "معامله",
    REPORT_VISIT: "بازدید",
    REPORT_PARTNER: "همکار",
    REPORT_CUSTOMER: "مشتری",
    REPORT_SYSTEM: "سیستم",
}

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_IN_PROGRESS = "in_progress"
STATUS_REMINDER = "reminder"
STATUS_INFO = "info"

ALL_REPORT_STATUSES = frozenset(
    {
        STATUS_SUCCESS,
        STATUS_ERROR,
        STATUS_IN_PROGRESS,
        STATUS_REMINDER,
        STATUS_INFO,
    }
)

STATUS_LABELS: dict[str, str] = {
    STATUS_SUCCESS: "انجام شد",
    STATUS_ERROR: "خطا",
    STATUS_IN_PROGRESS: "در جریان",
    STATUS_REMINDER: "یادآوری",
    STATUS_INFO: "اطلاع",
}
