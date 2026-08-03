from __future__ import annotations


def parallel_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_PARALLEL_AGENTS", default=True)


def parallel_max_workers() -> int:
    import os

    try:
        return max(1, min(4, int(os.environ.get("VINOR_PARALLEL_WORKERS") or 3)))
    except Exception:
        return 3


def parallel_merge_hint_chars() -> int:
    import os

    try:
        return max(40, min(100, int(os.environ.get("VINOR_PARALLEL_MERGE_HINT_CHARS") or 80)))
    except Exception:
        return 80


def parallel_inject_merged_hint() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_PARALLEL_INJECT_MERGE_HINT", default=True)
