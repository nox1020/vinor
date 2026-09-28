# -*- coding: utf-8 -*-
"""آنبوردینگ مشاور فاز ۱ روی همان رکورد Express Partner.

برچسب UI «بازاریاب وینور» معادل نقش API برابر ``consultant`` است.
درخواست موازی ساخته نمی‌شود؛ وضعیت داخل ``consultant_onboarding`` همان همکار است.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

_log = logging.getLogger(__name__)

from app.express_partner.partner_session_sync import (
    canonical_partner_phone,
    find_partner_record,
)
from app.utils.storage import data_dir, load_express_partners, save_express_partners

CONSULTANT_ROLE = "consultant"
UI_LABEL = "بازاریاب وینور"
SERVER_MESSAGE = "مشکلی پیش آمد؛ دوباره تلاش کنید."
DEFAULT_REJECT_REASON = "درخواست همکاری مشاور تأیید نشد."
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_SPECIALTIES = ("buy", "sell")
_TEHRAN = ZoneInfo("Asia/Tehran")

# قفل مشترک وب/apk — ترتیب و برچسب‌ها دقیقاً مطابق قرارداد فاز ۱.
PHASE1_CITIES: Tuple[Tuple[str, str], ...] = (
    ("tehran", "تهران"),
    ("rey", "شهرری"),
    ("eslamshahr", "اسلامشهر"),
    ("baharestan", "بهارستان"),
    ("shahriar", "شهریار"),
    ("malard", "ملارد"),
    ("qods", "قدس"),
    ("robat_karim", "رباط‌کریم"),
    ("pakdasht", "پاکدشت"),
    ("varamin", "ورامین"),
    ("qarchak", "قرچک"),
    ("pardis", "پردیس"),
    ("shemiranat", "شمیرانات"),
    ("damavand", "دماوند"),
    ("andisheh", "اندیشه"),
)
CITY_IDS = frozenset(item[0] for item in PHASE1_CITIES)
_DOC_KINDS = ("national_id", "license")
_DOC_EXTS = ("jpg", "png", "pdf")


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def consultant_api_enabled() -> bool:
    return _env_bool("VINOR_CONSULTANT_API_ENABLED", "1")


def dry_run_enabled() -> bool:
    """شبیه‌سازی تأیید برای کلاینت. پیش‌فرض خاموش است تا همکار نتواند خودش را تأیید کند.

    این یک گیت امنیتی است، نه فلگ قابلیت محصول: فقط با VINOR_CONSULTANT_DRY_RUN=1 روشن می‌شود.
    """
    return _env_bool("VINOR_CONSULTANT_DRY_RUN", "0")


def env_review_override() -> str:
    """VINOR_CONSULTANT_SIMULATE روی خواندن اثر می‌گذارد و روی دیسک تأیید دائمی نمی‌نویسد.

    فقط وقتی dry-run صریحاً روشن باشد اعمال می‌شود. در حالت پیش‌فرض (خاموش) نادیده گرفته می‌شود.
    """
    if not dry_run_enabled():
        return ""
    raw = (os.environ.get("VINOR_CONSULTANT_SIMULATE") or "").strip().lower()
    if raw in ("approved", "rejected", "pending"):
        return raw
    return ""


def cities_payload() -> Dict[str, Any]:
    return {
        "ok": True,
        "cities": [{"id": cid, "label": label} for cid, label in PHASE1_CITIES],
    }


def tehran_now_iso() -> str:
    return datetime.now(_TEHRAN).isoformat(timespec="seconds")


def _err(code: str, message: str, status: int, fields: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], int]:
    body: Dict[str, Any] = {"ok": False, "error": code, "message": message}
    if fields:
        body["fields"] = fields
    return body, status


def _ok(body: Dict[str, Any], status: int = 200) -> Tuple[Dict[str, Any], int]:
    payload = {"ok": True}
    payload.update(body)
    return payload, status


def _partners() -> List[Dict[str, Any]]:
    items = load_express_partners() or []
    if not isinstance(items, list):
        return []
    return [p for p in items if isinstance(p, dict)]


def _next_partner_id(partners: List[Dict[str, Any]]) -> int:
    highest = 0
    for row in partners:
        try:
            highest = max(highest, int(row.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return highest + 1


def _public_id(record: Dict[str, Any]) -> str:
    return str(record.get("id") or "")


def _blank_onboarding() -> Dict[str, Any]:
    return {
        "role": CONSULTANT_ROLE,
        "ui_label": UI_LABEL,
        "name": "",
        "city": "",
        "specialties": [],
        "documents": {
            "national_id": {"uploaded": False},
            "license": {"uploaded": False},
        },
        "review": "",
        "reject_reason": None,
        "online": False,
        "online_updated_at": None,
        "onboarding_slides_seen": False,
        "created_at": tehran_now_iso(),
    }


def _onboarding(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    block = record.get("consultant_onboarding")
    if isinstance(block, dict) and block.get("role") == CONSULTANT_ROLE:
        return block
    return None


def _ensure_onboarding(record: Dict[str, Any]) -> Dict[str, Any]:
    block = _onboarding(record)
    if block is None:
        block = _blank_onboarding()
        record["consultant_onboarding"] = block
    record["api_role"] = CONSULTANT_ROLE
    return block


def _load_pair(phone: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    partners = _partners()
    return partners, find_partner_record(partners, phone)


def _require_block(phone: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Tuple[Dict[str, Any], int]]]:
    partners, record = _load_pair(phone)
    if record is None:
        return None, None, None, _err(
            "not_applied",
            "ابتدا درخواست همکاری مشاور را ثبت کنید.",
            404,
        )
    block = _onboarding(record)
    if block is None:
        return None, None, None, _err(
            "not_applied",
            "ابتدا درخواست همکاری مشاور را ثبت کنید.",
            404,
        )
    return partners, record, block, None


def _persist(partners: List[Dict[str, Any]]) -> None:
    save_express_partners(partners)


def normalize_name(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    name = " ".join(raw.split())
    if len(name) < 2 or len(name) > 40:
        return None
    return name


def normalize_city(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    city = raw.strip()
    if city not in CITY_IDS:
        return None
    return city


def normalize_specialties(raw: Any) -> Optional[List[str]]:
    if not isinstance(raw, list) or not raw:
        return None
    found = []
    for item in raw:
        if not isinstance(item, str):
            return None
        value = item.strip().lower()
        if value not in ALLOWED_SPECIALTIES:
            return None
        if value not in found:
            found.append(value)
    if not found:
        return None
    return [item for item in ALLOWED_SPECIALTIES if item in found]


def profile_complete(block: Dict[str, Any]) -> bool:
    return bool(
        normalize_name(block.get("name"))
        and normalize_city(block.get("city"))
        and normalize_specialties(block.get("specialties"))
    )


def _doc_uploaded(block: Dict[str, Any], kind: str) -> bool:
    docs = block.get("documents") if isinstance(block.get("documents"), dict) else {}
    item = docs.get(kind) if isinstance(docs, dict) else None
    return bool(isinstance(item, dict) and item.get("uploaded"))


def documents_complete(block: Dict[str, Any]) -> bool:
    return _doc_uploaded(block, "national_id")


def review_outcome(block: Dict[str, Any]) -> Optional[str]:
    """approved/rejected مؤثر؛ None یعنی هنوز در جریان آنبوردینگ."""
    forced = env_review_override()
    if forced == "pending":
        return None
    if forced in ("approved", "rejected"):
        return forced
    stored = str(block.get("review") or "").strip().lower()
    if stored in ("approved", "rejected"):
        return stored
    return None


def coarse_status(block: Dict[str, Any]) -> str:
    return review_outcome(block) or "pending"


def detail_status(block: Dict[str, Any]) -> str:
    outcome = review_outcome(block)
    if outcome in ("approved", "rejected"):
        return outcome
    if not profile_complete(block):
        return "pending_profile"
    if not documents_complete(block):
        return "pending_documents"
    return "pending"


def next_step(block: Dict[str, Any]) -> str:
    outcome = review_outcome(block)
    if outcome == "approved":
        return "dashboard"
    if outcome == "rejected":
        return "status"
    if not profile_complete(block):
        return "profile"
    if not documents_complete(block):
        return "documents"
    return "status"


def public_online(block: Dict[str, Any]) -> bool:
    if coarse_status(block) != "approved":
        return False
    return bool(block.get("online"))


def reject_reason_public(block: Dict[str, Any]) -> Optional[str]:
    if coarse_status(block) != "rejected":
        return None
    text = str(block.get("reject_reason") or "").strip()
    return text or DEFAULT_REJECT_REASON


def public_documents(block: Dict[str, Any]) -> Dict[str, Dict[str, bool]]:
    return {
        "national_id": {"uploaded": _doc_uploaded(block, "national_id")},
        "license": {"uploaded": _doc_uploaded(block, "license")},
    }


def status_body(record: Dict[str, Any], block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": CONSULTANT_ROLE,
        "status": coarse_status(block),
        "reject_reason": reject_reason_public(block),
        "profile_complete": profile_complete(block),
        "documents_complete": documents_complete(block),
        "online": public_online(block),
        "next_step": next_step(block),
        "onboarding_slides_seen": bool(block.get("onboarding_slides_seen")),
    }


def apply_body(record: Dict[str, Any], block: Dict[str, Any]) -> Dict[str, Any]:
    ident = _public_id(record)
    return {
        "consultant_id": ident,
        "partner_id": ident,
        "role": CONSULTANT_ROLE,
        "status": detail_status(block),
        "next_step": next_step(block),
    }


def start_application(phone: str) -> Tuple[Dict[str, Any], int]:
    """شروع یا ادامهٔ آنبوردینگ. رکورد همکار موجود را بازنویسیِ تأیید نمی‌کند."""
    canonical = canonical_partner_phone(phone)
    if not canonical:
        return _err("unauthorized", "برای ادامه باید با حساب همکار وارد شوید.", 401)
    partners, record = _load_pair(canonical)
    if record is None:
        record = {
            "id": _next_partner_id(partners),
            "phone": canonical,
            "name": "",
            "status": "pending",
            "created_at": tehran_now_iso(),
        }
        partners.append(record)
    elif not record.get("id"):
        record["id"] = _next_partner_id(partners)
    block = _ensure_onboarding(record)
    try:
        _persist(partners)
    except Exception:
        _log.exception("consultant apply save failed")
        return _err("server", SERVER_MESSAGE, 500)
    return _ok(apply_body(record, block))


def update_profile(phone: str, data: Any) -> Tuple[Dict[str, Any], int]:
    if not isinstance(data, dict):
        return _err("validation", "بدنهٔ درخواست نامعتبر است.", 400)
    partners, record, block, failure = _require_block(phone)
    if failure:
        return failure
    assert partners is not None and record is not None and block is not None

    fields: Dict[str, str] = {}
    name = normalize_name(data.get("name"))
    city = normalize_city(data.get("city"))
    specialties = normalize_specialties(data.get("specialties"))
    if name is None:
        fields["name"] = "نام باید بین ۲ تا ۴۰ نویسه باشد."
    if city is None:
        fields["city"] = "شهر باید یکی از شناسه‌های فاز ۱ باشد."
    if specialties is None:
        fields["specialties"] = "تخصص فقط خرید (buy) یا فروش (sell) است."
    if fields:
        return _err("validation", "اطلاعات واردشده معتبر نیست.", 400, fields)

    block["name"] = name
    block["city"] = city
    block["specialties"] = specialties
    # نام نمایشی همان همکار است. شناسهٔ شهر فاز ۱ روی city سراسری نوشته نمی‌شود
    # چون پنل موجود برچسب فارسی شهر را نگه می‌دارد.
    record["name"] = name
    record["api_role"] = CONSULTANT_ROLE
    try:
        _persist(partners)
    except Exception:
        _log.exception("consultant profile save failed")
        return _err("server", SERVER_MESSAGE, 500)
    return _ok(
        {
            "profile": {"name": name, "city": city, "specialties": specialties},
            "status": detail_status(block),
            "next_step": next_step(block),
        }
    )


def sniff_upload(raw: bytes) -> Optional[str]:
    if raw.startswith(b"%PDF"):
        return "pdf"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def _private_root() -> str:
    root = os.path.join(data_dir(), "consultant_private")
    os.makedirs(root, exist_ok=True)
    return os.path.realpath(root)


def _partner_dir(partner_id: str) -> str:
    if not str(partner_id).isdigit():
        raise ValueError("invalid partner id")
    root = _private_root()
    path = os.path.realpath(os.path.join(root, str(partner_id)))
    if path != root and not path.startswith(root + os.sep):
        raise ValueError("invalid partner path")
    os.makedirs(path, exist_ok=True)
    return path


def _remove_kind_files(partner_id: str, kind: str, *, keep_ext: str = "") -> None:
    if kind not in _DOC_KINDS:
        return
    folder = _partner_dir(partner_id)
    for ext in _DOC_EXTS:
        if keep_ext and ext == keep_ext:
            continue
        target = os.path.join(folder, f"{kind}.{ext}")
        if os.path.isfile(target):
            try:
                os.remove(target)
            except OSError:
                pass


def _write_kind(partner_id: str, kind: str, raw: bytes, ext: str) -> Dict[str, Any]:
    folder = _partner_dir(partner_id)
    _remove_kind_files(partner_id, kind)
    path = os.path.join(folder, f"{kind}.{ext}")
    with open(path, "wb") as handle:
        handle.write(raw)
    return {"uploaded": True, "ext": ext, "size": len(raw)}


def validate_upload(raw: bytes, *, required: bool, present: bool) -> Tuple[Optional[str], Optional[str]]:
    """برمی‌گرداند (ext, message). present=False و required=False یعنی فایل نیامده."""
    if not present:
        if required:
            return None, "بارگذاری تصویر کارت ملی الزامی است."
        return None, None
    if not raw:
        return None, "فایل خالی است."
    if len(raw) > MAX_UPLOAD_BYTES:
        return None, "حجم هر فایل حداکثر ۵ مگابایت است."
    ext = sniff_upload(raw)
    if not ext:
        return None, "فقط فایل jpg، png یا pdf مجاز است."
    return ext, None


def save_documents(
    phone: str,
    *,
    national_id: Optional[bytes],
    national_id_present: bool,
    license_file: Optional[bytes],
    license_present: bool,
) -> Tuple[Dict[str, Any], int]:
    partners, record, block, failure = _require_block(phone)
    if failure:
        return failure
    assert partners is not None and record is not None and block is not None
    if not profile_complete(block):
        return _err(
            "validation",
            "ابتدا پروفایل را کامل کنید.",
            400,
            {"profile": "ابتدا نام، شهر و تخصص را ثبت کنید."},
        )

    fields: Dict[str, str] = {}
    nat_ext, nat_msg = validate_upload(
        national_id or b"",
        required=True,
        present=national_id_present,
    )
    lic_ext, lic_msg = validate_upload(
        license_file or b"",
        required=False,
        present=license_present,
    )
    if nat_msg:
        fields["national_id"] = nat_msg
    if lic_msg:
        fields["license"] = lic_msg
    if fields:
        summary = fields.get("national_id") or fields.get("license") or "فایل مدرک معتبر نیست."
        return _err("validation", summary, 400, fields)

    partner_id = _public_id(record)
    try:
        docs = block.get("documents") if isinstance(block.get("documents"), dict) else {}
        block["documents"] = docs
        docs["national_id"] = _write_kind(partner_id, "national_id", national_id or b"", nat_ext or "jpg")
        if license_present:
            docs["license"] = _write_kind(partner_id, "license", license_file or b"", lic_ext or "pdf")
        elif not isinstance(docs.get("license"), dict):
            docs["license"] = {"uploaded": False}
        if review_outcome(block) != "approved" and not env_review_override():
            block["review"] = "pending"
            block["reject_reason"] = None
        record["api_role"] = CONSULTANT_ROLE
        _persist(partners)
    except Exception:
        _log.exception("consultant documents save failed")
        return _err("server", SERVER_MESSAGE, 500)
    return _ok(
        {
            "status": detail_status(block),
            "next_step": next_step(block),
            "documents": public_documents(block),
        }
    )


def read_status(phone: str) -> Tuple[Dict[str, Any], int]:
    _partners_list, record, block, failure = _require_block(phone)
    if failure:
        return failure
    assert record is not None and block is not None
    return _ok(status_body(record, block))


def set_availability(phone: str, data: Any) -> Tuple[Dict[str, Any], int]:
    if not isinstance(data, dict) or not isinstance(data.get("online"), bool):
        return _err(
            "validation",
            "وضعیت آنلاین باید true یا false باشد.",
            400,
            {"online": "وضعیت آنلاین باید true یا false باشد."},
        )
    partners, record, block, failure = _require_block(phone)
    if failure:
        return failure
    assert partners is not None and record is not None and block is not None
    if coarse_status(block) != "approved":
        return _err(
            "not_approved",
            "تغییر وضعیت آنلاین فقط پس از تأیید درخواست ممکن است.",
            409,
        )
    online = bool(data.get("online"))
    block["online"] = online
    updated = tehran_now_iso()
    block["online_updated_at"] = updated
    try:
        _persist(partners)
    except Exception:
        _log.exception("consultant availability save failed")
        return _err("server", SERVER_MESSAGE, 500)
    return _ok({"online": online, "updated_at": updated})


def apply_simulation(phone: str, target: str, reject_reason: Any = None) -> Tuple[Dict[str, Any], int]:
    target = (target or "").strip().lower()
    if target not in ("approved", "rejected", "pending"):
        return _err(
            "validation",
            "وضعیت آزمایشی باید approved، rejected یا pending باشد.",
            400,
            {"status": "وضعیت آزمایشی باید approved، rejected یا pending باشد."},
        )
    partners, record, block, failure = _require_block(phone)
    if failure:
        return failure
    assert partners is not None and record is not None and block is not None
    if target == "approved":
        block["review"] = "approved"
        block["reject_reason"] = None
    elif target == "rejected":
        block["review"] = "rejected"
        text = str(reject_reason or "").strip() if reject_reason is not None else ""
        block["reject_reason"] = (text[:300] if text else DEFAULT_REJECT_REASON)
    else:
        block["review"] = "pending"
        block["reject_reason"] = None
    try:
        _persist(partners)
    except Exception:
        _log.exception("consultant simulate save failed")
        return _err("server", SERVER_MESSAGE, 500)
    return _ok(status_body(record, block))
