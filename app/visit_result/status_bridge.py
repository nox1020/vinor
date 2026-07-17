# -*- coding: utf-8 -*-
"""Status bridge — extend visit status sets when Phase 2 flags are ON."""
from __future__ import annotations

from typing import Dict, FrozenSet

from app.visit_result.config import visit_no_show_status_enabled, visit_result_enabled


def no_show_status_value() -> str:
    return "no_show"


def is_no_show_writable() -> bool:
    return visit_result_enabled() and visit_no_show_status_enabled()


def extend_admin_statuses(base: FrozenSet[str]) -> FrozenSet[str]:
    """Always recognize no_show as a known status constant; writes still gated."""
    return frozenset(set(base) | {no_show_status_value()})


def extend_admin_transitions(
    base: Dict[str, FrozenSet[str]],
) -> Dict[str, FrozenSet[str]]:
    """When no_show writable: allow approved/done_pending → no_show; no_show terminal."""
    out: Dict[str, FrozenSet[str]] = {k: frozenset(v) for k, v in base.items()}
    if not is_no_show_writable():
        return out
    ns = no_show_status_value()
    from app.express_partner.visit_requests import APPROVED_STATUS, DONE_PENDING_STATUS

    for key in (APPROVED_STATUS, DONE_PENDING_STATUS):
        cur = set(out.get(key, frozenset()))
        cur.add(ns)
        out[key] = frozenset(cur)
    out[ns] = frozenset({ns})
    return out
