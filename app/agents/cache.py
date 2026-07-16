from __future__ import annotations

import threading
from typing import Callable

from app.agents.config import agents_cache_enabled
from app.agents.interfaces import Agent


class AgentCache:
    """Lazy agent instance cache — avoids re-constructing agents per request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, Agent] = {}

    def get_or_create(self, agent_id: str, factory: Callable[[], Agent]) -> Agent:
        if not agents_cache_enabled():
            return factory()
        cached = self._cache.get(agent_id)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._cache.get(agent_id)
            if cached is not None:
                return cached
            agent = factory()
            self._cache[agent_id] = agent
            return agent

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
