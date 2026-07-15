# -*- coding: utf-8 -*-
"""مربی فروش همکاران اکسپرس — اسکریپت مرحله‌ای، متن آگهی، پیگیری منظم اعلان+پیامک.

نوبت‌های روزانه (تهران): ۱۰، ۱۴، ۲۰ — تا فروش نهایی فایل ادامه دارد.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, current_app, url_for

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

from ..services.sms import is_valid_iran_mobile, normalize_iran_mobile, send_sms_direct
from ..services.sms_config import get_sms_line_number
from ..utils.storage import (
    ensure_file,
    load_express_partners,
    load_express_visit_requests,
    load_settings,
    load_sms_history,
    save_sms_history,
    _load,
    _save,
    data_dir,
)

_APPROVED = frozenset({"approved", "active", "enabled", "ok", "true", "1"})
# سه نوبت منظم به وقت تهران — تا فروش نهایی ادامه دارد
_NUDGE_HOURS = (10, 14, 20)
_STATE_NAME = "sales_coach_nudge_state.json"
_LOCK_NAME = "sales_coach_nudge.run.lock"
_SLOT_LABELS = {10: "صبح", 14: "ظهر", 20: "شب"}


def _tehran_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Tehran"))
        except Exception:
            pass
    return datetime.now()


def _is_partner_approved(profile: Dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    status = str(profile.get("status") or "").strip().lower()
    return profile.get("status") is True or status in _APPROVED


def _fmt_toman(amount: Any) -> str:
    try:
        v = max(0, int(str(amount).replace(",", "").strip() or "0"))
    except Exception:
        v = 0
    if v == 0:
        return "0"
    return f"{v:,}".replace(",", "،")


def _first_name(full_name: str) -> str:
    name = (full_name or "").strip()
    if not name:
        return "همکار"
    return name.split()[0]


def coach_tip_for_stage(
    *,
    stage_label: str = "",
    has_visit: bool = False,
    in_transaction: bool = False,
    sold: bool = False,
    commission_amount: int = 0,
) -> str:
    """یک جمله عملی برای چت/اعلان — تشویق به فروش."""
    amt = _fmt_toman(commission_amount) if commission_amount else ""
    por = f" تا پورسانت {amt} تومن مال خودت بشه" if amt and amt != "0" else " تا پورسانتت قطعی بشه"
    if sold:
        return "فروش تموم شد؛ برو از کیف پول برداشت بزن."
    if in_transaction:
        return f"معامله رو از همین چت ببند یا پیگیری کن{por}."
    label = (stage_label or "").strip()
    if "پورسانت بازدید" in label:
        return "صبر کن تا پورسانت بازدید تأیید بشه؛ بعد معامله رو از چت ثبت کن."
    if label in ("در انتظار تأیید انجام",) or "تأیید انجام" in label:
        return "منتظر تأیید انجام بازدید باش؛ بعد قدم بعدی رو از چت می‌گی."
    if label in ("معامله یا بازدید مجدد", "بازدید انجام شد"):
        return f"حله؛ از همین چت درخواست معامله بده{por}."
    if label in ("بازدید تأییدشد", "در انتظار بازدید", "پیگیری بازدید") or has_visit:
        return "بازدید مهمه؛ وقتی رفتی، از چت «بازدید انجام شد» رو ثبت کن."
    if label in ("بازاریابی", "بازاریابی مجدد"):
        return (
            "آگهی بده یا وقتی مشتری آماده شد از همین کارت «ثبت بازدید» بزن "
            f"{por}."
        )
    return (
        f"دیوار بذار و تو اینستا استوری/پست بزن"
        f"{por}. متنش رو از همین چت بخواه؛ بازدید هم از اینجا ثبت می‌شه."
    )


def build_voided_encouragement(
    *,
    land_code: str = "",
    land_title: str = "",
    reason: str = "",
) -> Tuple[str, str, str]:
    """تشکر گرم بعد از منتفی شدن + راهنمای بازاریابی مجدد.

    Returns: (notif_title, chat_body, notif_body)
    """
    code = (land_code or "").strip()
    title = (land_title or "").strip()
    file_bit = f"فایل {code}" if code else "این فایل"
    if title:
        file_bit = f"{file_bit} ({title})"
    reason_s = (reason or "").strip()
    head = "معامله/پیگیری منتفی شد"
    if reason_s:
        head = reason_s

    notif_title = "ممنون از تلاشت"
    chat_body = (
        f"{notif_title}.\n"
        f"{head} — برای {file_bit}.\n"
        "تلاشت رو دیدی؛ گاهی مشتری منصرف می‌شه و طبیعیه.\n\n"
        "حالا دوباره برو جلو: دیوار رو آپدیت/ثبت کن، نردبان بزن، "
        "اینستا پست/استوری بذار، و به هرکی ممکنه مشتری باشه معرفی کن.\n"
        "متن دیوار یا کپشن خواستی همین‌جا بگو تا برات بنویسم."
    )
    notif_body = (
        f"{head}. ممنون که تلاش کردی. "
        "دوباره: دیوار + نردبان + اینستا + معرفی. "
        "متن آماده رو از چت بخواه."
    )
    return notif_title, chat_body, notif_body


def deliver_voided_encouragement(
    *,
    partner_phone: str,
    land_code: str = "",
    land_title: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    """اعلان داخل اپ + پیام در چت مأموریت (در صورت وجود)."""
    ph = normalize_iran_mobile(str(partner_phone or "").strip())
    if not is_valid_iran_mobile(ph):
        return {"ok": False, "error": "bad_phone"}
    title, chat_body, notif_body = build_voided_encouragement(
        land_code=land_code,
        land_title=land_title,
        reason=reason,
    )
    out: Dict[str, Any] = {"ok": True, "notif": False, "chat": False}
    try:
        from app.services.notifications import add_notification

        action_url = _home_url()
        add_notification(
            ph,
            title,
            notif_body,
            ntype="sales_coach",
            ad_id=(land_code or None),
            action_url=action_url,
            source="voided_encouragement",
        )
        out["notif"] = True
    except Exception as exc:
        current_app.logger.warning("voided encouragement notif failed: %s", exc)

    try:
        from .partner_missions import append_mission_chat_followup, get_active_mission

        mission = get_active_mission(ph)
        tid = ""
        if mission and str(mission.get("land_code") or "").strip() == str(land_code or "").strip():
            tid = str(mission.get("thread_id") or "").strip()
        if tid:
            out["chat"] = bool(
                append_mission_chat_followup(
                    ph,
                    land_code=str(land_code or ""),
                    thread_id=tid,
                    body=chat_body,
                )
            )
        else:
            # بدون مأموریت فعال: باز هم در ترد فعال بگذار
            from app.ai.audience import AUDIENCE_PARTNER
            from app.ai.chat_store import append_exchange, ensure_active_thread

            tid = ensure_active_thread(ph, audience=AUDIENCE_PARTNER)
            append_exchange(
                ph,
                "",
                chat_body,
                thread_id=tid,
                audience=AUDIENCE_PARTNER,
            )
            out["chat"] = True
    except Exception as exc:
        current_app.logger.warning("voided encouragement chat failed: %s", exc)
    return out


def _inject_partner_system_chat(
    partner_phone: str,
    *,
    land_code: str = "",
    body: str,
    agent_actions: list | None = None,
) -> bool:
    """پیام سیستمی در چت همکار (ترد مأموریت اگر باشد، وگرنه ترد فعال)."""
    ph = normalize_iran_mobile(str(partner_phone or "").strip())
    text = (body or "").strip()
    actions = [a for a in (agent_actions or []) if isinstance(a, dict)][:3]
    if not is_valid_iran_mobile(ph) or (not text and not actions):
        return False
    try:
        from .partner_missions import append_mission_chat_followup, get_active_mission

        mission = get_active_mission(ph)
        tid = ""
        code = str(land_code or "").strip()
        if mission and str(mission.get("land_code") or "").strip() == code and code:
            tid = str(mission.get("thread_id") or "").strip()
        if tid:
            return bool(
                append_mission_chat_followup(
                    ph,
                    land_code=code,
                    thread_id=tid,
                    body=text,
                    agent_actions=actions,
                )
            )
        from app.ai.audience import AUDIENCE_PARTNER
        from app.ai.chat_store import append_exchange, ensure_active_thread

        tid = ensure_active_thread(ph, audience=AUDIENCE_PARTNER)
        append_exchange(
            ph,
            "",
            text,
            thread_id=tid,
            audience=AUDIENCE_PARTNER,
            assistant_agent_actions=actions or None,
        )
        return True
    except Exception as exc:
        current_app.logger.warning("partner system chat inject failed: %s", exc)
        return False


def _referral_invite_action() -> Dict[str, Any]:
    """کارت CTA دعوت همکار بعد از فروش."""
    try:
        from flask import url_for
        from .referrals import REFERRAL_BONUS_AMOUNT

        bonus = int(REFERRAL_BONUS_AMOUNT or 0)
        bonus_fa = f"{bonus:,}".replace(",", "،") if bonus else "۰"
        url = url_for("express_partner.invite_colleagues")
    except Exception:
        bonus_fa = "۵۰۰٬۰۰۰"
        url = "/express/partner/invite"
    return {
        "type": "next_action",
        "title": "دعوت همکار",
        "subtitle": (
            f"همکار جدید دعوت کن؛ با تأیید هر نفر، {bonus_fa} تومان "
            "پورسانت دعوت به موجودی‌ات اضافه می‌شود."
        ),
        "cta": "دعوت کن و پورسانت بگیر",
        "url": url,
    }


def build_progress_update(
    *,
    event: str,
    land_code: str = "",
    land_title: str = "",
    visit_date: str = "",
    amount: Any = 0,
    commission_type: str = "",
    visit_commission_pending: bool = False,
) -> Tuple[str, str, str]:
    """پیام پیشرفت فروش برای نوتیف و چت.

    Returns: (notif_title, chat_body, notif_body)
    """
    code = (land_code or "").strip()
    title = (land_title or "").strip()
    file_bit = f"فایل {code}" if code else "فایل"
    if title:
        file_bit = f"{file_bit} ({title})"
    vdate = (visit_date or "").strip()
    ev = (event or "").strip()

    def _amt() -> str:
        try:
            v = max(0, int(str(amount).replace(",", "").strip() or "0"))
        except Exception:
            v = 0
        return f"{v:,}".replace(",", "،") if v else "۰"

    if ev == "visit_approved":
        notif_title = "بازدید تأیید شد"
        chat_body = (
            f"{notif_title} — {file_bit}"
            + (f" · {vdate}" if vdate else "")
            + ".\n"
            "قدم بعدی: با مشتری هماهنگ کن؛ بعد از بازدید از همین چت بگو «بازدید انجام شد» "
            "تا کارت تأیید بیاید."
        )
        notif_body = f"{file_bit} تأیید شد. بعد از بازدید از چت بگو بازدید انجام شد."
        return notif_title, chat_body, notif_body

    if ev == "visit_done_pending":
        notif_title = "انجام بازدید ثبت شد"
        chat_body = (
            f"{notif_title} — {file_bit}.\n"
            "قدم بعدی: صبر کن تا ادمین تأیید کند؛ وضعیت را از همین چت پیگیری کن."
        )
        notif_body = f"{file_bit}: انجام بازدید ثبت شد؛ منتظر تأیید ادمین باش."
        return notif_title, chat_body, notif_body

    if ev == "visit_completed":
        notif_title = "بازدید توسط ادمین تأیید شد"
        if visit_commission_pending:
            chat_body = (
                f"{notif_title} — {file_bit}.\n"
                "پورسانت بازدید در انتظار تأیید است.\n"
                "قدم بعدی: بعد از واریز پورسانت، از همین چت می‌تونی «ثبت معامله» را بزنی."
            )
            notif_body = f"{file_bit} تأیید شد؛ پورسانت در انتظار تأیید."
        else:
            chat_body = (
                f"{notif_title} — {file_bit}.\n"
                "قدم بعدی: از همین چت بگو «ثبت معامله» تا کارت تأیید بیاید."
            )
            notif_body = f"{file_bit} تأیید شد؛ از چت معامله را ثبت کن."
        return notif_title, chat_body, notif_body

    if ev == "deal_started":
        notif_title = "معامله شروع شد"
        chat_body = (
            f"{notif_title} — {file_bit}.\n"
            "قدم بعدی: منتظر تأیید ادمین باش؛ بعد از تأیید، پورسانت فروش به کیف پول می‌آید."
        )
        notif_body = f"{file_bit}: معامله شروع شد؛ منتظر تأیید ادمین."
        return notif_title, chat_body, notif_body

    if ev == "commission_approved":
        ct = (commission_type or "").strip().lower()
        if ct == "referral" or code == "referral":
            kind = "پورسانت دعوت"
            is_deal_sale = False
        elif "visit" in ct:
            kind = "پورسانت بازدید"
            is_deal_sale = False
        else:
            kind = "پورسانت فروش"
            is_deal_sale = True
        amt = _amt()
        notif_title = "پورسانت واریز شد"
        file_line = f" · {file_bit}" if code and code != "referral" else ""
        if is_deal_sale:
            chat_body = (
                f"{notif_title}: +{amt} تومان ({kind}){file_line}.\n"
                "فروش این فایل نهایی شد.\n"
                "پیشنهاد بعدی: همکار جدید دعوت کن و با تأیید هر نفر، پورسانت دعوت بگیر."
            )
            notif_body = f"+{amt} تومن {kind}. همکار دعوت کن و پورسانت بگیر."
        else:
            chat_body = (
                f"{notif_title}: +{amt} تومان ({kind}){file_line}.\n"
                + (
                    "قدم بعدی: از همین چت بگو «ثبت معامله» تا کارت تأیید بیاید."
                    if "visit" in ct
                    else "قدم بعدی: از کیف پول می‌تونی برداشت بزنی؛ ادامه فروش را از همین چت جلو ببر."
                )
            )
            notif_body = (
                f"+{amt} تومن {kind}. از چت معامله را ثبت کن."
                if "visit" in ct
                else f"+{amt} تومن {kind} وارد کیف پول شد."
            )
        return notif_title, chat_body, notif_body

    if ev == "withdrawal_paid":
        amt = _amt()
        notif_title = "برداشت پرداخت شد"
        chat_body = (
            f"{notif_title}: −{amt} تومان به حسابت واریز شد.\n"
            "اگر ادامه فروش داری، از همین چت قدم بعدی را بپرس."
        )
        notif_body = f"−{amt} تومن به حسابت واریز شد."
        return notif_title, chat_body, notif_body

    if ev == "deal_auto_released":
        notif_title = "مهلت معامله تمام شد"
        chat_body = (
            f"{notif_title} — {file_bit}.\n"
            "معاملهٔ در انتظار تأیید بعد از ۵ روز آزاد شد و می‌تونی دوباره از همین چت "
            "«ثبت معامله» بزنی. اول مطمئن شو مشتری هنوز آماده‌ست."
        )
        notif_body = f"{file_bit}: مهلت معامله تمام شد؛ از چت دوباره ثبت کن."
        return notif_title, chat_body, notif_body

    return "", "", ""


def deliver_partner_progress_update(
    *,
    partner_phone: str,
    event: str,
    land_code: str = "",
    land_title: str = "",
    visit_date: str = "",
    amount: Any = 0,
    commission_type: str = "",
    visit_commission_pending: bool = False,
) -> Dict[str, Any]:
    """اعلان داخل اپ + پیام در چت — مکمل پیامک (جایگزین آن نیست)."""
    ph = normalize_iran_mobile(str(partner_phone or "").strip())
    if not is_valid_iran_mobile(ph):
        return {"ok": False, "error": "bad_phone"}
    title, chat_body, notif_body = build_progress_update(
        event=event,
        land_code=land_code,
        land_title=land_title,
        visit_date=visit_date,
        amount=amount,
        commission_type=commission_type,
        visit_commission_pending=visit_commission_pending,
    )
    if not chat_body:
        return {"ok": False, "skipped": True, "error": "unsupported_event"}

    ct = (commission_type or "").strip().lower()
    code = str(land_code or "").strip()
    invite_after_deal = (
        (event or "").strip() == "commission_approved"
        and ct not in ("referral",)
        and "visit" not in ct
        and code != "referral"
    )

    out: Dict[str, Any] = {"ok": True, "notif": False, "chat": False}
    try:
        from app.services.notifications import add_notification

        action_url = _home_url()
        if invite_after_deal:
            try:
                from flask import url_for

                action_url = url_for("express_partner.invite_colleagues")
            except Exception:
                action_url = "/express/partner/invite"
        add_notification(
            ph,
            title,
            notif_body,
            ntype="sales_progress",
            ad_id=(land_code or None) if land_code and land_code != "referral" else None,
            action_url=action_url,
            source=f"progress_{event}",
        )
        out["notif"] = True
    except Exception as exc:
        current_app.logger.warning("progress update notif failed: %s", exc)

    actions = [_referral_invite_action()] if invite_after_deal else None
    out["chat"] = _inject_partner_system_chat(
        ph,
        land_code=str(land_code or ""),
        body=chat_body,
        agent_actions=actions,
    )
    return out


def build_coach_chat_prompt(*, code: str, title: str = "", stage_label: str = "") -> str:
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    stage = (stage_label or "").strip()
    bits = [f"فایل {code_s}"]
    if title_s:
        bits.append(f"({title_s})")
    head = " ".join(bits)
    if stage in ("در حال معامله",):
        return (
            f"{head} تو معامله‌ست. "
            "بگو الان چیکار کنم؛ اگر باید ببندم، کارت تأیید بستن معامله رو بده."
        )
    if stage in ("معامله یا بازدید مجدد", "بازدید انجام شد"):
        return (
            f"{head} آماده‌ست برای معامله. "
            "کارت تأیید معامله رو بده؛ اگر بازدید مجدد لازم بود اول بپرس."
        )
    if stage in ("بازدید تأییدشد",):
        return (
            f"{head}: بازدید تأیید شده. "
            "کارت «بازدید انجام شد» رو بده تا ثبت کنم."
        )
    if stage in ("درخواست بازدید", "در انتظار بازدید", "پیگیری بازدید"):
        return (
            f"{head} تو مسیر بازدیده. "
            "وضعیت رو کوتاه بگو و بگو قدم بعدی چیه."
        )
    if stage and stage not in ("علاقه‌مند",):
        return (
            f"{head} تو مرحله «{stage}»ه. "
            "قدم بعدی فروش رو بگو؛ اگر ثبت لازم بود کارت تأییدش رو بده."
        )
    return (
        f"{head} رو بهم دادن. "
        "متن دیوار و کپشن اینستا رو آماده کن و بگو چطور معرفی کنم؛ "
        "وقتی مشتری آماده بازدید شد از همین چت ثبتش می‌کنیم."
    )


def build_journey_chat_cta(
    *,
    code: str,
    title: str = "",
    tx_mode: str = "",
    stage_label: str = "",
    funnel_key: str = "",
    can_revisit: bool = False,
) -> Dict[str, str]:
    """CTA کارت سفر خانه → پرامپت چت؛ هم‌تراز با مرحله قیف (funnel_key) و tx_mode."""
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    mode = (tx_mode or "").strip()
    stage = (stage_label or "").strip()
    key = (funnel_key or "").strip()
    bits = [f"فایل {code_s}"]
    if title_s:
        bits.append(f"({title_s})")
    head = " ".join(bits)

    visit_step_line = (
        "همان اول propose_visit_request را با land_code خالی بزن (کد را از کاربر نپرس؛ بدون نام/شماره/تاریخ)؛ "
        "بعد فقط همان فیلدی که ابزار گفته را بپرس و جواب را دوباره به ابزار بفرست: "
        "نام مشتری → موبایل → لیست تاریخ ۱ تا ۵ → فقط شمارهٔ تاریخ. "
        "چند سؤال را یکجا نپرس."
    )
    visit_prompt = f"{head}: ثبت بازدید را یکی‌یکی شروع کن. {visit_step_line}"
    revisit_prompt = f"{head}: بازدید مجدد را یکی‌یکی شروع کن. {visit_step_line}"
    marketing_prompt = (
        f"{head}: متن دیوار و کپشن اینستا رو آماده کن و بگو چطور معرفی کنم. "
        "وقتی مشتری آماده شد از همین چت بازدید ثبت می‌کنیم."
    )

    # اولویت ۱: وضعیت‌های درحال‌انتظار / بستن معامله
    if mode == "deal_pending" or stage == "در حال معامله":
        return {
            "label": "وضعیت معامله",
            "icon": "fa-clock",
            "action": "status",
            "prompt": (
                f"{head}: فروشم ثبت شده و منتظر تأیید ادمین برای بستن فایل و پورسانت است؛ "
                "وضعیت کوتاه بگو. اگر انصراف می‌خوام بگو کارت بستن معامله بده."
            ),
        }
    if mode == "release":
        return {
            "label": "بستن معامله",
            "icon": "fa-check-circle",
            "action": "release",
            "prompt": f"{head}: می‌خوام معامله رو ببندم — کارت تأیید بده.",
        }
    if mode in ("visit_pending", "visit_done_pending", "visit_commission_pending"):
        return {
            "label": "وضعیت بازدید",
            "icon": "fa-clock",
            "action": "status",
            "prompt": (
                f"{head} هنوز تو تأییده؛ وضعیت رو کوتاه بگو و بگو قدم بعدی چیه."
            ),
        }
    if mode == "visit_done" or stage == "بازدید تأییدشد":
        return {
            "label": "بازدید انجام شد",
            "icon": "fa-map-marker-alt",
            "action": "complete_visit",
            "prompt": f"{head}: بازدید انجام شد — کارت تأییدش رو بده.",
        }

    # اولویت ۲: مرحله قیف جاری
    if key in ("assigned", "marketing") or stage in ("بازاریابی", "بازاریابی مجدد"):
        return {
            "label": "بازاریابی کن",
            "icon": "fa-bullhorn",
            "action": "marketing",
            "prompt": marketing_prompt,
            # مسیر روشن به مرحله بازدید — بدون گیر کردن روی بازاریابی
            "secondary_label": "ثبت بازدید",
            "secondary_icon": "fa-calendar-days",
            "secondary_action": "visit",
            "secondary_prompt": visit_prompt,
        }
    if key == "visit_request":
        if mode == "visit" or not mode:
            return {
                "label": "ثبت بازدید",
                "icon": "fa-calendar-days",
                "action": "visit",
                "prompt": visit_prompt,
                "secondary_label": "آگهی / معرفی",
                "secondary_icon": "fa-bullhorn",
                "secondary_action": "marketing",
                "secondary_prompt": marketing_prompt,
            }
        return {
            "label": "وضعیت بازدید",
            "icon": "fa-clock",
            "action": "status",
            "prompt": (
                f"{head} هنوز تو مسیر بازدیده؛ وضعیت رو کوتاه بگو و بگو قدم بعدی چیه."
            ),
        }
    if key == "deal_or_revisit" or mode == "deal" or stage in ("معامله یا بازدید مجدد", "بازدید انجام شد"):
        return {
            "label": "ثبت معامله",
            "icon": "fa-handshake",
            "action": "deal",
            "prompt": f"{head}: می‌خوام معامله ثبت کنم — کارت تأیید بده.",
            "secondary_label": "بازدید مجدد" if can_revisit else "",
            "secondary_icon": "fa-calendar-plus" if can_revisit else "",
            "secondary_action": "visit" if can_revisit else "",
            "secondary_prompt": (
                revisit_prompt
            ) if can_revisit else "",
        }
    if mode == "visit":
        return {
            "label": "ثبت بازدید",
            "icon": "fa-calendar-days",
            "action": "visit",
            "prompt": visit_prompt,
            "secondary_label": "آگهی / معرفی",
            "secondary_icon": "fa-bullhorn",
            "secondary_action": "marketing",
            "secondary_prompt": marketing_prompt,
        }
    if stage in ("بازاریابی", "بازاریابی مجدد") or mode in ("", "hidden"):
        return {
            "label": "بازاریابی کن",
            "icon": "fa-bullhorn",
            "action": "marketing",
            "prompt": marketing_prompt,
            "secondary_label": "ثبت بازدید",
            "secondary_icon": "fa-calendar-days",
            "secondary_action": "visit",
            "secondary_prompt": visit_prompt,
        }
    return {
        "label": "ثبت بازدید",
        "icon": "fa-calendar-days",
        "action": "visit",
        "prompt": visit_prompt,
    }


def enrich_funnel_steps_for_nav(
    steps: List[Dict[str, Any]] | None,
    *,
    code: str,
    title: str = "",
    tx_mode: str = "",
    can_revisit: bool = False,
) -> List[Dict[str, Any]]:
    """هر مرحله قیف را قابل‌جابه‌جایی در چت می‌کند (کلیک → پرامپت مرحله)."""
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    mode = (tx_mode or "").strip()
    bits = [f"فایل {code_s}"] if code_s else ["فایل مأموریت"]
    if title_s:
        bits.append(f"({title_s})")
    head = " ".join(bits)

    visit_step_line = (
        "همان اول propose_visit_request را با land_code خالی بزن (کد را از کاربر نپرس؛ بدون نام/شماره/تاریخ)؛ "
        "بعد فقط همان فیلدی که ابزار گفته را بپرس و جواب را دوباره به ابزار بفرست: "
        "نام مشتری → موبایل → لیست تاریخ ۱ تا ۵ → فقط شمارهٔ تاریخ. "
        "چند سؤال را یکجا نپرس."
    )
    visit_prompt = f"{head}: ثبت بازدید را یکی‌یکی شروع کن. {visit_step_line}"
    marketing_prompt = (
        f"{head}: متن دیوار و کپشن اینستا رو آماده کن و بگو چطور معرفی کنم. "
        "وقتی مشتری آماده شد از همین چت بازدید ثبت می‌کنیم."
    )
    complete_prompt = f"{head}: بازدید انجام شد — کارت تأییدش رو بده."
    deal_prompt = f"{head}: می‌خوام معامله ثبت کنم — کارت تأیید بده."
    status_prompt = f"{head}: وضعیت مأموریت و قدم بعدی رو کوتاه بگو."

    out: List[Dict[str, Any]] = []
    for raw in steps or []:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        key = str(step.get("key") or "").strip()
        state = str(step.get("state") or "todo").strip()
        prompt = ""
        actionable = False

        if key == "assigned":
            prompt = (
                f"{head}: اختصاص شده. قدم بعدی بازاریابی یا ثبت بازدید برای مشتری — "
                "کوتاه بگو از کجا شروع کنم."
            )
            actionable = True
        elif key == "marketing":
            prompt = marketing_prompt
            actionable = True
        elif key == "visit_request":
            if mode == "visit_done":
                prompt = complete_prompt
            elif mode in ("visit_pending", "visit_done_pending", "visit_commission_pending"):
                prompt = status_prompt
            else:
                prompt = visit_prompt
            # در معامله باز قفل می‌شود؛ بقیه مراحل به مسیر بازدید برمی‌گردند
            actionable = mode not in ("deal_pending", "release", "blocked")
        elif key == "deal_or_revisit":
            if mode == "deal":
                prompt = deal_prompt
                actionable = True
            elif mode == "deal_pending":
                prompt = (
                    f"{head}: فروشم ثبت شده و منتظر تأیید ادمین است؛ "
                    "وضعیت کوتاه بگو. اگر انصراف می‌خوام بگو کارت بستن معامله بده."
                )
                actionable = True
            elif mode == "release":
                prompt = f"{head}: می‌خوام معامله رو ببندم — کارت تأیید بده."
                actionable = True
            elif mode == "visit_commission_pending":
                prompt = (
                    f"{head}: منتظر تأیید پورسانت بازدید هستم؛ وضعیت و قدم بعدی رو بگو."
                )
                actionable = True
            elif can_revisit and mode not in ("deal_pending", "release", "blocked", "hidden"):
                prompt = (
                    f"{head}: هنوز برای معامله آماده‌ام نیستم؛ "
                    "اگر بازدید مجدد لازم است یکی‌یکی شروع کن، وگرنه بگو قدم تا معامله چیه."
                )
                actionable = True
            elif state == "current":
                prompt = (
                    f"{head}: هنوز معامله فعال نیست. "
                    "بگو برای رسیدن به معامله چه قدمی لازم است (از همین چت)."
                )
                actionable = True
            else:
                # مرحلهٔ هنوز نرسیده — قابل‌کلیک برای پرسیدن مسیر، بدون propose_deal
                prompt = (
                    f"{head}: هنوز به معامله نرسیده‌ام؛ "
                    "کوتاه بگو الان کدام قدم (بازدید/انجام/پورسانت) مانده."
                )
                actionable = True
        else:
            prompt = status_prompt
            actionable = state in ("current", "done")

        step["chat_prompt"] = prompt if actionable else ""
        step["chat_intent"] = ""
        if actionable:
            if key == "marketing":
                step["chat_intent"] = "marketing"
            elif key == "visit_request":
                if mode == "visit_done":
                    step["chat_intent"] = "complete_visit"
                elif mode not in (
                    "visit_pending",
                    "visit_done_pending",
                    "visit_commission_pending",
                ):
                    step["chat_intent"] = "visit"
            elif key == "deal_or_revisit":
                if mode == "deal":
                    step["chat_intent"] = "deal"
                elif mode == "release":
                    step["chat_intent"] = "release"
                # deal_pending / visit_commission_pending / راهنما → بدون intent ابزار
        step["actionable"] = bool(actionable and prompt)
        out.append(step)
    return out


def build_limited_ai_quick_prompts(
    *,
    me_phone: str = "",
    has_pending_app: bool = False,
) -> List[Dict[str, str]]:
    """چیپ‌های نیت‌محور برای مهمان / کاربر عادی — پیام کوتاه + intent ابزار."""
    out: List[Dict[str, str]] = []

    _ICONS = {
        "coop_levels": "fa-layer-group",
        "coop_terms": "fa-percent",
        "coop_status": "fa-clock",
        "coop_apply": "fa-user-plus",
        "find_land": "fa-magnifying-glass",
    }

    def add(label: str, *, prompt: str, intent: str) -> None:
        label = (label or "").strip()
        prompt = (prompt or "").strip()
        intent = (intent or "").strip()
        if not label or not prompt or not intent:
            return
        out.append({
            "label": label,
            "prompt": prompt,
            "intent": intent,
            "icon": _ICONS.get(intent, "fa-sparkles"),
        })

    add("سطوح همکاری", prompt="سطوح همکاری چیه؟", intent="coop_levels")
    add("پورسانت", prompt="پورسانت چطوره؟", intent="coop_terms")

    if has_pending_app:
        add("وضعیت درخواست", prompt="وضعیت درخواست همکاری‌ام چیه؟", intent="coop_status")
    elif (me_phone or "").strip():
        add("ثبت درخواست", prompt="می‌خوام همکار شم", intent="coop_apply")
    else:
        add("شروع همکاری", prompt="می‌خوام همکار شم", intent="coop_apply")

    add("پیدا کردن ملک", prompt="یه فایل مناسب می‌خوام", intent="find_land")
    return out[:4]


def build_ai_quick_prompts(
    *,
    code: str = "",
    title: str = "",
    stage_label: str = "",
    is_mission: bool = False,
    tx_mode: str = "",
    can_revisit: bool = False,
) -> List[Dict[str, str]]:
    """چیپ‌های نیت‌محور همکار — وابسته به مرحله مأموریت/فروش."""
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    stage = (stage_label or "").strip()
    mode = (tx_mode or "").strip()
    head = f"فایل {code_s}" if code_s else "فایل مأموریت"
    if title_s:
        head = f"{head} ({title_s})"

    out: List[Dict[str, str]] = []

    _ICONS = {
        "next_action": "fa-compass",
        "release": "fa-check-circle",
        "deal": "fa-handshake",
        "visit": "fa-calendar-days",
        "complete_visit": "fa-map-marker-alt",
        "marketing": "fa-bullhorn",
    }

    def add(label: str, *, prompt: str, intent: str) -> None:
        label = (label or "").strip()
        prompt = (prompt or "").strip()
        intent = (intent or "").strip()
        if label and prompt and intent:
            out.append({
                "label": label,
                "prompt": prompt,
                "intent": intent,
                "icon": _ICONS.get(intent, "fa-sparkles"),
            })

    add("قدم بعدی", prompt="قدم بعدی‌م چیه؟", intent="next_action")

    if mode in ("deal_pending", "release") or stage == "در حال معامله":
        add("بستن معامله", prompt=f"{head}: معامله رو ببند", intent="release")
    elif mode in ("visit_pending", "visit_done_pending", "visit_commission_pending", "status"):
        add("وضعیت", prompt=f"{head}: وضعیتش چیه؟", intent="next_action")
    elif mode == "deal" or stage in ("معامله یا بازدید مجدد", "بازدید انجام شد"):
        add("ثبت معامله", prompt=f"{head}: معامله ثبت کن", intent="deal")
        if can_revisit:
            add(
                "بازدید مجدد",
                prompt=f"{head}: بازدید مجدد را یکی‌یکی شروع کن",
                intent="visit",
            )
    elif mode == "complete_visit" or mode == "visit_done" or stage == "بازدید تأییدشد":
        add("بازدید انجام شد", prompt=f"{head}: بازدید انجام شد", intent="complete_visit")
    elif mode == "visit":
        add("ثبت بازدید", prompt=f"{head}: بازدید را یکی‌یکی ثبت کن", intent="visit")
        add("آگهی", prompt=f"{head}: متن دیوار و اینستا بده", intent="marketing")
    elif mode == "marketing" or stage in ("بازاریابی", "بازاریابی مجدد") or is_mission:
        add("آگهی دیوار", prompt=f"{head}: متن آگهی بده", intent="marketing")
        add("ثبت بازدید", prompt=f"{head}: بازدید را یکی‌یکی ثبت کن", intent="visit")
    else:
        add("ثبت بازدید", prompt=f"{head}: بازدید را یکی‌یکی ثبت کن", intent="visit")

    # بدون تکرار intent یکسان پشت‌سرهم
    seen: set[str] = set()
    deduped: List[Dict[str, str]] = []
    for item in out:
        key = f"{item.get('intent')}|{item.get('label')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:4]


def draft_listing_copy(land: Dict[str, Any], *, channel: str = "both") -> Dict[str, str]:
    """متن آماده آگهی از روی داده فایل — بدون فراخوانی مدل."""
    code = str(land.get("code") or "").strip()
    title = str(land.get("title") or "ملک").strip()
    city = str(land.get("city") or "").strip()
    loc = str(land.get("location") or "").strip()
    cat = str(land.get("category") or "").strip()
    price = land.get("price_total") or land.get("price")
    try:
        price_i = int(str(price).replace(",", "").strip() or "0")
    except Exception:
        price_i = 0
    price_fa = _fmt_toman(price_i) if price_i else "توافقی"
    built = str(
        land.get("villa_built_area") or land.get("built_area") or land.get("size") or ""
    ).strip()
    land_area = str(land.get("villa_land_area") or land.get("land_area") or "").strip()
    desc = str(land.get("description") or land.get("desc") or "").strip()
    if len(desc) > 160:
        desc = desc[:157] + "…"

    place = " / ".join(x for x in (city, loc) if x) or "ایران"
    area_bits = []
    if built:
        area_bits.append(f"بنا {built} متر")
    if land_area:
        area_bits.append(f"زمین {land_area} متر")
    area_line = "، ".join(area_bits) if area_bits else ""

    divar_lines = [
        title,
        "",
        f"📍 {place}",
    ]
    if cat:
        divar_lines.append(f"🏷 {cat}")
    if area_line:
        divar_lines.append(area_line)
    divar_lines.append(f"💰 قیمت: {price_fa} تومان")
    if desc:
        divar_lines.extend(["", desc])
    divar_lines.extend(
        [
            "",
            "برای بازدید هماهنگ کنید.",
            f"کد فایل وینور: {code}" if code else "از طریق وینور اکسپرس",
        ]
    )
    divar = "\n".join(divar_lines).strip()

    hashtags = " ".join(
        h
        for h in (
            "#ملک",
            f"#{city}" if city else "",
            f"#{cat}" if cat else "",
            "#وینور",
            "#زمین" if "زمین" in (cat + title) else "",
            "#ویلا" if "ویلا" in (cat + title) else "",
            "#باغ" if "باغ" in (cat + title) else "",
        )
        if h
    )
    ig_lines = [
        f"✨ {title}",
        f"📍 {place}",
    ]
    if area_line:
        ig_lines.append(area_line)
    ig_lines.append(f"💰 {price_fa} تومان")
    ig_lines.extend(
        [
            "",
            "علاقه‌مندید؟ دایرکت بدید یا تماس بگیرید 👇",
            hashtags,
        ]
    )
    instagram = "\n".join(ig_lines).strip()

    ch = (channel or "both").strip().lower()
    out: Dict[str, str] = {"channel": ch}
    if ch in ("divar", "both", ""):
        out["divar"] = divar
    if ch in ("instagram", "insta", "both", ""):
        out["instagram"] = instagram
    out["tips"] = (
        "دیوار: عنوان کوتاه + عکس واضح + قیمت. "
        "اینستا: ۳–۵ عکس/ریلز + استوری با لوکیشن. "
        "هر تماس → سریع در اپ درخواست بازدید ثبت کن."
    )
    return out


def resolve_stuck_nudge_for_partner(
    phone: str,
    *,
    assigned_lands: List[Dict[str, Any]],
    visit_rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    بهترین فایل باز برای پیگیری — اولویت با مأموریت فعال؛ تا sold ادامه دارد.
    """
    ph = (phone or "").strip()
    if not ph:
        return None
    from .routes import _home_funnel_for_land, _home_score_suggested_land

    mission = None
    mission_code = ""
    mission_tid = ""
    try:
        from .partner_missions import refresh_mission_if_land_closed

        mission = refresh_mission_if_land_closed(ph)
        if mission:
            mission_code = str(mission.get("land_code") or "").strip()
            mission_tid = str(mission.get("thread_id") or "").strip()
    except Exception:
        mission = None

    def _nudge_from_land(land: Dict[str, Any], *, is_mission: bool = False) -> Optional[Dict[str, Any]]:
        st = str(land.get("_assignment_status") or "").strip().lower()
        if st == "sold" or land.get("_is_expired"):
            return None
        code = str(land.get("code") or "").strip()
        if not code:
            return None
        funnel = _home_funnel_for_land(ph, land, visit_rows=visit_rows)
        stage = str(funnel.get("stage_label") or "")
        in_tx = st == "in_transaction" or bool(land.get("_in_transaction"))
        has_row = any(
            isinstance(r, dict)
            and str(r.get("partner_phone") or "").strip() == ph
            and str(r.get("land_code") or "").strip() == code
            for r in (visit_rows or [])
        )
        tip = coach_tip_for_stage(
            stage_label=stage,
            has_visit=has_row,
            in_transaction=in_tx,
            sold=False,
            commission_amount=int(land.get("_commission_amount") or 0),
        )
        return {
            "code": code,
            "title": str(land.get("title") or code).strip(),
            "stage_label": stage,
            "commission_amount": int(land.get("_commission_amount") or 0),
            "tip": tip,
            "in_transaction": in_tx,
            "has_visit": has_row,
            "is_mission": is_mission,
            "mission_thread_id": mission_tid if is_mission else "",
        }

    if mission_code:
        for land in assigned_lands or []:
            if not isinstance(land, dict):
                continue
            if str(land.get("code") or "").strip() != mission_code:
                continue
            picked = _nudge_from_land(land, is_mission=True)
            if picked:
                return picked
        # فایل موقتاً در لیست خانه نیست — مأموریت را نکش؛ از کاتالوگ راهنما بساز
        try:
            from app.utils.storage import load_ads_cached

            land_row = next(
                (
                    l
                    for l in (load_ads_cached() or [])
                    if isinstance(l, dict)
                    and str(l.get("code") or "").strip() == mission_code
                ),
                None,
            )
            if land_row:
                proxy = dict(land_row)
                proxy.setdefault("_assignment_status", "active")
                proxy.setdefault("_commission_amount", 0)
                picked = _nudge_from_land(proxy, is_mission=True)
                if picked:
                    return picked
        except Exception:
            pass
        try:
            current_app.logger.info(
                "sales_coach nudge: mission land %s missing from assigned; keep mission",
                mission_code,
            )
        except Exception:
            pass

    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    now = datetime.utcnow()
    for land in assigned_lands or []:
        if not isinstance(land, dict):
            continue
        st = str(land.get("_assignment_status") or "").strip().lower()
        if st == "sold" or land.get("_is_expired"):
            continue
        code = str(land.get("code") or "").strip()
        if not code:
            continue
        funnel = _home_funnel_for_land(ph, land, visit_rows=visit_rows)
        stage = str(funnel.get("stage_label") or "")
        in_tx = st == "in_transaction" or bool(land.get("_in_transaction"))
        has_row = any(
            isinstance(r, dict)
            and str(r.get("partner_phone") or "").strip() == ph
            and str(r.get("land_code") or "").strip() == code
            for r in (visit_rows or [])
        )
        score = float(_home_score_suggested_land(land, now=now))
        if in_tx:
            score += 40
        elif stage in ("بازدید انجام شد",):
            score += 30
        elif stage in ("بازدید تأییدشد", "در انتظار بازدید", "پیگیری بازدید"):
            score += 20
        elif not has_row:
            score += 25
        if score > best_score:
            best_score = score
            tip = coach_tip_for_stage(
                stage_label=stage,
                has_visit=has_row,
                in_transaction=in_tx,
                sold=False,
                commission_amount=int(land.get("_commission_amount") or 0),
            )
            best = {
                "code": code,
                "title": str(land.get("title") or code).strip(),
                "stage_label": stage,
                "commission_amount": int(land.get("_commission_amount") or 0),
                "tip": tip,
                "in_transaction": in_tx,
                "has_visit": has_row,
                "is_mission": False,
                "mission_thread_id": "",
            }
    return best


def _nudge_phase(nudge_count: int) -> str:
    """شدت پیام بر اساس تعداد یادآوری‌های قبلی همین فایل."""
    n = max(0, int(nudge_count or 0))
    if n <= 1:
        return "start"
    if n <= 4:
        return "follow"
    if n <= 9:
        return "push"
    return "urgent"


def build_nudge_messages(
    nudge: Dict[str, Any],
    *,
    partner_name: str = "",
    slot_hour: int = 20,
    nudge_count: int = 0,
) -> Tuple[str, str, str]:
    """(title, notif_body, sms_body) — متناسب مرحله + نوبت روز + شدت پیگیری."""
    name = _first_name(partner_name)
    code = str(nudge.get("code") or "").strip()
    title_land = str(nudge.get("title") or code).strip()
    amt = _fmt_toman(nudge.get("commission_amount") or 0)
    in_tx = bool(nudge.get("in_transaction"))
    stage = str(nudge.get("stage_label") or "").strip()
    has_visit = bool(nudge.get("has_visit"))
    phase = _nudge_phase(nudge_count)
    slot = _SLOT_LABELS.get(int(slot_hour), "امروز")
    por = f"پورسانت تا {amt} تومن" if amt and amt != "0" else "پورسانتت"

    if in_tx:
        titles = {
            "start": "معامله رو جمع کن",
            "follow": "پیگیری معامله",
            "push": "معامله هنوز بازه",
            "urgent": "امروز معامله رو ببند",
        }
        bodies = {
            "start": f"{name}، فایل {title_land} در معامله است. با مشتری هماهنگ کن تا {por} قطعی بشه.",
            "follow": f"{name}، هنوز معامله {title_land} بسته نشده. یک تماس کوتاه کافی‌ست.",
            "push": f"{name}، معامله {code} معطل مونده. الان پیگیری کن؛ {por} منتظرته.",
            "urgent": f"{name}، چند بار یادآوری شد — فایل {code} رو همین امروز ببند و {por} رو بگیر.",
        }
        sms_map = {
            "start": f"وینور\n{name} معامله {code} رو ببند\n{por}",
            "follow": f"وینور\nپیگیری معامله {code}\n{por}",
            "push": f"وینور\n{name} معامله {code} معطل است\nالان تماس بگیر\n{por}",
            "urgent": f"وینور\nفوری: معامله {code} رو ببند\n{por}",
        }
    elif stage in ("بازدید انجام شد",) or "انجام" in stage:
        titles = {
            "start": "درخواست معامله بده",
            "follow": "بعد از بازدید پیگیری کن",
            "push": "معامله رو شروع کن",
            "urgent": "فروش رو نهایی کن",
        }
        bodies = {
            "start": f"{name}، بازدید {title_land} انجام شده. الان درخواست معامله بده تا {por} مال خودت بشه.",
            "follow": f"{name}، مشتری {code} رو پیگیری کن و معامله رو ثبت کن.",
            "push": f"{name}، از بازدید {code} چند وقته گذشته — درخواست معامله رو عقب ننداز.",
            "urgent": f"{name}، فروش {code} نزدیکه؛ امروز معامله رو ثبت کن و {por} رو بگیر.",
        }
        sms_map = {
            "start": f"وینور\n{name} بعد بازدید {code}\nدرخواست معامله بده\n{por}",
            "follow": f"وینور\nپیگیری معامله {code}\n{por}",
            "push": f"وینور\n{name} معامله {code} رو شروع کن\n{por}",
            "urgent": f"وینور\nفوری: فروش {code}\nمعامله ثبت کن\n{por}",
        }
    elif has_visit or stage in ("بازدید تأییدشد", "در انتظار بازدید", "پیگیری بازدید"):
        titles = {
            "start": "بازدید رو جدی بگیر",
            "follow": "یادآوری بازدید",
            "push": "بازدید رو عقب ننداز",
            "urgent": "امروز بازدید رو انجام بده",
        }
        bodies = {
            "start": f"{name}، برای {title_land} بازدید داری. قبلش فایل رو مرور کن و با مشتری هماهنگ باش.",
            "follow": f"{name}، نوبت {slot}: وضعیت بازدید {code} رو چک کن و جلو ببر.",
            "push": f"{name}، بازدید {code} هنوز تمام نشده. امروز پیگیری کن تا به فروش برسه.",
            "urgent": f"{name}، چند بار گفتیم — بازدید {code} رو امروز ببند؛ بعدش معامله و {por}.",
        }
        sms_map = {
            "start": f"وینور\n{name} بازدید {code}\nهماهنگ کن\n{por}",
            "follow": f"وینور\nیادآوری بازدید {code}\n{por}",
            "push": f"وینور\n{name} بازدید {code} رو امروز انجام بده\n{por}",
            "urgent": f"وینور\nفوری: بازدید {code}\nامروز تمام کن\n{por}",
        }
    else:
        # معرفی / آگهی
        titles = {
            "start": "فایل رو آگهی کن",
            "follow": "یادآوری فروش",
            "push": "هنوز آگهی نزدی؟",
            "urgent": "امروز حتماً آگهی کن",
        }
        bodies = {
            "start": (
                f"{name}، فایل {title_land} مال توست. تو دیوار آگهی کن و تو اینستا پست/استوری بذار "
                f"تا بفروشی و {por} بگیری."
            ),
            "follow": (
                f"{name}، نوبت {slot}: فایل {code} هنوز فروش نرفته. "
                f"دیوار یا اینستا رو امروز کار کن — {por}."
            ),
            "push": (
                f"{name}، چند بار یادآوری شد. فایل {code} رو همین امروز تو دیوار و اینستا بگذار؛ "
                f"بدون آگهی فروشی نیست."
            ),
            "urgent": (
                f"{name}، پیگیری جدی: فایل {code} معطل مونده. "
                f"الان آگهی کن، تماس‌ها رو به بازدید تبدیل کن، {por} مال خودته."
            ),
        }
        sms_map = {
            "start": f"وینور\n{name} فایل {code} رو تو دیوار/اینستا آگهی کن\n{por}",
            "follow": f"وینور\nیادآوری {slot}: فایل {code}\nآگهی کن تا بفروشی\n{por}",
            "push": f"وینور\n{name} هنوز {code} آگهی نشده\nامروز دیوار+اینستا\n{por}",
            "urgent": f"وینور\nفوری: فایل {code}\nالان آگهی کن\n{por}",
        }

    title = titles.get(phase) or titles["follow"]
    body = bodies.get(phase) or bodies["follow"]
    sms = sms_map.get(phase) or sms_map["follow"]
    if bool(nudge.get("is_mission")):
        title = f"ماموریت {code}" if code else "ماموریت فروش"
        body = f"ماموریت فایل {code} — تا معامله رها نکن. {body}"
        sms = f"ماموریت وینور فایل {code}: {sms}"
    return title, body, sms


def _detail_url(code: str) -> str:
    try:
        return url_for("express_partner.land_detail", code=code, _external=True)
    except Exception:
        return f"https://vinor.ir/express/partner/lands/{code}"


def _home_url() -> str:
    try:
        return url_for("express_partner.home", _external=True)
    except Exception:
        return "https://vinor.ir/express/partner/home"


def _load_state() -> Dict[str, Any]:
    path = ensure_file("SALES_COACH_NUDGE_STATE_FILE", _STATE_NAME, {}, current_app)
    data = _load(path)
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any]) -> None:
    path = ensure_file("SALES_COACH_NUDGE_STATE_FILE", _STATE_NAME, {}, current_app)
    _save(path, state)


def _partner_track(state: Dict[str, Any], phone: str, code: str) -> Dict[str, Any]:
    tracks = state.setdefault("partner_tracks", {})
    if not isinstance(tracks, dict):
        tracks = {}
        state["partner_tracks"] = tracks
    key = f"{phone}|{code}"
    row = tracks.get(key)
    if not isinstance(row, dict):
        row = {"nudge_count": 0}
        tracks[key] = row
    return row


def _try_acquire_run_lock():
    try:
        lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        return fd
    except FileExistsError:
        try:
            lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
            age = time.time() - os.path.getmtime(lock_path)
            if age > 3600:
                os.remove(lock_path)
                return _try_acquire_run_lock()
        except Exception:
            pass
        return None
    except Exception:
        return None


def _release_run_lock(fd) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path = os.path.join(data_dir(current_app), _LOCK_NAME)
        if os.path.isfile(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


def _sms_enabled() -> bool:
    raw = os.environ.get("VINOR_SALES_COACH_SMS", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        settings = load_settings(current_app) or {}
        if settings.get("sales_coach_sms_enabled") is False:
            return False
    except Exception:
        pass
    return True


def _notif_enabled() -> bool:
    raw = os.environ.get("VINOR_SALES_COACH_NOTIF", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _send_nudge_sms(*, phone: str, message: str, dry_run: bool) -> Dict[str, Any]:
    ph = normalize_iran_mobile(phone) or (phone or "").strip()
    if not is_valid_iran_mobile(ph):
        return {"ok": False, "error": "invalid_phone"}
    if dry_run:
        return {"ok": True, "dry_run": True, "phone": ph, "message": message}
    try:
        line = get_sms_line_number()
        ok = send_sms_direct(ph, message, line_number=line)
        try:
            history = load_sms_history(current_app) or []
            if not isinstance(history, list):
                history = []
            history.append(
                {
                    "phone": ph,
                    "message": message,
                    "type": "sales_coach_nudge",
                    "ok": bool(ok),
                    "created_at": datetime.utcnow().isoformat() + "Z",
                }
            )
            if len(history) > 5000:
                history = history[-5000:]
            save_sms_history(history, current_app)
        except Exception:
            pass
        return {"ok": bool(ok), "phone": ph}
    except Exception as exc:
        current_app.logger.warning("sales coach SMS failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _active_slot_hour(now: datetime | None = None) -> Optional[int]:
    """اگر الان داخل یکی از نوبت‌های روزانه هستیم، همان ساعت را برگردان."""
    now = now or _tehran_now()
    h = int(now.hour)
    if h in _NUDGE_HOURS:
        return h
    return None


def run_sales_coach_nudge_slot(
    *,
    slot_hour: int,
    dry_run: bool = False,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """ارسال یک نوبت پیگیری (اعلان + پیامک) به همکاران دارای فایل باز."""
    from .routes import _build_partner_dashboard_lands

    partners = load_express_partners(current_app) or []
    if not isinstance(partners, list):
        partners = []
    visit_rows = load_express_visit_requests(current_app) or []
    if not isinstance(visit_rows, list):
        visit_rows = []

    state = state if isinstance(state, dict) else _load_state()
    results: List[Dict[str, Any]] = []
    sent_notif = 0
    sent_sms = 0
    skipped = 0
    sms_on = _sms_enabled()
    notif_on = _notif_enabled()

    for p in partners:
        if not isinstance(p, dict) or not _is_partner_approved(p):
            continue
        phone = normalize_iran_mobile(str(p.get("phone") or "").strip())
        if not is_valid_iran_mobile(phone):
            continue
        try:
            assigned, _ = _build_partner_dashboard_lands(phone, True)
        except Exception:
            assigned = []
        nudge = resolve_stuck_nudge_for_partner(
            phone, assigned_lands=assigned or [], visit_rows=visit_rows
        )
        if not nudge:
            skipped += 1
            continue

        code = str(nudge.get("code") or "")
        track = _partner_track(state, phone, code)
        prev_code = str(track.get("code") or "")
        if prev_code and prev_code != code:
            track["nudge_count"] = 0
        track["code"] = code
        count_before = int(track.get("nudge_count") or 0)

        title, body, sms_body = build_nudge_messages(
            nudge,
            partner_name=str(p.get("name") or p.get("full_name") or ""),
            slot_hour=slot_hour,
            nudge_count=count_before,
        )
        action_url = _detail_url(code) if code else _home_url()
        item: Dict[str, Any] = {
            "phone": phone,
            "code": code,
            "title": title,
            "slot": slot_hour,
            "phase": _nudge_phase(count_before),
            "stage": nudge.get("stage_label"),
        }

        if notif_on:
            if not dry_run:
                try:
                    from app.services.notifications import add_notification

                    add_notification(
                        phone,
                        title,
                        body,
                        ntype="sales_coach",
                        ad_id=code or None,
                        action_url=action_url,
                        source="sales_coach_nudge",
                    )
                    sent_notif += 1
                    item["notif"] = True
                except Exception as exc:
                    item["notif"] = False
                    item["notif_error"] = str(exc)
                    current_app.logger.warning(
                        "sales coach notif failed | %s | %s", phone, exc
                    )
            else:
                item["notif"] = "dry_run"
                item["notif_body"] = body
                sent_notif += 1
        else:
            item["notif"] = {"ok": False, "skipped": "notif_disabled"}

        if sms_on:
            sms_res = _send_nudge_sms(phone=phone, message=sms_body, dry_run=dry_run)
            item["sms"] = sms_res
            if dry_run:
                item["sms_body"] = sms_body
            if sms_res.get("ok"):
                sent_sms += 1
        else:
            item["sms"] = {"ok": False, "skipped": "sms_disabled"}

        # پیگیری داخل چت مأموریت (حداکثر یک‌بار در هر اسلات)
        mission_tid = str(nudge.get("mission_thread_id") or "").strip()
        if bool(nudge.get("is_mission")) and mission_tid and not dry_run:
            tip = str(nudge.get("tip") or "").strip()
            chat_body = (
                f"یادآوری ماموریت ({_SLOT_LABELS.get(int(slot_hour), 'امروز')}): "
                f"فایل {code} هنوز باز است. {tip or 'قدم بعدی را همین امروز بردار.'}"
            )
            try:
                from .partner_missions import append_mission_chat_followup

                ok_chat = append_mission_chat_followup(
                    phone,
                    land_code=code,
                    thread_id=mission_tid,
                    body=chat_body,
                )
                item["mission_chat"] = bool(ok_chat)
            except Exception as exc:
                item["mission_chat"] = False
                item["mission_chat_error"] = str(exc)

        if not dry_run:
            track["nudge_count"] = count_before + 1
            track["last_slot"] = int(slot_hour)
            track["last_stage"] = str(nudge.get("stage_label") or "")
            track["last_at"] = datetime.utcnow().isoformat() + "Z"

        results.append(item)

    return {
        "ok": True,
        "slot_hour": int(slot_hour),
        "partners_nudged": len(results),
        "notifications": sent_notif,
        "sms": sent_sms,
        "skipped_no_open_file": skipped,
        "dry_run": dry_run,
        "items": results[:50],
        "state": state,
    }


# سازگاری با نام قبلی — اسلات شب به‌جای ساعت ثابت
def maybe_run_evening_sales_coach_nudge(
    *,
    force: bool = False,
    dry_run: bool = False,
    slot_hour: Optional[int] = None,
) -> Dict[str, Any]:
    """
    پیگیری منظم: در هر نوبت ۱۰ / ۱۴ / ۲۰ تهران یک‌بار اجرا می‌شود.
    تا وقتی فایل sold نشده برای همان همکار ادامه دارد.
    """
    if os.environ.get("VINOR_DISABLE_SALES_COACH_NUDGE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return {"skipped": True, "reason": "disabled"}

    now = _tehran_now()
    today = now.date().isoformat()
    hour = int(slot_hour) if slot_hour is not None else _active_slot_hour(now)
    if hour is None and not force:
        return {
            "skipped": True,
            "reason": "not_nudge_slot",
            "hour": now.hour,
            "slots": list(_NUDGE_HOURS),
        }
    if hour is None and force:
        hour = int(now.hour) if now.hour in _NUDGE_HOURS else 20

    slot_key = f"{today}:{int(hour)}"
    lock_fd = _try_acquire_run_lock()
    if lock_fd is None:
        return {"skipped": True, "reason": "another_worker_running", "slot": slot_key}

    try:
        state = _load_state()
        done = state.get("slots_done")
        if not isinstance(done, dict):
            done = {}
            state["slots_done"] = done
        if not force and done.get(slot_key):
            return {"skipped": True, "reason": "slot_already_ran", "slot": slot_key}

        result = run_sales_coach_nudge_slot(
            slot_hour=int(hour), dry_run=dry_run, state=state
        )
        state = result.pop("state", state) or state

        if not dry_run:
            done[slot_key] = {
                "at": datetime.utcnow().isoformat() + "Z",
                "partners_nudged": result.get("partners_nudged"),
                "notifications": result.get("notifications"),
                "sms": result.get("sms"),
            }
            # پاکسازی کلیدهای قدیمی‌تر از ۷ روز
            try:
                from datetime import timedelta

                cutoff = (now.date() - timedelta(days=7)).isoformat()
                for k in list(done.keys()):
                    day = str(k).split(":", 1)[0]
                    if day < cutoff:
                        done.pop(k, None)
            except Exception:
                pass
            state["slots_done"] = done
            state["last_run_date"] = today  # سازگاری
            state["last_slot_key"] = slot_key
            state["last_run_at"] = datetime.utcnow().isoformat() + "Z"
            state["last_result"] = {
                "partners_nudged": result.get("partners_nudged"),
                "notifications": result.get("notifications"),
                "sms": result.get("sms"),
                "slot_hour": hour,
            }
            _save_state(state)
        result["slot_key"] = slot_key
        return result
    finally:
        _release_run_lock(lock_fd)


def _scheduler_loop(app: Flask) -> None:
    time.sleep(90)
    while True:
        try:
            with app.app_context():
                maybe_run_evening_sales_coach_nudge()
        except Exception:
            app.logger.exception("Sales coach nudge scheduler tick failed")
        time.sleep(600)  # هر ۱۰ دقیقه چک نوبت


def schedule_sales_coach_nudge(app: Flask) -> None:
    """زمان‌بندی پیگیری فروش — روی LiteSpeed فقط با cron؛ اینجا opt-in."""
    if os.environ.get("VINOR_DISABLE_SALES_COACH_NUDGE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        app.logger.info("Sales coach nudge disabled via VINOR_DISABLE_SALES_COACH_NUDGE")
        return
    flag = os.environ.get("VINOR_SALES_COACH_SCHEDULER", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        app.logger.info(
            "Sales coach in-process scheduler off "
            "(cron: scripts/run_sales_coach_nudge.py every 10min, or VINOR_SALES_COACH_SCHEDULER=1)"
        )
        return
    threading.Thread(
        target=_scheduler_loop,
        args=(app,),
        daemon=True,
        name="vinor-sales-coach-nudge",
    ).start()
    app.logger.info(
        "Sales coach follow-up scheduler started (Tehran hours %s — notif+SMS until sold)",
        list(_NUDGE_HOURS),
    )
