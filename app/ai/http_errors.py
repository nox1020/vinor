"""کدهای HTTP مناسب برای API چت AI."""
from __future__ import annotations

from typing import Any


def ai_chat_http_status(result: dict[str, Any]) -> int:
    if not result or result.get("ok"):
        return 200
    if result.get("rate_limited"):
        return 429
    return 400
