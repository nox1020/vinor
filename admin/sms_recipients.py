# -*- coding: utf-8 -*-
"""گروه‌های گیرنده پیامک ادمین — ذخیره و ویرایش دستی."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.express_partner.new_land_sms import list_approved_express_partners
from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile
from app.utils.storage import load_express_partners, load_sms_recipient_groups, load_users, save_sms_recipient_groups

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


def normalize_recipient_group(value: str) -> str:
    key = (value or RECIPIENT_GROUP_APPROVED).strip().lower()
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
    save_sms_recipient_groups(data)


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
