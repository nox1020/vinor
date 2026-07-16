from __future__ import annotations

import json
import os
import time
from typing import Any


def optimization_reports_dir() -> str:
    try:
        from flask import current_app

        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "instance")
        )
    path = os.path.join(base, "data", "optimization_reports")
    os.makedirs(path, exist_ok=True)
    return path


def save_optimization_report(report: dict[str, Any]) -> str:
    """Persist report JSON — never applies config."""
    folder = optimization_reports_dir()
    rid = str(report.get("report_id") or int(time.time()))
    path = os.path.join(folder, f"{rid}.json")
    payload = dict(report)
    payload["applied"] = False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # also append index line
    index = os.path.join(folder, "index.jsonl")
    try:
        with open(index, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "report_id": rid,
                        "created_at": payload.get("created_at"),
                        "optimization_count": payload.get("optimization_count"),
                        "estimated_gain": payload.get("estimated_gain"),
                        "cost_saving": payload.get("cost_saving"),
                        "path": path,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    return path


def list_optimization_reports(limit: int = 50) -> list[dict[str, Any]]:
    folder = optimization_reports_dir()
    index = os.path.join(folder, "index.jsonl")
    rows: list[dict[str, Any]] = []
    if os.path.isfile(index):
        try:
            with open(index, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            rows = []
    rows = rows[-limit:]
    rows.reverse()
    return rows


def load_optimization_report(report_id: str) -> dict[str, Any] | None:
    path = os.path.join(optimization_reports_dir(), f"{report_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data["applied"] = False
            return data
    except Exception:
        return None
    return None
