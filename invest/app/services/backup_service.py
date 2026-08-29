"""Backup and restore of the SQLite database file."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from shutil import copy2

from app.config import DB_PATH


def _sidecars(db_path: Path) -> list[Path]:
    return [Path(str(db_path) + suffix) for suffix in ("-wal", "-shm")]


def _remove_sidecars(db_path: Path) -> None:
    for path in _sidecars(db_path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


class BackupService:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH

    def backup(self, destination: Path) -> Path:
        if not self.db_path.exists():
            raise FileNotFoundError("فایل پایگاه داده یافت نشد.")
        destination = Path(destination)
        if destination.is_dir():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = destination / f"invest_backup_{stamp}.db"
        destination.parent.mkdir(parents=True, exist_ok=True)

        # sqlite3 backup copies WAL pages, so live writes are not lost.
        src = sqlite3.connect(str(self.db_path))
        try:
            dest = sqlite3.connect(str(destination))
            try:
                src.backup(dest)
            finally:
                dest.close()
        finally:
            src.close()
        return destination

    def restore(self, source: Path) -> Path:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError("فایل پشتیبان یافت نشد.")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _remove_sidecars(self.db_path)
        copy2(source, self.db_path)
        _remove_sidecars(self.db_path)
        return self.db_path
