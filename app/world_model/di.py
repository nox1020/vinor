from __future__ import annotations

from app.world_model.interfaces import WorldModelManager
from app.world_model.manager import DefaultWorldModelManager
from app.world_model.reasoner import RuleWorldReasoner


def make_world_model_manager() -> WorldModelManager:
    return DefaultWorldModelManager(reasoner=RuleWorldReasoner())
