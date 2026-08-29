from app.database.connection import get_connection


def test_foreign_keys_and_wal(tmp_path) -> None:
    conn = get_connection(tmp_path / "pragma.db")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert fk == 1
    assert str(journal).lower() == "wal"
