#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اجرای روزانه پیامک تبریک تولد و سالگرد عضویت — برای cron.

مثال cron (هر روز ساعت ۹:۳۰ صبح به وقت تهران ≈ 06:00 UTC):
  0 6 * * * cd /path/to/vinor && .venv/bin/python scripts/run_daily_celebration_sms.py
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("VINOR_DISABLE_CELEBRATION_SMS", "1")

from app import create_app
from app.express_partner.user_celebration_sms import maybe_run_daily_celebration_sms


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vinor daily birthday/anniversary SMS")
    parser.add_argument("--force", action="store_true", help="Run even if already ran today")
    parser.add_argument("--dry-run", action="store_true", help="Log messages without sending SMS")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = maybe_run_daily_celebration_sms(force=args.force, dry_run=args.dry_run)
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
