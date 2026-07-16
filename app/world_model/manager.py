from __future__ import annotations

from typing import Any

from app.world_model.interfaces import WorldModelManager, WorldReasoner, WorldSnapshot
from app.world_model.reasoner import RuleWorldReasoner


class DefaultWorldModelManager(WorldModelManager):
    def __init__(self, *, reasoner: WorldReasoner | None = None):
        self._reasoner = reasoner or RuleWorldReasoner()

    def update(self, *, shared: dict[str, Any] | None = None) -> WorldSnapshot:
        return self._reasoner.snapshot(shared=dict(shared or {}))
