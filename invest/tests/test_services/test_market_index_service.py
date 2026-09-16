"""Tests for market index refresh coalescing and stale-while-revalidate."""

from __future__ import annotations

import time
from pathlib import Path

from invest_app.services.market_index_service import MarketIndexService
from invest_app.services.market_index_store import MarketIndexStore


def _payload(price: float = 100000.0) -> dict:
    return {
        "essentials": [
            {
                "id": "usdt",
                "name": "تتر",
                "symbol": "USDT",
                "unit": "toman",
                "price": price,
            },
            {
                "id": "gold",
                "name": "طلای ۱۸ عیار",
                "symbol": "GOLD",
                "unit": "toman_per_gram",
                "price": 7000000,
            },
        ],
        "wallex_markets": [],
        "source": "test",
    }


def test_fresh_cache_skips_network(tmp_path: Path, monkeypatch) -> None:
    store = MarketIndexStore(tmp_path / "market_index.db")
    store.save_latest(_payload())
    store.save_inflation({"period": "1404-01", "cpi_index": 200.0})
    svc = MarketIndexService(store, ttl_seconds=60)
    calls: list[str] = []

    def fake_http(url: str, *, timeout: float = 8.0):
        calls.append(url)
        return None

    monkeypatch.setattr(
        "invest_app.services.market_index_service._http_json", fake_http
    )
    bundle = svc.get_bundle(force=False)
    assert bundle["essentials"][0]["price"] == 100000
    assert bundle["stale"] is False
    assert calls == []


def test_stale_cache_returns_immediately(tmp_path: Path, monkeypatch) -> None:
    store = MarketIndexStore(tmp_path / "market_index.db")
    store.save_latest(_payload(111))
    store.save_inflation({"period": "1404-01", "cpi_index": 200.0})
    svc = MarketIndexService(store, ttl_seconds=60)
    monkeypatch.setattr(svc.store, "age_seconds", lambda *_args, **_kw: 999.0)
    started = time.perf_counter()

    def fake_http(url: str, *, timeout: float = 8.0):
        time.sleep(0.4)
        return None

    monkeypatch.setattr(
        "invest_app.services.market_index_service._http_json", fake_http
    )
    bundle = svc.get_bundle(force=False)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25
    assert bundle["essentials"][0]["price"] == 111
    assert bundle["stale"] is True


def test_refresh_markets_runs_sources_in_parallel(
    tmp_path: Path, monkeypatch
) -> None:
    store = MarketIndexStore(tmp_path / "market_index.db")
    svc = MarketIndexService(store, ttl_seconds=60)
    hits: list[float] = []

    def fake_http(url: str, *, timeout: float = 8.0):
        hits.append(time.perf_counter())
        time.sleep(0.2)
        if "wallex" in url:
            return {
                "result": {
                    "symbols": {
                        "USDTTMN": {
                            "baseAsset": "USDT",
                            "quoteAsset": "TMN",
                            "faBaseAsset": "تتر",
                            "stats": {"lastPrice": "91000"},
                        }
                    }
                }
            }
        return {
            "ok": True,
            "data": {
                "gold": {"pricePerGram": 10000000, "change24h": 0.1},
                "currencies": {"IRR": {"rate": 1000000}},
            },
        }

    monkeypatch.setattr(
        "invest_app.services.market_index_service._http_json", fake_http
    )
    started = time.perf_counter()
    bundle = svc._refresh_markets()
    elapsed = time.perf_counter() - started
    assert bundle is not None
    assert elapsed < 0.35
    assert len(hits) == 2
    assert abs(hits[0] - hits[1]) < 0.15
    gold = next(q for q in bundle["essentials"] if q["id"] == "gold")
    assert gold["unit"] == "toman_per_gram"
    assert gold["symbol"] == "GOLD"
