"""مدیریت پیام‌های flash بر اساس scope (صفحه)."""
from __future__ import annotations

from flask import session

FLASH_PROFILE = 'profile'
FLASH_LAND = 'land'
FLASH_AUTH = 'auth'
FLASH_AUTH_ERROR = 'auth_error'
FLASH_AUTH_WARNING = 'auth_warning'
FLASH_AUTH_INFO = 'auth_info'
FLASH_AUTH_SUCCESS = 'auth_success'

_AUTH_CATEGORIES = frozenset({
    FLASH_AUTH,
    FLASH_AUTH_ERROR,
    FLASH_AUTH_WARNING,
    FLASH_AUTH_INFO,
    FLASH_AUTH_SUCCESS,
})

_LAND_LEGACY_MARKERS = (
    'وضعیت ملک',
    'در حال معامله',
    'پورسانت در انتظار',
    'پورسانت شما به لیست',
    'ملک به عنوان',
)

_AUTH_LEGACY_MARKERS = (
    'کد تأیید',
    'شماره موبایل',
    'حریم خصوصی',
    'قوانین استفاده',
    'ورود شما',
    'از حساب خارج شدید',
    'همه فیلدها',
    'حساب کاربری شما حذف شد',
)


def _is_auth_category(cat: str) -> bool:
    c = str(cat or '')
    return c == FLASH_AUTH or c.startswith('auth_')


def _is_auth_flash(cat: str, text: str) -> bool:
    if _is_auth_category(cat):
        return True
    if cat in ('error', 'warning', 'info', 'success', 'ok') and any(m in text for m in _AUTH_LEGACY_MARKERS):
        return True
    return False


AUTH_FLASH_CATEGORY_FILTER = list(_AUTH_CATEGORIES)


def purge_stale_land_flashes() -> None:
    """حذف flashهای معامله ملک از session (مثلاً هنگام ورود به ویرایش پروفایل)."""
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


def purge_stale_auth_flashes() -> None:
    """حذف flashهای ورود/OTP از session (صفحات داخل پنل)."""
    flashes = list(session.get('_flashes') or [])
    if not flashes:
        return
    kept = []
    for item in flashes:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            kept.append(item)
            continue
        cat, msg = item[0], item[1]
        text = str(msg or '')
        if _is_auth_flash(str(cat or ''), text):
            continue
        kept.append(item)
    session['_flashes'] = kept


def purge_non_auth_flashes() -> None:
    """فقط پیام‌های مربوط به ورود را نگه دار (صفحات login / verify)."""
    flashes = list(session.get('_flashes') or [])
    if not flashes:
        return
    kept = []
    for item in flashes:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        cat, msg = item[0], item[1]
        text = str(msg or '')
        if _is_auth_flash(str(cat or ''), text):
            kept.append(item)
    session['_flashes'] = kept
