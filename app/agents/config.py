from __future__ import annotations

import os


def agents_enabled() -> bool:
    return (os.environ.get("VINOR_AGENTS_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def agents_cache_enabled() -> bool:
    return (os.environ.get("VINOR_AGENTS_CACHE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
