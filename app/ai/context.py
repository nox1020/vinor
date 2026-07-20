"""ساخت زمینهٔ داخلی وینور برای چت AI همکار."""
from __future__ import annotations

import re
from typing import Any

from app.utils.storage import (
    load_active_cities,
    load_ads_cached,
    load_express_assignments,
    load_express_lands_cached,
    load_express_partners,
    load_settings,
)
from app.utils.dates import is_ad_expired

_LAND_QUERY_RE = re.compile(r"[a-z]{2,}[-_]?\d+", re.I)
_LAND_KEYWORDS = (
    "فایل",
    "ملک",
    "زمین",
    "ویلا",
    "باغ",
    "کد",
    "قیمت",
    "متر",
    "محله",
    "آگهی",
    "دیوار",
    "اینستا",
    "اینستاگرام",
    "فروش",
    "پورسانت",
    "اختصاصی",
    "عمومی",
)


_DEICTIC_LAND_RE = re.compile(
    r"(این\s*فایل|همین\s*فایل|این\s*ملک|همین\s*ملک|این\s*آگهی|همین\s*آگهی|"
    r"این\s*یکی|همین\s*یکی|درباره‌?(?:\s*این|‌?ش|اش)|"
    r"خصوصیات(?:ش|‌ش| این)|ویژگی(?:‌ها)?(?:ی?\s*این|ش|‌ش)|"
    r"مشخصات(?:ش|‌ش| این)|جزئیات(?:ش|‌ش| این)|"
    r"قیمت(?:ش|‌ش| این)|متراژ(?:ش|‌ش| این)|مساحت(?:ش|‌ش| این)|"
    r"موقعیت(?:ش|‌ش| این)|آدرس(?:ش|‌ش| این)|عکس(?:‌ها)?(?:ی?\s*این|ش)|"
    r"چطوره|چیه\b|چی داره)",
    re.I,
)


def _needs_land_context(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    if _LAND_QUERY_RE.search(q):
        return True
    if _DEICTIC_LAND_RE.search(q):
        return True
    return any(k in q for k in _LAND_KEYWORDS)


def _is_deictic_land_query(query: str) -> bool:
    """ارجاع به «همین فایل روی چت» بدون نام‌بردن کد دیگر."""
    q = (query or "").strip()
    if not q:
        return False
    return bool(_DEICTIC_LAND_RE.search(q))


def _query_targets_other_land(
    query: str,
    focus_codes: list[str],
    lands: list[dict[str, Any]],
) -> bool:
    """آیا سوال صریحاً فایل/موضوع دیگری غیر از فایل‌های روی چت را هدف گرفته؟"""
    q = (query or "").strip()
    if not q or not focus_codes:
        return False
    focus_set = {str(c).strip().lower() for c in focus_codes if str(c).strip()}
    mentioned = [m.lower() for m in _LAND_QUERY_RE.findall(q)]
    for m in mentioned:
        if any(m in f or f in m for f in focus_set):
            continue
        return True
    focus_lands = [
        l for l in lands if str(l.get("code") or "").strip().lower() in focus_set
    ]
    other_lands = [
        l for l in lands if str(l.get("code") or "").strip().lower() not in focus_set
    ]
    matched_focus = [l for l in focus_lands if _land_matches_query(l, q)]
    matched_other = [l for l in other_lands if _land_matches_query(l, q)]
    if matched_other and not matched_focus and not _is_deictic_land_query(q):
        return True
    return False


def _should_prefer_chat_focus(
    query: str,
    focus_codes: list[str],
    lands: list[dict[str, Any]],
) -> bool:
    if not focus_codes:
        return False
    if _query_targets_other_land(query, focus_codes, lands):
        return False
    if _is_deictic_land_query(query):
        return True
    if not _needs_land_context(query):
        return False
    focus_set = {str(c).strip().lower() for c in focus_codes if str(c).strip()}
    focus_lands = [
        l for l in lands if str(l.get("code") or "").strip().lower() in focus_set
    ]
    if any(_land_matches_query(l, query) for l in focus_lands):
        return True
    # پیگیری کوتاه بعد از کارت (قیمت/متراژ/…) بدون نام‌بردن فایل دیگر
    q = (query or "").strip()
    if len(q) <= 48 and not _LAND_QUERY_RE.search(q):
        broad = (
            "جستجو",
            "پیدا",
            "پیشنهاد",
            "لیست",
            "همه",
            "چند فایل",
            "می‌خوام",
            "ميخوام",
            "میخوام",
            "دنبال",
            "بودجه",
        )
        ql = q.lower()
        if any(b in q or b in ql for b in broad):
            return False
        return True
    return False


def _lands_by_codes(
    lands: list[dict[str, Any]],
    codes: list[str],
) -> list[dict[str, Any]]:
    by_code = {str(l.get("code") or "").strip(): l for l in lands if l.get("code")}
    out: list[dict[str, Any]] = []
    for code in codes:
        c = str(code or "").strip()
        land = by_code.get(c)
        if land:
            out.append(land)
    return out


def _lookup_public_lands_by_codes(codes: list[str]) -> list[dict[str, Any]]:
    """پیدا کردن فایل عمومی با کد — از کل کش، نه فقط نمونهٔ کوتاه."""
    want = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not want:
        return []
    try:
        lands = load_express_lands_cached() or []
    except Exception:
        lands = []
    by_code = {
        str(l.get("code") or "").strip(): l
        for l in lands
        if isinstance(l, dict) and l.get("code")
    }
    out: list[dict[str, Any]] = []
    for code in want:
        land = by_code.get(code)
        if not land:
            continue
        item = dict(land)
        item["_assignment_status"] = "public"
        item["_is_public"] = True
        item["_is_expired"] = is_ad_expired(land)
        out.append(item)
    return out


def _focus_lands_block(
    lands: list[dict[str, Any]],
    *,
    show_commission: bool = True,
) -> str:
    if not lands:
        return ""
    codes = [str(l.get("code") or "").strip() for l in lands if l.get("code")]
    parts = [
        "=== فایل‌های روی این گفتگو (موضوع پیش‌فرض) ===",
        "کاربر به این فایل‌ها اشاره می‌کند («این فایل»، خصوصیات، قیمت، …). "
        "جواب را دربارهٔ همین فایل‌ها بده مگر صریحاً فایل یا موضوع دیگری بپرسد. "
        f"کدها: {', '.join(codes)}",
    ]
    for land in lands:
        assigned = (
            not land.get("_is_public")
            and str(land.get("_assignment_status") or "").strip().lower() != "public"
        )
        parts.append(
            _land_summary(
                land,
                assigned=assigned,
                show_commission=show_commission and assigned,
                compact=False,
            )
        )
    return "\n".join(parts)


def _land_matches_query(land: dict[str, Any], query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    code = str(land.get("code") or "").strip().lower()
    if code and code in q:
        return True
    if code and _LAND_QUERY_RE.search(q):
        for m in _LAND_QUERY_RE.findall(q):
            if m.lower() in code or code in m.lower():
                return True
    title = str(land.get("title") or "").strip().lower()
    if title and len(title) >= 3 and title in q:
        return True
    city = str(land.get("city") or "").strip().lower()
    if city and len(city) >= 2 and city in q:
        return True
    loc = str(land.get("location") or "").strip().lower()
    if loc and len(loc) >= 3 and loc in q:
        return True
    for word in re.findall(r"[\w\u0600-\u06ff]{3,}", q):
        if word in title or word in city or word in loc:
            return True
    return False


def _norm_phone(phone: str) -> str:
    import re

    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def _assignment_status(assignment: dict[str, Any] | None) -> str:
    if not assignment or not isinstance(assignment, dict):
        return "active"
    if assignment.get("transaction_holder"):
        return "in_transaction"
    try:
        st = str(assignment.get("status") or "active").strip().lower()
    except Exception:
        st = "active"
    if st in ("in_transaction", "in-transaction", "in transaction"):
        return "in_transaction"
    return st or "active"


_STATUS_FA = {
    "active": "فعال",
    "pending": "در انتظار",
    "approved": "تأیید شده",
    "in_transaction": "در حال معامله",
    "sold": "فروخته شد",
    "closed": "بسته",
}


def _fmt_price(val: Any) -> str:
    try:
        n = int(str(val or "0").replace(",", "").strip() or 0)
        if n <= 0:
            return "—"
        return f"{n:,}"
    except Exception:
        return str(val or "—")


def _land_summary(
    land: dict[str, Any],
    *,
    assigned: bool,
    show_commission: bool = True,
    compact: bool = True,
) -> str:
    code = str(land.get("code") or "").strip()
    title = str(land.get("title") or "—").strip()
    city = str(land.get("city") or "").strip()
    loc = str(land.get("location") or "").strip()
    cat = str(land.get("category") or "").strip()
    price = _fmt_price(land.get("price_total") or land.get("price"))
    built = str(land.get("villa_built_area") or land.get("built_area") or land.get("size") or "").strip()
    land_area = str(land.get("villa_land_area") or land.get("land_area") or "").strip()
    st = _STATUS_FA.get(
        str(land.get("_assignment_status") or "active").lower(),
        str(land.get("_assignment_status") or "فعال"),
    )
    prefix = "اختصاصی" if assigned else "عمومی"
    pct = land.get("_commission_pct")
    comm = land.get("_commission_amount")
    comm_bit = ""
    if show_commission and (pct or comm):
        comm_bit = f" | پورسانت {_fmt_price(comm)}ت"
    if compact:
        area = built or land_area or "—"
        return (
            f"[{prefix}] {code} | {title} | {city or '—'}/{loc or '—'} | "
            f"{cat or '—'} | {price}ت | {area}م | {st}{comm_bit}"
        )
    expired = "منقضی" if land.get("_is_expired") else "معتبر"
    desc = str(land.get("description") or land.get("desc") or "").strip()
    if len(desc) > 120:
        desc = desc[:117] + "…"
    lines = [
        f"[{prefix}] کد:{code} | {title}",
        f"  شهر:{city or '—'} | محله:{loc or '—'} | نوع:{cat or '—'}",
        f"  قیمت:{price} ت | بنا:{built or '—'}م | زمین:{land_area or '—'}م | {st} | {expired}{comm_bit}",
    ]
    if desc:
        lines.append(f"  توضیح: {desc}")
    return "\n".join(lines)


def _partner_profile_block(phone: str) -> str:
    me = _norm_phone(phone)
    if not me:
        return ""
    partners = load_express_partners() or []
    prof = next((p for p in partners if _norm_phone(str(p.get("phone") or "")) == me), None)
    if not prof:
        return "پروفایل بازاریاب: هنوز تأیید نشده یا ثبت نشده.\nنقش مخاطب: مشتری/خریدار تا تأیید بازاریاب شدن."
    name = str(prof.get("name") or prof.get("full_name") or "—").strip()
    city = str(prof.get("city") or "—").strip()
    status = str(prof.get("status") or "—").strip()
    role_fa = "بازاریاب فروش"
    try:
        from app.express_partner.partner_roles import partner_is_approved, partner_is_special

        if partner_is_special(prof):
            role_fa = "بازاریاب ویژه (مالک/فروشنده — بالاترین دسترسی)"
        elif not partner_is_approved(prof):
            role_fa = "متقاضی بازاریاب شدن (در انتظار تأیید)"
    except Exception:
        pass
    return (
        f"پروفایل بازاریاب: نام={name} | شهر={city} | وضعیت={status}\n"
        f"نقش مخاطب: {role_fa}"
    )


def _assigned_lands(phone: str) -> list[dict[str, Any]]:
    me = _norm_phone(phone)
    if not me:
        return []
    try:
        assignments = load_express_assignments() or []
    except Exception:
        assignments = []
    my_assignments = [
        a
        for a in assignments
        if _norm_phone(str(a.get("partner_phone") or "")) == me
        and (a.get("status") or "active")
        in (None, "active", "pending", "approved", "in_transaction", "sold")
    ]
    lands_all = load_ads_cached() or []
    code_to_land = {str(l.get("code")): l for l in lands_all}
    out: list[dict[str, Any]] = []
    for a in my_assignments:
        land = code_to_land.get(str(a.get("land_code")))
        if not land:
            continue
        item = dict(land)
        item["_assignment_status"] = _assignment_status(a)
        item["_is_expired"] = is_ad_expired(land)
        from app.express_partner.new_land_sms import attach_express_land_commission
        attach_express_land_commission(item)
        out.append(item)
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    # سقف بالاتر تا همکار از چت به فایل‌های بازدید/اختصاص بیشتری دسترسی داشته باشد
    return out[:80]


def _public_lands_sample(limit: int = 8) -> list[dict[str, Any]]:
    try:
        from app.utils.iran_cities import land_in_service_focus

        lands = load_express_lands_cached() or []
    except Exception:
        return []
    focus = [l for l in lands if isinstance(l, dict) and land_in_service_focus(l)]
    pool = focus if focus else [l for l in lands if isinstance(l, dict)]
    return list(pool[:limit])


def build_partner_context_base(phone: str) -> str:
    """بخش ثابت زمینه — قابل کش برای هر همکار."""
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    assigned = _assigned_lands(phone)
    guide = "راهنما: خانه=کار بعدی و پیشنهاد؛ فایل‌ها=جستجو؛ بازدیدها=مسیر ۷ مرحله‌ای؛ AI=راهنما و پستچی."
    try:
        from app.express_partner.partner_roles import partner_is_special

        partners = load_express_partners() or []
        me = _norm_phone(phone)
        prof = next((p for p in partners if _norm_phone(str(p.get("phone") or "")) == me), None)
        if partner_is_special(prof):
            guide = (
                "راهنما ویژه: خانه و AI؛ آگهی‌های من؛ بازدیدهای دریافتی؛ "
                "مدیریت فایل‌های خودتان و هماهنگی با همکاران تخصیص‌یافته."
            )
    except Exception:
        pass
    try:
        from app.utils.iran_cities import focus_location_block
        loc_block = focus_location_block()
    except Exception:
        loc_block = "محدوده: استان تهران · شهرستان دماوند · روستای گرمابسرد."
    return "\n".join(
        [
            "=== اطلاعات داخلی وینور ===",
            _partner_profile_block(phone),
            f"تعداد فایل اختصاصی: {len(assigned)}",
            loc_block,
            f"پشتیبانی: {admin_phone}",
            guide,
        ]
    )


def build_partner_status_context(phone: str) -> str:
    """وضعیت زنده فشرده — هم‌راستا با «کار بعدی» داشبورد؛ خارج از کش base."""
    ph = _norm_phone(phone)
    if not ph:
        return ""
    try:
        from flask import g, has_request_context

        from app.express_partner.routes import (
            _build_partner_dashboard_lands,
            _commissions_for_phone,
            _home_follow_up_count,
            _home_urgent_actions,
            _is_partner_approved,
            _partner_commission_stats,
        )
        from app.express_partner.visit_requests import (
            APPROVED_STATUS,
            DONE_PENDING_STATUS,
            PENDING_STATUS,
        )
        from app.utils.storage import load_express_visit_requests

        profile = None
        if has_request_context():
            profile = getattr(g, "express_partner_profile", None)
        is_approved = _is_partner_approved(profile)
        visit_rows = load_express_visit_requests() or []
        if not isinstance(visit_rows, list):
            visit_rows = []
        assigned, _ = _build_partner_dashboard_lands(ph, is_approved)
        my_comms = _commissions_for_phone(ph)
        stats = _partner_commission_stats(ph, my_comms)
        withdrawable = int(stats.get("withdrawable_balance") or 0)
        follow_up = _home_follow_up_count(ph, visit_rows)
        actions = _home_urgent_actions(
            ph,
            assigned_lands=assigned,
            visit_rows=visit_rows,
            withdrawable_balance=withdrawable,
            follow_up_count=follow_up,
        )

        lines = [
            "=== وضعیت فعلی ===",
            "نقش: بازاریاب فروش — از همین چت بفروش.",
            "مسیر چت: (۱) مشتری+معیار → search_lands → [[LAND:کد]] "
            "یا (۲) نوع فایل برای بازاریابی → search_lands → معرفی.",
        ]
        try:
            personal_codes: list[str] = []
            for a in assigned or []:
                if not isinstance(a, dict) or not a.get("_assignment_id"):
                    continue
                c = str(a.get("code") or a.get("land_code") or "").strip()
                if c and c not in personal_codes:
                    personal_codes.append(c)
            if len(personal_codes) == 1:
                lines.append(
                    f"فایل شخصی فعال: {personal_codes[0]} — اگر گفتگو همین فایل است کد نپرس؛ "
                    "propose_* را با land_code خالی بزن."
                )
            elif personal_codes:
                lines.append(
                    "فایل‌های اختصاصی: "
                    + "، ".join(personal_codes[:5])
                    + " — اگر گفتگو روی یک فایل است کد نپرس؛ land_code خالی بگذار."
                )
        except Exception:
            pass
        if actions:
            a = actions[0]
            title = str(a.get("title") or "").strip()
            sub = str(a.get("subtitle") or "").strip()
            line = f"کار بعدی (اولویت): {title}"
            if sub:
                line += f" | {sub}"
            chat_p = str(a.get("chat_prompt") or "").strip()
            if chat_p:
                line += " — از همین چت با ابزار propose_* جلو ببر؛ لینک صفحه نده."
            lines.append(line)
        else:
            lines.append("کار بعدی: فعلاً کار فوری نیست")

        mine = [
            r
            for r in visit_rows
            if isinstance(r, dict) and _norm_phone(str(r.get("partner_phone") or "")) == ph
        ]
        n_pending = sum(1 for r in mine if str(r.get("status") or "") == PENDING_STATUS)
        n_approved = sum(1 for r in mine if str(r.get("status") or "") == APPROVED_STATUS)
        n_done_p = sum(1 for r in mine if str(r.get("status") or "") == DONE_PENDING_STATUS)
        bits: list[str] = []
        if n_pending:
            bits.append(f"قدیمی در صف:{n_pending}")
        if n_approved:
            bits.append(f"نهایی‌شده:{n_approved}")
        if n_done_p:
            bits.append(f"منتظر تأیید انجام:{n_done_p}")
        if bits:
            lines.append("بازدیدها: " + "، ".join(bits))
        if withdrawable > 0:
            lines.append(f"قابل برداشت: {withdrawable:,} تومان")

        try:
            from app.express_partner.sales_coach import (
                coach_tip_for_stage,
                resolve_stuck_nudge_for_partner,
            )

            stuck = resolve_stuck_nudge_for_partner(
                ph, assigned_lands=assigned or [], visit_rows=visit_rows
            )
            if stuck:
                tip = str(stuck.get("tip") or "").strip()
                code = str(stuck.get("code") or "").strip()
                if tip:
                    lines.append(f"نکته مربی ({code}): {tip}")
            elif assigned:
                land0 = assigned[0]
                from app.express_partner.routes import _home_funnel_for_land

                funnel = _home_funnel_for_land(ph, land0, visit_rows=visit_rows)
                st0 = str(land0.get("_assignment_status") or "").strip().lower()
                tip = coach_tip_for_stage(
                    stage_label=str(funnel.get("stage_label") or ""),
                    in_transaction=st0 == "in_transaction",
                    sold=st0 == "sold",
                    commission_amount=int(land0.get("_commission_amount") or 0),
                )
                code = str(land0.get("code") or "").strip()
                if tip:
                    lines.append(f"نکته مربی ({code}): {tip}")
        except Exception:
            pass

        return "\n".join(lines)[:720]
    except Exception:
        return ""


def _select_lands_for_query(
    lands: list[dict[str, Any]],
    query: str,
    *,
    default_limit: int,
    match_limit: int,
) -> list[dict[str, Any]]:
    if not lands:
        return []
    try:
        from app.utils.iran_cities import land_in_service_focus

        focus = [l for l in lands if land_in_service_focus(l)]
        pool = focus if focus else lands
    except Exception:
        pool = lands
    q = (query or "").strip()
    if q:
        rag_picked = _select_lands_by_rag(
            pool,
            q,
            limit=match_limit,
        )
        if rag_picked:
            return rag_picked[:match_limit]
        matched = [l for l in pool if _land_matches_query(l, q)]
        if matched:
            return matched[:match_limit]
        # کوئری خارج از محدوده → باز هم فقط فایل‌های گرمابسرد
        return pool[:match_limit]
    return pool[:default_limit]


def _select_lands_by_rag(
    pool: list[dict[str, Any]],
    query: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """RAG selection bridge: returns only property codes; text format stays unchanged."""
    try:
        from app.supervisor.service import allow_component

        if not allow_component("rag", default=True):
            return []
    except Exception:
        pass
    try:
        from app.knowledge.interfaces import RetrievalRequest
        from app.knowledge.service import get_property_retriever
    except Exception:
        return []
    retriever = get_property_retriever()
    if retriever is None:
        return []
    allowed: list[str] = []
    for l in pool:
        code = str(l.get("code") or "").strip()
        if code:
            allowed.append(code)
    if not allowed:
        return []
    try:
        codes = retriever.retrieve_property_codes(
            RetrievalRequest(
                query=(query or "").strip(),
                top_k=max(1, min(20, int(limit or 6))),
                allowed_codes=tuple(allowed),
            )
        )
    except Exception:
        return []
    if not codes:
        return []
    lookup = {str(l.get("code") or "").strip(): l for l in pool if str(l.get("code") or "").strip()}
    return [lookup[c] for c in codes if c in lookup]


def build_partner_land_context(
    phone: str,
    user_message: str = "",
    *,
    focus_codes: list[str] | None = None,
) -> str:
    """فقط وقتی سوال به فایل/ملک مربوط است — خلاصهٔ فشرده؛ اولویت با فایل‌های روی چت."""
    assigned = _assigned_lands(phone)
    public = _public_lands_sample()
    all_lands = list(assigned) + [
        {**dict(l), "_assignment_status": "public", "_is_public": True} for l in public
    ]
    focus = [str(c).strip() for c in (focus_codes or []) if str(c).strip()]
    if focus:
        for land in _lookup_public_lands_by_codes(focus):
            code = str(land.get("code") or "").strip()
            if code and not any(str(x.get("code")) == code for x in all_lands):
                all_lands.append(land)
    if focus and _should_prefer_chat_focus(user_message, focus, all_lands):
        focus_assigned = _lands_by_codes(assigned, focus)
        missing = [
            c
            for c in focus
            if c not in {str(l.get("code") or "").strip() for l in focus_assigned}
        ]
        focus_public = _lookup_public_lands_by_codes(missing)
        # اگر هنوز از نمونهٔ عمومی چیزی مانده بود
        for land in _lands_by_codes(public, missing):
            code = str(land.get("code") or "").strip()
            if any(str(p.get("code")) == code for p in focus_public):
                continue
            item = dict(land)
            item["_assignment_status"] = "public"
            item["_is_public"] = True
            item["_is_expired"] = is_ad_expired(land)
            focus_public.append(item)
        parts: list[str] = []
        if focus_assigned or focus_public:
            merged = focus_assigned + focus_public
            parts.append(_focus_lands_block(merged, show_commission=True))
            return "\n".join(parts)
    if not _needs_land_context(user_message):
        return ""
    picked_assigned = _select_lands_for_query(
        assigned, user_message, default_limit=4, match_limit=6
    )
    picked_public = _select_lands_for_query(
        public, user_message, default_limit=3, match_limit=4
    )
    parts = []
    if picked_assigned:
        parts.append(f"--- فایل‌های اختصاصی ({len(picked_assigned)}/{len(assigned)}) ---")
        for land in picked_assigned:
            parts.append(_land_summary(land, assigned=True, compact=True))
    if picked_public:
        parts.append(f"--- فایل‌های عمومی ({len(picked_public)}) ---")
        for land in picked_public:
            item = dict(land)
            item["_assignment_status"] = "public"
            item["_is_expired"] = is_ad_expired(land)
            parts.append(_land_summary(item, assigned=False, compact=True))
    return "\n".join(parts)


def build_public_context_base() -> str:
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    try:
        from app.utils.iran_cities import focus_location_block

        loc_block = focus_location_block()
    except Exception:
        loc_block = "محدوده: استان تهران · شهرستان دماوند · روستای گرمابسرد."
    return "\n".join(
        [
            "=== وینور (مهمان/کاربر عادی) ===",
            "خرید/فروش زمین، باغ، ویلا با پرونده تأییدشده.",
            loc_block,
            f"پشتیبانی: {admin_phone}",
            "سطوح: عادی → همکار → ویژه. جزئیات/ثبت/وضعیت فقط با ابزار چت.",
            "هرگز URL یا مسیر صفحه نده.",
        ]
    )


def build_public_land_context(
    user_message: str = "",
    *,
    focus_codes: list[str] | None = None,
) -> str:
    public = _public_lands_sample(10)
    focus = [str(c).strip() for c in (focus_codes or []) if str(c).strip()]
    prepared = []
    for land in public:
        item = dict(land)
        item["_assignment_status"] = "public"
        item["_is_public"] = True
        item["_is_expired"] = is_ad_expired(land)
        prepared.append(item)
    # برای تشخیص «موضوع دیگر» همهٔ فوکوس‌ها را هم اضافه کن
    focused_lookup = _lookup_public_lands_by_codes(focus) if focus else []
    for land in focused_lookup:
        code = str(land.get("code") or "").strip()
        if code and not any(str(p.get("code")) == code for p in prepared):
            prepared.append(land)
    if focus and _should_prefer_chat_focus(user_message, focus, prepared):
        focused = focused_lookup or _lands_by_codes(prepared, focus)
        if focused:
            return _focus_lands_block(focused, show_commission=False)
    if not _needs_land_context(user_message):
        return ""
    picked = _select_lands_for_query(public, user_message, default_limit=4, match_limit=6)
    if not picked:
        return ""
    parts = [f"--- آگهی‌های عمومی ({len(picked)}) ---"]
    for land in picked:
        item = dict(land)
        item["_assignment_status"] = "public"
        item["_is_expired"] = is_ad_expired(land)
        parts.append(_land_summary(item, assigned=False, show_commission=False, compact=True))
    return "\n".join(parts)


def append_admin_answers_block(base_context: str, admin_notes: list[dict[str, str]]) -> str:
    if not admin_notes:
        return base_context
    lines = ["", "--- پاسخ‌های تیم وینور به سوالات قبلی این کاربر (الزاماً در پاسخ بگو) ---"]
    for n in admin_notes:
        q = (n.get("question") or "").strip()
        a = (n.get("answer") or "").strip()
        if q and a:
            lines.append(f"سوال: {q}\nپاسخ: {a}")
    return base_context + "\n".join(lines)
