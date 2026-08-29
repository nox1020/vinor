"""Live market quotes from PersianToolbox (gold, etc.)."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass

from app.config import DEFAULT_PERSIANTOOLBOX_URL

logger = logging.getLogger(__name__)

DEFAULT_CACHE_SECONDS = 60


@dataclass
class GoldQuote:
    """Gold price per gram in Tomans."""

    price_toman: float
    change_24h: float | None
    source: str
    fetched_at: float

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


class MarketService:
    """Fetch gold (and related) quotes from PersianToolbox."""

    def __init__(
        self,
        *,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        api_url: str | None = None,
    ) -> None:
        self._cache_seconds = cache_seconds
        self.api_url = api_url or DEFAULT_PERSIANTOOLBOX_URL
        self._gold: GoldQuote | None = None
        self._last_error: str | None = None
        self._raw: dict | None = None
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
    def gold(self) -> GoldQuote | None:
        return self._gold

    @property
    def gold_toman_per_gram(self) -> float | None:
        return self._gold.price_toman if self._gold else None

    def seed_gold(self, price_toman: float, *, source: str = "saved") -> None:
        if price_toman > 0:
            self._gold = GoldQuote(
                price_toman=price_toman,
                change_24h=None,
                source=source,
                fetched_at=0.0,
            )

    def apply_fetched_gold(
        self,
        price_toman: float,
        *,
        change_24h: float | None = None,
        source: str = "persiantoolbox",
    ) -> None:
        """Apply gold quote fetched off-thread (call from UI thread only)."""
        if price_toman > 0:
            self._gold = GoldQuote(
                price_toman=price_toman,
                change_24h=change_24h,
                source=source,
                fetched_at=time.time(),
            )
            self._last_error = None

    def get_gold_toman(self, *, force: bool = False) -> float | None:
        if not self.enabled:
            return self._gold.price_toman if self._gold else None
        if (
            not force
            and self._gold is not None
            and self._gold.fetched_at > 0
            and self._gold.age_seconds < self._cache_seconds
        ):
            return self._gold.price_toman

        quote = self._fetch_gold()
        if quote is not None:
            self._gold = quote
            self._last_error = None
            return quote.price_toman

        if self._gold is not None:
            return self._gold.price_toman
        return None

    def refresh(self, *, force: bool = True) -> dict[str, float | None]:
        """Refresh quotes used by the app."""
        return {"gold_toman": self.get_gold_toman(force=force)}

    def _fetch_gold(self) -> GoldQuote | None:
        try:
            data = self._http_get_json(self.api_url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("PersianToolbox fetch failed: %s", exc)
            self._last_error = str(exc)
            return None

        if not data.get("ok", True):
            self._last_error = "PersianToolbox ok=false"
            return None

        payload = data.get("data") or data
        self._raw = payload if isinstance(payload, dict) else None
        gold = (payload or {}).get("gold") or {}
        raw_price = gold.get("pricePerGram")
        if raw_price is None:
            self._last_error = "gold.pricePerGram missing"
            return None

        units = (payload or {}).get("units") or {}
        unit = str(units.get("goldPricePerGram", "IRR")).upper()
        price = float(raw_price)
        # API documents gold in IRR; app stores toman (1 toman = 10 rial).
        if unit in ("IRR", "RIAL", "RLS"):
            price_toman = price / 10.0
        else:
            price_toman = price

        change = gold.get("change24h")
        return GoldQuote(
            price_toman=price_toman,
            change_24h=float(change) if change is not None else None,
            source="persiantoolbox",
            fetched_at=time.time(),
        )

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
