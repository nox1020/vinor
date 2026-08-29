"""Fetch live USDT/gold quotes off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from app.services.fx_service import FxService
from app.services.market_service import MarketService

logger = logging.getLogger(__name__)


class LiveQuotesWorker(QObject):
    """Network-only worker; uses temporary FX/Market instances (not shared with UI)."""

    finished = Signal(object)

    def __init__(
        self,
        *,
        live_enabled: bool,
        usdt_enabled: bool,
        gold_enabled: bool,
        wallex_url: str,
        persian_url: str,
    ) -> None:
        super().__init__()
        self._live = live_enabled
        self._usdt = usdt_enabled
        self._gold = gold_enabled
        self._wallex_url = wallex_url
        self._persian_url = persian_url

    def run(self) -> None:
        usdt = gold = None
        gold_change = None
        try:
            fx = FxService(markets_url=self._wallex_url)
            market = MarketService(api_url=self._persian_url)
            fx.enabled = self._live and self._usdt
            market.enabled = self._live and self._gold
            if self._live and self._usdt:
                usdt = fx.get_usdt_tmn(force=True)
            if self._live and self._gold:
                gold = market.get_gold_toman(force=True)
                quote = market.gold
                if quote:
                    gold_change = quote.change_24h
        except Exception:
            logger.exception("Live quote fetch failed")
        finally:
            self.finished.emit(
                {"usdt": usdt, "gold": gold, "gold_change_24h": gold_change}
            )


class QuotesTestWorker(QObject):
    """Test API connectivity without touching AppContext or SQLite."""

    finished = Signal(object)

    def __init__(
        self,
        *,
        live_enabled: bool,
        usdt_enabled: bool,
        gold_enabled: bool,
        wallex_url: str,
        persian_url: str,
    ) -> None:
        super().__init__()
        self._live = live_enabled
        self._usdt = usdt_enabled
        self._gold = gold_enabled
        self._wallex_url = wallex_url
        self._persian_url = persian_url

    def run(self) -> None:
        usdt = gold = None
        errors: list[str] = []
        try:
            fx = FxService(markets_url=self._wallex_url)
            market = MarketService(api_url=self._persian_url)
            fx.enabled = self._live and self._usdt
            market.enabled = self._live and self._gold
            if self._live and self._usdt:
                usdt = fx.get_usdt_tmn(force=True)
                if usdt is None and fx.last_error:
                    errors.append(f"تتر: {fx.last_error}")
            if self._live and self._gold:
                gold = market.get_gold_toman(force=True)
                if gold is None and market.last_error:
                    errors.append(f"طلا: {market.last_error}")
        except Exception as exc:  # noqa: BLE001 — surface to UI
            errors.append(str(exc))
        finally:
            self.finished.emit({"usdt": usdt, "gold": gold, "errors": errors})
