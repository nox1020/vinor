#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اجرای یک‌بار jobهای پیامک زمان‌بندی‌شده ادمین — برای cron.

مثال cron (هر دقیقه):
  * * * * * cd /home/vinorir/public_html/vinor && vinor/bin/python scripts/run_admin_sms_scheduled_jobs.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from admin.sms_scheduled import process_due_scheduled_jobs


def main() -> int:
    app = create_app()
    with app.app_context():
        processed = process_due_scheduled_jobs(app)
        print({"processed": processed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
