# -*- coding: utf-8 -*-
"""اتصال Supervisor Agent به sales_coach و broadcast ادمین."""
from __future__ import annotations

from typing import Any


def report_sales_coach_result(result: dict[str, Any] | None) -> None:
    """گزارش نوبت پیگیری همکار (sales_coach)."""
    if not isinstance(result, dict) or not result.get("ok"):
        return
    nudged = int(result.get("partners_nudged") or 0)
    if nudged <= 0:
        return
    failed = 0
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("notif") is False or item.get("notif_error"):
            failed += 1
            continue
        sms = item.get("sms")
        if isinstance(sms, dict) and not sms.get("ok") and not sms.get("dry_run"):
            failed += 1
    try:
        from app.supervisor_agent.service import emit_domain_event

        emit_domain_event(
            "partner_followup_sent",
            sent_count=nudged,
            failed_count=failed,
        )
    except Exception:
        pass


def report_admin_broadcast_sms(
    *,
    sent: int,
    failed: int,
    group_label: str = "",
) -> None:
    try:
        from app.supervisor_agent.service import emit_domain_event

        emit_domain_event(
            "admin_broadcast_sms",
            region=(group_label or "").strip() or "همکاران",
            sent_count=max(0, int(sent or 0)),
            failed_count=max(0, int(failed or 0)),
        )
    except Exception:
        pass


def report_admin_broadcast_push(
    *,
    sent: int,
    failed: int,
    title: str = "",
) -> None:
    try:
        from app.supervisor_agent.service import emit_domain_event

        emit_domain_event(
            "admin_broadcast_push",
            body=(title or "").strip(),
            sent_count=max(0, int(sent or 0)),
            failed_count=max(0, int(failed or 0)),
        )
    except Exception:
        pass
