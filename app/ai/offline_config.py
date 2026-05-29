"""تنظیمات موتور AI آفلاین (GGUF)."""
from __future__ import annotations

import os
import sys


def _truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


def is_linux_server() -> bool:
    return sys.platform.startswith("linux")


def offline_enabled() -> bool:
    return _truthy("VINOR_AI_OFFLINE_ENABLED", "1")


def auto_download() -> bool:
    return _truthy("VINOR_AI_AUTO_DOWNLOAD", "1")


def auto_pip() -> bool:
    return _truthy("VINOR_AI_AUTO_PIP", "1")


def auto_bootstrap() -> bool:
    return _truthy("VINOR_AI_OFFLINE_BOOTSTRAP", "1")


def provider_mode() -> str:
    """offline | deepseek | auto — پیش‌فرض: offline (اولویت مدل محلی)"""
    mode = (os.environ.get("VINOR_AI_PROVIDER") or "offline").strip().lower()
    if mode not in ("offline", "deepseek", "auto"):
        return "auto"
    return mode


def offline_threads() -> int:
    try:
        n = int(os.environ.get("VINOR_AI_OFFLINE_THREADS", "2"))
        return max(1, min(n, 8))
    except ValueError:
        return 2


def offline_n_ctx() -> int:
    try:
        n = int(os.environ.get("VINOR_AI_OFFLINE_N_CTX", "4096"))
        return max(512, min(n, 8192))
    except ValueError:
        return 4096


def offline_max_tokens() -> int:
    try:
        n = int(os.environ.get("VINOR_AI_OFFLINE_MAX_TOKENS", "512"))
        return max(64, min(n, 2048))
    except ValueError:
        return 512
