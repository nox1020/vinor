from pathlib import Path

from app.database.connection import get_connection, init_database
from app.services.backup_service import BackupService


def test_init_database_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "closed.db"
    init_database(path)
    conn = get_connection(path)
    try:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("k", "v"))
        conn.commit()
    finally:
        conn.close()


def test_backup_includes_uncheckpointed_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    conn = get_connection(db_path)
    conn.executescript(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"
        "INSERT INTO t (v) VALUES ('old');"
    )
    conn.commit()
    conn.execute("INSERT INTO t (v) VALUES ('new')")
    conn.commit()

    dest = tmp_path / "copy.db"
    BackupService(db_path).backup(dest)
    conn.close()

    copied = get_connection(dest)
    rows = copied.execute("SELECT v FROM t ORDER BY id").fetchall()
    copied.close()
    assert [r[0] for r in rows] == ["old", "new"]


def test_restore_removes_wal_sidecars(tmp_path: Path) -> None:
    live = tmp_path / "invest.db"
    src = tmp_path / "backup.db"
    src.write_bytes(b"not-a-real-db-but-copy-ok")
    (tmp_path / "invest.db-wal").write_text("stale", encoding="utf-8")
    (tmp_path / "invest.db-shm").write_text("stale", encoding="utf-8")
    BackupService(live).restore(src)
    assert live.exists()
    assert not (tmp_path / "invest.db-wal").exists()
    assert not (tmp_path / "invest.db-shm").exists()
