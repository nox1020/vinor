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
    "اختصاصی",
    "عمومی",
)


def _needs_land_context(query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return False
    if _LAND_QUERY_RE.search(q):
        return True
    return any(k in q for k in _LAND_KEYWORDS)


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
        return "پروفایل همکار: هنوز تأیید نشده یا ثبت نشده."
    name = str(prof.get("name") or prof.get("full_name") or "—").strip()
    city = str(prof.get("city") or "—").strip()
    status = str(prof.get("status") or "—").strip()
    return f"پروفایل همکار: نام={name} | شهر={city} | وضعیت={status}"


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
    return out[:12]


def _public_lands_sample(limit: int = 8) -> list[dict[str, Any]]:
    try:
        lands = load_express_lands_cached() or []
    except Exception:
        lands = []
    return list(lands[:limit])


def build_partner_context_base(phone: str) -> str:
    """بخش ثابت زمینه — قابل کش برای هر همکار."""
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    cities = load_active_cities() or []
    assigned = _assigned_lands(phone)
    return "\n".join(
        [
            "=== اطلاعات داخلی وینور ===",
            _partner_profile_block(phone),
            f"تعداد فایل اختصاصی: {len(assigned)}",
            f"شهرهای فعال: {', '.join(str(c) for c in cities[:12])}",
            f"پشتیبانی: {admin_phone}",
            "راهنما: همکار فایل‌های وینور را بازاریابی می‌کند؛ اختصاصی=فقط این همکار؛ عمومی=همه همکاران.",
        ]
    )


def _select_lands_for_query(
    lands: list[dict[str, Any]],
    query: str,
    *,
    default_limit: int,
    match_limit: int,
) -> list[dict[str, Any]]:
    if not lands:
        return []
    q = (query or "").strip()
    if q:
        matched = [l for l in lands if _land_matches_query(l, q)]
        if matched:
            return matched[:match_limit]
    return lands[:default_limit]


def build_partner_land_context(phone: str, user_message: str = "") -> str:
    """فقط وقتی سوال به فایل/ملک مربوط است — خلاصهٔ فشرده."""
    if not _needs_land_context(user_message):
        return ""
    assigned = _assigned_lands(phone)
    public = _public_lands_sample()
    picked_assigned = _select_lands_for_query(
        assigned, user_message, default_limit=4, match_limit=6
    )
    picked_public = _select_lands_for_query(
        public, user_message, default_limit=3, match_limit=4
    )
    parts: list[str] = []
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


def build_partner_context(phone: str, user_message: str = "") -> str:
    """متن زمینه برای تزریق به system prompt."""
    parts = [build_partner_context_base(phone)]
    land_ctx = build_partner_land_context(phone, user_message)
    if land_ctx:
        parts.append(land_ctx)
    return "\n".join(parts)


def build_public_context_base() -> str:
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    cities = load_active_cities() or []
    return "\n".join(
        [
            "=== اطلاعات وینور (کاربر عادی) ===",
            f"شهرهای فعال: {', '.join(str(c) for c in cities[:12])}",
            f"پشتیبانی: {admin_phone}",
            "وینور: خرید/فروش زمین، باغ و ویلا با پرونده تأییدشده.",
            "خرید امن: بررسی سند، بازدید حضوری، پرداخت مرحله‌ای.",
        ]
    )


def build_public_land_context(user_message: str = "") -> str:
    if not _needs_land_context(user_message):
        return ""
    public = _public_lands_sample(10)
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


def build_public_context(user_message: str = "") -> str:
    """زمینه برای کاربر عادی — فقط آگهی‌های مرتبط با سوال."""
    parts = [build_public_context_base()]
    land_ctx = build_public_land_context(user_message)
    if land_ctx:
        parts.append(land_ctx)
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
