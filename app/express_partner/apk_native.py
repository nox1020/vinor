"""JSON payloads for native APK drawer/dashboard screens."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from flask import g, session


def json_ready(val: Any) -> Any:
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, dict):
        return {str(k): json_ready(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [json_ready(v) for v in val]
    return str(val)


def land_card(land: Dict[str, Any] | None) -> Dict[str, Any]:
    from ..utils.images import partner_card_image_url

    item = land if isinstance(land, dict) else {}
    code = str(item.get('code') or '').strip()
    price = int(item.get('price_total') or item.get('price') or 0)
    from app.listings.service import archive_payload

    card = {
        'code': code,
        'title': str(item.get('title') or '—').strip() or '—',
        'city': str(item.get('city') or '').strip(),
        'location': str(item.get('location') or '').strip(),
        'size': str(item.get('size') or '').strip(),
        'category': str(item.get('category') or '').strip(),
        'price_total': price,
        'commission_amount': int(item.get('_commission_amount') or 0),
        'assignment_status': str(item.get('_assignment_status') or 'active').strip() or 'active',
        'image_url': partner_card_image_url(item) or None,
    }
    card.update(archive_payload(item))
    return card


def training_payload() -> Dict[str, Any]:
    video = (os.environ.get('TRAINING_VIDEO_URL') or '').strip()
    return {
        'ok': True,
        'title': 'آموزش',
        'hero_title': 'چطور می‌تونم کمکت کنم؟',
        'hero_sub': 'آموزش ۳ مرحله‌ای جذب مشتری، بازدید و بستن معامله.',
        'video_url': video,
        'steps': [
            {'id': 'market', 'num': '۱', 'title': 'بازاریابی', 'sub': 'انتشار آگهی در همه جا و جذب مشتری'},
            {'id': 'visit', 'num': '۲', 'title': 'بازدید', 'sub': 'هماهنگی و مدیریت حرفه‌ای بازدید'},
            {'id': 'deal', 'num': '۳', 'title': 'معامله', 'sub': 'پیگیری، قرارداد و پورسانت'},
        ],
        'faqs': [
            {
                'tab': 'market',
                'q': 'آگهی را کجا منتشر کنم؟',
                'a': 'آگهی‌ها را در همه جا منتشر کنید — فقط یک پلتفرم کافی نیست. فایل را در اینستاگرام، کانال‌های تلگرام و دیوار بگذارید تا مشتری از هر مسیری شما را پیدا کند.',
            },
            {
                'tab': 'market',
                'q': 'فایل را چطور به مشتری معرفی کنم؟',
                'a': 'فایل را کامل و دقیق بخوانید، بعد به‌صورت تلفنی و شفاف معرفی کنید. مشتری باید از قیمت، موقعیت، متراژ و شرایط بازدید تصویر روشنی بگیرد.',
            },
            {
                'tab': 'market',
                'q': 'بعد از انتشار آگهی چه کار کنم؟',
                'a': 'به پیام و تماس مشتری سریع جواب بدهید. تأخیر در پاسخ یعنی از دست رفتن فایل به نفع مشاور دیگر.',
            },
            {
                'tab': 'visit',
                'q': 'بازدید را چطور هماهنگ کنم؟',
                'a': 'قبل از بازدید با ناظر معامله تلفنی هماهنگ کنید. زمان، آدرس و شرایط ورود را دقیق بگویید تا مشتری و مالک هر دو آماده باشند.',
            },
            {
                'tab': 'visit',
                'q': 'هدف بازدید فقط دیدن ملک است؟',
                'a': 'خیر. بازدید را حرفه‌ای مدیریت کنید، میزان علاقه مشتری را بسنجید و نتیجه را ثبت کنید. بدون ثبت نتیجه، پیگیری معامله ناقص می‌ماند.',
            },
            {
                'tab': 'deal',
                'q': 'بعد از بازدید چطور معامله را ببندم؟',
                'a': 'با پیگیری مؤثر و مذاکره اصولی، مشتری را به قرارداد برسانید. نتیجه این مرحله بستن معامله و دریافت پورسانت است.',
            },
        ],
    }


def levels_payload(me_phone: str, profile) -> Dict[str, Any]:
    from .partner_roles import partner_coop_level

    current = partner_coop_level(profile) if me_phone else ''
    approved = current not in ('', 'regular')
    special = current == 'plus'
    return {
        'ok': True,
        'current_level': current,
        'is_approved': approved,
        'is_special': special,
        'logged_in': bool(me_phone),
        'lead': 'چهار سطح در وینور. هر کدام یک کار مشخص دارد — از دیدن فایل تا فروش و آگهی خودت.',
        'levels': [
            {
                'id': 'plus',
                'kicker': 'سطح ۱',
                'title': 'پلاس',
                'copy': 'مالک فایل‌های خودت هستی؛ آگهی، بازدید و معامله در پنل خودت جمع می‌شود.',
                'points': ['آگهی اختصاصی و مدیریت فایل‌ها', 'پیگیری بازدید و معامله', 'اولویت در معرفی به مشتری'],
            },
            {
                'id': 'visitor',
                'kicker': 'سطح ۲',
                'title': 'ویزیتور',
                'copy': 'وقت بازدید می‌گیری و همراه مشتری سر زمین می‌روی.',
                'points': ['درخواست وقت بازدید', 'دیدن ملک از نزدیک', 'همراهی مشتری تا معامله'],
            },
            {
                'id': 'marketer',
                'kicker': 'سطح ۳',
                'title': 'بازاریاب',
                'copy': 'فایل آمادهٔ وینور را به مشتری می‌فروشی و بعد از تأیید معامله، پورسانت به کیف پول می‌آید.',
                'points': ['چت مشتری و معرفی فایل', 'فروش و پورسانت بعد از تأیید معامله', 'مسیر ارتقا به ویزیتور'],
            },
            {
                'id': 'regular',
                'kicker': 'سطح ۴',
                'title': 'عادی',
                'copy': 'جستجو، چت و آشنایی با فایل‌ها. بدون فروش و بدون پورسانت.',
                'points': ['جستجوی ملک', 'گفتگو با وینور', 'درخواست همکاری هر وقت آماده باشی'],
            },
        ],
    }


def invite_payload(me_phone: str, profile) -> Dict[str, Any]:
    from .routes import _canonical_partner_phone, _is_partner_approved
    from ..utils.share_tokens import encode_partner_ref
    from ..utils.short_urls import public_referral_url

    me_name = str((profile or {}).get('name') or '').strip()
    is_approved = _is_partner_approved(profile)
    canonical = _canonical_partner_phone(me_phone)
    ref_token = encode_partner_ref(canonical)
    invite_url = public_referral_url(ref_token)
    inviter = me_name or 'همکار وینور'
    if is_approved:
        share_text = f'{inviter} شما را به همکاری در وینور اکسپرس دعوت می‌کند.'
    else:
        share_text = f'{inviter} شما را به وینور دعوت می‌کند.'
    try:
        from .referrals import referral_stats_for_inviter, REFERRAL_BONUS_AMOUNT
        ref_stats = referral_stats_for_inviter(me_phone)
        bonus = REFERRAL_BONUS_AMOUNT
    except Exception:
        ref_stats = {
            'invite_count': 0,
            'waiting_invites': 0,
            'successful_invites': 0,
            'approved_count': 0,
            'pending_invites': 0,
            'pending_commission': 0,
            'approved_commission': 0,
            'paid_commission': 0,
            'total_earned': 0,
        }
        bonus = 100_000
    return {
        'ok': True,
        'is_approved': is_approved,
        'me_name': me_name,
        'invite_url': invite_url,
        'share_text': share_text,
        'bonus_per_invite': int(bonus or 0),
        'ref_stats': json_ready(ref_stats),
    }


def apply_payload(me_phone: str) -> Dict[str, Any]:
    from .routes import (
        _apply_form_defaults,
        _has_active_application,
        _is_partner_approved,
        _partner_profile_for_phone,
        _thanks_page_kwargs,
    )

    profile = _partner_profile_for_phone(me_phone)
    if _is_partner_approved(profile):
        return {'ok': True, 'status': 'approved', 'message': 'حساب شما هم‌اکنون همکار تأییدشده است.'}
    if _has_active_application(me_phone):
        thanks = _thanks_page_kwargs(me_phone, pending_review=True)
        thanks.pop('show_app_download', None)
        thanks.pop('android_apk_url', None)
        thanks.pop('android_apk_version', None)
        thanks.pop('android_apk_size_label', None)
        return {'ok': True, 'status': 'pending', **json_ready(thanks)}
    defaults = _apply_form_defaults(me_phone)
    return {
        'ok': True,
        'status': 'form',
        'first_name': defaults.get('first_name', ''),
        'last_name': defaults.get('last_name', ''),
        'national_id': defaults.get('national_id', ''),
    }


def requests_payload(me_phone: str, profile, tab: str = '', status: str = '') -> Dict[str, Any]:
    from .routes import _build_partner_sales_pipeline
    from .visit_requests import PIPELINE_TABS

    archive_status = 'archived' if str(status or '').strip().lower() == 'archived' else 'active'
    pipe = _build_partner_sales_pipeline(me_phone, profile, archive_status=archive_status)
    requested = str(tab or '').strip().lower()
    if requested not in PIPELINE_TABS:
        requested = str(pipe.get('default_tab') or 'requests')
        inbox_items = pipe.get('inbox_items') or []
        is_special = bool(pipe.get('is_special'))
        deal_needs = any(
            i.get('can_approve_deal') or i.get('can_start_deal') or i.get('can_confirm_deal')
            for i in inbox_items
            if isinstance(i, dict)
        )
        inbox_visit_count = sum(
            1 for i in inbox_items
            if isinstance(i, dict) and str(i.get('pipeline_tab') or '') == 'visits'
        )
        if is_special and deal_needs:
            requested = 'deals'
        elif is_special and inbox_visit_count:
            requested = 'visits'
        else:
            requested = 'requests'
    keys = (
        'items', 'inbox_items', 'cards', 'offers', 'tab_counts', 'open_count',
        'is_approved', 'is_special', 'support_phone', 'allow_attendance',
    )
    out = {k: json_ready(pipe.get(k)) for k in keys}
    out.update({
        'ok': True,
        'active_tab': requested,
        'status': archive_status,
        'archive_counts': pipe.get('archive_counts') or {'active': 0, 'archived': 0},
        'tabs': [
            {'id': 'requests', 'title': 'درخواست'},
            {'id': 'visits', 'title': 'بازدید'},
            {'id': 'deals', 'title': 'معامله'},
        ],
    })
    return out


def listings_payload(me_phone: str, status: str = 'active') -> Dict[str, Any]:
    from .special_listings import listings_owned_by
    from .home_ads_config import partner_divar_profile_entries
    from app.listings.service import archive_payload, is_archived, sweep_inactive_listings

    try:
        if me_phone:
            sweep_inactive_listings()
    except Exception:
        pass
    rows = listings_owned_by(me_phone)
    want_archived = str(status or '').strip().lower() == 'archived'
    visible = []
    active_count = 0
    archived_count = 0
    for land in rows:
        archived = is_archived(land)
        if archived:
            archived_count += 1
        else:
            active_count += 1
        if archived is want_archived:
            card = land_card(land)
            card.update(archive_payload(land))
            visible.append(card)
    items = visible
    divar = []
    for entry in partner_divar_profile_entries(me_phone) or []:
        if not isinstance(entry, dict):
            continue
        divar.append({
            'url': str(entry.get('url') or '').strip(),
            'commission_pct': entry.get('commission_pct'),
        })
    return {
        'ok': True,
        'status': 'archived' if want_archived else 'active',
        'counts': {'active': active_count, 'archived': archived_count},
        'items': items,
        'divar_profiles': divar,
    }


def favorites_items(codes: List[str], me_phone: str) -> Dict[str, Any]:
    from .routes import _lands_for_favorite_codes, _is_partner_approved

    clean = [str(c).strip() for c in (codes or []) if str(c).strip()][:200]
    lands = _lands_for_favorite_codes(clean, me_phone)
    items = [land_card(land) for land in lands]
    return {
        'ok': True,
        'count': len(items),
        'requested': len(clean),
        'valid_codes': [it['code'] for it in items if it.get('code')],
        'items': items,
        'is_approved': _is_partner_approved(getattr(g, 'express_partner_profile', None)),
    }


def legal_payload(doc: str) -> Dict[str, Any]:
    kind = (doc or 'terms').strip().lower()
    if kind == 'privacy':
        return {
            'ok': True,
            'doc': 'privacy',
            'title': 'حریم خصوصی',
            'sections': [
                {
                    'heading': 'چه داده‌هایی جمع می‌شود',
                    'body': 'شماره موبایل، نام، شهر، سوابق درخواست بازدید و معامله، و داده‌های فنی لازم برای امنیت ورود.',
                },
                {
                    'heading': 'هدف استفاده',
                    'body': 'ارائه پنل همکار، پیگیری فروش، پرداخت پورسانت، و بهبود امنیت حساب.',
                },
                {
                    'heading': 'اشتراک با دیگران',
                    'body': 'اطلاعات مشتری و فایل فقط برای انجام بازدید و معامله در چارچوب پنل استفاده می‌شود و فروش داده انجام نمی‌شود.',
                },
                {
                    'heading': 'حقوق شما',
                    'body': 'می‌توانید اصلاح مشخصات را از تنظیمات بخواهید و از حساب خارج شوید. حذف حساب با پشتیبانی وینور پیگیری می‌شود.',
                },
            ],
        }
    return {
        'ok': True,
        'doc': 'terms',
        'title': 'قوانین استفاده',
        'updated': '۱۴۰۴/۰۳/۰۱',
        'sections': [
            {
                'heading': '۱. پذیرش قوانین',
                'body': 'استفاده از پنل همکاران وینور اکسپرس، اپلیکیشن و وب‌سایت مرتبط، منوط به پذیرش این قوانین و حریم خصوصی است.',
            },
            {
                'heading': '۲. تعریف سرویس',
                'body': 'وینور اکسپرس بستری برای مشاهده فایل‌های ملک، همکاری در معرفی و پیگیری، ثبت وضعیت معامله و پیگیری پورسانت است. همکار صرفاً مجوز استفاده حرفه‌ای در چارچوب پنل را دارد.',
            },
            {
                'heading': '۳. شرایط حساب کاربری',
                'body': 'ورود با شماره موبایل واقعی، حفظ محرمانگی کد تأیید، مسئولیت فعالیت‌های حساب، و عدم واگذاری حساب به شخص ثالث.',
            },
            {
                'heading': '۴. رفتار مجاز و ممنوع',
                'body': 'اطلاعات فایل‌ها فقط برای اهداف حرفه‌ای؛ ممنوعیت انتشار غیرمجاز تصاویر، قیمت‌ها یا داده‌های مشتریان.',
            },
        ],
    }


def session_phone() -> str:
    return str(session.get('user_phone') or '').strip()


def session_profile():
    return getattr(g, 'express_partner_profile', None)
