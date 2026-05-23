"""مدیریت پیام‌های flash بر اساس scope (صفحه)."""
from __future__ import annotations

from flask import session

FLASH_PROFILE = 'profile'
FLASH_LAND = 'land'

_LAND_LEGACY_MARKERS = (
    'وضعیت ملک',
    'در حال معامله',
    'پورسانت در انتظار',
    'پورسانت شما به لیست',
    'ملک به عنوان',
)


def purge_stale_land_flashes() -> None:
    """حذف flashهای قدیمی معامله ملک که با category عمومی ذخیره شده‌اند."""
    flashes = list(session.get('_flashes') or [])
    if not flashes:
        return
    kept = []
    for item in flashes:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            kept.append(item)
            continue
        cat, msg = item[0], item[1]
        if cat == FLASH_LAND:
            continue
        text = str(msg or '')
        if cat in ('success', 'warning', 'info') and any(m in text for m in _LAND_LEGACY_MARKERS):
            continue
        kept.append(item)
    session['_flashes'] = kept
