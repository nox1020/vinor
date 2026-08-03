"""کدهای HTTP مناسب برای API چت AI."""
from __future__ import annotations

from typing import Any


def ai_chat_http_status(result: dict[str, Any]) -> int:
    if not result or result.get("ok"):
        return 200
    if result.get("need_login"):
        return 401
    if result.get("rate_limited"):
        return 429
    if result.get("error_code") == "api_unavailable":
        return 503
    if result.get("error_code") == "ai_paused":
        return 503
    return 400
