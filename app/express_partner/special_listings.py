# -*- coding: utf-8 -*-
"""آگهی‌های همکار ویژه — مالکیت بر اساس owner=phone."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from werkzeug.utils import secure_filename

from app.utils.images import save_upload_image
from app.utils.storage import load_ads, load_ads_cached, save_ads


def _norm_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or "").strip())


def _uploads_folder() -> str:
    folder = current_app.config.get("UPLOAD_FOLDER") or os.path.join(
        current_app.root_path, "static", "uploads"
    )
    os.makedirs(folder, exist_ok=True)
    return folder


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


def create_special_listing(
    *,
    owner_phone: str,
    title: str,
    city: str,
    location: str,
    size: int,
    price_total: int,
    description: str = "",
    commission_pct: float = 0.0,
    image_file=None,
    contact_phone: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    title = (title or "").strip()
    city = (city or "").strip()
    location = (location or "").strip() or city
    desc = (description or "").strip()
    owner = _norm_phone(owner_phone)
    contact = _norm_phone(contact_phone) or owner

    if not owner:
        return None, "invalid_owner"
    if len(title) < 8:
        return None, "title_short"
    if not city:
        return None, "city_required"
    if size <= 0 or price_total <= 0:
        return None, "invalid_price"
    if commission_pct < 0 or commission_pct > 100:
        return None, "invalid_commission"

    lands = load_ads() or []
    if not isinstance(lands, list):
        lands = []
    new_code = _next_numeric_code(lands)
    images: List[str] = []
    if image_file is not None and getattr(image_file, "filename", None):
        stored = save_upload_image(image_file, _uploads_folder())
        if stored:
            images.append(stored)
        else:
            fname = secure_filename(
                f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}__{image_file.filename}"
            )
            abs_path = os.path.join(_uploads_folder(), fname)
            image_file.save(abs_path)
            images.append(f"uploads/{fname}")

    price_per_meter = int(round(price_total / size)) if size > 0 else 0
    commission_amount = (
        int(round(price_total * (commission_pct / 100.0))) if commission_pct else 0
    )

    rec: Dict[str, Any] = {
        "code": new_code,
        "title": title,
        "location": location,
        "city": city,
        "size": int(size),
        "price_total": int(price_total),
        "price_per_meter": price_per_meter,
        "description": desc,
        "images": images,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "owner": owner,
        "status": "approved",
        "ad_type": "express",
        "category": "زمین",
        "payment_method": "نقدی",
        "payment_terms": [],
        "is_express": True,
        "express_status": "approved",
        "expert_verified": False,
        "express_documents": [],
        "vinor_contact": contact,
        "extras": {
            "express_commission_pct": float(commission_pct),
            "express_commission_amount": commission_amount,
            "listed_by_special": True,
        },
    }
    lands.append(rec)
    save_ads(lands)
    return rec, None
