# -*- coding: utf-8 -*-
"""Card text for the home/search listing rows, ported from the Android app.

The web home must look exactly like the APK home (``SearchFragment`` rows), so
price, area and place use the same rules as ``SearchAds.cardPrice``,
``SearchAds.cardArea`` and ``SearchAds.cardPlace`` in nox1020/vinor-apk.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

_FA = '۰۱۲۳۴۵۶۷۸۹'
_AR = '٠١٢٣٤٥٦٧٨٩'
_SEPARATORS = {',', '،', '٬'}


def _latin(text: str) -> str:
    out = []
    for ch in text:
        if ch in _FA:
            out.append(str(_FA.index(ch)))
        elif ch in _AR:
            out.append(str(_AR.index(ch)))
        else:
            out.append(ch)
    return ''.join(out)


def fa_grouped(value: int) -> str:
    """Same as ``PartnerFormat.toman``: Persian digits grouped with «،»."""
    if value == 0:
        return '۰'
    grouped = '{:,}'.format(int(value)).replace(',', '،')
    return ''.join(_FA[int(c)] if c.isdigit() else c for c in grouped)


def _text(ad: Dict[str, Any], key: str) -> str:
    value = ad.get(key)
    if value is None:
        return ''
    return str(value).strip()


def _pure_integer_amount(text: str) -> bool:
    digits = 0
    for ch in text:
        if ch.isdigit() and (ch in _FA or ch in _AR or '0' <= ch <= '9'):
            digits += 1
        elif ch in _SEPARATORS or ch.isspace():
            continue
        else:
            return False
    return digits > 0


def _is_word_boundary(ch: str) -> bool:
    if ch.isspace():
        return True
    return unicodedata.category(ch).startswith('P')


def _standalone_word(text: str, word: str) -> bool:
    start = 0
    while start <= len(text) - len(word):
        at = text.find(word, start)
        if at < 0:
            return False
        before_ok = at == 0 or _is_word_boundary(text[at - 1])
        after = at + len(word)
        after_ok = after >= len(text) or _is_word_boundary(text[after])
        if before_ok and after_ok:
            return True
        start = at + 1
    return False


def _text_after_standalone_dar(loc: str) -> Optional[str]:
    word = 'در'
    start_of_rest = -1
    start = 0
    while start <= len(loc) - len(word):
        at = loc.find(word, start)
        if at < 0:
            break
        before_ok = at == 0 or _is_word_boundary(loc[at - 1])
        after = at + len(word)
        if before_ok and after < len(loc) and loc[after].isspace():
            rest = after + 1
            while rest < len(loc) and loc[rest].isspace():
                rest += 1
            if rest < len(loc):
                start_of_rest = rest
        start = at + 1
    if start_of_rest < 0:
        return None
    return loc[start_of_rest:]


def _dar_followed_by_space(loc: str) -> bool:
    start = 0
    while start <= len(loc) - 2:
        at = loc.find('در', start)
        if at < 0:
            return False
        after = at + 2
        if after < len(loc) and loc[after].isspace():
            return True
        start = at + 1
    return False


def district_from_location(location: str) -> str:
    loc = (location or '').strip()
    if not loc:
        return ''
    return (_text_after_standalone_dar(loc) or '').strip()


def price_raw(ad: Dict[str, Any]) -> str:
    price = _text(ad, 'price')
    if price:
        return price
    for key in ('price_toman', 'price_total'):
        try:
            amount = int(float(ad.get(key) or 0))
        except (TypeError, ValueError):
            amount = 0
        if amount > 0:
            return str(amount)
    return ''


def card_price(raw: str) -> str:
    trimmed = (raw or '').strip()
    if not trimmed:
        return 'توافقی'
    if not _pure_integer_amount(trimmed):
        return trimmed
    digits = re.sub(r'\D', '', _latin(trimmed))
    if not digits:
        return trimmed
    return fa_grouped(int(digits)) + ' تومان'


def _parse_area(raw: str) -> Optional[int]:
    trimmed = (raw or '').strip()
    if not trimmed or 'توافقی' in trimmed:
        return None
    latin = re.sub(r'[,،٬\s]', '', _latin(trimmed))
    head = latin.split('متر', 1)[0]
    numbers = re.findall(r'\d+', head)
    if not numbers:
        return None
    value = int(numbers[-1])
    return value if 1 <= value <= 1_000_000 else None


def card_area(raw: str) -> str:
    trimmed = re.sub(r'\s+', ' ', (raw or '').strip())
    if not trimmed:
        return ''
    if 'متر' in trimmed:
        # «400 متر» از کارت وب همان «۴۰۰ متر» اپ است (اپ عدد خام size را قالب می‌کند)
        if re.fullmatch(r'[\d۰-۹٠-٩,،٬]+\s*متر(?:\s*مربع)?', trimmed):
            meters = _parse_area(trimmed)
            if meters is not None:
                return fa_grouped(meters) + ' متر'
        return trimmed
    meters = _parse_area(trimmed)
    if meters is None:
        return ''
    return fa_grouped(meters) + ' متر'


def card_place(ad: Dict[str, Any]) -> str:
    loc = _text(ad, 'location')
    district = _text(ad, 'district') or _text(ad, 'neighborhood')
    if loc and (_standalone_word(loc, 'پیش') or 'ساعت' in loc or 'هفته' in loc):
        return loc
    if loc and not district and _text_after_standalone_dar(loc) is None and _dar_followed_by_space(loc):
        return loc
    town = _text(ad, 'city')
    hood = district or district_from_location(loc) or loc.removeprefix('در ').strip()
    hood = hood.removeprefix('در ').strip()
    listed = bool(town) and (
        hood == town
        or hood.startswith(town + '،')
        or hood.startswith(town + ',')
        or hood.startswith(town + ' ·')
    )
    if town and hood and not listed:
        return 'در {}، {}'.format(town, hood)
    if hood:
        return 'در ' + hood
    if town:
        return 'در ' + town
    return ''


def card_fields(ad: Dict[str, Any]) -> Dict[str, str]:
    area_raw = _text(ad, 'area') or _text(ad, 'size') or _text(ad, 'area_m2')
    return {
        'card_price': card_price(price_raw(ad)),
        'card_area': card_area(area_raw),
        'card_place': card_place(ad),
    }
