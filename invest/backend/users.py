# -*- coding: utf-8 -*-
"""پروفایل کاربر Invest — لینک به users.json وینور."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app

from app.services.sms import normalize_iran_mobile
from app.utils.storage import load_users

from .config import user_profile_path


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _load_profile_file(path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_profile_file(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _vinor_user(phone: str) -> Optional[Dict[str, Any]]:
    mobile = normalize_iran_mobile(phone)
    if not mobile:
        return None
    for u in load_users(current_app) or []:
        if not isinstance(u, dict):
            continue
        up = normalize_iran_mobile(str(u.get("phone") or ""))
        if up == mobile:
            return u
    return None


def get_or_create_profile(phone: str) -> Dict[str, Any]:
    mobile = normalize_iran_mobile(phone) or (phone or "").strip()
    path = user_profile_path(mobile)
    profile = _load_profile_file(path)
    vinor = _vinor_user(mobile) or {}

    name = (
        str(profile.get("name") or "").strip()
        or str(vinor.get("name") or vinor.get("full_name") or "").strip()
        or mobile
    )
    now = _now_iso()
    out = {
        "phone": mobile,
        "name": name,
        "created_at": profile.get("created_at") or now,
        "updated_at": now,
        "first_run_done": bool(profile.get("first_run_done")),
        "source": "vinor",
    }
    if vinor:
        out["vinor_user_id"] = vinor.get("id") or vinor.get("user_id")
        if vinor.get("registered_at"):
            out["registered_at"] = vinor.get("registered_at")
    if not profile:
        out["first_run_done"] = False
        _save_profile_file(path, out)
    return out


def update_profile(phone: str, *, name: str | None = None, first_run_done: bool | None = None) -> Dict[str, Any]:
    mobile = normalize_iran_mobile(phone) or (phone or "").strip()
    path = user_profile_path(mobile)
    profile = get_or_create_profile(mobile)
    if name is not None:
        profile["name"] = (name or "").strip() or profile.get("name") or mobile
    if first_run_done is not None:
        profile["first_run_done"] = bool(first_run_done)
    profile["updated_at"] = _now_iso()
    _save_profile_file(path, profile)
    return profile
