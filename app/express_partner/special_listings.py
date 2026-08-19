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


def listings_owned_by(phone: str) -> List[Dict[str, Any]]:
    ph = _norm_phone(phone)
    if not ph:
        return []
    lands = load_ads_cached() or []
    out: List[Dict[str, Any]] = []
    for land in lands if isinstance(lands, list) else []:
        if not isinstance(land, dict):
            continue
        if not land.get("is_express"):
            continue
        owner = _norm_phone(str(land.get("owner") or land.get("user_phone") or ""))
        if owner == ph:
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
    return _norm_phone(str(land.get("owner") or "")) == _norm_phone(phone)


def find_owned_land(phone: str, code: str) -> Optional[Dict[str, Any]]:
    code = str(code or "").strip()
    for land in listings_owned_by(phone):
        if str(land.get("code") or "") == code:
            return land
    return None


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
}


def create_special_listing_from_express_form(
    *,
    owner_phone: str,
    form,
    files,
    cities: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """ثبت آگهی اکسپرس همکار ویژه — همان فیلدهای فرم ادمین."""
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
    if not payment_method:
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


def save_special_listing_upload_document(file) -> Optional[str]:
    return _save_express_document(file, "draft")
