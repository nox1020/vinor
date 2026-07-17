# -*- coding: utf-8 -*-
"""CRM JSON stores — fail-open, gated by crm_enabled."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.crm.config import crm_enabled
from app.crm.interfaces import CallLog, Contact, FollowUp, Lead, Task

_LOCK = threading.Lock()

_CONTACTS = "crm_contacts.json"
_LEADS = "crm_leads.json"
_CALLS = "crm_call_logs.json"
_FOLLOWUPS = "crm_followups.json"
_TASKS = "crm_tasks.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(file_name: str, app=None) -> str:
    from app.utils.storage import data_dir

    return os.path.join(data_dir(app), file_name)


def _load_raw(file_name: str, app=None) -> List[dict[str, Any]]:
    from app.utils.storage import _load

    data = _load(_path(file_name, app))
    return data if isinstance(data, list) else []


def _save_raw(file_name: str, rows: List[dict[str, Any]], app=None) -> None:
    from app.utils.storage import _save

    _save(_path(file_name, app), rows)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _normalize_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(raw) or raw
    except Exception:
        return raw


# ── Contacts ──────────────────────────────────────────────────────────────


def upsert_contact(
    *,
    partner_phone: str,
    customer_phone: str,
    first_name: str = "",
    last_name: str = "",
    display_name: str = "",
    source: str = "manual",
    visit_id: str = "",
    lead_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Contact]:
    """Create or update Contact keyed by (partner_phone, customer_phone)."""
    if not crm_enabled():
        return None
    pp = _normalize_phone(partner_phone)
    cp = _normalize_phone(customer_phone)
    if not pp or not cp:
        return None
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    dn = (display_name or "").strip() or f"{fn} {ln}".strip() or cp
    now = _now_iso()
    vid = (visit_id or "").strip()
    lid = (lead_id or "").strip()
    try:
        with _LOCK:
            rows = _load_raw(_CONTACTS, app)
            found: dict[str, Any] | None = None
            idx = -1
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                if (
                    _normalize_phone(str(row.get("partner_phone") or "")) == pp
                    and _normalize_phone(str(row.get("customer_phone") or "")) == cp
                ):
                    found = row
                    idx = i
                    break
            if found is None:
                contact = Contact(
                    id=_new_id(),
                    partner_phone=pp,
                    customer_phone=cp,
                    first_name=fn,
                    last_name=ln,
                    display_name=dn,
                    source=(source or "manual").strip() or "manual",
                    visit_ids=[vid] if vid else [],
                    lead_id=lid,
                    notes=(notes or "").strip(),
                    created_at=now,
                    updated_at=now,
                    metadata=dict(metadata or {}),
                )
                rows.append(contact.to_dict())
                _save_raw(_CONTACTS, rows, app)
                return contact
            # update existing
            c = Contact.from_dict(found)
            if fn:
                c.first_name = fn
            if ln:
                c.last_name = ln
            if dn:
                c.display_name = dn
            if source and c.source != "visit":
                # keep visit as stronger source once set
                if source == "visit" or not c.source:
                    c.source = source
            elif source == "visit":
                c.source = "visit"
            if vid and vid not in c.visit_ids:
                c.visit_ids.append(vid)
            if lid and not c.lead_id:
                c.lead_id = lid
            if notes:
                c.notes = notes
            if metadata:
                c.metadata.update(metadata)
            c.updated_at = now
            rows[idx] = c.to_dict()
            _save_raw(_CONTACTS, rows, app)
            return c
    except Exception:
        return None


def get_contact(contact_id: str, *, app=None) -> Optional[Contact]:
    if not crm_enabled():
        return None
    cid = (contact_id or "").strip()
    if not cid:
        return None
    try:
        for row in _load_raw(_CONTACTS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == cid:
                return Contact.from_dict(row)
    except Exception:
        return None
    return None


def list_contacts(
    *,
    partner_phone: str = "",
    limit: int = 200,
    app=None,
) -> List[Contact]:
    if not crm_enabled():
        return []
    pp = _normalize_phone(partner_phone)
    try:
        rows = _load_raw(_CONTACTS, app)
    except Exception:
        return []
    out: List[Contact] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _normalize_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        out.append(Contact.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out


# ── Leads ─────────────────────────────────────────────────────────────────


def create_lead(
    *,
    partner_phone: str,
    customer_phone: str = "",
    first_name: str = "",
    last_name: str = "",
    display_name: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Lead]:
    if not crm_enabled():
        return None
    pp = _normalize_phone(partner_phone)
    if not pp:
        return None
    cp = _normalize_phone(customer_phone)
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    dn = (display_name or "").strip() or f"{fn} {ln}".strip() or cp or "لید"
    now = _now_iso()
    lead = Lead(
        id=_new_id(),
        partner_phone=pp,
        customer_phone=cp,
        first_name=fn,
        last_name=ln,
        display_name=dn,
        status="open",
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_LEADS, app)
            rows.append(lead.to_dict())
            _save_raw(_LEADS, rows, app)
        return lead
    except Exception:
        return None


def convert_lead_to_contact(lead_id: str, *, app=None) -> Optional[Contact]:
    if not crm_enabled():
        return None
    lid = (lead_id or "").strip()
    if not lid:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_LEADS, app)
            lead_row: dict[str, Any] | None = None
            idx = -1
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == lid:
                    lead_row = row
                    idx = i
                    break
            if lead_row is None:
                return None
            lead = Lead.from_dict(lead_row)
            if not lead.customer_phone:
                return None
    except Exception:
        return None
    contact = upsert_contact(
        partner_phone=lead.partner_phone,
        customer_phone=lead.customer_phone,
        first_name=lead.first_name,
        last_name=lead.last_name,
        display_name=lead.display_name,
        source="lead",
        lead_id=lead.id,
        notes=lead.notes,
        app=app,
    )
    if contact is None:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_LEADS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == lid:
                    lead = Lead.from_dict(row)
                    lead.status = "converted"
                    lead.contact_id = contact.id
                    lead.updated_at = _now_iso()
                    rows[i] = lead.to_dict()
                    _save_raw(_LEADS, rows, app)
                    break
    except Exception:
        pass
    return contact


def list_leads(
    *,
    partner_phone: str = "",
    status: str = "",
    limit: int = 200,
    app=None,
) -> List[Lead]:
    if not crm_enabled():
        return []
    pp = _normalize_phone(partner_phone)
    st = (status or "").strip()
    try:
        rows = _load_raw(_LEADS, app)
    except Exception:
        return []
    out: List[Lead] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _normalize_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Lead.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out


# ── Call logs ─────────────────────────────────────────────────────────────


def append_call_log(
    *,
    partner_phone: str,
    contact_id: str = "",
    lead_id: str = "",
    called_at: str = "",
    outcome: str = "",
    notes: str = "",
    to_number: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[CallLog]:
    if not crm_enabled():
        return None
    from app.crm.config import VISIT_CALL_TARGET

    pp = _normalize_phone(partner_phone)
    if not pp:
        return None
    now = _now_iso()
    call = CallLog(
        id=_new_id(),
        partner_phone=pp,
        contact_id=(contact_id or "").strip(),
        lead_id=(lead_id or "").strip(),
        called_at=(called_at or "").strip() or now,
        outcome=(outcome or "").strip(),
        notes=(notes or "").strip(),
        to_number=_normalize_phone(to_number) or VISIT_CALL_TARGET,
        created_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_CALLS, app)
            rows.append(call.to_dict())
            _save_raw(_CALLS, rows, app)
        return call
    except Exception:
        return None


def list_call_logs(
    *,
    partner_phone: str = "",
    contact_id: str = "",
    limit: int = 100,
    app=None,
) -> List[CallLog]:
    if not crm_enabled():
        return []
    pp = _normalize_phone(partner_phone)
    cid = (contact_id or "").strip()
    try:
        rows = _load_raw(_CALLS, app)
    except Exception:
        return []
    out: List[CallLog] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _normalize_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if cid and str(row.get("contact_id") or "").strip() != cid:
            continue
        out.append(CallLog.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


# ── Follow-ups ────────────────────────────────────────────────────────────


def create_followup(
    *,
    partner_phone: str,
    contact_id: str = "",
    lead_id: str = "",
    due_at: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[FollowUp]:
    if not crm_enabled():
        return None
    pp = _normalize_phone(partner_phone)
    if not pp:
        return None
    now = _now_iso()
    fu = FollowUp(
        id=_new_id(),
        partner_phone=pp,
        contact_id=(contact_id or "").strip(),
        lead_id=(lead_id or "").strip(),
        due_at=(due_at or "").strip(),
        status="pending",
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_FOLLOWUPS, app)
            rows.append(fu.to_dict())
            _save_raw(_FOLLOWUPS, rows, app)
        return fu
    except Exception:
        return None


def update_followup_status(
    followup_id: str,
    status: str,
    *,
    app=None,
) -> Optional[FollowUp]:
    if not crm_enabled():
        return None
    fid = (followup_id or "").strip()
    st = (status or "").strip()
    if not fid or st not in ("pending", "done", "cancelled"):
        return None
    try:
        with _LOCK:
            rows = _load_raw(_FOLLOWUPS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == fid:
                    fu = FollowUp.from_dict(row)
                    fu.status = st
                    fu.updated_at = _now_iso()
                    rows[i] = fu.to_dict()
                    _save_raw(_FOLLOWUPS, rows, app)
                    return fu
    except Exception:
        return None
    return None


def list_followups(
    *,
    partner_phone: str = "",
    contact_id: str = "",
    status: str = "",
    limit: int = 100,
    app=None,
) -> List[FollowUp]:
    if not crm_enabled():
        return []
    pp = _normalize_phone(partner_phone)
    cid = (contact_id or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_FOLLOWUPS, app)
    except Exception:
        return []
    out: List[FollowUp] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _normalize_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if cid and str(row.get("contact_id") or "").strip() != cid:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(FollowUp.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


# ── Tasks ─────────────────────────────────────────────────────────────────


def create_task(
    *,
    partner_phone: str,
    title: str,
    contact_id: str = "",
    lead_id: str = "",
    due_at: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Task]:
    if not crm_enabled():
        return None
    pp = _normalize_phone(partner_phone)
    title_s = (title or "").strip()
    if not pp or not title_s:
        return None
    now = _now_iso()
    task = Task(
        id=_new_id(),
        partner_phone=pp,
        contact_id=(contact_id or "").strip(),
        lead_id=(lead_id or "").strip(),
        title=title_s,
        status="pending",
        due_at=(due_at or "").strip(),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_TASKS, app)
            rows.append(task.to_dict())
            _save_raw(_TASKS, rows, app)
        return task
    except Exception:
        return None


def list_tasks(
    *,
    partner_phone: str = "",
    status: str = "",
    limit: int = 100,
    app=None,
) -> List[Task]:
    if not crm_enabled():
        return []
    pp = _normalize_phone(partner_phone)
    st = (status or "").strip()
    try:
        rows = _load_raw(_TASKS, app)
    except Exception:
        return []
    out: List[Task] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _normalize_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Task.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out
