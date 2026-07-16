from __future__ import annotations

import json
import os
import time
from typing import Any


def evaluation_log_path() -> str:
    try:
        from flask import current_app

        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance")
        )
    return os.path.join(base, "data", "ai_evaluation.jsonl")


def append_evaluation_record(record: dict[str, Any]) -> None:
    """Persist evaluation outside prompt — fail-open."""
    path = evaluation_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = dict(record)
    if not row.get("ts"):
        row["ts"] = int(time.time())
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_evaluation_records(
    *,
    since_ts: int | None = None,
    until_ts: int | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    path = evaluation_log_path()
    if not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = int(row.get("ts") or 0)
                if since_ts is not None and ts < since_ts:
                    continue
                if until_ts is not None and ts > until_ts:
                    continue
                out.append(row)
                if len(out) >= limit:
                    break
    except Exception:
        return out
    return out
