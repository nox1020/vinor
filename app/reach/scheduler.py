"""زمان‌بندی رسدکننده — نوبت‌های تهران ۱۰/۱۴/۲۰.

روی PC: thread پس‌زمینه (پیش‌فرض).
روی Passenger/LiteSpeed: VINOR_REACH_SCHEDULER=0 → بدون thread ماندگار؛
  lazy tick روی درخواست‌های وب نوبت معوق را خودکار اجرا می‌کند (بدون نیاز به cron).
"""
from __future__ import annotations

import os
import threading
import time

from flask import Flask

from app.reach.config import reach_enabled, reach_hours
from app.utils.dates import tehran_now

_lazy_lock = threading.Lock()
_lazy_last_attempt = 0.0
_LAZY_MIN_INTERVAL_SEC = 90


def run_listing_quiet_nudge() -> None:
    """همان نوبت رسدکننده، آگهی ساکت ۷۲ساعته را هم یک‌بار بررسی می‌کند."""
    try:
        from app.listings.quiet_nudge import maybe_send_quiet_listing_nudges

        maybe_send_quiet_listing_nudges()
    except Exception:
        try:
            from flask import current_app

            current_app.logger.exception("listing quiet nudge failed")
        except Exception:
            pass


def _loop(app: Flask) -> None:
    last_slot: int | None = None
    while True:
        try:
            with app.app_context():
                try:
                    from app.reach.service import _active_slot_hour, maybe_run_reach_followup

                    due = _active_slot_hour()
                    if due is not None and due != last_slot:
                        maybe_run_reach_followup()
                        last_slot = due
                    if due is None:
                        last_slot = None
                except Exception:
                    app.logger.exception("Reach scheduler tick failed")
                run_listing_quiet_nudge()
        except Exception:
            try:
                app.logger.exception("Reach scheduler tick failed")
            except Exception:
                pass
        time.sleep(600)


def _install_lazy_tick(app: Flask) -> None:
    """خودکار روی ترافیک وب — نوبت معوق را بدون cron و بدون دستور دستی اجرا می‌کند."""

    @app.before_request
    def _reach_lazy_tick():  # type: ignore[misc]
        global _lazy_last_attempt
        try:
            if not reach_enabled():
                return None
            from app.reach.service import (
                _active_slot_hour,
                _slot_already_done,
                maybe_run_reach_followup,
            )

            due = _active_slot_hour()
            if due is None:
                return None
            now_ts = time.time()
            if now_ts - _lazy_last_attempt < _LAZY_MIN_INTERVAL_SEC:
                return None
            if not _lazy_lock.acquire(blocking=False):
                return None
            try:
                if now_ts - _lazy_last_attempt < _LAZY_MIN_INTERVAL_SEC:
                    return None
                _lazy_last_attempt = now_ts
                if _slot_already_done(due):
                    return None

                def _worker() -> None:
                    try:
                        with app.app_context():
                            try:
                                maybe_run_reach_followup()
                            except Exception:
                                app.logger.exception("Reach lazy tick failed")
                            run_listing_quiet_nudge()
                    except Exception:
                        try:
                            app.logger.exception("Reach lazy tick failed")
                        except Exception:
                            pass

                threading.Thread(
                    target=_worker,
                    daemon=True,
                    name="vinor-reach-lazy",
                ).start()
            finally:
                _lazy_lock.release()
        except Exception:
            return None
        return None

    app.logger.info(
        "Reach auto lazy-tick ON (Tehran slots %s — no cron required)",
        list(reach_hours()),
    )


def schedule_reach(app: Flask) -> None:
    """PC: thread. هاست اشتراکی: lazy tick خودکار (بدون cron)."""
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
        _install_lazy_tick(app)
        return
    threading.Thread(
        target=_loop,
        args=(app,),
        daemon=True,
        name="vinor-reach",
    ).start()
    app.logger.info(
        "Reach follow-up scheduler started (Tehran hours %s - buyer SMS/FCM from funnel signals)",
        list(reach_hours()),
    )
