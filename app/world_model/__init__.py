"""World Model (Phase 21) — state only, no prompt text."""

from app.world_model.di import make_world_model_manager
from app.world_model.service import get_world_model, update_world_model

__all__ = ["make_world_model_manager", "update_world_model", "get_world_model"]
