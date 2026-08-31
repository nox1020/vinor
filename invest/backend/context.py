# -*- coding: utf-8 -*-
"""AppContext per-user برای API — بدون PySide6."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

from flask import current_app, g

from .config import INVEST_ROOT, user_db_path

# invest/invest_app را در مسیر import قرار بده (بدون تداخل با app وینور)
_INVEST_ROOT_STR = str(INVEST_ROOT)
if _INVEST_ROOT_STR not in sys.path:
    sys.path.insert(0, _INVEST_ROOT_STR)

from invest_app.bootstrap import AppContext, bootstrap  # noqa: E402

_CTX_CACHE: Dict[str, AppContext] = {}


def create_user_context(phone: str) -> AppContext:
    db = user_db_path(phone)
    return bootstrap(db_path=db)


def get_request_context() -> AppContext:
    phone = getattr(g, "invest_phone", None) or ""
    if not phone:
        raise RuntimeError("invest_phone missing")
    if getattr(g, "invest_ctx", None) is not None:
        return g.invest_ctx
    ctx = create_user_context(phone)
    g.invest_ctx = ctx
    return ctx


def close_request_context() -> None:
    ctx = g.pop("invest_ctx", None)
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            current_app.logger.debug("invest ctx close failed", exc_info=True)
