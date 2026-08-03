#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پیگیری فروش همکار — اختیاری؛ روی هاست lazy tick خودکار کافی است."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("INSTANCE_PATH", os.path.join(ROOT, "instance"))
os.environ["VINOR_SALES_COACH_SCHEDULER"] = "0"
os.environ["VINOR_REACH_SCHEDULER"] = "0"
os.environ["VINOR_CELEBRATION_SMS_SCHEDULER"] = "0"
os.environ["VINOR_ADMIN_SMS_SCHEDULER"] = "0"
os.environ["VINOR_OPTIMIZATION_SCHEDULER"] = "0"

from app import create_app
from app.express_partner.sales_coach import maybe_run_evening_sales_coach_nudge


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vinor sales-coach follow-up (notif+SMS)")
    parser.add_argument("--force", action="store_true", help="Run even outside slot / already ran")
    parser.add_argument("--dry-run", action="store_true", help="Build messages without sending")
    parser.add_argument(
        "--slot",
        type=int,
        choices=tuple(range(24)),
        default=None,
        help="Force a specific Tehran hour slot (0-23)",
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
