"""Tests for portfolio snapshot migration / dual-write."""

from app.repositories.portfolio_snapshot_repo import PortfolioSnapshotRepository


def test_record_snapshot_writes_rich_row(trade_service, db_conn) -> None:
    trade_service.create_asset(
        name="Snap",
        symbol="S",
        quantity=2,
        avg_buy_price=50,
        current_price=55,
    )
    value = trade_service.portfolio.record_snapshot()
    assert value > 0
    repo = PortfolioSnapshotRepository(db_conn)
    rows = repo.list_values()
    assert rows
    assert rows[-1][1] == value


def test_migration_v2_tables(db_conn) -> None:
    names = {
        r[0]
        for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "portfolio_snapshots" in names
    assert "portfolio_snapshot_assets" in names
    ver = db_conn.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0]
    assert int(ver) >= 2
