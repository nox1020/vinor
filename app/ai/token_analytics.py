from __future__ import annotations

import json
import os
import time
from typing import Any

from flask import current_app


def estimate_tokens(text: str) -> int:
    # Fast heuristic for Persian/English mixed text.
    s = str(text or "")
    if not s:
        return 0
    return max(1, int(len(s) / 3.6))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        total += estimate_tokens(str(m.get("content") or ""))
        total += 4  # role/frame overhead
    return total


def usage_cost(usage: dict[str, Any] | None) -> float:
    if not isinstance(usage, dict):
        return 0.0
    # Optional env-configurable rates ($ / 1M tokens)
    in_rate = _env_float("VINOR_AI_INPUT_RATE_PER_1M", 0.27)
    out_rate = _env_float("VINOR_AI_OUTPUT_RATE_PER_1M", 1.10)
    in_tok = int(usage.get("prompt_tokens") or 0)
    out_tok = int(usage.get("completion_tokens") or 0)
    return (in_tok * in_rate + out_tok * out_rate) / 1_000_000.0


def record_token_analytics(payload: dict[str, Any]) -> None:
    path = _analytics_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = dict(payload)
    row["ts"] = int(time.time())
    line = json.dumps(row, ensure_ascii=False)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _analytics_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "instance"))
    return os.path.join(base, "data", "ai_token_analytics.jsonl")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except Exception:
        return default

