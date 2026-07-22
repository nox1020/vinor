#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پیگیری خودکار خریدار (رسدکننده) — نوبت‌های ۱۰، ۱۴، ۲۰ تهران.

روی Passenger/LiteSpeed فقط از cron اجرا شود (نه thread داخل web worker).

cron پیشنهادی (هر ۱۰ دقیقه):
  */10 * * * * cd /home/vinorir/public_html/vinor && /home/vinorir/virtualenv/public_html/vinor/3.11/bin/python scripts/run_reach_followup.py

تست:
  python scripts/run_reach_followup.py --force --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VINOR_REACH_SCHEDULER"] = "0"

from app import create_app
from app.reach.service import maybe_run_reach_followup


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vinor buyer reach follow-up (SMS/FCM)")
    parser.add_argument("--force", action="store_true", help="Run even outside slot")
    parser.add_argument("--dry-run", action="store_true", help="Build without sending")
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
        result = maybe_run_reach_followup(
            force=args.force,
            dry_run=args.dry_run,
            slot_hour=args.slot,
        )
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
