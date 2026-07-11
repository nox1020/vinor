#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""قفل فوری موجودی DeepSeek روی سرور — تا وقتی شارژ نشود درخواست 402 نزند.

  cd ~/public_html/vinor && ./venv/bin/python scripts/mark_deepseek_balance_depleted.py
  # بعد از شارژ:
  ./venv/bin/python scripts/mark_deepseek_balance_depleted.py --clear
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("VINOR_SALES_COACH_SCHEDULER", "0")
os.environ.setdefault("VINOR_CELEBRATION_SMS_SCHEDULER", "0")
os.environ.setdefault("VINOR_ADMIN_SMS_SCHEDULER", "0")

from app import create_app
from app.ai.credits import (
    clear_api_balance_depleted,
    is_api_balance_depleted,
    mark_api_balance_depleted,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="Clear depleted flag after recharge")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if args.clear:
            clear_api_balance_depleted()
            print({"ok": True, "cleared": True, "depleted": is_api_balance_depleted()})
        else:
            mark_api_balance_depleted()
            print({"ok": True, "marked": True, "depleted": is_api_balance_depleted()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
