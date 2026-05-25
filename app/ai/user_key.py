"""شناسه ذخیره چت — موبایل یا مهمان."""
from __future__ import annotations

import uuid

from flask import session


def ai_user_key() -> str:
    phone = (session.get("user_phone") or "").strip()
    if phone:
        return phone
    gid = session.get("ai_guest_id")
    if not gid:
        gid = uuid.uuid4().hex[:16]
        session["ai_guest_id"] = gid
    return f"guest_{gid}"
