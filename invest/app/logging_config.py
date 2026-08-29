"""Central logging setup for the desktop application."""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
DEFAULT_LEVEL = logging.INFO

_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "%(filename)s:%(lineno)d | %(funcName)s | %(message)s"
)


def setup_logging(*, level: int = DEFAULT_LEVEL, log_to_console: bool = True) -> None:
    """Configure root logger with daily rotating file under data/logs/."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "invest.log"

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(level)

    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    if log_to_console:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)

    logging.getLogger(__name__).debug("Logging initialized: %s", log_file)
