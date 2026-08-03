#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اجرای یک‌بار jobهای پیامک زمان‌بندی‌شده ادمین — اختیاری؛ روی هاست lazy tick کافی است."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("INSTANCE_PATH", os.path.join(ROOT, "instance"))
os.environ["VINOR_ADMIN_SMS_SCHEDULER"] = "0"
os.environ["VINOR_REACH_SCHEDULER"] = "0"
os.environ["VINOR_SALES_COACH_SCHEDULER"] = "0"
os.environ["VINOR_CELEBRATION_SMS_SCHEDULER"] = "0"
os.environ["VINOR_OPTIMIZATION_SCHEDULER"] = "0"

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
