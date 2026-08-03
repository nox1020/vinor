"""Lazy tick مشترک — اجرای نوبت‌های پس‌زمینه روی ترافیک وب (بدون cron / بدون thread ماندگار).

روی Passenger وقتی VINOR_*_SCHEDULER=0 است، به‌جای loop پس‌زمینه از این استفاده می‌شود.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from flask import Flask

_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def install_lazy_tick(
    app: Flask,
    *,
    name: str,
    should_run: Callable[[], bool],
    run: Callable[[], Any],
    min_interval_sec: float = 90.0,
) -> None:
    """ثبت یک before_request سبک؛ کار سنگین در daemon کوتاه اجرا می‌شود."""
    key = str(name or "").strip() or "anon"
    app_id = id(app)
    with _REGISTRY_LOCK:
        prev = _REGISTRY.get(key)
        if prev is not None and prev.get("app_id") == app_id:
            return
        state = {"last_attempt": 0.0, "lock": threading.Lock(), "app_id": app_id}
        _REGISTRY[key] = state

    if not callable(getattr(app, "before_request", None)):
        try:
            app.logger.info("Lazy-tick skipped (no before_request) name=%s", key)
        except Exception:
            pass
        return

    interval = max(15.0, float(min_interval_sec or 90.0))

    @app.before_request
    def _lazy_tick_hook():  # type: ignore[misc]
        try:
            now_ts = time.time()
            if now_ts - float(state["last_attempt"]) < interval:
                return None
            lock: threading.Lock = state["lock"]
            if not lock.acquire(blocking=False):
                return None
            try:
                if now_ts - float(state["last_attempt"]) < interval:
                    return None
                if not should_run():
                    return None
                state["last_attempt"] = now_ts

                def _worker() -> None:
                    try:
                        with app.app_context():
                            run()
                    except Exception:
                        try:
                            app.logger.exception("Lazy tick failed name=%s", key)
                        except Exception:
                            pass

                threading.Thread(
                    target=_worker,
                    daemon=True,
                    name=f"vinor-lazy-{key}",
                ).start()
            finally:
                lock.release()
        except Exception:
            return None
        return None

    # نام یکتا برای تست/دیباگ
    _lazy_tick_hook.__name__ = f"_lazy_tick_{key.replace('-', '_')}"

    try:
        app.logger.info("Auto lazy-tick ON name=%s interval=%ss (no cron required)", key, int(interval))
    except Exception:
        pass
