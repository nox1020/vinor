from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from app.optimization.config import load_optimization_config, optimization_scheduler_enabled

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


def start_optimization_scheduler(app: "Flask") -> None:
    """Background thread — default ON. Never on request path. Disable with VINOR_OPTIMIZATION_SCHEDULER=0."""
    global _STARTED
    if not optimization_scheduler_enabled():
        try:
            app.logger.info(
                "Optimization scheduler off "
                "(set VINOR_OPTIMIZATION_SCHEDULER=1 to enable, or run scripts/run_optimization_engine.py)"
            )
        except Exception:
            pass
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
