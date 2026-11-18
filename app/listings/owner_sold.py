# -*- coding: utf-8 -*-
"""«فروخته شد» از طرف مالک آگهی.

دو مسیر، هر دو روی منطق موجود:

* ``vinor``: فروش از طریق بازدید یک بازاریاب وینور. همان مسیر پیگیری مالک اجرا
  می‌شود: «تأیید معامله» (confirm_deal) و بعد «بستن پرونده» (close_deal). پورسانت از
  بلوکهٔ انتشار به بازاریاب می‌رسد و آگهی فروخته‌شده و بایگانی می‌شود.
* ``outside``: مالک خودش بیرون از وینور فروخته. آگهی فروخته‌شده و بایگانی می‌شود.
  اگر هیچ بازدید انجام‌شده یا معاملهٔ بازی روی آگهی نباشد، بلوکه مثل لغو آگهی آزاد
  می‌شود. اگر بازاریابی بازدید انجام‌شده داشته باشد، بلوکه آزاد نمی‌شود و برای
  تصمیم ادمین علامت می‌خورد تا «فروخته شد» راه فرار از پورسانت نشود.

مالکیت روی سرور چک می‌شود. تکرار روی آگهی فروخته‌شده همان نتیجه را می‌دهد.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

CHANNEL_VINOR = "vinor"
CHANNEL_OUTSIDE = "outside"
CHANNELS = (CHANNEL_VINOR, CHANNEL_OUTSIDE)

LABEL = "فروخته شد"
CONFIRM_VINOR = (
    "فروش از طریق بازدید {name} ثبت شود؟ پورسانت اعلام‌شده از مبلغ بلوکه‌شده به کیف پول "
    "بازاریاب منتقل و آگهی بسته می‌شود."
)
CONFIRM_OUTSIDE = (
    "ملک را خودتان بیرون از وینور فروخته‌اید؟ آگهی بسته و از فهرست عمومی برداشته می‌شود "
    "و پورسانت بلوکه‌شده آزاد می‌شود."
)
CONFIRM_OUTSIDE_REVIEW = (
    "ملک را خودتان بیرون از وینور فروخته‌اید؟ آگهی بسته و از فهرست عمومی برداشته می‌شود. "
    "چون بازاریاب وینور از این ملک بازدید انجام‌شده دارد، پورسانت بلوکه‌شده تا بررسی "
    "پشتیبانی وینور آزاد نمی‌شود."
)

ERRORS_FA = {
    "forbidden": "فقط مالک آگهی می‌تواند آن را فروخته‌شده اعلام کند.",
    "not_found": "این آگهی پیدا نشد.",
    "invalid_channel": "روش فروش را انتخاب کنید.",
    "visit_required": "بازدیدی را که به فروش رسید انتخاب کنید.",
    "visit_not_found": "این بازدید برای این آگهی پیدا نشد یا هنوز انجام نشده است.",
    "failed": "ثبت فروش ممکن نشد. دوباره تلاش کنید.",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def is_sold(land: Dict[str, Any] | None) -> bool:
    return isinstance(land, dict) and _clean(land.get("express_status")).lower() == "sold"


def can_mark_sold(land: Dict[str, Any] | None, phone: str) -> bool:
    """دکمه فقط برای مالک همان آگهی و فقط وقتی هنوز فروخته نشده."""
    from app.listings.service import owner_phone, same_owner

    if not isinstance(land, dict) or not _clean(phone):
        return False
    if not same_owner(owner_phone(land), phone):
        return False
    return not is_sold(land)


def _resolve_owned(code: str, phone: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from app.listings.service import _listing_for_code, listings_path, _read_json

    items = _read_json(listings_path())
    return _listing_for_code(items, code, phone, require_owner=True)


def completed_visits(code: str, owner: str = "", rows: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """بازدیدهای انجام‌شدهٔ بازاریاب‌ها روی همین آگهی (کد قبلی هم حساب می‌شود)."""
    from app.express_partner.visit_requests import (
        COMPLETED_STATUS,
        canonical_land_code,
        load_visit_requests_fresh,
    )
    from app.listings.service import same_owner

    want = canonical_land_code(code)
    if not want:
        return []
    if rows is None:
        rows = load_visit_requests_fresh() or []
    out: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if _clean(row.get("status")) != COMPLETED_STATUS:
            continue
        if canonical_land_code(_clean(row.get("land_code"))) != want:
            continue
        partner = _clean(row.get("partner_phone"))
        if not partner or (owner and same_owner(partner, owner)):
            continue
        out.append(row)
    return out


def _visit_option(row: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean(row.get("partner_name")) or "بازاریاب وینور"
    day = _clean(row.get("visit_date"))
    label = f"{name} · بازدید {day}" if day else name
    return {
        "visit_id": _clean(row.get("id")),
        "partner_name": name,
        "visit_date": day,
        "deal_decision": _clean(row.get("deal_decision")),
        "label": label,
        "confirm_message": CONFIRM_VINOR.format(name=name),
    }


def _held_amount(code: str) -> int:
    try:
        from app.express_partner.commission_escrow import find_hold
        from app.utils.storage import load_express_commissions

        row = find_hold(load_express_commissions() or [], code)
        return int((row or {}).get("commission_amount") or 0)
    except Exception:
        return 0


def _open_deal(code: str) -> bool:
    try:
        from app.express_partner.commission_escrow import listing_has_open_deal

        if listing_has_open_deal(code):
            return True
        from app.utils.storage import load_express_commissions

        for row in load_express_commissions() or []:
            if not isinstance(row, dict):
                continue
            if _clean(row.get("commission_type")) != "deal":
                continue
            if _clean(row.get("land_code")) == code and _clean(row.get("status")).lower() == "pending":
                return True
    except Exception:
        return False
    return False


def sold_options(phone: str, code: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """گزینه‌های صفحهٔ «فروخته شد». فقط مالک."""
    from app.listings.service import code_key

    land, err = _resolve_owned(code, phone)
    if err or land is None:
        return None, err or "not_found"
    key = code_key(land)
    visits = [_visit_option(row) for row in completed_visits(key, phone)]
    review = bool(visits) or _open_deal(key)
    return {
        "ok": True,
        "code": key,
        "title": _clean(land.get("title")),
        "sold": is_sold(land),
        "can_mark_sold": can_mark_sold(land, phone),
        "label": LABEL,
        "visits": visits,
        "has_completed_visits": bool(visits),
        "review_required_if_outside": review,
        "held_amount": _held_amount(key),
        "outside_confirm_message": CONFIRM_OUTSIDE_REVIEW if review else CONFIRM_OUTSIDE,
        "outside_label": "خودم بیرون از وینور فروختم",
        "question": "ملک از طریق بازدید بازاریاب وینور فروخته شد؟",
    }, None


def _audit(action: str, *, phone: str, code: str, payload: Dict[str, Any]) -> None:
    try:
        from app.foundation.activity_store import append_activity

        append_activity(
            action=action,
            actor_key=_clean(phone),
            actor_role="owner",
            entity_type="listing",
            entity_id=code,
            land_code=code,
            object_type="listing",
            summary=f"Owner marked listing {code} sold ({payload.get('channel')})",
            payload=dict(payload),
            source="owner_mark_sold",
        )
    except Exception:
        pass


def _stamp_sold(code: str, phone: str, *, channel: str, visit_id: str, review: bool) -> Optional[Dict[str, Any]]:
    """آگهی را sold و با دلیل «بسته» بایگانی کن. بلوکه اینجا لمس نمی‌شود."""
    from app.listings.service import (
        ARCHIVE_CLOSED,
        _archive_now,
        _listing_for_code,
        _read_json,
        _stamp_archive,
        code_key,
        listings_lock,
        listings_path,
        save_listings,
    )

    with listings_lock():
        items = _read_json(listings_path())
        target, err = _listing_for_code(items, code, phone, require_owner=True)
        if err or target is None:
            return None
        stamp = _archive_now()
        target["express_status"] = "sold"
        extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
        if not extras.get("sold_at"):
            extras["sold_at"] = stamp
            extras["sold_by_owner"] = True
            extras["sold_channel"] = channel
            extras["sold_visit_id"] = visit_id
            extras["sold_review_required"] = bool(review)
        target["extras"] = extras
        target["sold_at"] = extras["sold_at"]
        _stamp_archive(target, ARCHIVE_CLOSED)
        written = save_listings(items)
        want = code_key(target)
        for land in written:
            if isinstance(land, dict) and code_key(land) == want:
                return land
        return target


def _sync_followups(land: Dict[str, Any]) -> None:
    from app.listings.service import _sync_archived_followups, code_key

    _sync_archived_followups(
        code_key(land),
        _clean(land.get("archived_reason")) or "closed",
        _clean(land.get("archived_at")),
    )


def _result(land: Dict[str, Any], *, already: bool, channel: str, review: bool, message: str) -> Dict[str, Any]:
    from app.listings.service import archive_payload, code_key

    body = archive_payload(land)
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    body.update({
        "ok": True,
        "code": code_key(land),
        "sold": True,
        "already": already,
        "can_mark_sold": False,
        "channel": _clean(extras.get("sold_channel")) or channel,
        "review_required": bool(extras.get("sold_review_required", review)),
        "message": message,
    })
    return body


def _sell_via_visit(phone: str, code: str, visit_id: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """همان دو قدم پیگیری مالک: تأیید معامله و بستن پرونده (پرداخت از بلوکه)."""
    from app.express_partner.special_visit_inbox import apply_special_visit_action, inject_visit_deal_chat
    from app.express_partner.visit_requests import (
        DEAL_DECISION_APPROVED,
        DEAL_DECISION_CLOSED,
        locked_mutate_visit_requests,
        visit_deal_decision,
    )

    held: Dict[str, Any] = {"steps": []}

    def _mutate(rows):
        rec = next((r for r in rows if isinstance(r, dict) and _clean(r.get("id")) == visit_id), None)
        if rec is None or rec not in completed_visits(code, phone, rows):
            held["err"] = "visit_not_found"
            return False
        saved = False
        decision = visit_deal_decision(rec)
        if decision == DEAL_DECISION_CLOSED:
            held["rec"] = rec
            return False
        if decision != DEAL_DECISION_APPROVED:
            out, err = apply_special_visit_action(
                rows, owner_phone=phone, visit_id=visit_id, action="confirm_deal",
            )
            if err:
                held["err"] = err
                return False
            saved = True
            held["steps"].append("confirm_deal")
            held["rec"] = out
        out, err = apply_special_visit_action(
            rows, owner_phone=phone, visit_id=visit_id, action="close_deal",
        )
        if err:
            held["err"] = err
            return saved
        held["steps"].append("close_deal")
        held["rec"] = out
        return True

    locked_mutate_visit_requests(_mutate)
    rec = held.get("rec")
    for step in held["steps"]:
        try:
            inject_visit_deal_chat(rec, decision={"confirm_deal": "approved", "close_deal": "closed"}[step])
        except Exception:
            pass
    return held.get("err"), held


def mark_sold(
    phone: str,
    code: str,
    *,
    channel: str,
    visit_id: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """(body, error_code, detail). error_code=None یعنی موفق یا تکراری."""
    from app.listings.service import code_key

    land, err = _resolve_owned(code, phone)
    if err or land is None:
        return None, err or "not_found", {}
    key = code_key(land)
    if is_sold(land):
        return _result(land, already=True, channel=channel, review=False,
                       message="این آگهی از قبل فروخته‌شده ثبت شده است."), None, {}
    chan = _clean(channel).lower()
    if chan not in CHANNELS:
        return None, "invalid_channel", {}

    if chan == CHANNEL_VINOR:
        vid = _clean(visit_id)
        if not vid:
            return None, "visit_required", {}
        if vid not in {_clean(row.get("id")) for row in completed_visits(key, phone)}:
            return None, "visit_not_found", {}
        deal_err, detail = _sell_via_visit(phone, key, vid)
        if deal_err:
            return None, deal_err, detail
        sold_land = _stamp_sold(key, phone, channel=chan, visit_id=vid, review=False)
        if sold_land is None:
            return None, "failed", detail
        _sync_followups(sold_land)
        _audit("owner_mark_sold", phone=phone, code=key,
               payload={"channel": chan, "visit_id": vid, "steps": detail.get("steps") or []})
        return _result(sold_land, already=False, channel=chan, review=False,
                       message="فروش ثبت شد. پورسانت به بازاریاب رسید و آگهی بسته شد."), None, detail

    visits = completed_visits(key, phone)
    review = bool(visits) or _open_deal(key)
    if review:
        # Flag before closing the listing, so no auto-release can slip in between.
        try:
            from app.express_partner.commission_escrow import REVIEW_OWNER_SOLD_OUTSIDE, flag_hold_for_review

            flag_hold_for_review(
                key,
                reason=REVIEW_OWNER_SOLD_OUTSIDE,
                actor_phone=phone,
                visit_ids=[_clean(row.get("id")) for row in visits],
            )
        except Exception:
            return None, "failed", {}
    sold_land = _stamp_sold(key, phone, channel=chan, visit_id="", review=review)
    if sold_land is None:
        return None, "failed", {}
    _sync_followups(sold_land)
    released = False
    if not review:
        try:
            from app.express_partner.commission_escrow import release_publish_hold

            released = release_publish_hold(key, reason="owner_sold_outside")
        except Exception:
            released = False
    _audit("owner_mark_sold", phone=phone, code=key,
           payload={"channel": chan, "review_required": review, "hold_released": released,
                    "visit_ids": [_clean(row.get("id")) for row in visits]})
    if review:
        message = ("آگهی فروخته‌شده ثبت و بسته شد. چون بازاریاب وینور بازدید انجام‌شده داشت، "
                   "پورسانت بلوکه‌شده تا بررسی پشتیبانی وینور آزاد نمی‌شود.")
    else:
        message = "آگهی فروخته‌شده ثبت و بسته شد. پورسانت بلوکه‌شده آزاد شد."
    body = _result(sold_land, already=False, channel=chan, review=review, message=message)
    body["hold_released"] = released
    return body, None, {}


def error_message(err: str) -> str:
    if err == "wallet_insufficient":
        try:
            from app.express_partner.special_visit_inbox import listing_deal_error_fa

            return listing_deal_error_fa(err)
        except Exception:
            pass
    if err in ERRORS_FA:
        return ERRORS_FA[err]
    try:
        from app.express_partner.special_visit_inbox import LISTING_DEAL_ERROR_FA

        if err in LISTING_DEAL_ERROR_FA:
            return LISTING_DEAL_ERROR_FA[err]
    except Exception:
        pass
    return ERRORS_FA["failed"]
