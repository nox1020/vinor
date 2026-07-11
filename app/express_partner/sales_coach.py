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
        return "فروش تموم شد؛ از کیف پول برداشت بزن."
    if in_transaction:
        return f"الان با مشتری هماهنگ کن و معامله رو ببند{por}."
    label = (stage_label or "").strip()
    if label in ("بازدید انجام شد",) or "انجام" in label:
        return f"بعد از بازدید، فردا صبح پیگیری کن و درخواست معامله بده{por}."
    if label in ("بازدید تأییدشد", "در انتظار بازدید", "پیگیری بازدید") or has_visit:
        return "بازدید رو جدی بگیر؛ قبلش فایل رو مرور کن و با مشتری هماهنگ باش."
    # مرحله معرفی / علاقه‌مند — هنوز بازدید نیست
    return (
        f"فایل رو تو دیوار آگهی کن و تو پیج اینستا استوری/پست بذار"
        f"{por}. از چت بخواه متن آماده برات بنویسم."
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

    notif_title = "ممنون از تلاشت 🌿"
    chat_body = (
        f"{notif_title}\n"
        f"{head} — برای {file_bit}.\n"
        "تو تلاشت رو کردی و کارت ارزشمند بود؛ گاهی مشتری منصرف می‌شود و این بخشی از مسیر فروشه.\n\n"
        "الان روی بازاریابی مجدد تمرکز کن:\n"
        "۱) دوباره در دیوار ثبت یا آپدیت کن\n"
        "۲) آگهی را نردبان کن تا بیشتر دیده شود\n"
        "۳) پست و استوری اینستا بگذار\n"
        "۴) به هر کسی که ممکن است مشتری باشد معرفی کن\n\n"
        "اگر متن دیوار یا کپشن اینستا می‌خواهی، همین‌جا بگو تا آماده کنم."
    )
    notif_body = (
        f"{head}. ممنون که تلاش کردی. "
        "حالا بازاریابی مجدد: دیوار + نردبان + اینستا + معرفی به اطرافیان. "
        "از چت متن آماده بخواه."
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

        action_url = _detail_url(land_code) if land_code else _home_url()
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
                assistant_land_codes=[land_code] if land_code else None,
                audience=AUDIENCE_PARTNER,
            )
            out["chat"] = True
    except Exception as exc:
        current_app.logger.warning("voided encouragement chat failed: %s", exc)
    return out


def build_coach_chat_prompt(*, code: str, title: str = "", stage_label: str = "") -> str:
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    stage = (stage_label or "").strip()
    bits = [f"فایل {code_s}"]
    if title_s:
        bits.append(f"({title_s})")
    head = " ".join(bits)
    if stage and stage not in ("علاقه‌مند",):
        return (
            f"{head} در مرحله «{stage}» است. "
            "قدم بعدی فروش و گرفتن پورسانت رو دقیق بگو و اگر لازمه متن پیگیری مشتری بده."
        )
    return (
        f"{head} رو بهم اختصاص دادی. "
        "متن آگهی دیوار و کپشن اینستا آماده کن و بگو چطور معرفی کنم تا بفروشم و پورسانت بگیرم."
    )


def build_ai_quick_prompts(
    *,
    code: str = "",
    title: str = "",
    stage_label: str = "",
    is_mission: bool = False,
) -> List[Dict[str, str]]:
    """سوال/دستور آماده بالای باکس چت — مرتبط با فایل/مرحله مأموریت."""
    code_s = (code or "").strip()
    title_s = (title or "").strip()
    stage = (stage_label or "").strip()
    head = f"فایل {code_s}" if code_s else "فایل مأموریت"
    if title_s:
        head = f"{head} ({title_s})"

    out: List[Dict[str, str]] = []

    def add(label: str, prompt: str) -> None:
        label = (label or "").strip()
        prompt = (prompt or "").strip()
        if label and prompt:
            out.append({"label": label, "prompt": prompt})

    if code_s:
        if stage in ("در حال معامله", "تماس فوری") or "معامله" in stage:
            add("بستن معامله", f"{head}: فقط ۲–۳ کار بعدی برای بستن معامله امروز را کوتاه بگو.")
            add("متن پیگیری", f"برای {head} یک پیام کوتاه پیگیری مشتری بنویس (حداکثر ۴ خط).")
            add("مخالف‌ها", f"برای {head} ۳ ایراد رایج + جواب یک‌خطی هر کدام.")
        elif stage in ("بازدید انجام شد", "بازدید تأییدشد", "در انتظار بازدید", "پیگیری بازدید"):
            add("بعد از بازدید", f"{head} در «{stage}»: فقط قدم بعدی فروش را خیلی کوتاه بگو.")
            add("پیام مشتری", f"برای {head} یک پیام کوتاه واتساپ بعد بازدید بنویس.")
            add("درخواست معامله", f"برای {head} کی درخواست معامله بزنم؟ جواب در ۲ جمله.")
        else:
            add("متن دیوار", f"برای {head} فقط متن آگهی دیوار را کامل بفرست.")
            add("کپشن اینستا", f"برای {head} فقط کپشن اینستا را کامل بفرست.")
            add("چطور بفروشم؟", f"برای {head} فقط ۳ قدم بعدی فروش را خیلی کوتاه بگو.")
        if is_mission:
            add("قدم بعدی", f"ماموریت {head}: فقط یک کار بعدی همین الان را بگو.")
        add(
            "منتفی شد",
            f"برای {head} پیگیری منتفی شد. خیلی گرم تشکر کن که تلاش کردم، بگو تلاشم ارزشمند بود، "
            "بعد کوتاه راهنمایی کن برای بازاریابی مجدد: دیوار، نردبان، اینستا و معرفی به اطرافیان.",
        )
    else:
        add("شروع فروش", "فقط یک کار بعدی فروش را خیلی کوتاه بگو.")
        add("متن آگهی", "متن کامل دیوار فایل فعلی‌ام را بفرست.")
        add("پورسانت", "چطور سریع‌تر به معامله برسم؟ ۳ نکته کوتاه.")

    return out[:5]


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
        # فایل در assigned نبود ولی mission هنوز باز است — از کاتالوگ نساز؛ کامل کن
        try:
            from .partner_missions import complete_mission

            complete_mission(ph, land_code=mission_code)
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


# سازگاری با نام قبلی
def run_evening_sales_coach_nudge(*, dry_run: bool = False) -> Dict[str, Any]:
    hour = _active_slot_hour() or 20
    out = run_sales_coach_nudge_slot(slot_hour=hour, dry_run=dry_run)
    out.pop("state", None)
    return out


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
