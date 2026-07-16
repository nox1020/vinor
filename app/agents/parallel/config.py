from __future__ import annotations

import os


def parallel_enabled() -> bool:
    return (os.environ.get("VINOR_PARALLEL_AGENTS") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def parallel_max_workers() -> int:
    try:
        return max(1, min(4, int(os.environ.get("VINOR_PARALLEL_WORKERS") or 3)))
    except Exception:
        return 3


def parallel_merge_hint_chars() -> int:
    try:
        return max(40, min(100, int(os.environ.get("VINOR_PARALLEL_MERGE_HINT_CHARS") or 80)))
    except Exception:
        return 80


def parallel_inject_merged_hint() -> bool:
    return (os.environ.get("VINOR_PARALLEL_INJECT_MERGE_HINT") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
