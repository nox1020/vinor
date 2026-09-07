"""Fetch + cache full market index (essentials, Wallex TMN book, inflation)."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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

_REFRESH_LOCK = threading.Lock()


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


def _http_json(url: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
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

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_bundle(self, *, force: bool = False) -> dict[str, Any]:
        """Return latest bundle, refreshing when stale."""
        cached, updated_at = self.store.load_latest()
        age = self.store.age_seconds(updated_at)
        need_refresh = force or cached is None or age is None or age >= self.ttl_seconds

        if need_refresh:
            with _REFRESH_LOCK:
                cached2, updated2 = self.store.load_latest()
                age2 = self.store.age_seconds(updated2)
                still = force or cached2 is None or age2 is None or age2 >= self.ttl_seconds
                if still:
                    refreshed = self._refresh_markets()
                    if refreshed is not None:
                        cached, updated_at = refreshed, refreshed.get("updated_at")
                    elif cached2 is not None:
                        cached, updated_at = cached2, updated2
                else:
                    cached, updated_at = cached2, updated2

        inflation = self._get_inflation(force=force)
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
        out["stale"] = False
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

    def _refresh_markets(self) -> dict[str, Any] | None:
        market = self._fetch_persian_market()
        wallex = self._fetch_wallex()
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

    def _get_inflation(self, *, force: bool = False) -> dict[str, Any] | None:
        cached, updated_at = self.store.load_inflation()
        age = self.store.age_seconds(updated_at)
        if (
            not force
            and cached is not None
            and age is not None
            and age < INFLATION_TTL_SECONDS
        ):
            return cached
        try:
            snap = self._fetch_inflation()
            if snap:
                self.store.save_inflation(snap)
                return snap
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inflation refresh failed: %s", exc)
        return cached

    def _fetch_persian_market(self) -> dict[str, Any] | None:
        data = _http_json(self.market_url, timeout=12)
        if not data:
            return None
        nested = _as_map(data.get("data"))
        return nested or data

    def _fetch_wallex(self) -> dict[str, Any] | None:
        return _http_json(self.wallex_url, timeout=15)

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
                change24h=(w_btc or {}).get("change24h"),
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
                change24h=(w_eth or {}).get("change24h"),
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
            timeout=20,
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
            timeout=25,
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
