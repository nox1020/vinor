from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING

from app.optimization.config import (
    load_optimization_config,
    optimization_enabled,
    optimization_scheduler_enabled,
)

if TYPE_CHECKING:
    from flask import Flask

_STARTED = False
_LOCK = threading.Lock()


def _scheduler_loop(app: "Flask") -> None:
    cfg = load_optimization_config()
    interval = max(300, int(cfg.interval_seconds or 3600))
    # Stagger first run so it never races request startup path
    time.sleep(min(60, interval // 10 or 30))
    while True:
        try:
            with app.app_context():
                from app.optimization.service import run_optimization

                run_optimization()
        except Exception:
            try:
                app.logger.exception("Optimization scheduler tick failed")
            except Exception:
                pass
        time.sleep(interval)


def _stamp_path() -> str:
    try:
        from app.utils.storage import data_dir

        return os.path.join(data_dir(), "optimization_lazy_tick.stamp")
    except Exception:
        return os.path.join(os.getcwd(), "instance", "data", "optimization_lazy_tick.stamp")


def _optimization_due() -> bool:
    if not optimization_enabled():
        return False
    cfg = load_optimization_config()
    interval = max(300, int(cfg.interval_seconds or 3600))
    path = _stamp_path()
    try:
        if not os.path.isfile(path):
            return True
        return (time.time() - os.path.getmtime(path)) >= interval
    except Exception:
        return True


def _touch_stamp() -> None:
    path = _stamp_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass


def _run_optimization_tick() -> None:
    from app.optimization.service import run_optimization

    run_optimization()
    _touch_stamp()


def start_optimization_scheduler(app: "Flask") -> None:
    """PC: thread. هاست اشتراکی: lazy tick خودکار (بدون cron)."""
    global _STARTED
    if not optimization_scheduler_enabled():
        from app.utils.lazy_scheduler import install_lazy_tick

        with _LOCK:
            if _STARTED:
                return
            _STARTED = True
        install_lazy_tick(
            app,
            name="optimization",
            should_run=_optimization_due,
            run=_run_optimization_tick,
            min_interval_sec=120,
        )
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    t = threading.Thread(
        target=_scheduler_loop,
        args=(app,),
        name="vinor-optimization-scheduler",
        daemon=True,
    )
    t.start()
    try:
        app.logger.info("Optimization background scheduler started")
    except Exception:
        pass
