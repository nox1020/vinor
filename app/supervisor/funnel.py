"""ناظر قیف فروش — داخلی، بدون UI و بدون ارسال پیام.

مرحله و پیشرفت هر کاربر را می‌سنجد؛ به چت hint و به رسدکننده سیگنال می‌دهد.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.memory.interfaces import MEMORY_LONG, MEMORY_RELATIONSHIP

_LOCK = threading.Lock()

# مراحل محصول (چارت)
STAGE_SEARCH = "search"
STAGE_LAND = "land"
STAGE_VISIT = "visit"
STAGE_DEAL = "deal"
STAGE_IDLE = "idle"
STAGE_DONE = "done"

_STAGE_ORDER = {
    STAGE_IDLE: 0,
    STAGE_SEARCH: 1,
    STAGE_LAND: 2,
    STAGE_VISIT: 3,
    STAGE_DEAL: 4,
    STAGE_DONE: 5,
}

_PROGRESS = {
    STAGE_IDLE: 0.05,
    STAGE_SEARCH: 0.25,
    STAGE_LAND: 0.45,
    STAGE_VISIT: 0.7,
    STAGE_DEAL: 0.88,
    STAGE_DONE: 1.0,
}

_STALL_HOURS_DEFAULT = 24


@dataclass
class FunnelSnapshot:
    user_key: str
    audience: str = ""
    voice: str = ""
    stage: str = STAGE_SEARCH
    progress: float = 0.25
    stalled: bool = False
    idle_hours: float = 0.0
    land_code: str = ""
    next_hint: str = ""
    signal_reach: bool = False
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime | None:
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _funnel_dir() -> str:
    """مسیر ai_funnel — همیشه زیر instance/data (نه cwd؛ روی cron/Passenger حیاتی است)."""
    try:
        from app.utils.storage import data_dir

        path = os.path.join(data_dir(), "ai_funnel")
    except Exception:
        try:
            from flask import current_app

            path = os.path.join(current_app.instance_path, "data", "ai_funnel")
        except Exception:
            from app.utils.storage import _standalone_instance_path

            path = os.path.join(_standalone_instance_path(), "data", "ai_funnel")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_key(user_key: str) -> str:
    digits = re.sub(r"\D+", "", str(user_key or ""))
    if digits.startswith("0098") and len(digits) >= 14:
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) >= 12 and digits[2:].startswith("9"):
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) >= 8:
        return digits
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_key or ""))
    return safe[:64] if safe else ""


def _path(user_key: str) -> str | None:
    key = _safe_key(user_key)
    if not key:
        return None
    return os.path.join(_funnel_dir(), f"{key}.json")


def load_snapshot(user_key: str) -> FunnelSnapshot | None:
    path = _path(user_key)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return FunnelSnapshot(
            user_key=str(data.get("user_key") or user_key),
            audience=str(data.get("audience") or ""),
            voice=str(data.get("voice") or ""),
            stage=str(data.get("stage") or STAGE_SEARCH),
            progress=float(data.get("progress") or 0.25),
            stalled=bool(data.get("stalled")),
            idle_hours=float(data.get("idle_hours") or 0),
            land_code=str(data.get("land_code") or ""),
            next_hint=str(data.get("next_hint") or ""),
            signal_reach=bool(data.get("signal_reach")),
            updated_at=str(data.get("updated_at") or ""),
            metadata=dict(data.get("metadata") or {})
            if isinstance(data.get("metadata"), dict)
            else {},
        )
    except Exception:
        return None


def save_snapshot(snap: FunnelSnapshot) -> None:
    path = _path(snap.user_key)
    if not path:
        return
    with _LOCK:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _memory_signals(user_key: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "has_budget": False,
        "has_pref": False,
        "land_codes": [],
        "has_visit": False,
        "has_deal": False,
        "has_reject": False,
        "last_event_at": "",
    }
    try:
        from app.memory.di import make_memory_store
        from app.memory.lifecycle import filter_active

        items = filter_active(make_memory_store().list_items(user_key) or [])
    except Exception:
        return out
    codes: list[str] = []
    for it in items:
        k = str(it.key or "")
        if k == "budget" or k.startswith("budget"):
            out["has_budget"] = True
        if k.startswith(("city:", "category:", "pref:")):
            out["has_pref"] = True
        if it.memory_type == MEMORY_RELATIONSHIP:
            meta = it.metadata or {}
            code = str(meta.get("land_code") or "")
            if ":" in k:
                code = code or k.split(":", 1)[1]
            if code:
                codes.append(code)
            if k.startswith(("visit:", "visit_done:")):
                out["has_visit"] = True
            if k.startswith("deal:"):
                out["has_deal"] = True
            if k.startswith("rejected:"):
                out["has_reject"] = True
            ts = it.updated_at or it.created_at
            if ts and ts > str(out["last_event_at"] or ""):
                out["last_event_at"] = ts
        if it.memory_type == MEMORY_LONG and k == "live_summary":
            pass
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    out["land_codes"] = uniq[:8]
    return out


def _goal_stage(user_key: str) -> str:
    try:
        from app.goals.registry import SessionGoalRegistry

        goals = SessionGoalRegistry().load(user_key) or []
    except Exception:
        return ""
    if not goals:
        return ""
    # prefer highest priority active
    order = {
        "deal": 5,
        "visit": 4,
        "negotiate": 4,
        "buy": 3,
        "sell": 3,
        "search": 2,
        "partner": 2,
        "general": 1,
    }
    best = ""
    best_score = -1
    for g in goals:
        if not isinstance(g, dict):
            continue
        if str(g.get("status") or "") in ("completed", "abandoned"):
            continue
        gt = str(g.get("goal_type") or "").strip().lower()
        sc = order.get(gt, 0)
        if sc > best_score:
            best_score = sc
            best = gt
    if best == "buy":
        return STAGE_SEARCH
    if best == "sell":
        return STAGE_LAND
    if best in ("visit", "negotiate"):
        return STAGE_VISIT
    if best == "deal":
        return STAGE_DEAL
    if best == "search":
        return STAGE_SEARCH
    return ""


def _chat_last_activity(user_key: str, audience: str) -> datetime | None:
    try:
        from app.ai.chat_store import load_user_record

        rec = load_user_record(user_key, audience or None)
        threads = rec.get("threads") or []
        latest = None
        for th in threads:
            if not isinstance(th, dict):
                continue
            for m in th.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                ts = _parse_iso(str(m.get("created_at") or m.get("ts") or ""))
                if ts and (latest is None or ts > latest):
                    latest = ts
            ut = _parse_iso(str(th.get("updated_at") or ""))
            if ut and (latest is None or ut > latest):
                latest = ut
        return latest
    except Exception:
        return None


def _hint_for_stage(stage: str, *, land_code: str = "", audience: str = "") -> str:
    code = (land_code or "").strip()
    bit = f" {code}" if code else ""
    if stage == STAGE_DONE:
        return "فروش تموم شده؛ اگه فایل جدید خواست کمک کن."
    if stage == STAGE_DEAL:
        return f"معامله{bit} بازه — از چت ببندش."
    if stage == STAGE_VISIT:
        return f"بازدید{bit} مونده — هماهنگ کن یا ثبت انجام بزن."
    if stage == STAGE_LAND:
        return f"فایل{bit} دیده شده — هل به بازدید یا آگهی."
    if stage == STAGE_SEARCH:
        if (audience or "") == "partner":
            return "جستجو/آگهی — بهترین فایل رو بده و ببر بازدید."
        return "معیار رو کامل کن و بهترین فایل سیستم رو پیشنهاد بده."
    return "راکد است — با یک قدم فروش دوباره فعالش کن."


def assess_funnel(
    user_key: str,
    *,
    audience: str = "",
    voice: str = "",
    stall_hours: float | None = None,
) -> FunnelSnapshot:
    """سنجش مرحله و پیشرفت — بدون ارسال پیام."""
    uk = str(user_key or "").strip()
    aud = (audience or "").strip().lower() or "public"
    stall_h = float(stall_hours if stall_hours is not None else _STALL_HOURS_DEFAULT)
    if stall_hours is None:
        try:
            from app.supervisor.config import funnel_stall_hours

            stall_h = float(funnel_stall_hours())
        except Exception:
            stall_h = float(_STALL_HOURS_DEFAULT)

    mem = _memory_signals(uk)
    gstage = _goal_stage(uk)

    stage = STAGE_SEARCH
    land = ""
    if mem["has_deal"]:
        stage = STAGE_DEAL
        land = (mem["land_codes"] or [""])[0]
    elif mem["has_visit"]:
        stage = STAGE_VISIT
        land = (mem["land_codes"] or [""])[0]
    elif mem["land_codes"]:
        stage = STAGE_LAND
        land = mem["land_codes"][0]
    elif mem["has_budget"] or mem["has_pref"]:
        stage = STAGE_SEARCH
    else:
        stage = STAGE_SEARCH

    # goals can raise stage
    if gstage and _STAGE_ORDER.get(gstage, 0) > _STAGE_ORDER.get(stage, 0):
        stage = gstage

    last = _chat_last_activity(uk, aud)
    idle_hours = 0.0
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        idle_hours = max(0.0, (_now() - last).total_seconds() / 3600.0)
    else:
        idle_hours = stall_h + 1  # بدون چت = راکد بالقوه

    stalled = False
    if stage != STAGE_DONE and idle_hours >= stall_h:
        stalled = True
        if stage == STAGE_SEARCH and not mem["has_budget"] and not mem["land_codes"]:
            # مهمان تازه‌وارد بدون فعالیت معنی‌دار — هنوز سیگنال نده
            if idle_hours < stall_h * 2 and uk.startswith("guest_"):
                stalled = False

    if stalled and stage not in (STAGE_IDLE, STAGE_DONE):
        # نگه داشتن مرحله واقعی + پرچم راکد
        pass

    progress = float(_PROGRESS.get(stage, 0.25))
    if stalled:
        progress = max(0.05, progress - 0.1)

    # سیگنال به رسد: راکد + موبایل ایران معتبر (نه guest / شناسهٔ جعلی)
    try:
        from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

        phone = normalize_iran_mobile(uk) or ""
        can_reach = is_valid_iran_mobile(phone)
    except Exception:
        can_reach = (not uk.startswith("guest_")) and bool(_safe_key(uk))
    signal = bool(stalled and can_reach and stage != STAGE_DONE)

    hint = _hint_for_stage(stage if not stalled else STAGE_IDLE, land_code=land, audience=aud)
    if stalled and stage != STAGE_IDLE:
        hint = f"راکد در مرحلهٔ {stage}: " + _hint_for_stage(stage, land_code=land, audience=aud)

    return FunnelSnapshot(
        user_key=uk,
        audience=aud,
        voice=(voice or "").strip().lower(),
        stage=stage,
        progress=round(progress, 3),
        stalled=stalled,
        idle_hours=round(idle_hours, 2),
        land_code=land,
        next_hint=hint,
        signal_reach=signal,
        updated_at=_now_iso(),
        metadata={
            "goal_stage": gstage,
            "mem_lands": mem.get("land_codes") or [],
            "has_visit": bool(mem.get("has_visit")),
            "has_deal": bool(mem.get("has_deal")),
        },
    )


def update_funnel(
    user_key: str,
    *,
    audience: str = "",
    voice: str = "",
) -> FunnelSnapshot | None:
    if not user_key:
        return None
    try:
        from app.supervisor.config import funnel_watch_enabled

        if not funnel_watch_enabled():
            return None
    except Exception:
        pass
    try:
        snap = assess_funnel(user_key, audience=audience, voice=voice)
        save_snapshot(snap)
        return snap
    except Exception:
        return None


def list_reach_signals(*, limit: int = 200) -> list[FunnelSnapshot]:
    """سیگنال‌های باز برای رسدکننده — فقط stalled+signal_reach."""
    root = _funnel_dir()
    out: list[FunnelSnapshot] = []
    try:
        names = os.listdir(root)
    except Exception:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            if not data.get("signal_reach"):
                continue
            snap = FunnelSnapshot(
                user_key=str(data.get("user_key") or ""),
                audience=str(data.get("audience") or ""),
                voice=str(data.get("voice") or ""),
                stage=str(data.get("stage") or ""),
                progress=float(data.get("progress") or 0),
                stalled=bool(data.get("stalled")),
                idle_hours=float(data.get("idle_hours") or 0),
                land_code=str(data.get("land_code") or ""),
                next_hint=str(data.get("next_hint") or ""),
                signal_reach=True,
                updated_at=str(data.get("updated_at") or ""),
                metadata=dict(data.get("metadata") or {})
                if isinstance(data.get("metadata"), dict)
                else {},
            )
            if snap.user_key:
                out.append(snap)
        except Exception:
            continue
    out.sort(key=lambda s: s.idle_hours, reverse=True)
    return out[: max(1, int(limit))]


def clear_reach_signal(user_key: str) -> None:
    snap = load_snapshot(user_key)
    if not snap:
        return
    snap.signal_reach = False
    snap.stalled = False
    snap.updated_at = _now_iso()
    save_snapshot(snap)


def _discover_public_chat_keys(*, limit: int = 400) -> list[str]:
    """کلیدهای چت عمومی با موبایل ایران معتبر — برای کشف خریدارانی که هنوز snapshot ندارند."""
    out: list[str] = []
    seen: set[str] = set()
    try:
        from app.ai.paths import ai_data_file
        from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

        root = os.path.join(ai_data_file("ai_chats"), "public")
    except Exception:
        return []
    if not os.path.isdir(root):
        return []
    try:
        names = os.listdir(root)
    except Exception:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        stem = name[:-5]
        if stem.startswith("guest_"):
            continue
        phone = normalize_iran_mobile(stem) or ""
        if not is_valid_iran_mobile(phone):
            continue
        if phone in seen:
            continue
        seen.add(phone)
        out.append(phone)
        if len(out) >= max(1, int(limit)):
            break
    return out


def refresh_funnels_for_reach(*, limit: int = 400) -> int:
    """قبل از نوبت رسد: snapshotها + خریداران چت عمومی را بسنج تا سیگنال تازه شود."""
    root = _funnel_dir()
    n = 0
    stall = None
    try:
        from app.supervisor.config import funnel_stall_hours

        stall = funnel_stall_hours()
    except Exception:
        stall = _STALL_HOURS_DEFAULT

    # user_key → audience از snapshot موجود
    pending: dict[str, str] = {}
    try:
        names = os.listdir(root)
    except Exception:
        names = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            uk = str(data.get("user_key") or "").strip()
            if not uk or uk.startswith("guest_") or uk.startswith("admin_"):
                continue
            aud = str(data.get("audience") or "public").strip().lower() or "public"
            if aud == "admin":
                continue
            pending[uk] = aud
        except Exception:
            continue

    # کشف خریداران چت عمومی که هنوز در ai_funnel نیستند
    for phone in _discover_public_chat_keys(limit=limit):
        pending.setdefault(phone, "public")

    for uk, aud in list(pending.items())[: max(1, int(limit))]:
        try:
            if aud == "partner":
                # همکار را sales_coach پوشش می‌دهد — سیگنال خریدار نساز
                continue
            snap = assess_funnel(
                uk,
                audience=aud or "public",
                stall_hours=stall,
            )
            save_snapshot(snap)
            n += 1
        except Exception:
            continue
    return n
