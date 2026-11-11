# -*- coding: utf-8 -*-
"""قرارداد یک کارت پیگیری. وب و اپ فقط همین را رسم می‌کنند."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .visit_requests import (
    APPROVED_STATUS,
    CANCELLED_STATUS,
    COMPLETED_STATUS,
    DEAL_DECISION_APPROVED,
    DEAL_DECISION_CLOSED,
    DEAL_DECISION_REJECTED,
    DISPUTED_STATUS,
    DONE_PENDING_STATUS,
    NO_SHOW_STATUS,
    PENDING_STATUS,
    VISIT_OUTCOME_FOLLOW_UP,
    VISIT_OUTCOME_INTERESTED,
    VISIT_OUTCOME_NOT_INTERESTED,
    visit_deal_decision,
    visit_outcome,
)


def _action(
    action_id: str,
    label: str,
    endpoint: str,
    *,
    method: str = "POST",
    tone: str = "primary",
    confirmation: str = "",
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "tone": tone,
        "confirmation": confirmation,
        "body": body or {},
    }


def _money(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _grouped(amount: int) -> str:
    return f"{int(amount):,}".replace(",", "،")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _visit_started(card: Dict[str, Any], now: datetime) -> bool:
    raw_date = str(card.get("visit_date") or "").strip()
    if not raw_date:
        return True
    raw_time = str(card.get("visit_time") or "00:00").strip() or "00:00"
    try:
        start = datetime.strptime(f"{raw_date[:10]} {raw_time[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return now >= start


def effective_state(card: Dict[str, Any]) -> str:
    """اول پول قطعی، بعد تصمیم معامله، بعد نتیجه بازدید، بعد حضور."""
    financial = card.get("financial_state") if isinstance(card.get("financial_state"), dict) else {}
    if str(financial.get("status") or "") == "paid" or card.get("withdrawal_paid"):
        return "paid"
    decision = visit_deal_decision(card)
    if decision == DEAL_DECISION_CLOSED or str(financial.get("status") or "") == "closed":
        return "closed"
    if decision in (DEAL_DECISION_APPROVED, "in_transaction") or str(card.get("tx_status") or "") == "in_transaction":
        return "deal_approved"
    if decision == DEAL_DECISION_REJECTED:
        return "deal_rejected"
    outcome = visit_outcome(card)
    if outcome:
        return outcome
    status = str(card.get("status") or "").strip()
    if status == DISPUTED_STATUS:
        return "disputed"
    if status == DONE_PENDING_STATUS:
        return "done_pending"
    if status == NO_SHOW_STATUS:
        return "no_show"
    if status == CANCELLED_STATUS:
        return "cancelled"
    if status == COMPLETED_STATUS:
        return "completed"
    if status == APPROVED_STATUS:
        return "approved"
    return "pending"


def _incoming(card: Dict[str, Any]) -> bool:
    return str(card.get("direction") or "") == "incoming"


def _amount_line(card: Dict[str, Any]) -> int:
    financial = card.get("financial_state") if isinstance(card.get("financial_state"), dict) else {}
    return _money(
        financial.get("amount")
        or card.get("deal_commission_amount")
        or card.get("required_commission")
    )


def build_follow_contract(card: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """یک اقدام اصلی. بقیه ثانویه یا خطرناک‌اند."""
    moment = now or datetime.now()
    state = effective_state(card)
    incoming = _incoming(card)
    vid = str(card.get("id") or "").strip()
    amount = _amount_line(card)
    marketer = str(card.get("marketer_name") or card.get("partner_name") or card.get("partner_phone") or "بازاریاب")
    shortfall = _money(card.get("wallet_shortfall"))
    hold = _money(card.get("listing_hold"))
    archived = bool(card.get("read_only") or card.get("archived"))
    primary = None
    secondary: List[Dict[str, Any]] = []
    danger: List[Dict[str, Any]] = []
    label = str(card.get("status_label") or "")
    next_actor = "none"
    disabled = ""

    def owner(action: str) -> str:
        return f"/express/partner/inbox-visits/{vid}/{action}"

    def mine(suffix: str) -> str:
        return f"/express/partner/requests/{vid}{suffix}"

    if archived:
        label = label or "بایگانی"
        disabled = "این کارت بایگانی است و فقط بازگرداندن دارد."
        secondary.append(_action(
            "restore",
            "بازگرداندن به پیگیری",
            f"/express/partner/api/requests/{vid}/restore",
            tone="secondary",
        ))
    elif incoming and state == "pending":
        label = "پذیرش وقت بازدید"
        next_actor = "owner"
        primary = _action("accept_visit", "پذیرش وقت بازدید", owner("approve"))
        danger.append(_action("reject_visit", "رد بازدید", owner("reject"), tone="danger", confirmation="این بازدید رد شود؟"))
    elif not incoming and state == "approved":
        label = "ثبت وضعیت حضور"
        next_actor = "marketer"
        if not _visit_started(card, moment):
            disabled = "از زمان بازدید می‌توانید وضعیت حضور را ثبت کنید."
        else:
            primary = _action("attendance_done", "بازدید انجام شد", mine("/complete"))
            danger.append(_action(
                "customer_absent",
                "مشتری نیامد",
                mine("/no-show"),
                tone="danger",
                confirmation="عدم حضور مشتری ثبت شود؟",
            ))
    elif not incoming and state == "done_pending":
        label = "منتظر تأیید بازدید توسط مالک"
        next_actor = "owner"
        phone = str(card.get("call_owner_phone") or card.get("owner_phone") or "").strip()
        if phone:
            secondary.append(_action("call_owner", "تماس با مالک", f"tel:{phone}", method="GET", tone="secondary"))
    elif incoming and state == "done_pending":
        label = "تأیید انجام بازدید"
        next_actor = "owner"
        primary = _action("confirm_attendance", "تأیید انجام بازدید", owner("complete"))
        danger.append(_action(
            "dispute_attendance",
            "اعتراض",
            owner("no_show"),
            tone="danger",
            confirmation="اعتراض به انجام بازدید ثبت شود؟ دلیل حداقل ۳ نویسه لازم است. این عدم حضور مشتری نیست.",
            body={"requires_reason": True},
        ))
    elif not incoming and state == "completed":
        label = "نتیجه بازدید"
        next_actor = "marketer"
        primary = _action(
            "record_result",
            "ثبت نتیجه",
            mine("/visit-result"),
            body={"choices": ["interested", "follow_up", "not_interested"], "default": ""},
        )
    elif state == VISIT_OUTCOME_INTERESTED and not incoming:
        label = "بازدید بعدی"
        next_actor = "marketer"
        primary = _action("next_visit", "بازدید بعدی", mine("/revisit"))
    elif state == VISIT_OUTCOME_INTERESTED and incoming:
        if card.get("can_confirm_deal"):
            label = "تأیید فروش"
            next_actor = "owner"
            primary = _action(
                "confirm_sale",
                "تأیید فروش",
                owner("confirm_deal"),
                confirmation=f"فروش برای {marketer} تأیید شود؟",
            )
        else:
            label = "علاقه‌مند"
    elif state == "deal_approved" and incoming:
        label = "بستن پرونده و پرداخت پورسانت"
        next_actor = "owner"
        if shortfall > 0:
            primary = _action(
                "cover_shortfall",
                "رفع کسری",
                str(card.get("wallet_charge_path") or "/express/partner/wallet/charge"),
                method="GET",
                confirmation=f"کسری {_grouped(shortfall)} تومان. بعد از شارژ این کارت تازه می‌شود.",
            )
        else:
            hold_bit = "بلوکه کافی است." if hold >= amount and amount else "مانده از موجودی قابل استفاده کم می‌شود."
            primary = _action(
                "close_case",
                "بستن پرونده و پرداخت پورسانت",
                owner("close_deal"),
                confirmation=f"پرداخت {_grouped(amount)} تومان به {marketer}. {hold_bit}",
            )
    elif state == "deal_approved":
        label = "فروش تأیید شد؛ منتظر بستن پرونده توسط مالک"
        next_actor = "owner"
    elif state == "closed":
        label = f"پرونده بسته شد؛ {_grouped(amount)} تومان به کیف پول افزوده شد" if not incoming and amount else "پرونده بسته شد"
        next_actor = "none"
        if not incoming:
            secondary.append(_action(
                "view_receipt",
                "مشاهده رسید",
                "/express/partner/commissions",
                method="GET",
                tone="secondary",
            ))
    elif state == "paid":
        label = "پرداخت شده"
        next_actor = "none"
    elif state == "deal_rejected":
        reason = str(card.get("deal_reject_reason") or card.get("notes") or "").strip()
        label = "معامله رد شد" + (f" — {reason}" if reason else "")
        next_actor = "none"
    elif state == "disputed":
        reason = str(card.get("dispute_reason") or "").strip()
        label = "اعتراض مالک" + (f" — {reason}" if reason else "")
        next_actor = "marketer"
    elif state in ("no_show", "cancelled"):
        actor = str(card.get("status_actor") or ("مالک" if incoming else "بازاریاب"))
        reason = str(card.get("dispute_reason") or card.get("notes") or "").strip()
        base = "عدم حضور" if state == "no_show" else "لغو شده"
        label = f"{base} توسط {actor}" + (f" — {reason}" if reason else "")
        next_actor = "none"
    elif state == VISIT_OUTCOME_FOLLOW_UP:
        label = "پیگیری دوباره"
        next_actor = "marketer"
        if not incoming:
            primary = _action("next_visit", "بازدید بعدی", mine("/revisit"))
    elif state == VISIT_OUTCOME_NOT_INTERESTED:
        label = "بی‌علاقه"
        next_actor = "none"
    elif state == "pending" and not incoming:
        label = label or "در انتظار پذیرش"
        next_actor = "owner"
    else:
        label = label or state

    if not archived and card.get("can_archive"):
        secondary.append(_action(
            "archive_card",
            "بایگانی این پیگیری",
            f"/express/partner/api/requests/{vid}/archive",
            tone="secondary",
        ))
    if not archived and card.get("can_remove"):
        danger.append(_action(
            "hide_card",
            "حذف از پیگیری من",
            f"/express/partner/requests/{vid}/remove",
            tone="danger",
            confirmation="این مورد فقط از پیگیری شما برداشته می‌شود و برای طرف دیگر می‌ماند.",
        ))

    if card.get("deal_overdue") and state == "deal_approved":
        label = "معامله دیرکرد دارد. " + label

    financial = {
        "amount": amount,
        "hold": hold,
        "status": "paid" if state == "paid" else ("shortfall" if shortfall and state == "deal_approved" and incoming else state),
        "receipt": "/express/partner/commissions" if state in ("closed", "paid") else "",
    }
    return {
        "effective_state": state,
        "status_label": label,
        "next_actor": next_actor,
        "primary_action": primary,
        "secondary_actions": secondary,
        "danger_actions": danger,
        "disabled_reason": disabled,
        "financial_state": financial,
        "needs_my_action": bool(primary) and (
            (incoming and next_actor == "owner") or ((not incoming) and next_actor == "marketer")
        ),
    }


def sort_follow_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """اول کارِ خودم، بعد دیرکرد، بعد تازه‌ترین."""
    ordered = sorted(
        cards,
        key=lambda card: str(card.get("updated_at") or card.get("created_at") or ""),
        reverse=True,
    )
    ordered.sort(key=lambda card: 0 if card.get("deal_overdue") else 1)
    ordered.sort(key=lambda card: 0 if (card.get("contract") or {}).get("needs_my_action") else 1)
    return ordered


def offer_contract(offer: Dict[str, Any]) -> Dict[str, Any]:
    oid = str(offer.get("id") or "").strip()
    proposed = str(offer.get("proposed_by") or "").strip().lower()
    your_turn = proposed not in ("special", "owner")
    base = f"/express/partner/inbox-offers/{oid}"
    primary = None
    secondary: List[Dict[str, Any]] = []
    danger: List[Dict[str, Any]] = []
    if your_turn:
        primary = _action("accept_offer", "پذیرش پیشنهاد", f"{base}/accept", confirmation="این پیشنهاد پذیرفته شود؟")
        secondary.append(_action(
            "counter_offer",
            "پیشنهاد متقابل",
            f"{base}/counter",
            tone="secondary",
            confirmation="مبلغ متقابل برای طرف مقابل فرستاده شود؟",
        ))
        danger.append(_action("reject_offer", "رد پیشنهاد", f"{base}/reject", tone="danger", confirmation="این پیشنهاد رد شود؟"))
    return {
        "effective_state": "offer",
        "status_label": "نوبت شما" if your_turn else "منتظر پاسخ طرف مقابل",
        "next_actor": "owner" if your_turn else "marketer",
        "primary_action": primary,
        "secondary_actions": secondary,
        "danger_actions": danger,
        "disabled_reason": "" if your_turn else "نوبت شما نیست.",
        "financial_state": {"amount": _money(offer.get("amount")), "hold": 0, "status": "offer", "receipt": ""},
        "your_turn": your_turn,
        "proposed_by": proposed,
    }
