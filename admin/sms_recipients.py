# -*- coding: utf-8 -*-
"""گروه‌های گیرنده پیامک ادمین — ذخیره و ویرایش دستی."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.express_partner.new_land_sms import list_approved_express_partners
from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
from app.utils.storage import (
    ensure_file,
    load_express_partners,
    load_sms_recipient_groups,
    load_users,
    save_sms_recipient_groups,
)

RECIPIENT_GROUP_APPROVED = "approved"
RECIPIENT_GROUP_ALL_USERS = "all_users"
RECIPIENT_GROUP_CUSTOMER_CLUB = "customer_club"

RECIPIENT_GROUP_ORDER = (
    RECIPIENT_GROUP_APPROVED,
    RECIPIENT_GROUP_ALL_USERS,
    RECIPIENT_GROUP_CUSTOMER_CLUB,
)

RECIPIENT_GROUP_LABELS: Dict[str, str] = {
    RECIPIENT_GROUP_APPROVED: "همکاران تأییدشده",
    RECIPIENT_GROUP_ALL_USERS: "همه کاربران",
    RECIPIENT_GROUP_CUSTOMER_CLUB: "باشگاه مشتریان",
}

RECIPIENT_GROUP_HINTS: Dict[str, str] = {
    RECIPIENT_GROUP_APPROVED: "فقط همکاران تأییدشده با شماره معتبر",
    RECIPIENT_GROUP_ALL_USERS: "همهٔ شماره‌های ثبت‌شده در پرتال و کاربران سایت",
    RECIPIENT_GROUP_CUSTOMER_CLUB: "کاربران عادی (غیرهمکار تأییدشده) با شماره معتبر",
}

# محدودیت آپلود گروهی — حجم بالا مجاز
MAX_UPLOAD_FILES = 200
MAX_UPLOAD_BYTES = 80 * 1024 * 1024  # 80MB مجموع فایل‌ها
MAX_SINGLE_FILE_BYTES = 40 * 1024 * 1024  # 40MB هر فایل
_COMPACT_SAVE_THRESHOLD = 2500  # بالای این تعداد عضو → JSON فشرده (سریع‌تر)

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PURE_ASCII_PHONE = re.compile(r"^0?9\d{9}$")
_HAS_NON_ASCII = re.compile(r"[^\x00-\x7f]")


def normalize_recipient_group(value: str) -> str:
    key = (value or RECIPIENT_GROUP_APPROVED).strip().lower()
    if "=" in key:
        key = key.rsplit("=", 1)[-1].strip()
    if key.startswith("recipient_group"):
        key = key[len("recipient_group"):].lstrip("=_")
    if key in RECIPIENT_GROUP_LABELS:
        return key
    return RECIPIENT_GROUP_APPROVED


def recipient_group_label(group: str) -> str:
    key = normalize_recipient_group(group)
    data = _load_store()
    grp = data.get("groups", {}).get(key) or {}
    return str(grp.get("label") or RECIPIENT_GROUP_LABELS[key])


def recipient_group_hint(group: str) -> str:
    key = normalize_recipient_group(group)
    data = _load_store()
    grp = data.get("groups", {}).get(key) or {}
    return str(grp.get("hint") or RECIPIENT_GROUP_HINTS[key])


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_store() -> Dict[str, Any]:
    raw = load_sms_recipient_groups() or {}
    if not isinstance(raw, dict):
        raw = {}
    groups = raw.get("groups")
    if not isinstance(groups, dict):
        raw["groups"] = {}
    return raw


def _save_store(data: Dict[str, Any]) -> None:
    """ذخیره اتمی — برای حجم بالا بدون indent تا سرعت و حجم فایل بهتر شود."""
    member_total = 0
    groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
    for grp in groups.values():
        if isinstance(grp, dict) and isinstance(grp.get("members"), list):
            member_total += len(grp["members"])

    if member_total < _COMPACT_SAVE_THRESHOLD:
        save_sms_recipient_groups(data)
        return

    path = ensure_file("SMS_RECIPIENT_GROUPS_FILE", "sms_recipient_groups.json", {"groups": {}})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _default_group_block(key: str) -> Dict[str, Any]:
    return {
        "label": RECIPIENT_GROUP_LABELS[key],
        "hint": RECIPIENT_GROUP_HINTS[key],
        "members": [],
        "synced_at": "",
        "updated_at": "",
    }


def _approved_phone_set() -> set[str]:
    return {p["phone"] for p in list_approved_express_partners() if p.get("phone")}


def _normalize_member(phone_raw: str, name: str, source: str = "manual") -> Optional[Dict[str, str]]:
    phone = normalize_iran_mobile(str(phone_raw or "").strip())
    if not is_valid_iran_mobile(phone):
        return None
    return {
        "phone": phone,
        "name": str(name or phone).strip() or phone,
        "source": source if source in ("auto", "manual") else "manual",
    }


def _auto_recipients_for_group(group: str) -> List[Dict[str, str]]:
    key = normalize_recipient_group(group)
    approved_phones = _approved_phone_set()
    store: Dict[str, Dict[str, str]] = {}

    def add(phone_raw: str, name: str) -> None:
        member = _normalize_member(phone_raw, name, "auto")
        if member and member["phone"] not in store:
            store[member["phone"]] = member

    if key == RECIPIENT_GROUP_APPROVED:
        for item in list_approved_express_partners():
            add(item.get("phone"), item.get("name") or "")
        return list(store.values())

    users = load_users() or []
    partners = load_express_partners() or []

    if key == RECIPIENT_GROUP_ALL_USERS:
        for p in partners if isinstance(partners, list) else []:
            if isinstance(p, dict):
                add(p.get("phone"), str(p.get("name") or p.get("full_name") or "").strip())
        for u in users if isinstance(users, list) else []:
            if isinstance(u, dict):
                add(u.get("phone") or u.get("mobile"), str(u.get("name") or u.get("fullname") or "").strip())
        return list(store.values())

    if key == RECIPIENT_GROUP_CUSTOMER_CLUB:
        for u in users if isinstance(users, list) else []:
            if not isinstance(u, dict):
                continue
            phone = normalize_iran_mobile(str(u.get("phone") or u.get("mobile") or "").strip())
            if not is_valid_iran_mobile(phone) or phone in approved_phones:
                continue
            add(phone, str(u.get("name") or u.get("fullname") or "").strip())
        return list(store.values())

    return []


def ensure_sms_recipient_groups_initialized() -> None:
    data = _load_store()
    groups = data.setdefault("groups", {})
    changed = False
    for key in RECIPIENT_GROUP_ORDER:
        grp = groups.get(key)
        if not isinstance(grp, dict):
            groups[key] = _default_group_block(key)
            changed = True
            grp = groups[key]
        grp.setdefault("label", RECIPIENT_GROUP_LABELS[key])
        grp.setdefault("hint", RECIPIENT_GROUP_HINTS[key])
        if not isinstance(grp.get("members"), list) or not grp["members"]:
            grp["members"] = _auto_recipients_for_group(key)
            grp["synced_at"] = _now_iso()
            grp["updated_at"] = grp["synced_at"]
            changed = True
    if changed:
        _save_store(data)


def sync_sms_recipient_group(group: str) -> int:
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    grp["members"] = _auto_recipients_for_group(key)
    ts = _now_iso()
    grp["synced_at"] = ts
    grp["updated_at"] = ts
    _save_store(data)
    return len(grp["members"])


def load_sms_recipients(group: str) -> List[Dict[str, str]]:
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    grp = (_load_store().get("groups") or {}).get(key) or {}
    members = grp.get("members") if isinstance(grp.get("members"), list) else []
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in members:
        if not isinstance(item, dict):
            continue
        phone = normalize_iran_mobile(str(item.get("phone") or "").strip())
        if not is_valid_iran_mobile(phone) or phone in seen:
            continue
        seen.add(phone)
        out.append({
            "phone": phone,
            "name": str(item.get("name") or phone).strip() or phone,
            "source": str(item.get("source") or "manual"),
        })
    return out


def recipient_group_counts() -> Dict[str, int]:
    ensure_sms_recipient_groups_initialized()
    return {key: len(load_sms_recipients(key)) for key in RECIPIENT_GROUP_ORDER}


def list_sms_recipient_groups_summary() -> List[Dict[str, Any]]:
    ensure_sms_recipient_groups_initialized()
    data = _load_store().get("groups") or {}
    rows: List[Dict[str, Any]] = []
    for key in RECIPIENT_GROUP_ORDER:
        grp = data.get(key) or {}
        rows.append({
            "key": key,
            "label": str(grp.get("label") or RECIPIENT_GROUP_LABELS[key]),
            "hint": str(grp.get("hint") or RECIPIENT_GROUP_HINTS[key]),
            "count": len(load_sms_recipients(key)),
            "synced_at": grp.get("synced_at") or "",
            "updated_at": grp.get("updated_at") or "",
        })
    return rows


def get_sms_recipient_group_detail(group: str) -> Dict[str, Any]:
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    grp = (_load_store().get("groups") or {}).get(key) or _default_group_block(key)
    return {
        "key": key,
        "label": str(grp.get("label") or RECIPIENT_GROUP_LABELS[key]),
        "hint": str(grp.get("hint") or RECIPIENT_GROUP_HINTS[key]),
        "members": load_sms_recipients(key),
        "synced_at": grp.get("synced_at") or "",
        "updated_at": grp.get("updated_at") or "",
    }


def update_sms_recipient_group_meta(group: str, *, label: str, hint: str) -> None:
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    grp["label"] = (label or RECIPIENT_GROUP_LABELS[key]).strip() or RECIPIENT_GROUP_LABELS[key]
    grp["hint"] = (hint or RECIPIENT_GROUP_HINTS[key]).strip() or RECIPIENT_GROUP_HINTS[key]
    grp["updated_at"] = _now_iso()
    _save_store(data)


def add_sms_recipient_member(group: str, phone: str, name: str) -> Optional[str]:
    member = _normalize_member(phone, name, "manual")
    if not member:
        return "شماره موبایل معتبر نیست."
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    members = grp.setdefault("members", [])
    for item in members:
        if isinstance(item, dict) and normalize_iran_mobile(str(item.get("phone") or "")) == member["phone"]:
            item["name"] = member["name"]
            item["source"] = "manual"
            grp["updated_at"] = _now_iso()
            _save_store(data)
            return None
    members.append(member)
    grp["updated_at"] = _now_iso()
    _save_store(data)
    return None


def update_sms_recipient_member(group: str, phone: str, name: str) -> Optional[str]:
    key = normalize_recipient_group(group)
    target = normalize_iran_mobile(str(phone or "").strip())
    if not is_valid_iran_mobile(target):
        return "شماره موبایل معتبر نیست."
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    members = grp.setdefault("members", [])
    for item in members:
        if isinstance(item, dict) and normalize_iran_mobile(str(item.get("phone") or "")) == target:
            item["name"] = str(name or target).strip() or target
            grp["updated_at"] = _now_iso()
            _save_store(data)
            return None
    return "عضو در این گروه یافت نشد."


def remove_sms_recipient_member(group: str, phone: str) -> Optional[str]:
    key = normalize_recipient_group(group)
    target = normalize_iran_mobile(str(phone or "").strip())
    if not is_valid_iran_mobile(target):
        return "شماره موبایل معتبر نیست."
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    before = len(grp.get("members") or [])
    grp["members"] = [
        m for m in (grp.get("members") or [])
        if not (isinstance(m, dict) and normalize_iran_mobile(str(m.get("phone") or "")) == target)
    ]
    if len(grp["members"]) == before:
        return "عضو در این گروه یافت نشد."
    grp["updated_at"] = _now_iso()
    _save_store(data)
    return None


def export_sms_recipient_phones_txt(group: str) -> str:
    """یک شماره در هر خط — برای دانلود فایل txt."""
    lines = [item["phone"] for item in load_sms_recipients(group) if item.get("phone")]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _fast_ascii_phone(raw: str) -> Optional[str]:
    """مسیر سریع برای خطوط فقط‌شماره ASCII (عمده آپلودهای حجیم)."""
    s = raw.strip().replace(" ", "").replace("-", "")
    if not s or not s[0].isdigit():
        return None
    if _PURE_ASCII_PHONE.match(s):
        return s if len(s) == 11 else ("0" + s)
    return None


def _parse_phone_import_line(raw: str) -> Optional[Dict[str, str]]:
    """هر خط: شماره، یا «شماره,نام» / «نام,شماره» / جدا با تب."""
    line = (raw or "").strip().lstrip("\ufeff")
    if not line or line.startswith("#"):
        return None

    # مسیر سریع: فقط شماره بدون جداکننده
    if "," not in line and "\t" not in line:
        if not _HAS_NON_ASCII.search(line):
            phone = _fast_ascii_phone(line)
            if phone and is_valid_iran_mobile(phone):
                return {"phone": phone, "name": phone, "source": "manual"}
            return None
        return _normalize_member(line.translate(_FA_DIGITS), "", "manual")

    name = ""
    phone_raw = line
    if "\t" in line:
        left, right = line.split("\t", 1)
        left, right = left.strip(), right.strip()
        na, nb = normalize_iran_mobile(left), normalize_iran_mobile(right)
        if is_valid_iran_mobile(na):
            phone_raw, name = left, right
        elif is_valid_iran_mobile(nb):
            phone_raw, name = right, left
        else:
            phone_raw = left or right
    elif "," in line:
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if len(parts) >= 2:
            a, b = parts[0], parts[1]
            na, nb = normalize_iran_mobile(a), normalize_iran_mobile(b)
            if is_valid_iran_mobile(na):
                phone_raw, name = a, b
            elif is_valid_iran_mobile(nb):
                phone_raw, name = b, a
            else:
                phone_raw = a
        elif parts:
            phone_raw = parts[0]
    return _normalize_member(phone_raw, name, "manual")


def parse_sms_recipient_phones_text(
    text: str,
    *,
    seen: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, str]], int, int]:
    """متن چندخطی → (اعضای معتبر جدید، نامعتبر، تکراری ردشده)."""
    if seen is None:
        seen = set()
    out: List[Dict[str, str]] = []
    invalid = 0
    skipped = 0
    if not text:
        return out, invalid, skipped
    # یک‌بار normalize خط‌شکن‌ها
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw in text.split("\n"):
        if not raw or not raw.strip():
            continue
        member = _parse_phone_import_line(raw)
        if not member:
            invalid += 1
            continue
        phone = member["phone"]
        if phone in seen:
            skipped += 1
            continue
        seen.add(phone)
        out.append(member)
    return out, invalid, skipped


def import_sms_recipient_phones(
    group: str,
    text: str,
    *,
    replace: bool = False,
) -> Dict[str, int]:
    """ورود شماره از متن/فایل .txt به گروه. replace=True لیست را عوض می‌کند."""
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    grp = data["groups"].setdefault(key, _default_group_block(key))
    members = grp.setdefault("members", [])
    if not isinstance(members, list):
        members = []
        grp["members"] = members

    added = 0
    updated = 0
    if replace:
        parsed, invalid, skipped = parse_sms_recipient_phones_text(text)
        grp["members"] = parsed
        added = len(parsed)
        grp["updated_at"] = _now_iso()
        _save_store(data)
        return {
            "added": added,
            "updated": 0,
            "skipped": skipped,
            "invalid": invalid,
            "total": len(parsed),
            "files": 0,
        }

    by_phone: Dict[str, Dict[str, Any]] = {}
    for item in members:
        if not isinstance(item, dict):
            continue
        ph = str(item.get("phone") or "").strip()
        if len(ph) == 11 and ph.startswith("09"):
            by_phone[ph] = item
        else:
            ph_n = normalize_iran_mobile(ph)
            if is_valid_iran_mobile(ph_n):
                by_phone[ph_n] = item

    parsed, invalid, skipped = parse_sms_recipient_phones_text(text)

    for member in parsed:
        phone = member["phone"]
        existing = by_phone.get(phone)
        if existing is None:
            members.append(member)
            by_phone[phone] = member
            added += 1
        else:
            new_name = member["name"]
            if new_name and new_name != phone and new_name != str(existing.get("name") or ""):
                existing["name"] = new_name
                updated += 1
            else:
                skipped += 1
            existing["source"] = "manual"

    grp["updated_at"] = _now_iso()
    _save_store(data)
    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "invalid": invalid,
        "total": len(by_phone),
        "files": 0,
    }


def _decode_upload_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1256", errors="ignore")
        except Exception:
            return raw.decode("latin1", errors="ignore")


def read_phones_upload_text(upload: Any) -> Optional[str]:
    """خواندن متن فایل آپلود (.txt) — UTF-8 / UTF-16 / cp1256."""
    if not upload or not getattr(upload, "filename", None):
        return None
    try:
        raw = upload.read()
    except Exception:
        return None
    if isinstance(raw, bytes):
        return _decode_upload_bytes(raw)
    return str(raw or "")


def _upload_content_length(upload: Any) -> int:
    try:
        pos = upload.tell()
        upload.seek(0, os.SEEK_END)
        size = int(upload.tell() or 0)
        upload.seek(pos)
        return size
    except Exception:
        try:
            data = upload.read()
            size = len(data) if data else 0
            if hasattr(upload, "seek"):
                upload.seek(0)
            return size
        except Exception:
            return 0


def read_phones_upload_files(
    uploads: Any,
) -> Tuple[str, List[str], List[str], Dict[str, Any]]:
    """چند فایل .txt → (متن ترکیبی، OK، ناموفق، متا).

    محدودیت‌ها: تعداد فایل، حجم هر فایل، حجم کل.
    """
    parts: List[str] = []
    ok_names: List[str] = []
    failed_names: List[str] = []
    meta: Dict[str, Any] = {
        "bytes_read": 0,
        "file_count": 0,
        "error": None,
    }
    items = uploads if isinstance(uploads, list) else ([uploads] if uploads else [])
    # فقط فایل‌های دارای نام
    named = [u for u in items if getattr(u, "filename", None)]
    if len(named) > MAX_UPLOAD_FILES:
        meta["error"] = f"حداکثر {MAX_UPLOAD_FILES} فایل در هر آپلود مجاز است."
        return "", [], [], meta

    total_bytes = 0
    for upload in named:
        name = upload.filename or "file"
        size = _upload_content_length(upload)
        if size > MAX_SINGLE_FILE_BYTES:
            failed_names.append(f"{name} (حجم بیش از {MAX_SINGLE_FILE_BYTES // (1024 * 1024)}MB)")
            continue
        if total_bytes + size > MAX_UPLOAD_BYTES:
            meta["error"] = (
                f"حجم کل فایل‌ها از {MAX_UPLOAD_BYTES // (1024 * 1024)}MB بیشتر است. "
                "فایل‌ها را چند بخش آپلود کنید."
            )
            break
        text = read_phones_upload_text(upload)
        if text is None:
            failed_names.append(name)
            continue
        # حتی فایل خالی هم ممکن است whitespace داشته باشد
        stripped = text.strip()
        if not stripped:
            failed_names.append(f"{name} (خالی)")
            continue
        parts.append(stripped)
        ok_names.append(name)
        total_bytes += size if size > 0 else len(text.encode("utf-8", errors="ignore"))

    meta["bytes_read"] = total_bytes
    meta["file_count"] = len(ok_names)
    combined = "\n".join(parts)
    return combined, ok_names, failed_names, meta


def format_import_result_message(label: str, result: Dict[str, int], *, replace: bool) -> str:
    if replace:
        msg = f"«{label}»: جایگزینی با {result['added']} شماره معتبر"
    else:
        msg = f"«{label}»: {result['added']} افزوده"
        if result.get("updated"):
            msg += f"، {result['updated']} به‌روز"
    if result.get("skipped"):
        msg += f"، {result['skipped']} تکراری"
    if result.get("invalid"):
        msg += f"، {result['invalid']} نامعتبر"
    msg += f" — جمع {result['total']} عضو"
    return msg


def get_saved_recipient_group() -> str:
    """آخرین گروه انتخاب‌شده در صفحه پیامک همکاران."""
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    prefs = data.get("preferences")
    if not isinstance(prefs, dict):
        return RECIPIENT_GROUP_APPROVED
    return normalize_recipient_group(str(prefs.get("last_recipient_group") or ""))


def save_recipient_group_preference(group: str) -> str:
    """ذخیرهٔ گروه گیرنده برای بازدید بعدی."""
    key = normalize_recipient_group(group)
    ensure_sms_recipient_groups_initialized()
    data = _load_store()
    prefs = data.get("preferences")
    if not isinstance(prefs, dict):
        prefs = {}
        data["preferences"] = prefs
    prefs["last_recipient_group"] = key
    prefs["updated_at"] = _now_iso()
    _save_store(data)
    return key
