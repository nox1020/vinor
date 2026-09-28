# app/api/__init__.py
# -*- coding: utf-8 -*-
"""
Make app.api a proper Python package and expose optional blueprints.
- uploads_bp:  /api/uploads/*
- push_bp:     /api/push/*
"""

from __future__ import annotations
from typing import Optional, List
from flask import Blueprint

# -----------------------------
# uploads (اختیاری)
# -----------------------------
try:
    from .uploads import uploads_bp  # type: ignore
except Exception:
    uploads_bp = None  # type: Optional[Blueprint]

# -----------------------------
# push (اختیاری + سازگاری عقب‌رو)
# -----------------------------
push_bp = None  # type: Optional[Blueprint]
try:
    # اول تلاش می‌کنیم alias سازگار با پروژه را برداریم
    from .push import push_bp as _push_bp  # type: ignore
    push_bp = _push_bp
except Exception:
    try:
        # اگر alias نبود، مستقیم api_push_bp را ایمپورت و به push_bp نگاشت می‌کنیم
        from .push import api_push_bp as _api_push_bp  # type: ignore
        push_bp = _api_push_bp
    except Exception:
        push_bp = None

# -----------------------------
# express (اختیاری)
# -----------------------------
try:
    from .express import express_api_bp  # type: ignore
except Exception:
    express_api_bp = None  # type: Optional[Blueprint]

# -----------------------------
# sms (اختیاری)
# -----------------------------
try:
    from .sms import sms_api_bp  # type: ignore
except Exception:
    sms_api_bp = None  # type: Optional[Blueprint]

# -----------------------------
# consultant onboarding stub
# -----------------------------
try:
    from .consultant import consultant_api_bp  # type: ignore
except Exception:
    consultant_api_bp = None  # type: Optional[Blueprint]

def available_blueprints() -> List[Blueprint]:
    """لیست بلوپرینت‌های موجود (Noneها حذف می‌شوند) برای ثبت سریع در create_app."""
    bps: List[Optional[Blueprint]] = [
        uploads_bp,
        push_bp,
        express_api_bp,
        sms_api_bp,
        consultant_api_bp,
    ]
    return [bp for bp in bps if bp is not None]

__all__ = [
    "uploads_bp",
    "push_bp",
    "express_api_bp",
    "sms_api_bp",
    "consultant_api_bp",
    "available_blueprints",
]
