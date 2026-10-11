# -*- coding: utf-8 -*-
"""آگهی‌های همکار ویژه — مالکیت بر اساس owner=phone."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app, url_for
from werkzeug.utils import secure_filename

from app.land_category_specs import apply_category_specs_from_form
from app.utils.images import save_upload_image
from app.utils.storage import load_ads, load_ads_cached, save_ads


def _norm_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or "").strip())


_FA_AR_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _canonical_mobile(phone: str) -> str:
    """شماره را به 09xxxxxxxxx برگردان. 98 و ارقام فارسی با 09 یکی‌اند."""
    s = str(phone or "").strip().translate(_FA_AR_DIGITS)
    s = re.sub(r"[^\d]", "", s)
    if not s:
        return ""
    if s.startswith("0098") and len(s) >= 14 and s[4:].startswith("9"):
        s = "0" + s[4:]
    elif s.startswith("98") and len(s) >= 12 and s[2:].startswith("9"):
        s = "0" + s[2:]
    elif len(s) == 10 and s.startswith("9"):
        s = "0" + s
    if len(s) > 11 and s.startswith("09"):
        s = s[:11]
    return s


def _owner_phone(land: Dict[str, Any]) -> str:
    return str(land.get("owner") or land.get("user_phone") or "")


def _same_phone(a: str, b: str) -> bool:
    left = _canonical_mobile(a)
    right = _canonical_mobile(b)
    if not left or not right:
        return False
    if left == right:
        return True
    return len(left) >= 10 and len(right) >= 10 and left[-10:] == right[-10:]


def _rows_for_code(lands: Any, code: str) -> List[Dict[str, Any]]:
    want = str(code or "").strip()
    if not want:
        return []
    out: List[Dict[str, Any]] = []
    for land in lands or []:
        if isinstance(land, dict) and str(land.get("code") or "").strip() == want:
            out.append(land)
    return out


def _uploads_folder() -> str:
    folder = current_app.config.get("UPLOAD_FOLDER") or os.path.join(
        current_app.static_folder or current_app.root_path, "static", "uploads"
    )
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_express_docs_dir() -> str:
    docs_dir = os.path.join(current_app.instance_path, "data", "express_docs")
    os.makedirs(docs_dir, exist_ok=True)
    return docs_dir


def _save_express_document(file, land_code: str) -> Optional[str]:
    if not file or not getattr(file, "filename", None):
        return None
    docs_dir = _get_express_docs_dir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    filename = secure_filename(f"{land_code}_{timestamp}_{file.filename}")
    file_path = os.path.join(docs_dir, filename)
    file.save(file_path)
    return filename


class _JsonForm:
    """آداپتور dict/JSON برای همان APIی که فرم HTML به create_special_listing می‌دهد."""

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self._d = data if isinstance(data, dict) else {}

    def get(self, key, default=None):
        if key not in self._d:
            return default
        return self._stringify(self._d.get(key), default)

    def getlist(self, key):
        v = self._d.get(key)
        if v is None:
            return []
        if isinstance(v, list):
            out: List[str] = []
            for item in v:
                s = self._stringify(item, "")
                if s:
                    out.append(s)
            return out
        s = self._stringify(v, "")
        return [s] if s else []

    @staticmethod
    def _stringify(v: Any, default: Any) -> Any:
        if v is None:
            return default
        if isinstance(v, bool):
            return "1" if v else ""
        if isinstance(v, list):
            if not v:
                return default
            return _JsonForm._stringify(v[0], default)
        return str(v)


class _EmptyFiles:
    def get(self, key, default=None):
        return default

    def getlist(self, key):
        return []

    def items(self):
        return iter(())

    def __contains__(self, key):
        return False


def form_from_mapping(data: Optional[Dict[str, Any]] = None):
    return _JsonForm(data)


def empty_upload_files():
    return _EmptyFiles()


def _normalize_images_from_form(form, files) -> List[str]:
    image_urls: List[str] = []
    for t in form.getlist("images") or []:
        t = (t or "").strip()
        if t:
            image_urls.append(t)

    upload_folder = _uploads_folder()
    for f in files.getlist("images") or []:
        if f and getattr(f, "filename", None):
            stored = save_upload_image(f, upload_folder)
            if stored:
                image_urls.append(stored)
            else:
                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{f.filename}"
                )
                try:
                    f.stream.seek(0)
                except Exception:
                    pass
                f.save(os.path.join(upload_folder, filename))
                image_urls.append(f"uploads/{filename}")
    return image_urls


def _save_video_from_form(files) -> Optional[str]:
    video_file = files.get("video")
    if not video_file or not getattr(video_file, "filename", None):
        return None
    allowed_extensions = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
    file_ext = os.path.splitext(video_file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return None
    upload_folder = _uploads_folder()
    filename = secure_filename(
        f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{video_file.filename}"
    )
    video_file.save(os.path.join(upload_folder, filename))
    return f"uploads/{filename}"


def _next_numeric_code(lands: List[Dict[str, Any]]) -> str:
    existing = [
        int(l["code"])
        for l in lands
        if isinstance(l, dict) and str(l.get("code") or "").isdigit()
    ]
    return str(max(existing) + 1) if existing else "1"


def is_published_for_sale(land: Dict[str, Any] | None) -> bool:
    """ملک «ملک من» که برای فروش منتشر شده و باید در فید عمومی بیاید."""
    if not isinstance(land, dict):
        return False
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    if extras.get("published_for_sale") is True:
        return True
    if str(land.get("source") or "").strip().lower() == "my_property_published":
        return True
    if land.get("public") is True and extras.get("listed_by_owner"):
        return True
    return False


def is_my_property_record(land: Dict[str, Any] | None) -> bool:
    """رکورد ثبت‌شده از صفحهٔ ملک من — خصوصی یا منتشرشده."""
    if not isinstance(land, dict):
        return False
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    src = str(land.get("source") or "").strip().lower()
    if src in ("my_property", "my_property_published", "owner_home"):
        return True
    if land.get("owner_home") or extras.get("owner_home") or extras.get("listed_by_owner"):
        return True
    if str(land.get("ad_type") or "").strip().lower() == "owner_home":
        return True
    return False


def is_owner_home(land: Dict[str, Any] | None) -> bool:
    """ملک ثبت‌شده از «ملک من» که هنوز برای فروش منتشر نشده."""
    if not is_my_property_record(land):
        return False
    return not is_published_for_sale(land)


def detail_sale_flag(land: Dict[str, Any] | None) -> bool:
    """پرچمی که صفحهٔ جزئیات به اپ می‌دهد.

    ملک من باید وضعیت واقعی را بگوید. آگهی عادی اکسپرس برای بقیه روشن می‌ماند
    تا اپ آن را به‌خاطر نبودن پرچم پنهان نکند.
    """
    if is_my_property_record(land):
        return is_published_for_sale(land)
    return True


def listings_owned_by(phone: str) -> List[Dict[str, Any]]:
    if not _canonical_mobile(phone):
        return []
    lands = load_ads_cached() or []
    out: List[Dict[str, Any]] = []
    for land in lands if isinstance(lands, list) else []:
        if not isinstance(land, dict):
            continue
        if is_owner_home(land):
            continue
        if not land.get("is_express"):
            continue
        if _same_phone(_owner_phone(land), phone):
            out.append(land)
    try:
        out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    except Exception:
        pass
    return out


def listings_owned_home(phone: str) -> List[Dict[str, Any]]:
    """ملک‌های «ملک من» متعلق به این شماره — شامل منتشرشده برای فروش."""
    if not _canonical_mobile(phone):
        return []
    lands = load_ads_cached() or []
    out: List[Dict[str, Any]] = []
    for land in lands if isinstance(lands, list) else []:
        if not isinstance(land, dict) or not is_my_property_record(land):
            continue
        if _same_phone(_owner_phone(land), phone):
            out.append(land)
    try:
        out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    except Exception:
        pass
    return out


ADMIN_CREATED_OWNERS = frozenset({"vinor_support", "admin", "vinor"})
ADMIN_CREATED_SOURCES = frozenset({"admin", "admin_ops_chat", "admin_panel"})


def is_admin_created_express_listing(land: Dict[str, Any] | None) -> bool:
    """آگهی اکسپرسی که از پنل/چت ادمین ثبت شده، نه توسط همکار پلاس."""
    if not isinstance(land, dict) or not land.get("is_express"):
        return False
    src = str(land.get("source") or "").strip().lower()
    if src in ADMIN_CREATED_SOURCES:
        return True
    owner = str(land.get("owner") or "").strip().lower()
    if owner in ADMIN_CREATED_OWNERS:
        return True
    return False


def plus_partner_map() -> Dict[str, Dict[str, Any]]:
    """کلید: شماره نرمال‌شده → رکورد همکار پلاس فعال."""
    from .partner_roles import partner_is_special
    from .partner_session_sync import canonical_partner_phone
    from app.utils.storage import load_express_partners

    out: Dict[str, Dict[str, Any]] = {}
    try:
        partners = load_express_partners() or []
    except Exception:
        partners = []
    for rec in partners:
        if not isinstance(rec, dict) or not partner_is_special(rec):
            continue
        raw = str(rec.get("phone") or "").strip()
        keys = {_norm_phone(raw)}
        try:
            can = canonical_partner_phone(raw)
            if can:
                keys.add(_norm_phone(can))
                keys.add(can)
        except Exception:
            pass
        keys.discard("")
        for key in keys:
            out[key] = rec
    return out


def _plus_display_name(rec: Dict[str, Any] | None, fallback: str = "") -> str:
    if not isinstance(rec, dict):
        return fallback
    return str(
        rec.get("name")
        or rec.get("full_name")
        or rec.get("display_name")
        or rec.get("phone")
        or fallback
    ).strip() or fallback


def listings_owned_by_plus_partners() -> List[Dict[str, Any]]:
    """آگهی‌های وینور ثبت‌شده توسط همکاران پلاس فعلی."""
    plus = plus_partner_map()
    if not plus:
        return []
    lands = load_ads_cached() or []
    out: List[Dict[str, Any]] = []
    for land in lands if isinstance(lands, list) else []:
        if not isinstance(land, dict) or not land.get("is_express"):
            continue
        if is_owner_home(land):
            continue
        if is_admin_created_express_listing(land):
            continue
        owner_raw = str(land.get("owner") or land.get("user_phone") or "")
        owner = _norm_phone(owner_raw)
        rec = plus.get(owner)
        if rec is None:
            try:
                from .partner_session_sync import canonical_partner_phone

                rec = plus.get(canonical_partner_phone(owner_raw))
            except Exception:
                rec = None
        if rec is None:
            continue
        item = dict(land)
        item["_source"] = "plus"
        item["_owner_phone"] = owner
        item["_owner_name"] = _plus_display_name(rec, owner)
        out.append(item)
    try:
        out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    except Exception:
        pass
    return out


def plus_listing_owner_by_code() -> Dict[str, Dict[str, str]]:
    """کد آگهی → مالک پلاس."""
    out: Dict[str, Dict[str, str]] = {}
    for land in listings_owned_by_plus_partners():
        code = str(land.get("code") or "").strip()
        if not code:
            continue
        out[code] = {
            "phone": str(land.get("_owner_phone") or "").strip(),
            "name": str(land.get("_owner_name") or "").strip(),
        }
    return out


def land_owned_by_special(land: Dict[str, Any] | None, phone: str) -> bool:
    if not isinstance(land, dict):
        return False
    return _same_phone(_owner_phone(land), phone)


def find_owned_land(phone: str, code: str) -> Optional[Dict[str, Any]]:
    code = str(code or "").strip()
    for land in listings_owned_by(phone):
        if str(land.get("code") or "") == code:
            return land
    return None


def _flag_on(raw: Any) -> bool:
    if raw is True or raw == 1:
        return True
    if raw is None or raw is False:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _flag_off(raw: Any) -> bool:
    if raw is False or raw == 0:
        return True
    if raw is None or raw is True:
        return False
    return str(raw).strip().lower() in ("0", "false", "no", "off")


def _mapping_get(src: Any, key: str) -> Any:
    if src is None:
        return None
    try:
        if key not in src:
            return None
        return src.get(key)
    except Exception:
        return None


def wants_unpublish(body: Any = None, query: Any = None, form: Any = None) -> bool:
    """درخواست توقف انتشار — قبل از اعتبارسنجی انتشار خوانده می‌شود.

    اپ مدیریت ملک همان مسیر انتشار را با ``unpublish`` و
    ``published_for_sale=false`` (و کوئری ``published_for_sale=0``) می‌زند.
    نبودن کلید به‌معنی توقف نیست تا ثبت عادی آگهی را خاموش نکند.
    """
    for src in (body, query, form):
        if _flag_on(_mapping_get(src, "unpublish")):
            return True
        if src is None:
            continue
        try:
            present = "published_for_sale" in src
        except Exception:
            present = False
        if present and _flag_off(_mapping_get(src, "published_for_sale")):
            return True
    return False


def _restore_private_owner_home(target: Dict[str, Any]) -> None:
    """برگرداندن ملک منتشرشده به حالت خصوصی «ملک من».

    هر سه علامتی که ``is_published_for_sale`` را روشن می‌کنند باید خاموش شوند،
    وگرنه آگهی در فید عمومی می‌ماند.
    """
    extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
    extras["published_for_sale"] = False
    extras["public"] = False
    extras["owner_home"] = True
    extras["listed_by_owner"] = True
    extras["listed_by_special"] = False
    target["extras"] = extras
    target["public"] = False
    target["is_express"] = False
    target["ad_type"] = "owner_home"
    target["status"] = "pending"
    target["express_status"] = "hidden"
    target["owner_home"] = True
    target["source"] = "my_property"


SPECIAL_LISTING_ERRORS: Dict[str, str] = {
    "invalid_owner": "شناسه همکار نامعتبر است.",
    "required_fields": "لطفاً فیلدهای اجباری را پر کنید.",
    "invalid_city": "شهر آگهی باید از بین شهرهای فعال انتخاب شود.",
    "title_short": "عنوان باید حداقل ۱۰ کاراکتر باشد.",
    "invalid_numbers": "متراژ و قیمت باید عدد معتبر باشند.",
    "invalid_price": "متراژ و قیمت باید بیشتر از صفر باشند.",
    "payment_required": "نحوه پرداخت را انتخاب کنید.",
    "invalid_contact": "شماره تماس پشتیبانی معتبر نیست.",
    "commission_required": "درصد پورسانت الزامی است.",
    "invalid_commission": "درصد پورسانت باید بین ۰ و ۱۰۰ باشد.",
    "installments_required": "برای پرداخت اقساطی حداقل یک قسط معتبر وارد کنید.",
    "save_failed": "ثبت آگهی ناموفق بود.",
    "not_found": "ابتدا ملک خود را در ملک من ثبت کنید.",
    "already_published": "این ملک قبلاً برای فروش منتشر شده است.",
}

PUBLISH_PAYMENT_METHODS = ("نقدی", "توافقی", "معاوضه")


def create_special_listing_from_express_form(
    *,
    owner_phone: str,
    form,
    files,
    cities: Optional[List[str]] = None,
    owner_home: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """ثبت آگهی اکسپرس همکار ویژه — همان فیلدهای فرم ادمین.
    owner_home=True: ملک خصوصی «ملک من»؛ در lands.json می‌ماند، منتشر نمی‌شود."""
    owner = _norm_phone(owner_phone)
    if not owner:
        return None, "invalid_owner"

    title = (form.get("title") or "").strip()
    location = (form.get("location") or "").strip()
    city = (form.get("city") or "").strip()
    size_raw = (form.get("size") or "").strip()
    price_total_raw = (form.get("price_total") or "").strip()

    size_clean = re.sub(r"[^\d]", "", size_raw) if size_raw else ""
    price_total_clean = re.sub(r"[^\d]", "", price_total_raw) if price_total_raw else ""

    if not all([title, location, city, size_clean, price_total_clean]):
        return None, "required_fields"

    if cities and city not in cities:
        return None, "invalid_city"

    if len(title) < 10:
        return None, "title_short"

    try:
        size = int(size_clean)
        price_total = int(price_total_clean)
    except (ValueError, TypeError):
        return None, "invalid_numbers"

    if size <= 0 or price_total <= 0:
        return None, "invalid_price"

    payment_method = (form.get("payment_method") or "").strip()
    if owner_home:
        payment_method = payment_method or "توافقی"
    elif not payment_method:
        return None, "payment_required"

    vinor_contact = _norm_phone(owner)
    if len(vinor_contact) < 10:
        return None, "invalid_contact"

    lands = load_ads() or []
    if not isinstance(lands, list):
        lands = []
    new_code = (form.get("code") or "").strip() or _next_numeric_code(lands)

    documents: List[str] = []
    for doc_key in ("document_1", "document_2"):
        pre = (form.get(doc_key) or "").strip()
        if pre:
            documents.append(pre)
    for key, file in files.items():
        if key.startswith("document_") and getattr(file, "filename", None):
            doc_filename = _save_express_document(file, new_code)
            if doc_filename and doc_filename not in documents:
                documents.append(doc_filename)

    images = _normalize_images_from_form(form, files)

    pct_raw = (form.get("express_commission_pct") or "").strip()
    if owner_home:
        pct_raw = pct_raw or "0"
        try:
            express_commission_pct = float(pct_raw)
            if express_commission_pct < 0 or express_commission_pct > 100:
                return None, "invalid_commission"
        except (ValueError, TypeError):
            express_commission_pct = 0.0
    else:
        if not pct_raw:
            return None, "commission_required"
        try:
            express_commission_pct = float(pct_raw)
            if express_commission_pct <= 0 or express_commission_pct > 100:
                return None, "invalid_commission"
        except (ValueError, TypeError):
            return None, "invalid_commission"

    price_per_meter_raw = (form.get("price_per_meter") or "").strip()
    price_per_meter_clean = (
        re.sub(r"[^\d]", "", price_per_meter_raw) if price_per_meter_raw else ""
    )
    try:
        price_per_meter = int(price_per_meter_clean) if price_per_meter_clean else 0
        if price_per_meter == 0 and size > 0:
            price_per_meter = int(round(price_total / size))
    except (ValueError, TypeError):
        price_per_meter = int(round(price_total / size)) if size > 0 else 0

    express_commission_amount = (
        int(round(price_total * (express_commission_pct / 100.0)))
        if price_total and express_commission_pct is not None
        else None
    )

    latitude = None
    longitude = None
    try:
        lat_str = (form.get("latitude") or "").strip()
        lon_str = (form.get("longitude") or "").strip()
        if lat_str:
            latitude = float(lat_str)
        if lon_str:
            longitude = float(lon_str)
    except (ValueError, TypeError):
        pass

    video_path = (form.get("video") or "").strip() or None
    if not video_path:
        try:
            video_path = _save_video_from_form(files)
        except Exception:
            video_path = None

    payment_terms: List[Dict[str, int]] = []
    if payment_method == "اقساطی":
        months_list = form.getlist("installment_months[]")
        amounts_list = form.getlist("installment_amounts[]")
        for i in range(max(len(months_list), len(amounts_list))):
            m_raw = (months_list[i] if i < len(months_list) else "") or ""
            a_raw = (amounts_list[i] if i < len(amounts_list) else "") or ""
            try:
                m = int(re.sub(r"[^\d]", "", str(m_raw))) if m_raw else 0
            except Exception:
                m = 0
            try:
                a = int(re.sub(r"[^\d]", "", str(a_raw))) if a_raw else 0
            except Exception:
                a = 0
            if m > 0 and a > 0:
                payment_terms.append({"months": m, "amount": a})
        if not payment_terms:
            return None, "installments_required"

    rec: Dict[str, Any] = {
        "code": new_code,
        "title": title,
        "location": location,
        "city": city,
        "size": size,
        "price_total": price_total,
        "price_per_meter": price_per_meter,
        "description": (form.get("description") or "").strip(),
        "images": images,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "owner": owner,
        "status": "approved",
        "ad_type": "express",
        "category": (form.get("category") or "").strip(),
        "payment_method": payment_method,
        "payment_terms": payment_terms,
        "is_express": True,
        "express_status": "approved",
        "expert_verified": False,
        "express_documents": documents,
        "vinor_contact": vinor_contact,
        "extras": {
            "express_commission_pct": express_commission_pct,
            "express_commission_amount": express_commission_amount,
            "listed_by_special": True,
        },
    }
    if owner_home:
        rec["is_express"] = False
        rec["ad_type"] = "owner_home"
        rec["status"] = "pending"
        rec["express_status"] = "hidden"
        rec["owner_home"] = True
        rec["public"] = False
        rec["source"] = "my_property"
        rec["extras"] = {
            "express_commission_pct": express_commission_pct,
            "express_commission_amount": express_commission_amount,
            "listed_by_special": False,
            "listed_by_owner": True,
            "owner_home": True,
            "public": False,
        }
    if video_path:
        rec["video"] = video_path
    if latitude is not None:
        rec["latitude"] = latitude
    if longitude is not None:
        rec["longitude"] = longitude

    apply_category_specs_from_form(rec, form)

    lands.append(rec)
    try:
        save_ads(lands)
    except Exception:
        current_app.logger.exception("special listing save failed code=%s", new_code)
        return None, "save_failed"
    return rec, None


def assign_land_to_all_partners(land: Dict[str, Any], commission_pct: float) -> None:
    """ساخت انتساب برای همه همکاران — معادل تیک «ارسال به همه همکاران» ادمین."""
    try:
        from app.services.notifications import add_notification
        from app.utils.storage import (
            load_express_assignments,
            load_express_partners,
            save_express_assignments,
        )

        new_code = str(land.get("code") or "")
        title = str(land.get("title") or "")
        partners = load_express_partners() or []
        items = load_express_assignments() or []
        existing = {
            (str(a.get("partner_phone")), str(a.get("land_code")))
            for a in items
            if isinstance(a, dict)
        }
        max_id = max(
            [int(x.get("id", 0) or 0) for x in items if isinstance(x, dict)],
            default=0,
        )
        for p in partners:
            phone = str((p or {}).get("phone") or "").strip()
            if not phone:
                continue
            key = (phone, new_code)
            if key in existing:
                continue
            max_id += 1
            items.append(
                {
                    "id": max_id,
                    "partner_phone": phone,
                    "land_code": new_code,
                    "commission_pct": commission_pct or 0,
                    "status": "active",
                    "created_at": datetime.utcnow().replace(microsecond=0).isoformat()
                    + "Z",
                }
            )
            existing.add(key)
            try:
                phone_normalized = _norm_phone(phone)
                if phone_normalized and len(phone_normalized) == 11:
                    add_notification(
                        user_id=phone_normalized,
                        title="فایل جدید اکسپرس",
                        body=f"کد فایل: {new_code} - {title}",
                        ntype="info",
                        ad_id=new_code,
                        action_url=url_for(
                            "express_partner.land_detail",
                            code=new_code,
                            _external=True,
                        ),
                    )
            except Exception:
                current_app.logger.exception(
                    "special listing assign notify failed phone=%s code=%s",
                    phone,
                    new_code,
                )
        save_express_assignments(items)
    except Exception:
        current_app.logger.exception(
            "assign_land_to_all_partners failed code=%s", land.get("code")
        )


def publish_owner_home(
    phone: str,
    *,
    payment_method: str,
    commission_pct: Any = "2",
    send_all: bool = False,
    land_code: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """انتشار ملک ثبت‌شده در «ملک من» به‌عنوان آگهی فروش عمومی."""
    homes = listings_owned_home(phone)
    if not homes:
        return None, "not_found"
    want = str(land_code or "").strip()
    land = None
    if want:
        for home in homes:
            if str(home.get("code") or "").strip() == want:
                land = home
                break
    else:
        land = homes[0]
    if land is None:
        return None, "not_found"
    if is_published_for_sale(land):
        return None, "already_published"

    method = str(payment_method or "").strip()
    if method not in PUBLISH_PAYMENT_METHODS:
        return None, "payment_required"

    pct_raw = str(commission_pct if commission_pct is not None else "").strip() or "2"
    try:
        pct = float(pct_raw.replace(",", ".").replace("٪", "").replace("%", ""))
    except (TypeError, ValueError):
        return None, "invalid_commission"
    if pct <= 0 or pct > 100:
        return None, "invalid_commission"

    code = str(land.get("code") or "").strip()
    if not code:
        return None, "not_found"

    items = load_ads() or []
    if not isinstance(items, list):
        items = []
    target = None
    for item in items:
        if isinstance(item, dict) and str(item.get("code") or "").strip() == code:
            target = item
            break
    if target is None:
        return None, "not_found"

    price = 0
    try:
        price = int(target.get("price_total") or target.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    amount = int(round(price * (pct / 100.0))) if price else 0

    extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
    extras.update({
        "express_commission_pct": pct,
        "express_commission_amount": amount,
        "listed_by_special": True,
        "listed_by_owner": True,
        "owner_home": False,
        "public": True,
        "published_for_sale": True,
    })
    target["extras"] = extras
    target["public"] = True
    target["is_express"] = True
    target["ad_type"] = "express"
    target["status"] = "approved"
    target["express_status"] = "approved"
    target["owner_home"] = False
    target["source"] = "my_property_published"
    target["payment_method"] = method
    target["expert_verified"] = bool(target.get("expert_verified"))

    try:
        save_ads(items)
    except Exception:
        current_app.logger.exception("publish owner home save failed code=%s", code)
        return None, "save_failed"

    try:
        from .new_land_sms import notify_all_partners_new_express_land_background
        notify_all_partners_new_express_land_background(target)
    except Exception:
        current_app.logger.exception("publish owner home SMS failed code=%s", code)

    if send_all:
        assign_land_to_all_partners(target, pct)
    return target, None


def resolve_listing_for_viewer(
    lands: Any,
    code: str,
    phone: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """ردیف قابل‌نمایش برای بیننده.

    مالک، ردیف «ملک من» خودش را می‌بیند — اگر هنوز نسخه‌ای منتشر باشد همان را —
    تا یک کپی اکسپرسِ جا مانده جزئیات را منتشر نشان ندهد. بقیه فقط آگهی عمومی
    را می‌بینند.
    """
    matches = _rows_for_code(lands, code)
    if not matches:
        return None, "missing"
    owned = [
        land
        for land in matches
        if is_my_property_record(land) and _same_phone(_owner_phone(land), phone)
    ]
    if owned:
        for land in owned:
            if is_published_for_sale(land):
                return land, "owner"
        return owned[0], "owner"
    for land in matches:
        if land.get("is_express") and not is_owner_home(land):
            return land, "public"
    return None, "missing"


def unpublished_owner_home_only(lands: Any, code: str) -> bool:
    """کد فقط به ملک خصوصی «ملک من» می‌خورد؛ آگهی عمومی با این کد نمانده."""
    matches = _rows_for_code(lands, code)
    if not matches:
        return False
    saw_private = False
    for land in matches:
        if is_published_for_sale(land):
            return False
        if land.get("is_express") and not is_owner_home(land):
            return False
        if is_my_property_record(land):
            saw_private = True
    return saw_private


def apply_owner_unpublish(
    items: Any,
    phone: str,
    land_code: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """هر ردیف ملک منِ این کد را خصوصی کن. خروجی: رکورد، خطا، و آیا فایلی عوض شد."""
    owned = [
        item
        for item in _rows_for_code(items, land_code)
        if is_my_property_record(item) and _same_phone(_owner_phone(item), phone)
    ]
    if not owned:
        return None, "not_found", False
    changed = False
    for target in owned:
        still_public = (
            is_published_for_sale(target)
            or bool(target.get("is_express"))
            or target.get("public") is True
            or str(target.get("source") or "").strip().lower() == "my_property_published"
        )
        if still_public:
            _restore_private_owner_home(target)
            changed = True
    return owned[0], None, changed


def unpublish_owner_home(
    phone: str,
    *,
    land_code: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """برداشتن ملک «ملک من» از آگهی‌های فروش.

    نحوهٔ پرداخت و پورسانت اینجا بررسی نمی‌شوند؛ همان مسیر انتشار این فیلدها را
    قبل از پرچم توقف اجباری می‌کرد و توقف را به خطای «نحوه پرداخت» یا
    «قبلاً منتشر شده» تبدیل می‌کرد و آگهی روشن می‌ماند.
    همهٔ ردیف‌های همین کد عوض می‌شوند؛ جزئیات، اولین ردیف اکسپرس را نشان می‌دهد
    و اگر فقط ردیف اول خصوصی شود اپ همچنان آگهی را منتشر می‌بیند.
    """
    want = str(land_code or "").strip()
    if not want:
        return None, "not_found"
    items = load_ads() or []
    if not isinstance(items, list):
        items = []
    target, err, changed = apply_owner_unpublish(items, phone, want)
    if err:
        return None, err
    if not changed:
        return target, None
    try:
        save_ads(items)
    except Exception:
        current_app.logger.exception("unpublish owner home save failed code=%s", want)
        return None, "save_failed"
    return target, None


def save_special_listing_upload_document(file) -> Optional[str]:
    return _save_express_document(file, "draft")
