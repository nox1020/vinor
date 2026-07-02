"""ساخت زمینهٔ داخلی وینور برای چت AI همکار."""
from __future__ import annotations

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


def _land_summary(land: dict[str, Any], *, assigned: bool, show_commission: bool = True) -> str:
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
    expired = "منقضی" if land.get("_is_expired") else "معتبر"
    pct = land.get("_commission_pct")
    comm = land.get("_commission_amount")
    comm_line = ""
    if show_commission and (pct or comm):
        comm_line = f" | پورسانت: {pct or '—'}٪ → {_fmt_price(comm)} تومان"
    desc = str(land.get("description") or land.get("desc") or "").strip()
    if len(desc) > 280:
        desc = desc[:277] + "…"
    prefix = "اختصاصی" if assigned else "عمومی"
    lines = [
        f"[{prefix}] کد:{code} | {title}",
        f"  شهر:{city or '—'} | محله:{loc or '—'} | نوع:{cat or '—'}",
        f"  قیمت:{price} تومان | بنا:{built or '—'}م | زمین:{land_area or '—'}م | وضعیت:{st} | {expired}{comm_line}",
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
    return out[:20]


def _public_lands_sample(limit: int = 12) -> list[dict[str, Any]]:
    try:
        lands = load_express_lands_cached() or []
    except Exception:
        lands = []
    return list(lands[:limit])


def build_partner_context(phone: str) -> str:
    """متن زمینه برای تزریق به system prompt."""
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    cities = load_active_cities() or []
    assigned = _assigned_lands(phone)
    public = _public_lands_sample()
    parts = [
        "=== اطلاعات داخلی وینور (فقط از همین بخش پاسخ بده) ===",
        _partner_profile_block(phone),
        f"شهرهای فعال همکاری: {', '.join(str(c) for c in cities[:20])}",
        f"پشتیبانی تماس: {admin_phone}",
        "",
        "راهنمای کوتاه همکاری اکسپرس:",
        "- همکار فایل‌های تأییدشده وینور را بازاریابی می‌کند و در صورت فروش پورسانت می‌گیرد.",
        "- فایل‌های «اختصاصی» فقط به این همکار انتساب شده‌اند؛ «عمومی» برای همه همکاران قابل مشاهده است.",
        "- وضعیت معامله: فعال، در حال معامله، فروخته شد و غیره در هر فایل آمده است.",
        "- برای پشتیبانی انسانی: تماس با شماره بالا یا سوال در همین چت (در صورت نبود پاسخ، تیم وینور پاسخ می‌دهد).",
        "",
    ]
    parts.append(f"--- فایل‌های اختصاصی همکار ({len(assigned)} مورد) ---")
    if assigned:
        for land in assigned:
            parts.append(_land_summary(land, assigned=True))
    else:
        parts.append("(فعلاً فایل اختصاصی ندارد)")
    parts.append("")
    parts.append(f"--- نمونه فایل‌های عمومی اکسپرس ({len(public)} مورد) ---")
    if public:
        for land in public:
            item = dict(land)
            item["_assignment_status"] = "public"
            item["_is_expired"] = is_ad_expired(land)
            parts.append(_land_summary(item, assigned=False))
    else:
        parts.append("(فایلی در لیست عمومی نیست)")
    return "\n".join(parts)


def build_public_context() -> str:
    """زمینه برای کاربر عادی — فقط آگهی‌های عمومی و راهنمای خریدار."""
    settings = load_settings() or {}
    admin_phone = str(settings.get("partner_application_admin_phone") or "09121471301").strip()
    cities = load_active_cities() or []
    public = _public_lands_sample(25)
    parts = [
        "=== اطلاعات داخلی وینور برای کاربر عادی (فقط از همین بخش پاسخ بده) ===",
        "نقش مخاطب: کاربر عادی / خریدار / علاقه‌مند — نه همکار.",
        f"شهرهای فعال: {', '.join(str(c) for c in cities[:20])}",
        f"پشتیبانی تماس: {admin_phone}",
        "",
        "درباره وینور:",
        "- پلتفرم موبایل‌محور خرید و فروش زمین، باغ و ویلا با پرونده‌های تأییدشده.",
        "- آگهی‌های نمایش‌داده‌شده در اکسپرس توسط تیم وینور بررسی شده‌اند.",
        "",
        "راهنمای کوتاه خرید امن:",
        "- مدارک ملک (سند، کد رهگیری و …) را بررسی کنید.",
        "- بازدید حضوری و مشاوره با تیم وینور پیش از پرداخت.",
        "- برای همکاری در فروش و پورسانت: ثبت‌نام در بخش همکاری وینور (نه در این چت).",
        "",
        f"--- آگهی‌های عمومی اکسپرس ({len(public)} مورد) ---",
    ]
    if public:
        for land in public:
            item = dict(land)
            item["_assignment_status"] = "public"
            item["_is_expired"] = is_ad_expired(land)
            parts.append(_land_summary(item, assigned=False, show_commission=False))
    else:
        parts.append("(فعلاً آگهی فعالی در لیست نیست)")
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
