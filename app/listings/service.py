# -*- coding: utf-8 -*-
"""منبع واحد آگهی‌ها.

همهٔ ساخت، خواندن، ویرایش، انتشار و توقف انتشار از همین ماژول رد می‌شوند
و فقط در ``<instance>/data/lands.json`` می‌نشینند. فایل قدیمی ``app/data/lands.json``
و هر مسیر پیکربندی جدا، یک‌بار در همین فایل ادغام می‌شوند و بعد دیگر خوانده نمی‌شوند.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

_FA_AR_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_GUARD = threading.RLock()
_LOCK_DEPTH = 0
_LOCK_HANDLE = None

_LIST_KEYS = ("images", "express_documents", "payment_terms", "features")
_EXTRAS_PUBLISH_KEYS = (
    "published_for_sale",
    "public",
    "owner_home",
    "listed_by_owner",
    "listed_by_special",
)
_CYCLE_KEYS = (
    "published_at",
    "first_published_at",
    "quiet_nudge_published_at",
)


def _digits(phone: str) -> str:
    text = str(phone or "").strip().translate(_FA_AR_DIGITS)
    return "".join(ch for ch in text if ch.isdigit())


def canonical_mobile(phone: str) -> str:
    """شماره را به 09xxxxxxxxx برگردان. 98 و ارقام فارسی با 09 یکی‌اند."""
    value = _digits(phone)
    if not value:
        return ""
    if value.startswith("0098") and len(value) >= 14 and value[4:].startswith("9"):
        value = "0" + value[4:]
    elif value.startswith("98") and len(value) >= 12 and value[2:].startswith("9"):
        value = "0" + value[2:]
    elif len(value) == 10 and value.startswith("9"):
        value = "0" + value
    if len(value) > 11 and value.startswith("09"):
        value = value[:11]
    return value


def same_owner(left: str, right: str) -> bool:
    a = canonical_mobile(left)
    b = canonical_mobile(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) >= 10 and len(b) >= 10 and a[-10:] == b[-10:]


def owner_phone(land: Dict[str, Any]) -> str:
    return str(
        land.get("owner")
        or land.get("user_phone")
        or land.get("phone")
        or land.get("owner_phone")
        or ""
    )


def code_key(land: Any) -> str:
    if not isinstance(land, dict):
        return ""
    return str(land.get("code") or "").strip().translate(_FA_AR_DIGITS)


def is_published_for_sale(land: Dict[str, Any] | None) -> bool:
    """ملک «ملک من» که برای فروش منتشر شده. هر سه علامت قدیمی یکی حساب می‌شوند."""
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


def is_private_owner_home(land: Dict[str, Any] | None) -> bool:
    """ملک منِ منتشرنشده. فید عمومی اکسپرس این ردیف را نشان نمی‌دهد."""
    if not isinstance(land, dict):
        return False
    if is_published_for_sale(land):
        return False
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    if land.get("owner_home") or extras.get("owner_home") or extras.get("listed_by_owner"):
        return True
    src = str(land.get("source") or "").strip().lower()
    if src in ("my_property", "owner_home"):
        return True
    if str(land.get("ad_type") or "").strip().lower() == "owner_home":
        return True
    return False


def mark_private(target: Dict[str, Any]) -> None:
    """هر علامتی که آگهی را عمومی می‌کند خاموش شود."""
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


def _cycle_stamp(land: Dict[str, Any], key: str) -> str:
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    return str(land.get(key) or extras.get(key) or "").strip()


def mark_published(
    target: Dict[str, Any],
    *,
    payment_method: str,
    commission_pct: float,
    amount: int,
) -> None:
    """انتشار فروش. وضعیت فروخته‌شدهٔ express_status حفظ می‌شود.

    اولین انتشار ``first_published_at`` را می‌نویسد و هر چرخهٔ انتشار
    ``published_at`` را تازه می‌کند. انتشار دوبارهٔ ردیفی که همین حالا زنده است
    ساعت چرخه را عوض نمی‌کند.
    """
    from app.utils.dates import iso_z, utcnow

    already_live = is_published_for_sale(target)
    now = iso_z(utcnow())
    extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
    extras.update({
        "express_commission_pct": commission_pct,
        "express_commission_amount": amount,
        "listed_by_special": True,
        "listed_by_owner": True,
        "owner_home": False,
        "public": True,
        "published_for_sale": True,
    })
    first = _cycle_stamp(target, "first_published_at")
    current = _cycle_stamp(target, "published_at")
    if not already_live:
        stamp = now
        if stamp == current:
            stamp = utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        extras["published_at"] = stamp
        extras["first_published_at"] = first or stamp
    else:
        if first:
            extras["first_published_at"] = first
        if current:
            extras["published_at"] = current
        elif first:
            extras["published_at"] = first
    target["extras"] = extras
    if extras.get("first_published_at"):
        target["first_published_at"] = extras["first_published_at"]
    if extras.get("published_at"):
        target["published_at"] = extras["published_at"]
    target["public"] = True
    target["is_express"] = True
    target["ad_type"] = "express"
    target["owner_home"] = False
    target["source"] = "my_property_published"
    target["payment_method"] = payment_method
    target["expert_verified"] = bool(target.get("expert_verified"))
    if str(target.get("express_status") or "").strip().lower() != "sold":
        target["status"] = "approved"
        target["express_status"] = "approved"
    elif str(target.get("status") or "").strip().lower() in ("", "pending", "hidden"):
        target["status"] = "approved"


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _union(left: Any, right: Any) -> List[Any]:
    out: List[Any] = []
    seen: set[str] = set()
    for item in list(left or []) + list(right or []):
        if isinstance(item, (dict, list)):
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        else:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_pair(base: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    """فیلدهای خالی پایه با ردیف دیگر پر می‌شود. هیچ کلیدی دور ریخته نمی‌شود."""
    for key, value in other.items():
        if key == "extras":
            continue
        if key in _LIST_KEYS:
            base[key] = _union(base.get(key), value if isinstance(value, list) else [])
            continue
        if _blank(base.get(key)) and not _blank(value):
            base[key] = value
    extras = dict(base.get("extras") or {}) if isinstance(base.get("extras"), dict) else {}
    incoming = other.get("extras") if isinstance(other.get("extras"), dict) else {}
    for key, value in incoming.items():
        if key not in extras or _blank(extras.get(key)):
            extras[key] = value
        elif key == "published_for_sale" and value is True:
            extras[key] = True
    base["extras"] = extras
    return base


def _flags_disagree(land: Dict[str, Any]) -> bool:
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    if is_published_for_sale(land):
        sold = str(land.get("express_status") or "").strip().lower() == "sold"
        return not (
            extras.get("published_for_sale") is True
            and land.get("public") is True
            and land.get("is_express") is True
            and land.get("owner_home") is False
            and str(land.get("source") or "").strip().lower() == "my_property_published"
            and (sold or str(land.get("express_status") or "").strip().lower() == "approved")
        )
    if not is_my_property_record(land):
        return False
    return bool(
        extras.get("published_for_sale") is True
        or land.get("public") is True
        or land.get("is_express") is True
        or str(land.get("source") or "").strip().lower() == "my_property_published"
    )


def _align_flags(land: Dict[str, Any]) -> None:
    """علامت‌های پراکنده را با وضعیت واقعی یکی کن، بدون دست زدن به قیمت و پورسانت."""
    if not _flags_disagree(land):
        return
    if is_published_for_sale(land):
        extras = dict(land.get("extras") or {}) if isinstance(land.get("extras"), dict) else {}
        extras["published_for_sale"] = True
        extras["public"] = True
        extras["owner_home"] = False
        extras["listed_by_owner"] = True
        land["extras"] = extras
        land["public"] = True
        land["is_express"] = True
        land["ad_type"] = "express"
        land["owner_home"] = False
        land["source"] = "my_property_published"
        if str(land.get("express_status") or "").strip().lower() != "sold":
            land["express_status"] = "approved"
            if str(land.get("status") or "").strip().lower() in ("", "pending", "hidden"):
                land["status"] = "approved"
        return
    mark_private(land)


def _next_code(lands: List[Any]) -> str:
    used = {code_key(land) for land in lands if code_key(land)}
    nums = []
    for code in used:
        if code.isdigit():
            try:
                nums.append(int(code))
            except ValueError:
                continue
    candidate = (max(nums) + 1) if nums else 1
    while str(candidate) in used:
        candidate += 1
    return str(candidate)


def normalize_listings(items: Any) -> List[Any]:
    """یک ردیف برای هر آگهی. مالک یکسان ادغام می‌شود؛ ردیف غریبه کد تازه می‌گیرد."""
    if not isinstance(items, list):
        return []
    passthrough = [item for item in items if not isinstance(item, dict)]
    rows = [item for item in items if isinstance(item, dict)]
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    anonymous: List[Dict[str, Any]] = []
    for land in rows:
        code = code_key(land)
        land["code"] = code
        phone = canonical_mobile(owner_phone(land))
        if not code or not phone:
            anonymous.append(land)
            continue
        key = (code, phone)
        if key not in grouped:
            grouped[key] = land
            order.append(key)
            continue
        grouped[key] = _merge_pair(grouped[key], land)
    merged = [grouped[key] for key in order] + anonymous
    used = {code_key(land) for land in merged if code_key(land)}
    seen: set[str] = set()
    for land in merged:
        code = code_key(land)
        if code and code not in seen:
            seen.add(code)
            continue
        fresh = _next_code(merged)
        while fresh in used:
            used.add(fresh)
            fresh = str(int(fresh) + 1) if fresh.isdigit() else _next_code(merged)
        used.add(fresh)
        if code:
            extras = dict(land.get("extras") or {}) if isinstance(land.get("extras"), dict) else {}
            extras.setdefault("previous_code", code)
            land["extras"] = extras
        land["code"] = fresh
        seen.add(fresh)
    for land in merged:
        if isinstance(land, dict):
            _align_flags(land)
    return merged + passthrough


def _resolve(app=None):
    from app.utils.storage import _resolve_app

    return _resolve_app(app)


def listings_path(app=None) -> str:
    """تنها مسیر نوشتن و خواندن آگهی."""
    from app.utils.storage import data_dir

    app = _resolve(app)
    path = os.path.join(data_dir(app), "lands.json")
    if app is not None:
        app.config["LANDS_FILE"] = path
    return path


def _other_sources(app, canonical: str) -> List[str]:
    from app.utils.storage import legacy_dir

    app = _resolve(app)
    configured = ""
    if app is not None:
        configured = str(app.config.get("LANDS_FILE") or "")
    legacy = os.path.join(legacy_dir(app), "lands.json")
    found: List[str] = []
    for path in (configured, legacy):
        if not path:
            continue
        absolute = os.path.abspath(path)
        if absolute == os.path.abspath(canonical) or absolute in found:
            continue
        if os.path.isfile(absolute):
            found.append(absolute)
    return found


def _read_json(path: str) -> List[Any]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        raw = data.get("lands") or data.get("items") or []
        return raw if isinstance(raw, list) else []
    return []


def _write_json(path: str, items: List[Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _source_stamp(path: str) -> str:
    try:
        stat = os.stat(path)
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}-{stat.st_size}"


@contextmanager
def listings_lock(app=None) -> Iterator[None]:
    """قفل تو در تو. ثبت و ذخیرهٔ همان درخواست همدیگر را مسدود نمی‌کنند."""
    global _LOCK_DEPTH, _LOCK_HANDLE
    import fcntl

    with _GUARD:
        _LOCK_DEPTH += 1
        if _LOCK_DEPTH == 1:
            path = listings_path(app) + ".lock"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle = open(path, "a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            _LOCK_HANDLE = handle
        try:
            yield
        finally:
            _LOCK_DEPTH -= 1
            if _LOCK_DEPTH == 0 and _LOCK_HANDLE is not None:
                import fcntl as _fcntl

                _fcntl.flock(_LOCK_HANDLE.fileno(), _fcntl.LOCK_UN)
                _LOCK_HANDLE.close()
                _LOCK_HANDLE = None


def _marker_path(path: str) -> str:
    return path + ".unified"


def _refresh_cache(path: str, items: List[Any]) -> None:
    from app.utils.storage import _update_ads_cache_after_save

    _update_ads_cache_after_save(path, items)


def _source_plan(app):
    from app.utils.storage import data_dir, legacy_dir

    resolved = _resolve(app)
    canonical = os.path.join(data_dir(resolved), "lands.json")
    configured = str(resolved.config.get("LANDS_FILE") or "") if resolved is not None else ""
    legacy = os.path.join(legacy_dir(resolved), "lands.json")
    others: List[str] = []
    for path in (configured, legacy):
        if not path:
            continue
        absolute = os.path.abspath(path)
        if absolute == os.path.abspath(canonical) or absolute in others:
            continue
        if os.path.isfile(absolute):
            others.append(absolute)
    return resolved, canonical, others


def ensure_migrated(app=None) -> None:
    """فایل‌های پراکنده را یک‌بار در فایل اصلی بریز. ردیف موجود حذف نمی‌شود."""
    _resolved, canonical, others = _source_plan(app)
    stamp = _migration_stamp(others)
    marker = _marker_path(canonical)
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8") as handle:
                if handle.read().strip() == stamp:
                    if _resolved is not None:
                        _resolved.config["LANDS_FILE"] = canonical
                    return
        except OSError:
            pass
    with listings_lock(app):
        # listings_path هم پیکربندی را به همین فایل برمی‌گرداند؛ منابع دیگر را زودتر بردار.
        from app.utils.storage import data_dir, legacy_dir

        resolved = _resolve(app)
        canonical = os.path.join(data_dir(resolved), "lands.json")
        if resolved is not None:
            # هنوز LANDS_FILE را عوض نکن تا منبع پیکربندی‌شده در ادغام بیاید.
            pass
        configured = str(resolved.config.get("LANDS_FILE") or "") if resolved is not None else ""
        legacy = os.path.join(legacy_dir(resolved), "lands.json")
        others = []
        for path in (configured, legacy):
            if not path:
                continue
            absolute = os.path.abspath(path)
            if absolute == os.path.abspath(canonical) or absolute in others:
                continue
            if os.path.isfile(absolute):
                others.append(absolute)
        if resolved is not None:
            resolved.config["LANDS_FILE"] = canonical
        marker = _marker_path(canonical)
        stamp = "|".join(_source_stamp(path) for path in others) or "none"
        if os.path.isfile(marker):
            try:
                with open(marker, "r", encoding="utf-8") as handle:
                    if handle.read().strip() == stamp:
                        return
            except OSError:
                pass
        current = _read_json(canonical)
        extras: List[Any] = []
        known = {code_key(row) for row in current if code_key(row)}
        for path in others:
            for row in _read_json(path):
                key = code_key(row)
                if key and key in known:
                    # همان کد در فایل اصلی هست؛ فیلدهای خالی‌اش از نسخهٔ قدیمی پر می‌شود.
                    for existing in current:
                        if isinstance(existing, dict) and code_key(existing) == key and isinstance(row, dict):
                            _merge_pair(existing, row)
                            break
                    continue
                extras.append(row)
                if key:
                    known.add(key)
        combined = list(current) + extras
        normalized = normalize_listings(combined)
        changed = normalized != current or not os.path.isfile(canonical)
        if changed:
            if os.path.isfile(canonical) and not os.path.isfile(canonical + ".pre-unify"):
                try:
                    shutil.copy2(canonical, canonical + ".pre-unify")
                except OSError:
                    pass
            for path in others:
                backup = canonical + ".legacy"
                if not os.path.isfile(backup):
                    try:
                        shutil.copy2(path, backup)
                    except OSError:
                        pass
                    break
            _write_json(canonical, normalized)
            _refresh_cache(canonical, normalized)
        elif not os.path.isfile(canonical):
            _write_json(canonical, [])
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(stamp)
        except OSError:
            pass


def load_listings(app=None) -> List[Any]:
    ensure_migrated(app)
    return _read_json(listings_path(app))


def load_listings_cached(app=None) -> List[Any]:
    ensure_migrated(app)
    from app.utils.storage import _ADS_CACHE, _file_cache_load, _load

    return _file_cache_load(_ADS_CACHE, listings_path(app), _load)


def _migration_stamp(others: List[str]) -> str:
    return "|".join(_source_stamp(path) for path in others) or "none"


def _remember_stamp(path: str, others: List[str]) -> None:
    try:
        with open(_marker_path(path), "w", encoding="utf-8") as handle:
            handle.write(_migration_stamp(others))
    except OSError:
        pass


def save_listings(items: Any, app=None) -> List[Any]:
    """لیست آگهی‌ها را نرمال کن و فقط در فایل اصلی بنویس.

    تا وقتی مهاجرت تمام نشده، ردیفی که فقط در فایل قدیمی یا در فایل اصلی است
    به این ذخیره اضافه می‌شود تا جایگزینیِ اول چیزی را پاک نکند.
    """
    with listings_lock(app):
        from app.utils.storage import data_dir, legacy_dir

        resolved = _resolve(app)
        canonical = os.path.join(data_dir(resolved), "lands.json")
        configured = str(resolved.config.get("LANDS_FILE") or "") if resolved is not None else ""
        legacy = os.path.join(legacy_dir(resolved), "lands.json")
        others: List[str] = []
        for path in (configured, legacy):
            if not path:
                continue
            absolute = os.path.abspath(path)
            if absolute == os.path.abspath(canonical) or absolute in others:
                continue
            if os.path.isfile(absolute):
                others.append(absolute)
        if resolved is not None:
            resolved.config["LANDS_FILE"] = canonical
        incoming = list(items) if isinstance(items, list) else []
        marker = _marker_path(canonical)
        if not os.path.isfile(marker):
            known = {code_key(row) for row in incoming if code_key(row)}
            for row in _read_json(canonical):
                key = code_key(row)
                if key and key in known:
                    continue
                incoming.append(row)
                if key:
                    known.add(key)
            for path in others:
                for row in _read_json(path):
                    key = code_key(row)
                    if key and key in known:
                        continue
                    incoming.append(row)
                    if key:
                        known.add(key)
                backup = canonical + ".legacy"
                if not os.path.isfile(backup):
                    try:
                        shutil.copy2(path, backup)
                    except OSError:
                        pass
        normalized = normalize_listings(incoming)
        if os.path.isfile(canonical) and not os.path.isfile(canonical + ".pre-unify"):
            previous = _read_json(canonical)
            if previous != normalized:
                try:
                    shutil.copy2(canonical, canonical + ".pre-unify")
                except OSError:
                    pass
        _write_json(canonical, normalized)
        _refresh_cache(canonical, normalized)
        _remember_stamp(canonical, others)
        return normalized


def get_listing(code: str, app=None) -> Optional[Dict[str, Any]]:
    want = str(code or "").strip().translate(_FA_AR_DIGITS)
    if not want:
        return None
    for land in load_listings(app):
        if isinstance(land, dict) and code_key(land) == want:
            return land
    return None


def create_listing(fields: Dict[str, Any], *, owner: str = "", app=None) -> Dict[str, Any]:
    """آگهی تازه. بدون وضعیت انتشار، ملک خصوصی «ملک من» ذخیره می‌شود."""
    record = dict(fields or {})
    if owner and not str(record.get("owner") or "").strip():
        record["owner"] = owner
    record.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    specified = any(
        key in record
        for key in ("is_express", "public", "source", "owner_home", "ad_type")
    )
    if not specified and not is_published_for_sale(record):
        mark_private(record)
    with listings_lock(app):
        items = _read_json(listings_path(app))
        if not code_key(record):
            record["code"] = _next_code(items)
        else:
            record["code"] = code_key(record)
        items.append(record)
        written = save_listings(items, app)
    want = code_key(record)
    for land in written:
        if isinstance(land, dict) and code_key(land) == want:
            return land
    return record


def update_listing(
    code: str,
    changes: Dict[str, Any],
    *,
    owner: str = "",
    app=None,
) -> Optional[Dict[str, Any]]:
    """ویرایش همان آگهی. کد، تاریخ ثبت و وضعیت انتشار عوض نمی‌شود."""
    want = str(code or "").strip().translate(_FA_AR_DIGITS)
    if not want:
        return None
    skip = {
        "code",
        "created_at",
        "source",
        "public",
        "is_express",
        "owner_home",
        "ad_type",
        "status",
        "express_status",
        *_CYCLE_KEYS,
    }
    with listings_lock(app):
        items = _read_json(listings_path(app))
        target = None
        for land in items:
            if not isinstance(land, dict) or code_key(land) != want:
                continue
            if owner and not same_owner(owner_phone(land), owner):
                continue
            target = land
            break
        if target is None:
            return None
        for key, value in (changes or {}).items():
            if key in skip:
                continue
            if key == "extras" and isinstance(value, dict):
                extras = dict(target.get("extras") or {}) if isinstance(target.get("extras"), dict) else {}
                for extra_key, extra_value in value.items():
                    if extra_key in _EXTRAS_PUBLISH_KEYS or extra_key in _CYCLE_KEYS:
                        continue
                    extras[extra_key] = extra_value
                target["extras"] = extras
                continue
            target[key] = value
        target["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        written = save_listings(items, app)
    for land in written:
        if isinstance(land, dict) and code_key(land) == want:
            return land
    return target


def _record_listing_published(land: Dict[str, Any]) -> None:
    """فعالیت listing_published. شکست ثبت، انتشار را برنمی‌گرداند."""
    try:
        from app.foundation.activity_store import append_activity

        code = code_key(land)
        append_activity(
            action="listing_published",
            actor_key=owner_phone(land),
            actor_role="owner",
            entity_type="listing",
            entity_id=code,
            land_code=code,
            summary="آگهی برای فروش منتشر شد",
            payload={
                "published_at": str(land.get("published_at") or ""),
                "first_published_at": str(land.get("first_published_at") or ""),
            },
            source="listings",
        )
    except Exception:
        pass


def publish_listing(
    phone: str,
    *,
    payment_method: str,
    commission_pct: float,
    land_code: str,
    app=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """هر ردیف ملک منِ این مالک را منتشر کن و در فایل اصلی بنویس."""
    from app.express_partner.special_listings import apply_owner_publish

    want = str(land_code or "").strip().translate(_FA_AR_DIGITS)
    with listings_lock(app):
        items = _read_json(listings_path(app))
        if not want:
            homes = [
                item
                for item in items
                if isinstance(item, dict)
                and is_my_property_record(item)
                and same_owner(owner_phone(item), phone)
                and not is_published_for_sale(item)
            ]
            if not homes:
                owned = [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and is_my_property_record(item)
                    and same_owner(owner_phone(item), phone)
                ]
                if owned:
                    return owned[0], "already_published", False
                return None, "not_found", False
            want = code_key(homes[0])
        target, err, changed = apply_owner_publish(
            items,
            phone,
            want,
            payment_method=payment_method,
            commission_pct=float(commission_pct),
        )
        if err:
            return None, err, False
        if changed and target is not None:
            written = save_listings(items, app)
            saved = target
            saved_code = code_key(target)
            for land in written:
                if isinstance(land, dict) and code_key(land) == saved_code:
                    saved = land
                    break
            _record_listing_published(saved)
            return saved, None, True
        return target, None, bool(changed)


def unpublish_listing(
    phone: str,
    *,
    land_code: str,
    app=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """انتشار فروش همین آگهی را متوقف کن و در فایل اصلی بنویس."""
    from app.express_partner.special_listings import apply_owner_unpublish

    want = str(land_code or "").strip().translate(_FA_AR_DIGITS)
    if not want:
        return None, "not_found", False
    with listings_lock(app):
        items = _read_json(listings_path(app))
        target, err, changed = apply_owner_unpublish(items, phone, want)
        if err:
            return None, err, False
        if changed:
            written = save_listings(items, app)
            for land in written:
                if isinstance(land, dict) and code_key(land) == want:
                    return land, None, True
            return target, None, True
        return target, None, False
