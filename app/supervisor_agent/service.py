# -*- coding: utf-8 -*-
"""ثبت گزارش Supervisor Agent در چت عملیات ادمین."""
from __future__ import annotations

from typing import Any

from app.ai.audience import AUDIENCE_ADMIN
from app.ai.message_types import MSG_NOTIFICATION
from app.supervisor_agent.admin_target import resolve_admin_ops_user_key
from app.supervisor_agent.categories import ALL_REPORT_CATEGORIES, REPORT_SYSTEM, STATUS_INFO
from app.supervisor_agent.config import supervisor_agent_enabled
from app.supervisor_agent.entity_links import entity_meta
from app.supervisor_agent.renderer import render_from_activity, render_report


def emit_domain_event(
    event: str,
    *,
    body: str = "",
    land_code: str = "",
    customer_name: str = "",
    customer_phone: str = "",
    partner_phone: str = "",
    partner_count: int = 0,
    response_count: int = 0,
    region: str = "",
    visit_time: str = "",
    deal_code: str = "",
    retry_minutes: int = 0,
    reviewed_count: int = 0,
    followup_count: int = 0,
    sent_count: int = 0,
    failed_count: int = 0,
    entity_type: str = "",
    entity_id: str = "",
    case_id: str = "",
    report_category: str = "",
    report_status: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """رویداد دامنه → گزارش فارسی در چت ادمین (fail-open)."""
    if not supervisor_agent_enabled():
        return {"ok": False, "skipped": "disabled"}

    rendered = render_report(
        event,
        body=body,
        land_code=land_code,
        customer_name=customer_name,
        customer_phone=customer_phone,
        partner_count=partner_count,
        response_count=response_count,
        region=region,
        visit_time=visit_time,
        deal_code=deal_code,
        retry_minutes=retry_minutes,
        reviewed_count=reviewed_count,
        followup_count=followup_count,
        sent_count=sent_count,
        failed_count=failed_count,
        meta=meta,
    )
    if not rendered:
        return {"ok": False, "skipped": "no_template"}

    text, category, status = rendered
    if report_category and report_category in ALL_REPORT_CATEGORIES:
        category = report_category
    if report_status:
        status = report_status

    return report_to_admin(
        text,
        event=event,
        category=category,
        status=status,
        land_code=land_code or deal_code,
        partner_phone=partner_phone,
        customer_name=customer_name,
        entity_type=entity_type,
        entity_id=entity_id,
        case_id=case_id,
        meta=meta,
    )


def report_from_activity(activity: Any) -> dict[str, Any]:
    """Bridge از Foundation Activity."""
    if not supervisor_agent_enabled() or activity is None:
        return {"ok": False, "skipped": "disabled"}
    try:
        rendered = render_from_activity(
            str(getattr(activity, "action", "") or ""),
            summary=str(getattr(activity, "summary", "") or ""),
            land_code=str(getattr(activity, "land_code", "") or ""),
            entity_type=str(getattr(activity, "entity_type", "") or ""),
            entity_id=str(getattr(activity, "entity_id", "") or ""),
            payload=dict(getattr(activity, "payload", None) or {}),
        )
    except Exception:
        return {"ok": False, "skipped": "render_error"}
    if not rendered:
        return {"ok": False, "skipped": "unmapped"}
    ev, text, category, status = rendered
    return report_to_admin(
        text,
        event=ev,
        category=category,
        status=status,
        land_code=str(getattr(activity, "land_code", "") or ""),
        partner_phone=str(getattr(activity, "actor_key", "") or ""),
        entity_type=str(getattr(activity, "entity_type", "") or ""),
        entity_id=str(getattr(activity, "entity_id", "") or ""),
    )


def report_from_chat_event(
    *,
    event: str,
    body: str = "",
    land_code: str = "",
    user_key: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bridge از emit_chat_event شریک/مشتری."""
    if not supervisor_agent_enabled():
        return {"ok": False, "skipped": "disabled"}
    skip = {
        "card_cancelled",
        "card_expired",
        "warning",
        "error",
        "admin_replied",
    }
    ev = (event or "").strip()
    if ev in skip:
        return {"ok": False, "skipped": "filtered"}

    customer_phone = user_key if user_key and not user_key.startswith("guest_") else ""
    return emit_domain_event(
        ev,
        body=body,
        land_code=land_code,
        customer_phone=customer_phone,
        meta=meta,
    )


def report_to_admin(
    text: str,
    *,
    event: str = "",
    category: str = REPORT_SYSTEM,
    status: str = STATUS_INFO,
    land_code: str = "",
    partner_phone: str = "",
    customer_name: str = "",
    entity_type: str = "",
    entity_id: str = "",
    case_id: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """پیام دائمی در گفتگوی فعال چت عملیات."""
    content = (text or "").strip()
    if not content:
        return {"ok": False, "error": "empty"}

    try:
        from app.ai.chat_store import append_typed_message, ensure_active_thread

        user_key = resolve_admin_ops_user_key()
        thread_id = ensure_active_thread(user_key, audience=AUDIENCE_ADMIN)
        msg_meta = entity_meta(
            entity_type=entity_type,
            entity_id=entity_id,
            land_code=land_code,
            partner_phone=partner_phone,
            customer_name=customer_name,
            case_id=case_id,
            extra={
                "report_category": category,
                "report_status": status,
                **(meta or {}),
            },
        )
        codes = [str(land_code).strip()] if land_code else None
        msgs, tid = append_typed_message(
            user_key,
            content,
            thread_id=thread_id,
            audience=AUDIENCE_ADMIN,
            msg_type=MSG_NOTIFICATION,
            source="supervisor_agent",
            land_codes=codes,
            event=(event or "supervisor_report").strip(),
            meta=msg_meta,
            quota=False,
        )
        return {"ok": True, "thread_id": tid, "messages": msgs, "event": event}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def list_reports(
    *,
    category: str = "",
    land_code: str = "",
    case_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """گزارش‌های Supervisor از چت ادمین (جدیدترین اول)."""
    if not supervisor_agent_enabled():
        return []
    try:
        from app.ai.chat_store import load_user_record

        user_key = resolve_admin_ops_user_key()
        record = load_user_record(user_key, audience=AUDIENCE_ADMIN)
        active_id = str(record.get("active_id") or "")
        threads = list(record.get("threads") or [])
        # ترجیح: گفتگوی فعال، سپس بقیه
        ordered = []
        for th in threads:
            if str(th.get("id") or "") == active_id:
                ordered.insert(0, th)
            else:
                ordered.append(th)

        cat = (category or "").strip().lower()
        land = str(land_code or "").strip()
        case = str(case_id or "").strip()
        out: list[dict[str, Any]] = []

        for th in ordered:
            for item in th.get("messages") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("source") or "") != "supervisor_agent":
                    continue
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                if cat and str(meta.get("report_category") or "") != cat:
                    continue
                if land:
                    item_land = str(meta.get("land_code") or "").strip()
                    codes = item.get("land_codes") or []
                    if item_land != land and land not in [str(c) for c in codes]:
                        continue
                if case and str(meta.get("case_id") or "") != case:
                    continue
                row = dict(item)
                row["thread_id"] = th.get("id")
                out.append(row)
        out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return out[: max(1, min(500, int(limit or 100)))]
    except Exception:
        return []
