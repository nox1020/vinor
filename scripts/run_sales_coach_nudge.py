#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پیگیری منظم فروش همکار (اعلان + پیامک) — نوبت‌های ۱۰، ۱۴، ۲۰ تهران.

تا وقتی فایل فروخته نشده برای همان همکار ادامه می‌دهد.

cron پیشنهادی (هر ۱۰ دقیقه):
  */10 * * * * cd /path/to/vinor && .venv/bin/python scripts/run_sales_coach_nudge.py

تست:
  python scripts/run_sales_coach_nudge.py --force --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VINOR_SALES_COACH_SCHEDULER"] = "0"

from app import create_app
from app.express_partner.sales_coach import maybe_run_evening_sales_coach_nudge


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vinor sales-coach follow-up (notif+SMS)")
    parser.add_argument("--force", action="store_true", help="Run even outside slot / already ran")
    parser.add_argument("--dry-run", action="store_true", help="Build messages without sending")
    parser.add_argument(
        "--slot",
        type=int,
        choices=(10, 14, 20),
        default=None,
        help="Force a specific Tehran hour slot",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = maybe_run_evening_sales_coach_nudge(
            force=args.force,
            dry_run=args.dry_run,
            slot_hour=args.slot,
        )
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
