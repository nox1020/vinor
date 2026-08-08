"""Card Registry — first-class cards with state, version, and history.

Cards are persisted inside message ``agent_actions`` (backward compatible).
New fields are additive: ``card_id``, ``schema_version``, ``state``, ``version``,
``history``, ``result``, ``updated_at``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Card states (shared)
# ---------------------------------------------------------------------------
STATE_PENDING = "pending"
STATE_CONFIRMED = "confirmed"
STATE_EXECUTING = "executing"
STATE_COMPLETED = "completed"
STATE_CANCELLED = "cancelled"
STATE_EXPIRED = "expired"
STATE_FAILED = "failed"
STATE_ACTIVE = "active"
STATE_USED = "used"
STATE_SUPERSEDED = "superseded"

CONFIRM_TRANSITIONS: dict[str, frozenset[str]] = {
    # pending→completed allowed: confirm+execute often happens in one request
    STATE_PENDING: frozenset(
        {
            STATE_CONFIRMED,
            STATE_CANCELLED,
            STATE_EXPIRED,
            STATE_EXECUTING,
            STATE_COMPLETED,
            STATE_FAILED,
        }
    ),
    STATE_CONFIRMED: frozenset({STATE_EXECUTING, STATE_COMPLETED, STATE_FAILED}),
    STATE_EXECUTING: frozenset({STATE_COMPLETED, STATE_FAILED}),
    STATE_COMPLETED: frozenset({STATE_COMPLETED}),
    STATE_CANCELLED: frozenset({STATE_CANCELLED}),
    STATE_EXPIRED: frozenset({STATE_EXPIRED}),
    STATE_FAILED: frozenset({STATE_PENDING, STATE_FAILED}),  # retry → pending
}

HINT_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_ACTIVE: frozenset({STATE_USED, STATE_EXPIRED, STATE_ACTIVE}),
    STATE_USED: frozenset({STATE_USED}),
    STATE_EXPIRED: frozenset({STATE_EXPIRED}),
    STATE_PENDING: frozenset({STATE_ACTIVE, STATE_EXPIRED, STATE_CANCELLED}),
}


@dataclass(frozen=True)
class CardSpec:
    type: str
    schema_version: int = 1
    kind: str = "confirm"  # confirm | hint | land | copy | other
    initial_state: str = STATE_PENDING
    transitions: dict[str, frozenset[str]] = field(default_factory=dict)
    expire_minutes: int | None = 30
    renderer: str = "confirm"  # logical renderer key for clients
    title_default: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _confirm_spec(ctype: str, title: str) -> CardSpec:
    return CardSpec(
        type=ctype,
        schema_version=1,
        kind="confirm",
        initial_state=STATE_PENDING,
        transitions=CONFIRM_TRANSITIONS,
        expire_minutes=30,
        renderer="confirm",
        title_default=title,
    )


CARD_SPECS: dict[str, CardSpec] = {
    "confirm_visit": _confirm_spec("confirm_visit", "تأیید ثبت بازدید"),
    "confirm_complete_visit": _confirm_spec("confirm_complete_visit", "تأیید: بازدید انجام شد"),
    "confirm_deal": _confirm_spec("confirm_deal", "تأیید معامله"),
    "confirm_release": _confirm_spec("confirm_release", "تأیید بستن معامله"),
    "confirm_partner_application": _confirm_spec(
        "confirm_partner_application", "تأیید همکاری بازاریاب"
    ),
    "confirm_log_call": _confirm_spec("confirm_log_call", "تأیید ثبت تماس"),
    "confirm_followup": _confirm_spec("confirm_followup", "تأیید ثبت پیگیری"),
    "confirm_visit_result": _confirm_spec("confirm_visit_result", "تأیید ثبت نتیجه بازدید"),
    "confirm_no_show": _confirm_spec("confirm_no_show", "تأیید عدم حضور"),
    "confirm_offer": _confirm_spec("confirm_offer", "تأیید ثبت پیشنهاد"),
    "confirm_counter_offer": _confirm_spec("confirm_counter_offer", "تأیید پیشنهاد متقابل"),
    "confirm_reservation": _confirm_spec("confirm_reservation", "تأیید رزرو نرم"),
    "confirm_contract": _confirm_spec("confirm_contract", "تأیید ثبت قرارداد"),
    "confirm_payment_milestone": _confirm_spec(
        "confirm_payment_milestone", "تأیید ثبت قسط"
    ),
    "confirm_settlement": _confirm_spec("confirm_settlement", "تأیید باز کردن تسویه"),
    "confirm_lead": _confirm_spec("confirm_lead", "ثبت مشتری"),
    "confirm_task": _confirm_spec("confirm_task", "تأیید ثبت وظیفه"),
    "need_login": CardSpec(
        type="need_login",
        kind="hint",
        initial_state=STATE_ACTIVE,
        transitions=HINT_TRANSITIONS,
        expire_minutes=None,
        renderer="need_login",
        title_default="ورود لازم است",
    ),
    "next_action": CardSpec(
        type="next_action",
        kind="hint",
        initial_state=STATE_ACTIVE,
        transitions=HINT_TRANSITIONS,
        expire_minutes=24 * 60,
        renderer="next_action",
        title_default="کار بعدی",
    ),
    "copy_blocks": CardSpec(
        type="copy_blocks",
        kind="copy",
        initial_state=STATE_ACTIVE,
        transitions=HINT_TRANSITIONS,
        expire_minutes=None,
        renderer="copy_blocks",
        title_default="متن آگهی",
    ),
    "land": CardSpec(
        type="land",
        kind="land",
        initial_state=STATE_ACTIVE,
        transitions=HINT_TRANSITIONS,
        expire_minutes=None,
        renderer="land",
        title_default="فایل",
    ),
    "progress": CardSpec(
        type="progress",
        kind="other",
        initial_state=STATE_ACTIVE,
        transitions=HINT_TRANSITIONS,
        expire_minutes=None,
        renderer="progress",
        title_default="پیشرفت پرونده",
    ),
}


def get_spec(card_type: str) -> CardSpec | None:
    return CARD_SPECS.get(str(card_type or "").strip())


def new_card_id() -> str:
    return uuid.uuid4().hex


def normalize_card(action: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure registry fields exist on a card/action dict (idempotent)."""
    if not isinstance(action, dict):
        return {}
    out = dict(action)
    ctype = str(out.get("type") or "").strip()
    spec = get_spec(ctype)
    if not out.get("card_id"):
        out["card_id"] = new_card_id()
    if "schema_version" not in out:
        out["schema_version"] = int(spec.schema_version) if spec else 1
    if not out.get("state"):
        # legacy used ``status`` for confirm cards
        legacy = str(out.get("status") or "").strip()
        if legacy:
            out["state"] = legacy
        elif spec:
            out["state"] = spec.initial_state
        else:
            out["state"] = STATE_PENDING
    # keep ``status`` in sync for old UI/renderers
    out["status"] = out["state"]
    if "version" not in out:
        out["version"] = 1
    if not isinstance(out.get("history"), list):
        out["history"] = [
            {
                "at": str(out.get("created_at") or _now_iso()),
                "state": out["state"],
                "event": "created",
            }
        ]
    if not out.get("created_at"):
        out["created_at"] = _now_iso()
    if not out.get("updated_at"):
        out["updated_at"] = out["created_at"]
    if spec and not out.get("renderer"):
        out["renderer"] = spec.renderer
    return out


def can_transition(card_type: str, from_state: str, to_state: str) -> bool:
    spec = get_spec(card_type)
    table = (spec.transitions if spec else None) or CONFIRM_TRANSITIONS
    allowed = table.get(str(from_state or "").strip(), frozenset())
    return str(to_state or "").strip() in allowed


def apply_card_transition(
    action: dict[str, Any],
    new_state: str,
    *,
    event: str = "",
    result: dict[str, Any] | None = None,
    lines: list[str] | None = None,
    note: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Transition card state, bump version, append history. Returns new dict."""
    card = normalize_card(action)
    ctype = str(card.get("type") or "")
    cur = str(card.get("state") or STATE_PENDING)
    target = str(new_state or "").strip() or cur
    if target != cur and not can_transition(ctype, cur, target):
        # Soft-fail: still record as failed transition attempt for observability
        hist = list(card.get("history") or [])
        hist.append(
            {
                "at": _now_iso(),
                "state": cur,
                "event": "illegal_transition",
                "attempted": target,
            }
        )
        card["history"] = hist[-40:]
        card["updated_at"] = _now_iso()
        return card

    card["state"] = target
    card["status"] = target
    card["version"] = int(card.get("version") or 1) + (0 if target == cur else 1)
    card["updated_at"] = _now_iso()
    if lines is not None:
        card["lines"] = [str(x) for x in lines if str(x).strip()]
    if note:
        card["note"] = str(note)
    if result is not None:
        prev = card.get("result") if isinstance(card.get("result"), dict) else {}
        merged = dict(prev)
        merged.update(result)
        card["result"] = merged
    if actor:
        card["actor"] = str(actor)
    hist = list(card.get("history") or [])
    hist.append(
        {
            "at": card["updated_at"],
            "state": target,
            "event": event or target,
            "actor": actor or "",
        }
    )
    card["history"] = hist[-40:]
    # Clear live token once terminal (except pending)
    if target in (
        STATE_COMPLETED,
        STATE_CONFIRMED,
        STATE_CANCELLED,
        STATE_EXPIRED,
        STATE_FAILED,
    ):
        # Keep token for audit but mark inactive; renderers ignore non-pending tokens
        card["token_active"] = False
    return card


def build_confirm_card(
    *,
    card_type: str,
    token: str,
    title: str = "",
    lines: list[str] | None = None,
    land_code: str = "",
    confirm_label: str = "",
    cancel_label: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = get_spec(card_type)
    ui: dict[str, Any] = {
        "type": card_type,
        "token": token,
        "token_active": True,
        "title": title or (spec.title_default if spec else "تأیید اقدام"),
        "lines": list(lines or []),
        "land_code": str(land_code or ""),
        "status": STATE_PENDING,
        "state": STATE_PENDING,
    }
    if confirm_label:
        ui["confirm_label"] = confirm_label
    if cancel_label:
        ui["cancel_label"] = cancel_label
    if extra:
        for k, v in extra.items():
            if k not in ui:
                ui[k] = v
    return normalize_card(ui)


def result_lines_from_confirm(
    *,
    card_type: str,
    message: str = "",
    out: dict[str, Any] | None = None,
) -> list[str]:
    """Human-readable result lines shown on the living card after confirm."""
    data = out if isinstance(out, dict) else {}
    lines: list[str] = []
    if message:
        lines.append(str(message))
    visit_id = str(data.get("visit_id") or "").strip()
    if visit_id:
        lines.append(f"شماره پیگیری بازدید: {visit_id}")
    # کد فایل در خط متن نمی‌آید — سمت کاربر با کارت فایل نشان داده می‌شود
    tx = str(data.get("tx_mode") or "").strip()
    if tx:
        lines.append(f"وضعیت معامله: {tx}")
    app_id = str(data.get("application_id") or "").strip()
    if app_id:
        lines.append(f"شناسه درخواست: {app_id}")
    deal_id = str(data.get("deal_id") or "").strip()
    if deal_id:
        lines.append(f"شناسه معامله: {deal_id}")
    offer_id = str(data.get("offer_id") or "").strip()
    if offer_id:
        lines.append(f"شناسه پیشنهاد: {offer_id}")
    contact_id = str(data.get("contact_id") or "").strip()
    if contact_id:
        lines.append(f"شناسه مشتری: {contact_id}")
    lines.append(f"زمان تأیید: {_now_iso()}")
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for line in lines:
        s = str(line).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq[:12]


# Optional hook type for future action handlers
CardActionHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
