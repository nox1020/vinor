# app/utils/dates.py
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Union


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


def tehran_now() -> datetime:
    """الان به وقت تهران — همیشه timezone-aware (+03:30 اگر zoneinfo/tzdata نباشد)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Tehran"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=3, minutes=30)))


def tehran_today() -> date:
    return tehran_now().date()


def to_fa_digits(value: Union[str, int]) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def to_en_digits(value: Union[str, int]) -> str:
    return str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


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


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ شمسی به میلادی."""
    if jy > 979:
        gy = 1600
        jy -= 979
    else:
        gy = 621
    days = (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + 78 + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186
    gy += 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0):
        sal_a[2] = 29
    gm = 1
    while gm <= 12 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


def _looks_like_jalali_year(year: int) -> bool:
    return 1200 <= year <= 1599


def _looks_like_gregorian_year(year: int) -> bool:
    return 1900 <= year <= 2200


def parse_jalali_date(raw: str) -> Optional[date]:
    """رشتهٔ شمسی مثل ۱۴۰۵/۰۴/۲۴ یا 1405-4-24 → date میلادی."""
    s = to_en_digits(raw or "").strip()
    if not s:
        return None
    for junk in ("ساعت", "تاریخ", "روز", "شمسی"):
        s = s.replace(junk, " ")
    s = s.replace(".", "/").replace("-", "/").replace(" ", "")
    parts = [p for p in s.split("/") if p]
    if len(parts) < 3:
        return None
    try:
        jy, jm, jd = int(parts[0]), int(parts[1]), int(parts[2][:2])
    except Exception:
        return None
    if not _looks_like_jalali_year(jy):
        return None
    if not (1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    try:
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        return date(gy, gm, gd)
    except Exception:
        return None


def parse_gregorian_iso_date(raw: str) -> Optional[date]:
    """فقط تاریخ میلادی واقعی (سال ۱۹۰۰–۲۲۰۰)؛ سال‌های شمسی را میلادی نمی‌خواند."""
    s = to_en_digits(raw or "").strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    s = s.replace("/", "-")[:10]
    try:
        y, m, d = (int(x) for x in s.split("-"))
    except Exception:
        return None
    if not _looks_like_gregorian_year(y):
        return None
    try:
        return date(y, m, d)
    except Exception:
        return None


def format_iso_date_jalali(iso: str, *, sep: str = "/", fa_digits: bool = False) -> str:
    """نمایش تاریخ ISO (YYYY-MM-DD) به شمسی. اگر ورودی شمسی باشد، نرمالش می‌کند."""
    s = (iso or "").strip()
    if not s:
        return ""
    # اگر به‌اشتباه خودِ شمسی پاس شده، همان را استاندارد برگردان
    j = parse_jalali_date(s)
    if j is not None:
        jy, jm, jd = gregorian_to_jalali(j.year, j.month, j.day)
        out = f"{jy:04d}{sep}{jm:02d}{sep}{jd:02d}"
        return to_fa_digits(out) if fa_digits else out
    d = parse_gregorian_iso_date(s)
    if d is None:
        return ""
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    out = f"{jy:04d}{sep}{jm:02d}{sep}{jd:02d}"
    return to_fa_digits(out) if fa_digits else out


def format_display_jalali_date(iso_or_any: str, *, with_weekday: bool = False) -> str:
    """برچسب نمایشی امن برای کاربر — همیشه شمسی با ارقام فارسی؛ هرگز میلادی خام برنمی‌گرداند."""
    raw = (iso_or_any or "").strip()
    if not raw:
        return ""
    d = parse_gregorian_iso_date(raw) or parse_jalali_date(raw)
    if d is None:
        return ""
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    core = to_fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")
    if with_weekday:
        WEEKDAY_FA = {
            0: "دوشنبه",
            1: "سه‌شنبه",
            2: "چهارشنبه",
            3: "پنجشنبه",
            4: "جمعه",
            5: "شنبه",
            6: "یکشنبه",
        }
        wd = WEEKDAY_FA.get(d.weekday(), "")
        if wd:
            return f"{wd} {core}"
    return core


def format_display_jalali_datetime(value: Union[str, datetime, None] = None) -> str:
    """تاریخ+ساعت شمسی به وقت تهران — برای نمایش دقیق."""
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    try:
        from zoneinfo import ZoneInfo
        tehran_tz = ZoneInfo("Asia/Tehran")
    except Exception:
        pass

    def _as_tehran(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            # naive را زمان دیوار تهران فرض می‌کنیم (نه UTC)
            return dt.replace(tzinfo=tehran_tz)
        return dt.astimezone(tehran_tz)

    if value is None:
        dt = tehran_now()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tehran_tz)
        else:
            dt = dt.astimezone(tehran_tz)
    elif isinstance(value, datetime):
        dt = _as_tehran(value)
    else:
        s = str(value).strip()
        if not s:
            return ""
        # فقط تاریخ بدون ساعت
        if len(s) <= 10 or ("T" not in s and " " not in s and len(to_en_digits(s)) <= 10):
            return format_display_jalali_date(s)
        try:
            iso_candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
            if " " in s and "T" not in s:
                iso_candidate = s.replace(" ", "T", 1)
            dt = _as_tehran(datetime.fromisoformat(iso_candidate))
        except Exception:
            return format_display_jalali_date(s[:10])
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return to_fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d} — {dt.hour:02d}:{dt.minute:02d}")
