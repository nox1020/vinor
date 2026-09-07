"""Tests for shared market index store."""

from __future__ import annotations

import json
from pathlib import Path

from invest_app.services.market_index_store import MarketIndexStore


def test_market_index_store_roundtrip(tmp_path: Path) -> None:
    store = MarketIndexStore(tmp_path / "market_index.db")
    payload = {
        "essentials": [
            {"id": "usdt", "name": "تتر", "symbol": "USDT", "unit": "toman", "price": 100000}
        ],
        "wallex_markets": [
            {"id": "wallex_BTCTMN", "symbol": "BTC", "price": 1.0, "unit": "toman"}
        ],
        "source": "test",
    }
    store.save_latest(payload)
    loaded, updated = store.load_latest()
    assert loaded is not None
    assert updated
    assert loaded["essentials"][0]["price"] == 100000
    ticks = store.load_ticks(hours=1)
    assert len(ticks) == 1
    assert ticks[0]["wallex_count"] == 1

    store.save_inflation({"period": "1404-01", "cpi_index": 200.0})
    inf, inf_at = store.load_inflation()
    assert inf is not None
    assert inf["cpi_index"] == 200.0
    assert inf_at
    assert store.age_seconds(updated) is not None
