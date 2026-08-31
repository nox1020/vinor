# -*- coding: utf-8 -*-
"""ثبت بک‌اند Invest در Flask وینور."""
from __future__ import annotations

import sys
from pathlib import Path

# invest/invest_app قبل از import سرویس‌ها
_INVEST_ROOT = Path(__file__).resolve().parent.parent
_ROOT_STR = str(_INVEST_ROOT)
if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)

from flask import Flask

from .config import invest_enabled
from .routes.api import invest_api_bp


def register_invest_backend(app: Flask) -> None:
    if not invest_enabled():
        app.logger.info("Invest backend disabled via VINOR_INVEST_ENABLED")
        return
    app.register_blueprint(invest_api_bp)
    app.logger.info("Invest API registered at /invest/api/v1")
