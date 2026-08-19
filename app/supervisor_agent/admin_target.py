# -*- coding: utf-8 -*-
"""شناسهٔ ذخیره‌سازی گزارش‌های ادمین (پس‌زمینه)."""
from __future__ import annotations

import os
import re


def resolve_admin_ops_user_key() -> str:
    explicit = (os.environ.get("VINOR_ADMIN_OPS_USER_KEY") or "").strip()
    if explicit:
        return explicit
    phone = (os.environ.get("VINOR_ADMIN_LOGIN_PHONE") or "09121471301").strip()
    digits = re.sub(r"\D+", "", phone)
    if len(digits) >= 11:
        return f"admin_{digits[-11:]}"
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", phone)[:40]
    return f"admin_{safe or 'ops'}"
