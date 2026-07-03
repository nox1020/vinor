# app/utils/dates.py
from datetime import datetime, timedelta, timezone
from typing import Optional

def parse_datetime_safe(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return datetime(1970, 1, 1)
        iso_candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
    return datetime(1970, 1, 1)

def utcnow() -> datetime:
    """برگرداندن زمان UTC فعلی"""
    return datetime.utcnow()

def iso_z(dt: datetime) -> str:
    """تبدیل datetime به فرمت ISO 8601 با Z (UTC)"""
    return dt.replace(microsecond=0).isoformat() + "Z"

def parse_iso_to_naive_utc(s: str) -> Optional[datetime]:
    """تبدیل رشته ISO 8601 به datetime (naive UTC)"""
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt.replace(tzinfo=None)
    except Exception:
        return None

def is_ad_expired(ad: dict) -> bool:
    """بررسی انقضای آگهی"""
    exp_str = ad.get("expires_at")
    if not exp_str:
        return False  # آگهی نامحدود، منقضی نشده
    exp_dt = parse_iso_to_naive_utc(exp_str)
    if exp_dt is None:
        return False  # تاریخ نامعتبر، منقضی محسوب نمی‌شود
    return exp_dt < utcnow()


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = (gy + 1) if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def format_iso_date_jalali(iso: str, *, sep: str = "/") -> str:
    """نمایش تاریخ ISO (YYYY-MM-DD) به شمسی."""
    s = (iso or "").strip()[:10]
    if not s:
        return ""
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return s
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    return f"{jy:04d}{sep}{jm:02d}{sep}{jd:02d}"
