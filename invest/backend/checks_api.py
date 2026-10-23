# -*- coding: utf-8 -*-
"""مسیرهای دفتر چک — /invest/api/v1/checks."""
from __future__ import annotations

from flask import request

from invest_app.services.check_service import (
    CheckError,
    CheckService,
    ascii_text,
    reminder_groups,
    summarize,
)

from .auth import require_invest_auth
from .context import get_request_context
from .routes.api import _json_err, _json_ok, invest_api_bp


def _service() -> CheckService:
    return CheckService(get_request_context().conn)


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _call(fn):
    try:
        return fn()
    except CheckError as exc:
        return _json_err(exc.message, error=exc.code, status=exc.status)


def _filtered(items: list[dict]) -> list[dict]:
    status = str(request.args.get("status") or "").strip().lower()
    direction = str(request.args.get("direction") or "").strip().lower()
    due = str(request.args.get("due") or "").strip().lower()
    query = str(request.args.get("q") or "").strip()
    archived = str(request.args.get("archived") or "").strip().lower()
    shown = []
    for item in items:
        if archived in ("only", "1", "true") and not item.get("is_archived"):
            continue
        if archived in ("exclude", "0", "false") and item.get("is_archived"):
            continue
        if status == "open" and not item.get("is_open"):
            continue
        if status == "settled" and item.get("is_open"):
            continue
        if status and status not in ("open", "settled") and item.get("status") != status:
            continue
        if direction and item.get("direction") != direction:
            continue
        days = int(item.get("days_until_due") or 0)
        if due == "overdue" and not (item.get("is_open") and days < 0):
            continue
        if due == "soon" and not (item.get("is_open") and 0 <= days <= 7):
            continue
        if query and ascii_text(query).casefold() not in ascii_text(_haystack(item)).casefold():
            continue
        shown.append(item)
    shown.sort(key=lambda item: (
        0 if item.get("is_open") else 1,
        str(item.get("due_date") or "") if item.get("is_open") else "",
        "" if item.get("is_open") else str(item.get("settled_date") or item.get("due_date") or ""),
    ))
    closed = [item for item in shown if not item.get("is_open")]
    closed.sort(key=lambda item: str(item.get("settled_date") or item.get("due_date") or ""), reverse=True)
    return [item for item in shown if item.get("is_open")] + closed


def _haystack(item: dict) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "check_number", "sayad_id", "bank_name", "branch",
            "counterparty", "purpose", "note", "direction_label", "status_label",
        )
    )


def register_check_routes() -> None:
    @invest_api_bp.get("/checks")
    @require_invest_auth
    def list_checks():
        items = _service().list_public()
        return _json_ok(items=_filtered(items), summary=summarize(items), count=len(items))

    @invest_api_bp.get("/checks/reminders")
    @require_invest_auth
    def check_reminders():
        raw = request.args.get("within_days")
        try:
            window = int(raw) if raw not in (None, "") else 7
        except (TypeError, ValueError):
            return _json_err("بازه سررسید نامعتبر است.", error="validation")
        groups = reminder_groups(_service().list_public(), within_days=window)
        return _json_ok(**groups)

    @invest_api_bp.post("/checks")
    @require_invest_auth
    def create_check():
        def _run():
            item = _service().create(_body())
            return _json_ok(item=item)
        return _call(_run)

    @invest_api_bp.get("/checks/<int:check_id>")
    @require_invest_auth
    def get_check(check_id: int):
        def _run():
            return _json_ok(item=_service().get_public(check_id))
        return _call(_run)

    @invest_api_bp.put("/checks/<int:check_id>")
    @invest_api_bp.patch("/checks/<int:check_id>")
    @require_invest_auth
    def update_check(check_id: int):
        def _run():
            return _json_ok(item=_service().update(check_id, _body()))
        return _call(_run)

    @invest_api_bp.delete("/checks/<int:check_id>")
    @require_invest_auth
    def delete_check(check_id: int):
        def _run():
            _service().delete(check_id)
            return _json_ok(deleted=True, id=check_id)
        return _call(_run)

    @invest_api_bp.post("/checks/<int:check_id>/delete")
    @require_invest_auth
    def delete_check_post(check_id: int):
        return delete_check(check_id)
