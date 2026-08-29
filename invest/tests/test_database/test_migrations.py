from app.config import SETTING_THEME, THEME_DARK
from app.database.migrations import CURRENT_SCHEMA_VERSION, run_migrations


def test_run_migrations_baseline(db_conn) -> None:
    run_migrations(db_conn)
    row = db_conn.execute(
        "SELECT version FROM schema_migrations WHERE version = 1"
    ).fetchone()
    assert row is not None


def test_migration_v3_sets_dark_theme(db_conn) -> None:
    run_migrations(db_conn)
    ver = db_conn.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0]
    assert int(ver) >= CURRENT_SCHEMA_VERSION
    theme = db_conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (SETTING_THEME,),
    ).fetchone()
    assert theme is not None
    assert theme[0] == THEME_DARK
