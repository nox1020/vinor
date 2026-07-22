"""زمان‌بندی رسدکننده — نوبت‌های تهران ۱۰/۱�۴/۲۰."""
from __future__ import annotations

import os
import threading
import time

from flask import Flask

from app.reach.config import REACH_HOURS, reach_enabled


def _tehran_hour() -> int:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        return int(datetime.now(ZoneInfo("Asia/Tehran")).hour)
    except Exception:
        from datetime import datetime

        return int(datetime.now().hour)


def _loop(app: Flask) -> None:
    last_slot: int | None = None
    while True:
        try:
            with app.app_context():
                h = _tehran_hour()
                if h in REACH_HOURS and h != last_slot:
                    from app.reach.service import maybe_run_reach_followup

                    maybe_run_reach_followup()
                    last_slot = h
                if h not in REACH_HOURS:
                    last_slot = None
        except Exception:
            try:
                app.logger.exception("Reach scheduler tick failed")
            except Exception:
                pass
        time.sleep(600)


def schedule_reach(app: Flask) -> None:
    """پیش‌فرض in-process ON؛ روی Passenger/LiteSpeed باید ۰ باشد (cron)."""
    if not reach_enabled():
        app.logger.info("Reach disabled via VINOR_REACH_ENABLED=0")
        return
    if (os.environ.get("VINOR_DISABLE_REACH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        app.logger.info("Reach disabled via VINOR_DISABLE_REACH")
        return
    flag = (os.environ.get("VINOR_REACH_SCHEDULER") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        app.logger.info(
            "Reach in-process scheduler off "
            "(cron: scripts/run_reach_followup.py every 10min, or set VINOR_REACH_SCHEDULER=1)"
        )
        return
    threading.Thread(
        target=_loop,
        args=(app,),
        daemon=True,
        name="vinor-reach",
    ).start()
    app.logger.info(
        "Reach follow-up scheduler started (Tehran hours %s - buyer SMS/FCM from funnel signals)",
        list(REACH_HOURS),
    )
