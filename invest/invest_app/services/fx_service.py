"""Live FX rates (USDT/TMN) from Wallex — Iran market."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WALLEX_MARKETS_URL = "https://api.wallex.ir/v1/markets"
WALLEX_OTC_URL = "https://api.wallex.ir/v1/account/otc/price?symbol=USDTTMN"
WALLEX_TRADES_URL = "https://api.wallex.ir/v1/trades?symbol=USDTTMN"
DEFAULT_CACHE_SECONDS = 60


@dataclass
class UsdtRate:
    """USDT price in Tomans (TMN)."""

    price: float
    source: str
    fetched_at: float

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


class FxService:
    """Fetch and cache live USDT→Toman rate from Wallex."""

    def __init__(
        self,
        *,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        markets_url: str | None = None,
    ) -> None:
        self._cache_seconds = cache_seconds
        self.markets_url = markets_url or WALLEX_MARKETS_URL
        self._cached: UsdtRate | None = None
        self._last_error: str | None = None
        self.enabled: bool = True

    @property
    def cache_seconds(self) -> float:
        return self._cache_seconds

    @cache_seconds.setter
    def cache_seconds(self, value: float) -> None:
        self._cache_seconds = max(1.0, float(value))

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def usdt_tmn(self) -> float | None:
        """Cached rate if still fresh; otherwise None until refreshed."""
        if self._cached is None:
            return None
        return self._cached.price

    @property
    def cached(self) -> UsdtRate | None:
        return self._cached

    def seed(self, price: float, *, source: str = "cache") -> None:
        """Seed from a previously saved rate (offline fallback)."""
        if price > 0:
            self._cached = UsdtRate(price=price, source=source, fetched_at=0.0)

    def apply_fetched_rate(self, price: float, *, source: str = "wallex") -> None:
        """Apply a rate fetched off-thread (call from UI thread only)."""
        if price > 0:
            self._cached = UsdtRate(price=price, source=source, fetched_at=time.time())
            self._last_error = None

    def get_usdt_tmn(self, *, force: bool = False) -> float | None:
        """Return rate, refreshing from network when cache is stale."""
        if not self.enabled:
            return self._cached.price if self._cached else None
        if (
            not force
            and self._cached is not None
            and self._cached.age_seconds < self._cache_seconds
            and self._cached.fetched_at > 0
        ):
            return self._cached.price

        rate = self._fetch_live()
        if rate is not None:
            self._cached = rate
            self._last_error = None
            return rate.price

        if self._cached is not None:
            return self._cached.price
        return None

    def _fetch_live(self) -> UsdtRate | None:
        # Prefer public markets (OTC price needs auth).
        for fetcher in (self._from_markets, self._from_trades, self._from_otc):
            try:
                rate = fetcher()
                if rate is not None and rate.price > 0:
                    return rate
            except Exception as exc:  # noqa: BLE001 — network may fail offline
                logger.debug("Wallex fetch failed via %s: %s", fetcher.__name__, exc)
                self._last_error = str(exc)
        return None

    def _http_get_json(self, url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "V+/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _from_markets(self) -> UsdtRate | None:
        data = self._http_get_json(self.markets_url)
        # Support both full markets payload and a nested result.
        symbols = (
            data.get("result", {}).get("symbols")
            if isinstance(data.get("result"), dict)
            else None
        )
        if symbols is None and isinstance(data.get("symbols"), dict):
            symbols = data["symbols"]
        if not isinstance(symbols, dict):
            return None
        stats = symbols.get("USDTTMN", {}).get("stats", {})
        last = stats.get("lastPrice")
        if last is None:
            bid = stats.get("bidPrice")
            ask = stats.get("askPrice")
            if bid is not None and ask is not None:
                price = (float(bid) + float(ask)) / 2.0
                return UsdtRate(price=price, source="wallex_markets_mid", fetched_at=time.time())
            return None
        return UsdtRate(
            price=float(last),
            source="wallex_markets",
            fetched_at=time.time(),
        )

    def _from_trades(self) -> UsdtRate | None:
        data = self._http_get_json(WALLEX_TRADES_URL)
        trades = data.get("result", {}).get("latestTrades") or []
        if not trades:
            return None
        return UsdtRate(
            price=float(trades[0]["price"]),
            source="wallex_trades",
            fetched_at=time.time(),
        )

    def _from_otc(self) -> UsdtRate | None:
        """User-suggested OTC endpoint (requires API key → usually 401)."""
        try:
            data = self._http_get_json(WALLEX_OTC_URL)
        except urllib.error.HTTPError as exc:
            self._last_error = f"OTC {exc.code}"
            return None
        result = data.get("result") or data
        for key in ("price", "Price", "amount", "value"):
            if key in result:
                return UsdtRate(
                    price=float(result[key]),
                    source="wallex_otc",
                    fetched_at=time.time(),
                )
        return None
