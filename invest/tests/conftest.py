"""Shared pytest fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import SCHEMA_PATH
from app.database.connection import get_connection
from app.database.migrations import ensure_default_settings, run_migrations
from app.services.portfolio_service import PortfolioService
from app.services.service_factory import build_services
from app.services.trade_service import TradeService


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    run_migrations(conn)
    ensure_default_settings(conn)
    yield conn
    conn.close()


@pytest.fixture
def trade_service(db_conn: sqlite3.Connection) -> TradeService:
    portfolio = PortfolioService(db_conn)
    return TradeService(db_conn, portfolio=portfolio)


@pytest.fixture
def services(db_conn: sqlite3.Connection, tmp_path: Path):
    return build_services(db_conn, db_path=tmp_path / "test.db")
