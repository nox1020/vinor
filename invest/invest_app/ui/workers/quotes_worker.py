"""Fetch live USDT/gold quotes off the UI thread."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from invest_app.services.fx_service import FxService
from invest_app.services.market_service import MarketService

logger = logging.getLogger(__name__)


def _fetch_quotes(
    *,
    live_enabled: bool,
    usdt_enabled: bool,
    gold_enabled: bool,
    wallex_url: str,
    persian_url: str,
) -> tuple[float | None, float | None, float | None, list[str]]:
    usdt = gold = gold_change = None
    errors: list[str] = []
    fx = FxService(markets_url=wallex_url)
    market = MarketService(api_url=persian_url)
    fx.enabled = live_enabled and usdt_enabled
    market.enabled = live_enabled and gold_enabled

    def _usdt() -> float | None:
        return fx.get_usdt_tmn(force=True)

    def _gold() -> float | None:
        return market.get_gold_toman(force=True)

    want_usdt = live_enabled and usdt_enabled
    want_gold = live_enabled and gold_enabled
    if want_usdt and want_gold:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_u = pool.submit(_usdt)
            fut_g = pool.submit(_gold)
            usdt = fut_u.result()
            gold = fut_g.result()
    elif want_usdt:
        usdt = _usdt()
    elif want_gold:
        gold = _gold()

    if want_usdt and usdt is None and fx.last_error:
        errors.append(f"تتر: {fx.last_error}")
    if want_gold:
        quote = market.gold
        if quote:
            gold_change = quote.change_24h
        if gold is None and market.last_error:
            errors.append(f"طلا: {market.last_error}")
    return usdt, gold, gold_change, errors


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
        usdt = gold = gold_change = None
        try:
            usdt, gold, gold_change, _ = _fetch_quotes(
                live_enabled=self._live,
                usdt_enabled=self._usdt,
                gold_enabled=self._gold,
                wallex_url=self._wallex_url,
                persian_url=self._persian_url,
            )
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
            usdt, gold, _, errors = _fetch_quotes(
                live_enabled=self._live,
                usdt_enabled=self._usdt,
                gold_enabled=self._gold,
                wallex_url=self._wallex_url,
                persian_url=self._persian_url,
            )
        except Exception as exc:  # noqa: BLE001 — surface to UI
            errors.append(str(exc))
        finally:
            self.finished.emit({"usdt": usdt, "gold": gold, "errors": errors})
