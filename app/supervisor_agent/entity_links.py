# -*- coding: utf-8 -*-
"""لینک موجودیت‌ها در پنل ادمین برای گزارش‌های Supervisor Agent."""
from __future__ import annotations

import re
from typing import Any


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    return digits[-11:] if len(digits) >= 11 else digits


def build_entity_link(
    *,
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    partner_phone: str = "",
) -> dict[str, str]:
    et = (entity_type or "").strip().lower()
    eid = (entity_id or "").strip()
    land = str(land_code or "").strip()
    partner = _norm_phone(partner_phone)

    label = ""
    url = ""

    if land:
        label = land
        url = f"/admin/lands?q={land}"
    elif et == "land" and eid:
        label = eid
        url = f"/admin/lands?q={eid}"
    elif et in ("partner", "contact", "lead") and (partner or eid):
        ph = partner or _norm_phone(eid)
        if ph:
            label = f"همکار {ph[-4:]}" if len(ph) >= 4 else "همکار"
            url = f"/admin/express/partners/{ph}"
    elif et == "negotiation" and eid:
        label = f"مذاکره {eid[:8]}"
        if land:
            url = f"/admin/lands?q={land}"
    elif et == "visit" and eid:
        label = f"بازدید {eid[:8]}"
        if land:
            url = f"/admin/lands?q={land}"
    elif et == "deal" and eid:
        label = f"معامله {eid[:8]}"
        if land:
            url = f"/admin/lands?q={land}"

    return {"entity_label": label, "entity_url": url}


def entity_meta(
    *,
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    partner_phone: str = "",
    customer_name: str = "",
    case_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    links = build_entity_link(
        entity_type=entity_type,
        entity_id=entity_id,
        land_code=land_code,
        partner_phone=partner_phone,
    )
    meta: dict[str, Any] = {
        "supervisor": True,
        "agent_name": "Supervisor Agent",
        "entity_type": (entity_type or "").strip(),
        "entity_id": (entity_id or "").strip(),
        "land_code": str(land_code or "").strip(),
        "case_id": str(case_id or "").strip(),
        "customer_name": (customer_name or "").strip(),
    }
    if links.get("entity_label"):
        meta["entity_label"] = links["entity_label"]
    if links.get("entity_url"):
        meta["entity_url"] = links["entity_url"]
    if extra:
        meta.update(extra)
    return meta
