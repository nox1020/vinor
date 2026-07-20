from __future__ import annotations

import threading

from app.memory.config import memory_budget_chars, memory_enabled, memory_top_k
from app.memory.di import make_memory_provider
from app.memory.interfaces import (
    MemoryExtractRequest,
    MemoryProvider,
    MemoryRetrieveRequest,
    MemoryRetrieveResult,
)

_LOCK = threading.Lock()
_PROVIDER: MemoryProvider | None = None


def get_memory_provider() -> MemoryProvider | None:
    global _PROVIDER
    if not memory_enabled():
        return None
    if _PROVIDER is not None:
        return _PROVIDER
    with _LOCK:
        if _PROVIDER is None:
            _PROVIDER = make_memory_provider()
    return _PROVIDER


def retrieve_memory_for_prompt(
    *,
    user_key: str,
    query: str,
    audience: str = "",
    thread_id: str | None = None,
    budget_chars: int | None = None,
) -> MemoryRetrieveResult:
    provider = get_memory_provider()
    if provider is None or not user_key:
        return MemoryRetrieveResult([], "", 0, 0, 0)
    try:
        budget = memory_budget_chars() if budget_chars is None else max(40, int(budget_chars))
        return provider.get_prompt_memory(
            MemoryRetrieveRequest(
                user_key=user_key,
                query=query or "",
                audience=audience,
                thread_id=thread_id,
                budget_chars=budget,
                top_k=memory_top_k(),
            )
        )
    except Exception:
        return MemoryRetrieveResult([], "", 0, 0, 0)


def learn_from_exchange(
    *,
    user_key: str,
    user_message: str,
    assistant_reply: str,
    audience: str = "",
    thread_id: str | None = None,
    land_codes: list[str] | None = None,
) -> int:
    provider = get_memory_provider()
    if provider is None or not user_key:
        return 0
    try:
        saved = provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key=user_key,
                user_message=user_message or "",
                assistant_reply=assistant_reply or "",
                audience=audience,
                thread_id=thread_id,
                land_codes=tuple(str(c).strip() for c in (land_codes or []) if str(c).strip()),
            )
        )
        return len(saved)
    except Exception:
        return 0


def memory_quota_for_user(user_key: str) -> dict[str, int]:
    """مصرف و سقف حافظهٔ اختصاصی یک کاربر (بایت)."""
    from app.memory.config import memory_max_bytes
    from app.memory.di import make_memory_store

    max_b = memory_max_bytes()
    used = 0
    if user_key:
        try:
            store = make_memory_store()
            used_fn = getattr(store, "usage_bytes", None)
            if callable(used_fn):
                used = int(used_fn(user_key) or 0)
            max_fn = getattr(store, "max_bytes", None)
            if callable(max_fn):
                max_b = int(max_fn() or max_b)
        except Exception:
            used = 0
    return {"bytes_used": used, "max_bytes": max_b}
