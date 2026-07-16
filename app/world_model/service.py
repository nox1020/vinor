from __future__ import annotations

import threading
from typing import Any

from app.world_model.config import world_model_enabled
from app.world_model.di import make_world_model_manager
from app.world_model.interfaces import WorldModelManager, WorldSnapshot

_LOCK = threading.Lock()
_MANAGER: WorldModelManager | None = None
_FALLBACK: dict[str, Any] = {}


def get_world_model_manager() -> WorldModelManager | None:
    global _MANAGER
    if not world_model_enabled():
        return None
    if _MANAGER is not None:
        return _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = make_world_model_manager()
    return _MANAGER


def _store(snap: WorldSnapshot | None) -> None:
    global _FALLBACK
    data = snap.to_dict() if snap else {}
    _FALLBACK = data
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            g.ai_world_model = data
    except Exception:
        pass


def get_world_model() -> dict[str, Any]:
    try:
        from flask import g, has_app_context, has_request_context

        if has_app_context() or has_request_context():
            raw = getattr(g, "ai_world_model", None)
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return dict(_FALLBACK)


def update_world_model(*, shared: dict[str, Any] | None = None) -> WorldSnapshot | None:
    manager = get_world_model_manager()
    if manager is None:
        return None
    try:
        shared = dict(shared or {})
        # Soft-pull from g
        try:
            from flask import g, has_app_context, has_request_context

            if has_app_context() or has_request_context():
                if not shared.get("decision"):
                    shared["decision"] = getattr(g, "ai_decision", None) or {}
                if not shared.get("business_intelligence"):
                    shared["business_intelligence"] = getattr(g, "ai_business_intelligence", None) or {}
                if not shared.get("goals"):
                    shared["goals"] = getattr(g, "ai_goals", None) or {}
                if not shared.get("customer_profile"):
                    shared["customer_profile"] = getattr(g, "ai_customer_profile", None) or {}
        except Exception:
            pass
        snap = manager.update(shared=shared)
        _store(snap)
        shared["world_model"] = snap.to_dict()
        return snap
    except Exception:
        return None
