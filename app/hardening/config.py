# -*- coding: utf-8 -*-
"""Phase 7 Hardening feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def hardening_enabled() -> bool:
    return _env_bool("VINOR_HARDENING_ENABLED", "1")


def hardening_audit_enabled() -> bool:
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_AUDIT_ENABLED", "1")


def hardening_audit_required() -> bool:
    """When ON, log warning if audit write fails; never blocks mutate (fail-open)."""
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_AUDIT_REQUIRED", "1")


def hardening_rbac_enabled() -> bool:
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_RBAC_ENABLED", "1")


def hardening_os_kpis_enabled() -> bool:
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_OS_KPIS_ENABLED", "1")


def hardening_soft_cleanup_enabled() -> bool:
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_SOFT_CLEANUP_ENABLED", "1")


def hardening_ui_enabled() -> bool:
    if not hardening_enabled():
        return False
    return _env_bool("VINOR_HARDENING_UI_ENABLED", "1")
