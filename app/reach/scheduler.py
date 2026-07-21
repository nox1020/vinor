"""زمان‌بندی رسدکننده — نوبت‌های تهران ۱۰/۱۴/۲۰."""
from __future__ import annotations

import threading
import time

from flask import Flask

from app.reach.config import REACH_HOURS, reach_scheduler_enabled


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
                    from app.reach.service import run_reach_slot

                    # فقط خریدار — همکار از sales_coach جداگانه زمان‌بندی شده
                    # تا دوبار SMS همکار نرود: run_buyer فقط
                    from app.reach.service import run_buyer_reach_slot
                    from app.supervisor.funnel import refresh_funnels_for_reach

                    refresh_funnels_for_reach()
                    run_buyer_reach_slot(slot_hour=h, dry_run=False)
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
    if not reach_scheduler_enabled():
        app.logger.info("Reach scheduler off (VINOR_REACH_SCHEDULER=0 or VINOR_REACH_ENABLED=0)")
        return
    threading.Thread(
        target=_loop,
        args=(app,),
        daemon=True,
        name="vinor-reach",
    ).start()
    app.logger.info(
        "Reach follow-up scheduler started (Tehran hours %s — buyer SMS/FCM from funnel signals)",
        list(REACH_HOURS),
    )
