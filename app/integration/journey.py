# -*- coding: utf-8 -*-
"""Lead → Settlement journey timeline aggregator (read-only, fail-open)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List


STAGES = (
    "lead",
    "contact",
    "call",
    "followup",
    "visit",
    "visit_result",
    "negotiation",
    "offer",
    "reservation",
    "deal",
    "contract",
    "payment",
    "settlement",
)


@dataclass
class JourneyEvent:
    ts: str = ""
    stage: str = ""
    source: str = ""
    action: str = ""
    summary: str = ""
    entity_type: str = ""
    entity_id: str = ""
    land_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(raw) or raw
    except Exception:
        return raw


def _ev(
    *,
    ts: str,
    stage: str,
    source: str,
    action: str,
    summary: str,
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> JourneyEvent:
    return JourneyEvent(
        ts=ts or "",
        stage=stage,
        source=source,
        action=action,
        summary=summary,
        entity_type=entity_type,
        entity_id=entity_id,
        land_code=str(land_code or "").strip(),
        metadata=dict(metadata or {}),
    )


def build_journey_timeline(
    *,
    partner_phone: str = "",
    land_code: str = "",
    contact_phone: str = "",
    limit: int = 200,
) -> List[JourneyEvent]:
    """Compose Lead→Settlement events from domain stores + Foundation timeline."""
    from app.integration.config import integration_enabled, integration_journey_enabled

    if not integration_enabled() or not integration_journey_enabled():
        return []

    pp = _norm_phone(partner_phone)
    cp = _norm_phone(contact_phone)
    lc = str(land_code or "").strip()
    events: List[JourneyEvent] = []

    # Foundation activities (partner / land)
    try:
        from app.foundation.activity_store import list_activities

        for a in list_activities(actor_key=pp, land_code=lc, limit=limit):
            stage = _stage_from_action(a.action, a.entity_type)
            if lc and a.land_code and a.land_code != lc:
                continue
            events.append(
                _ev(
                    ts=a.created_at,
                    stage=stage,
                    source="foundation",
                    action=a.action,
                    summary=a.summary or a.action,
                    entity_type=a.entity_type,
                    entity_id=a.entity_id,
                    land_code=a.land_code,
                )
            )
    except Exception:
        pass

    # CRM
    try:
        from app.crm import store as crm_store

        if pp:
            for lead in crm_store.list_leads(partner_phone=pp, limit=100):
                if cp and _norm_phone(lead.customer_phone) != cp:
                    continue
                events.append(
                    _ev(
                        ts=lead.created_at or lead.updated_at,
                        stage="lead",
                        source="crm",
                        action="crm_lead",
                        summary=f"Lead: {lead.display_name}",
                        entity_type="lead",
                        entity_id=lead.id,
                    )
                )
            for contact in crm_store.list_contacts(partner_phone=pp, limit=100):
                if cp and _norm_phone(contact.customer_phone) != cp:
                    continue
                events.append(
                    _ev(
                        ts=contact.created_at or contact.updated_at,
                        stage="contact",
                        source="crm",
                        action="crm_contact",
                        summary=f"Contact: {contact.display_name or contact.customer_phone}",
                        entity_type="contact",
                        entity_id=contact.id,
                    )
                )
            for call in crm_store.list_call_logs(partner_phone=pp, limit=100):
                events.append(
                    _ev(
                        ts=call.called_at or call.created_at,
                        stage="call",
                        source="crm",
                        action="crm_call",
                        summary=f"Call → {call.to_number}",
                        entity_type="call_log",
                        entity_id=call.id,
                    )
                )
            for fu in crm_store.list_followups(partner_phone=pp, limit=100):
                events.append(
                    _ev(
                        ts=fu.created_at or fu.due_at,
                        stage="followup",
                        source="crm",
                        action="crm_followup",
                        summary=f"Follow-up {fu.status}",
                        entity_type="followup",
                        entity_id=fu.id,
                    )
                )
    except Exception:
        pass

    # Visit results
    try:
        from app.visit_result import store as vr_store

        for r in vr_store.list_results(partner_phone=pp, land_code=lc, limit=100):
            if lc and r.land_code and r.land_code != lc:
                continue
            events.append(
                _ev(
                    ts=r.created_at or r.updated_at,
                    stage="visit_result",
                    source="visit_result",
                    action=f"visit_{r.outcome}",
                    summary=f"Visit result: {r.outcome}",
                    entity_type="visit_result",
                    entity_id=r.id,
                    land_code=r.land_code,
                )
            )
    except Exception:
        pass

    # Commercial
    try:
        from app.commercial import store as com_store

        for n in com_store.list_negotiations(partner_phone=pp, land_code=lc, limit=100):
            if cp and n.buyer_phone and _norm_phone(n.buyer_phone) != cp:
                continue
            events.append(
                _ev(
                    ts=n.created_at or n.updated_at,
                    stage="negotiation",
                    source="commercial",
                    action="negotiation",
                    summary=f"Negotiation {n.status}",
                    entity_type="negotiation",
                    entity_id=n.id,
                    land_code=n.land_code,
                )
            )
        for o in com_store.list_offers(partner_phone=pp, land_code=lc, limit=100):
            events.append(
                _ev(
                    ts=o.created_at or o.updated_at,
                    stage="offer",
                    source="commercial",
                    action="offer",
                    summary=f"Offer {o.amount} ({o.status})",
                    entity_type="offer",
                    entity_id=o.id,
                    land_code=o.land_code,
                )
            )
        for r in com_store.list_reservations(partner_phone=pp, land_code=lc, limit=100):
            events.append(
                _ev(
                    ts=r.created_at or r.updated_at,
                    stage="reservation",
                    source="commercial",
                    action="reservation",
                    summary=f"Reservation {r.status}",
                    entity_type="reservation",
                    entity_id=r.id,
                    land_code=r.land_code,
                )
            )
    except Exception:
        pass

    # Closing
    try:
        from app.closing import store as cl_store

        deals = cl_store.list_deals(partner_phone=pp, land_code=lc, limit=100)
        for d in deals:
            events.append(
                _ev(
                    ts=d.created_at or d.updated_at,
                    stage="deal",
                    source="closing",
                    action="deal",
                    summary=f"Deal {d.status}",
                    entity_type="deal",
                    entity_id=d.id,
                    land_code=d.land_code,
                )
            )
            for c in cl_store.list_contracts(deal_id=d.id, limit=50):
                events.append(
                    _ev(
                        ts=c.created_at or c.updated_at,
                        stage="contract",
                        source="closing",
                        action="contract",
                        summary=f"Contract {c.document_status}",
                        entity_type="contract",
                        entity_id=c.id,
                        land_code=d.land_code,
                    )
                )
            for p in cl_store.list_payments(deal_id=d.id, limit=50):
                events.append(
                    _ev(
                        ts=p.created_at or p.paid_at or p.due_at,
                        stage="payment",
                        source="closing",
                        action="payment",
                        summary=f"Payment {p.amount} ({p.status})",
                        entity_type="payment",
                        entity_id=p.id,
                        land_code=d.land_code,
                    )
                )
            for s in cl_store.list_settlements(deal_id=d.id, limit=50):
                events.append(
                    _ev(
                        ts=s.created_at or s.updated_at,
                        stage="settlement",
                        source="closing",
                        action="settlement",
                        summary=f"Settlement {s.status}",
                        entity_type="settlement",
                        entity_id=s.id,
                        land_code=d.land_code,
                    )
                )
    except Exception:
        pass

    # Deduplicate loosely by (source, entity_type, entity_id, action)
    seen: set[str] = set()
    unique: List[JourneyEvent] = []
    for e in events:
        key = f"{e.source}|{e.entity_type}|{e.entity_id}|{e.action}|{e.ts}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    unique.sort(key=lambda x: x.ts or "", reverse=True)
    return unique[: max(1, int(limit or 200))]


def _stage_from_action(action: str, entity_type: str) -> str:
    a = (action or "").lower()
    et = (entity_type or "").lower()
    for stage in STAGES:
        if stage in a or stage in et:
            return stage
    if "crm" in a or et.startswith("crm"):
        return "contact"
    if "commercial" in a:
        return "negotiation"
    if "closing" in a:
        return "deal"
    if "visit" in a:
        return "visit_result"
    return "visit"
