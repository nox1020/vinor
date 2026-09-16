"""Fetch + cache full market index (essentials, Wallex TMN book, inflation)."""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from invest_app.config import (
    DEFAULT_PERSIANTOOLBOX_URL,
    DEFAULT_WALLEX_MARKETS_URL,
)
from invest_app.services.market_index_store import MarketIndexStore

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 55.0
INFLATION_TTL_SECONDS = 6 * 3600
COIN_GOLD_GRAMS = 8.133
HF_DATASET = "Farmaanaa/iran_cpi_and_inflation_multisource"
HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
HTTP_TIMEOUT_MARKET = 8.0
HTTP_TIMEOUT_WALLEX = 8.0
HTTP_TIMEOUT_INFLATION = 12.0
REFRESH_WAIT_SECONDS = 18.0

_HTTP_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invest-mkt")
atexit.register(lambda: _HTTP_POOL.shutdown(wait=False, cancel_futures=True))


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_map(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return None


def _http_json(url: str, *, timeout: float = HTTP_TIMEOUT_MARKET) -> dict[str, Any] | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "VinorInvest/1.0 (+market-index)",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return _as_map(data)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Market index fetch failed (%s): %s", url, exc)
        return None


def _quote(
    *,
    id_: str,
    name: str,
    symbol: str,
    unit: str = "toman",
    price: float | None = None,
    change24h: float | None = None,
    quote_volume_24h: float | None = None,
    market_symbol: str | None = None,
    high24h: float | None = None,
    low24h: float | None = None,
    bid_price: float | None = None,
    ask_price: float | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "name": name,
        "symbol": symbol,
        "unit": unit,
        "price": price,
        "change24h": change24h,
        "quote_volume_24h": quote_volume_24h,
        "market_symbol": market_symbol,
        "high24h": high24h,
        "low24h": low24h,
        "bid_price": bid_price,
        "ask_price": ask_price,
    }


class MarketIndexService:
    """Server-side market index orchestrator with shared persistence."""

    def __init__(
        self,
        store: MarketIndexStore,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        wallex_url: str | None = None,
        market_url: str | None = None,
    ) -> None:
        self.store = store
        self.ttl_seconds = max(15.0, float(ttl_seconds))
        self.wallex_url = (wallex_url or DEFAULT_WALLEX_MARKETS_URL).strip()
        self.market_url = (market_url or DEFAULT_PERSIANTOOLBOX_URL).strip()
        self._last_error: str | None = None
        self._refresh_event: threading.Event | None = None
        self._refresh_guard = threading.Lock()
        self._inflation_event: threading.Event | None = None
        self._inflation_guard = threading.Lock()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_bundle(self, *, force: bool = False) -> dict[str, Any]:
        """Return latest bundle. Stale cache is served immediately; refresh is single-flight."""
        cached, updated_at = self.store.load_latest()
        age = self.store.age_seconds(updated_at)
        fresh = (
            cached is not None
            and age is not None
            and age < self.ttl_seconds
        )

        if force or cached is None:
            self._kick_market_refresh(wait=True)
            cached, updated_at = self.store.load_latest()
            age = self.store.age_seconds(updated_at)
        elif not fresh:
            self._kick_market_refresh(wait=False)

        inflation = self._inflation_nonblocking(force=force)
        if cached is None:
            return {
                "essentials": [],
                "wallex_markets": [],
                "inflation": inflation,
                "updated_at": updated_at,
                "stale": True,
                "error": self._last_error or "هنوز داده‌ای ذخیره نشده است.",
            }

        out = dict(cached)
        out["inflation"] = inflation
        out["updated_at"] = updated_at or out.get("updated_at")
        out["stale"] = not (
            age is not None and age < self.ttl_seconds
        )
        if self._last_error:
            out["warning"] = self._last_error
        return out

    def ingest_client_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Accept a full client snapshot and persist it (fallback path)."""
        essentials = payload.get("essentials") or []
        wallex = payload.get("wallex_markets") or []
        if not isinstance(essentials, list):
            essentials = []
        if not isinstance(wallex, list):
            wallex = []
        bundle = {
            "essentials": essentials,
            "wallex_markets": wallex,
            "source": "client",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.store.save_latest(bundle)
        inflation = payload.get("inflation")
        if isinstance(inflation, dict) and inflation:
            self.store.save_inflation(inflation)
        return self.get_bundle(force=False)

    def history(self, *, hours: float = 24) -> list[dict[str, Any]]:
        return self.store.load_ticks(hours=hours)

    def _kick_market_refresh(self, *, wait: bool) -> None:
        with self._refresh_guard:
            event = self._refresh_event
            if event is None or event.is_set():
                event = threading.Event()
                self._refresh_event = event
                threading.Thread(
                    target=self._market_refresh_worker,
                    args=(event,),
                    name="invest-mkt-refresh",
                    daemon=True,
                ).start()
        if wait:
            event.wait(timeout=REFRESH_WAIT_SECONDS)

    def _market_refresh_worker(self, event: threading.Event) -> None:
        try:
            self._refresh_markets()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Market index refresh failed: %s", exc)
            self._last_error = str(exc)
        finally:
            event.set()

    def _kick_inflation_refresh(self, *, wait: bool) -> None:
        with self._inflation_guard:
            event = self._inflation_event
            if event is None or event.is_set():
                event = threading.Event()
                self._inflation_event = event
                threading.Thread(
                    target=self._inflation_refresh_worker,
                    args=(event,),
                    name="invest-infl-refresh",
                    daemon=True,
                ).start()
        if wait:
            event.wait(timeout=HTTP_TIMEOUT_INFLATION + 2.0)

    def _inflation_refresh_worker(self, event: threading.Event) -> None:
        try:
            snap = self._fetch_inflation()
            if snap:
                self.store.save_inflation(snap)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inflation refresh failed: %s", exc)
        finally:
            event.set()

    def _inflation_nonblocking(self, *, force: bool = False) -> dict[str, Any] | None:
        cached, updated_at = self.store.load_inflation()
        age = self.store.age_seconds(updated_at)
        fresh = (
            cached is not None
            and age is not None
            and age < INFLATION_TTL_SECONDS
        )
        if cached is None:
            self._kick_inflation_refresh(wait=True)
            cached, _ = self.store.load_inflation()
        elif force or not fresh:
            self._kick_inflation_refresh(wait=False)
        return cached

    def _refresh_markets(self) -> dict[str, Any] | None:
        market_fut = _HTTP_POOL.submit(
            _http_json, self.market_url, timeout=HTTP_TIMEOUT_MARKET
        )
        wallex_fut = _HTTP_POOL.submit(
            _http_json, self.wallex_url, timeout=HTTP_TIMEOUT_WALLEX
        )
        try:
            market_raw = market_fut.result(timeout=HTTP_TIMEOUT_MARKET + 1.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PersianToolbox wait failed: %s", exc)
            market_raw = None
        try:
            wallex = wallex_fut.result(timeout=HTTP_TIMEOUT_WALLEX + 1.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Wallex wait failed: %s", exc)
            wallex = None
        market = None
        if market_raw:
            nested = _as_map(market_raw.get("data"))
            market = nested or market_raw
        essentials = self._build_essentials(market, wallex)
        wallex_markets = self._parse_wallex_tmn(wallex)
        has_price = any(_num(q.get("price")) for q in essentials) or any(
            _num(q.get("price")) for q in wallex_markets
        )
        if not has_price:
            self._last_error = "دریافت قیمت‌های شاخص ناموفق بود."
            return None
        updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bundle = {
            "essentials": essentials,
            "wallex_markets": wallex_markets,
            "source": "server",
            "updated_at": updated_at,
        }
        self.store.save_latest(bundle)
        # Keep USDT/gold settings in sync for portfolio when available.
        self._last_error = None
        return bundle

    def _symbols_map(self, wallex: dict[str, Any] | None) -> dict[str, Any] | None:
        if not wallex:
            return None
        result = _as_map(wallex.get("result"))
        if not result:
            return None
        return _as_map(result.get("symbols"))

    def _find_wallex_quote(
        self, wallex: dict[str, Any] | None, market_symbol: str
    ) -> dict[str, Any] | None:
        symbols = self._symbols_map(wallex)
        if not symbols:
            return None
        raw = _as_map(symbols.get(market_symbol))
        if not raw:
            return None
        stats = _as_map(raw.get("stats"))
        if not stats:
            return None
        price = _num(stats.get("lastPrice")) or _num(stats.get("bidPrice"))
        if price is None or price <= 0:
            return None
        return _quote(
            id_=market_symbol.lower(),
            name=str(raw.get("faBaseAsset") or market_symbol),
            symbol=str(raw.get("baseAsset") or market_symbol),
            price=price,
            change24h=_num(stats.get("24h_ch")),
            market_symbol=market_symbol,
            high24h=_num(stats.get("24h_highPrice")) or _num(stats.get("24h_high")),
            low24h=_num(stats.get("24h_lowPrice")) or _num(stats.get("24h_low")),
            bid_price=_num(stats.get("bidPrice")),
            ask_price=_num(stats.get("askPrice")),
            quote_volume_24h=_num(stats.get("24h_quoteVolume"))
            or _num(stats.get("24h_tmnVolume")),
        )

    def _usdt_from_wallex(self, wallex: dict[str, Any] | None) -> float | None:
        for key in ("USDTTMN", "USDTTOM", "USDTIRT"):
            q = self._find_wallex_quote(wallex, key)
            if q and q.get("price"):
                return float(q["price"])
        return None

    def _build_essentials(
        self,
        market: dict[str, Any] | None,
        wallex: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        usdt = self._usdt_from_wallex(wallex)
        currencies = _as_map((market or {}).get("currencies")) or {}
        usd_irr = _num(_as_map(currencies.get("IRR") or {}).get("rate"))
        usd_toman = (usd_irr / 10.0) if usd_irr and usd_irr > 0 else None

        def fx_toman(code: str) -> float | None:
            if usd_toman is None:
                return None
            if code == "USD":
                return usd_toman
            rate = _num(_as_map(currencies.get(code) or {}).get("rate"))
            if rate is None or rate <= 0:
                return None
            return usd_toman / rate

        def fx_change(code: str) -> float | None:
            return _num(_as_map(currencies.get(code) or {}).get("change24h"))

        gold = _as_map((market or {}).get("gold")) or {}
        gold_irr = _num(gold.get("pricePerGram"))
        gold_toman = (gold_irr / 10.0) if gold_irr and gold_irr > 0 else None
        gold_change = _num(gold.get("change24h"))

        crypto = _as_map((market or {}).get("crypto")) or {}
        btc_usd = _num(_as_map(crypto.get("BTC") or {}).get("priceUSD"))
        eth_usd = _num(_as_map(crypto.get("ETH") or {}).get("priceUSD"))

        w_usdt = self._find_wallex_quote(wallex, "USDTTMN")
        w_btc = self._find_wallex_quote(wallex, "BTCTMN")
        w_eth = self._find_wallex_quote(wallex, "ETHTMN")

        coin_price = (gold_toman * COIN_GOLD_GRAMS) if gold_toman else None

        return [
            _quote(
                id_="usdt",
                name="تتر",
                symbol="USDT",
                price=usdt,
                change24h=(w_usdt or {}).get("change24h"),
                market_symbol="USDTTMN",
                high24h=(w_usdt or {}).get("high24h"),
                low24h=(w_usdt or {}).get("low24h"),
                bid_price=(w_usdt or {}).get("bid_price"),
                ask_price=(w_usdt or {}).get("ask_price"),
                quote_volume_24h=(w_usdt or {}).get("quote_volume_24h"),
            ),
            _quote(
                id_="usd",
                name="دلار آمریکا",
                symbol="USD",
                price=fx_toman("USD"),
                change24h=fx_change("USD"),
            ),
            _quote(
                id_="eur",
                name="یورو",
                symbol="EUR",
                price=fx_toman("EUR"),
                change24h=fx_change("EUR"),
            ),
            _quote(
                id_="gbp",
                name="پوند",
                symbol="GBP",
                price=fx_toman("GBP"),
                change24h=fx_change("GBP"),
            ),
            _quote(
                id_="aed",
                name="درهم امارات",
                symbol="AED",
                price=fx_toman("AED"),
                change24h=fx_change("AED"),
            ),
            _quote(
                id_="try",
                name="لیر ترکیه",
                symbol="TRY",
                price=fx_toman("TRY"),
                change24h=fx_change("TRY"),
            ),
            _quote(
                id_="gold",
                name="طلای ۱۸ عیار",
                symbol="GOLD",
                unit="toman_per_gram",
                price=gold_toman,
                change24h=gold_change,
            ),
            _quote(
                id_="coin",
                name="سکه تمام (تقریبی)",
                symbol="COIN",
                price=coin_price,
                change24h=gold_change,
            ),
            _quote(
                id_="btc",
                name="بیت‌کوین",
                symbol="BTC",
                unit="toman" if w_btc and w_btc.get("price") else "usd",
                price=(w_btc or {}).get("price")
                or (btc_usd if btc_usd else None),
                change24h=(w_btc or {}).get("change24h")
                or _num(_as_map(crypto.get("BTC") or {}).get("change24h")),
                market_symbol="BTCTMN" if w_btc and w_btc.get("price") else None,
                high24h=(w_btc or {}).get("high24h"),
                low24h=(w_btc or {}).get("low24h"),
                bid_price=(w_btc or {}).get("bid_price"),
                ask_price=(w_btc or {}).get("ask_price"),
                quote_volume_24h=(w_btc or {}).get("quote_volume_24h"),
            ),
            _quote(
                id_="eth",
                name="اتریوم",
                symbol="ETH",
                unit="toman" if w_eth and w_eth.get("price") else "usd",
                price=(w_eth or {}).get("price")
                or (eth_usd if eth_usd else None),
                change24h=(w_eth or {}).get("change24h")
                or _num(_as_map(crypto.get("ETH") or {}).get("change24h")),
                market_symbol="ETHTMN" if w_eth and w_eth.get("price") else None,
                high24h=(w_eth or {}).get("high24h"),
                low24h=(w_eth or {}).get("low24h"),
                bid_price=(w_eth or {}).get("bid_price"),
                ask_price=(w_eth or {}).get("ask_price"),
                quote_volume_24h=(w_eth or {}).get("quote_volume_24h"),
            ),
        ]

    def _parse_wallex_tmn(self, wallex: dict[str, Any] | None) -> list[dict[str, Any]]:
        symbols = self._symbols_map(wallex)
        if not symbols:
            return []
        items: list[dict[str, Any]] = []
        for key, value in symbols.items():
            raw = _as_map(value)
            if not raw:
                continue
            if str(raw.get("quoteAsset") or "").upper() != "TMN":
                continue
            stats = _as_map(raw.get("stats"))
            if not stats:
                continue
            price = (
                _num(stats.get("lastPrice"))
                or _num(stats.get("bidPrice"))
                or _num(stats.get("askPrice"))
            )
            if price is None or price <= 0:
                continue
            base = str(raw.get("baseAsset") or key).upper()
            fa = str(raw.get("faBaseAsset") or raw.get("faName") or base).strip()
            volume = _num(stats.get("24h_quoteVolume")) or _num(
                stats.get("24h_tmnVolume")
            ) or 0.0
            items.append(
                _quote(
                    id_=f"wallex_{key}",
                    name=fa or base,
                    symbol=base,
                    price=price,
                    change24h=_num(stats.get("24h_ch")),
                    quote_volume_24h=volume,
                    market_symbol=str(key),
                    high24h=_num(stats.get("24h_highPrice"))
                    or _num(stats.get("24h_high")),
                    low24h=_num(stats.get("24h_lowPrice")) or _num(stats.get("24h_low")),
                    bid_price=_num(stats.get("bidPrice")),
                    ask_price=_num(stats.get("askPrice")),
                )
            )
        items.sort(
            key=lambda q: (
                -(float(q.get("quote_volume_24h") or 0)),
                str(q.get("symbol") or ""),
            )
        )
        return items

    def _fetch_inflation(self, history_months: int = 12) -> dict[str, Any] | None:
        probe = _http_json(
            f"{HF_ROWS_URL}?dataset={urllib.parse.quote(HF_DATASET)}"
            f"&config=mart&split=train&offset=0&length=1",
            timeout=HTTP_TIMEOUT_INFLATION,
        )
        if not probe:
            return None
        total = int(probe.get("num_rows_total") or 0)
        if total <= 0:
            return None
        need = max(12, min(48, history_months + 6))
        offset = max(0, total - need)
        page = _http_json(
            f"{HF_ROWS_URL}?dataset={urllib.parse.quote(HF_DATASET)}"
            f"&config=mart&split=train&offset={offset}&length={need}",
            timeout=HTTP_TIMEOUT_INFLATION,
        )
        if not page:
            return None
        sci: list[dict[str, Any]] = []
        for item in page.get("rows") or []:
            if not isinstance(item, dict):
                continue
            row = _as_map(item.get("row")) or {}
            if row.get("source_id") != "sci" or row.get("freq") != "M":
                continue
            yoy = _num(row.get("inflation_yoy"))
            mom = _num(row.get("inflation_mom"))
            annual = _num(row.get("inflation_annual"))
            cpi = _num(row.get("cpi_index"))
            if None in (yoy, mom, annual, cpi):
                continue
            sci.append(
                {
                    "period": str(row.get("period") or ""),
                    "year": int(row.get("year") or 0),
                    "month": int(round(float(row.get("month") or 0))),
                    "cpi_index": cpi,
                    "point_to_point_pct": yoy,
                    "monthly_pct": mom,
                    "annual_pct": annual,
                }
            )
        if not sci:
            return None
        sci.sort(key=lambda r: (r["year"], r["month"]))
        latest = sci[-1]
        hist = sci[-history_months:] if len(sci) > history_months else sci
        return {
            "period": latest["period"],
            "year": latest["year"],
            "month": latest["month"],
            "cpi_index": latest["cpi_index"],
            "point_to_point_pct": latest["point_to_point_pct"],
            "monthly_pct": latest["monthly_pct"],
            "annual_pct": latest["annual_pct"],
            "base_year": 1400,
            "source_label": "مرکز آمار ایران (SCI) — پایه ۱۴۰۰",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "history": hist,
        }
