"""تجمیع کاربران و همکاران برای کارت یکپارچهٔ دسترسی‌ها در پنل ادمین."""

from __future__ import annotations



from datetime import datetime

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple



from app.express_partner.partner_bank_accounts import admin_account_dict

from app.express_partner.partner_withdrawals import (

    ACTIVE_WITHDRAWAL_STATUSES,

    partner_commission_dashboard,

)





def _build_online_partner_lookup(
    entries: List[Dict[str, Any]] | None,
    normalize_phone: Callable[[str], str],
) -> Dict[str, Dict[str, Any]]:
    """نگاشت شماره نرمال + خام → آخرین رکورد آنلاین (برای تطابق با people)."""
    lookup: Dict[str, Dict[str, Any]] = {}
    for o in entries or []:
        if not isinstance(o, dict):
            continue
        raw = str(o.get('phone') or '').strip()
        if not raw:
            continue
        norm = (normalize_phone(raw) if normalize_phone else raw) or raw
        for key in {norm, raw}:
            prev = lookup.get(key)
            if not prev or float(o.get('timestamp') or 0) >= float(prev.get('timestamp') or 0):
                lookup[key] = o
    return lookup


def partner_is_approved(profile: Optional[Dict[str, Any]]) -> bool:

    if not profile or not isinstance(profile, dict):

        return False

    status = str(profile.get('status') or '').strip().lower()

    return profile.get('status') is True or status in (

        'approved', 'active', 'enabled', 'ok', 'true', '1',

    )





def _record_phone(normalize_phone: Callable[[str], str], row: Dict[str, Any], *keys: str) -> str:

    for key in keys:

        raw = str(row.get(key) or '').strip()

        if raw:

            return normalize_phone(raw) or raw

    return ''





def _sort_ts(row: Dict[str, Any], *keys: str) -> str:

    for key in keys:

        val = str(row.get(key) or '').strip()

        if val:

            return val

    return ''





def _land_title(lands_lookup: Dict[str, str], code: Any) -> str:

    c = str(code or '').strip()

    if not c:

        return ''

    return lands_lookup.get(c) or ''





def _assignment_status_label(status: Any) -> str:

    st = str(status or 'active').strip().lower()

    labels = {

        'active': 'فعال',

        'assigned': 'فعال',

        'open': 'فعال',

        'inactive': 'غیرفعال',

        'closed': 'بسته',

        'cancelled': 'لغو',

        'sold': 'فروخته',

    }

    return labels.get(st, st or '—')





def _commission_status_label(status: Any) -> str:

    st = str(status or 'pending').strip().lower()

    labels = {

        'pending': 'در انتظار',

        'approved': 'تأیید',

        'paid': 'پرداخت',

        'rejected': 'رد',

    }

    return labels.get(st, st or '—')





def _withdrawal_status_label(status: Any) -> str:

    st = str(status or 'pending').strip().lower()

    labels = {

        'pending': 'در انتظار',

        'approved': 'تأیید',

        'processing': 'در حال پردازش',

        'paid': 'پرداخت شده',

        'rejected': 'رد',

        'cancelled': 'لغو',

    }

    return labels.get(st, st or '—')





def _visit_status_label(status: Any) -> str:

    st = str(status or 'pending').strip().lower()

    labels = {

        'pending': 'در انتظار',

        'approved': 'تأیید',

        'completed': 'ثبت معامله',

        'cancelled': 'رد',

    }

    return labels.get(st, st or '—')





def _amount_int(value: Any) -> int:

    try:

        return int(float(value or 0))

    except (TypeError, ValueError):

        return 0





def _truncate(text: Any, limit: int = 120) -> str:
    s = str(text or '').strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + '…'


def _resolve_admin_avatar_url(partner: Dict[str, Any], user: Dict[str, Any]) -> str:
    raw = (partner.get('avatar') or partner.get('avatar_url') or user.get('avatar') or '').strip()
    if not raw:
        return ''
    try:
        from app.utils.images import display_avatar_url
        ver = partner.get('avatar_updated_at') or user.get('avatar_updated_at') or 0
        return display_avatar_url(raw, ver)
    except Exception:
        if '://' in raw:
            return raw
        if raw.startswith('/uploads/'):
            return raw
        if raw.startswith('uploads/'):
            return '/' + raw
        if raw.startswith('/'):
            return raw
        return f'/uploads/{raw}'


def _admin_bank_account_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    return admin_account_dict(row)


def _build_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    partner = row.get('partner') or {}
    user = row.get('user') or {}
    application = row.get('application') or {}
    return {

        'landline': (partner.get('landline') or user.get('landline') or '').strip(),

        'bio': (partner.get('bio') or user.get('bio') or '').strip(),

        'bio_short': _truncate(partner.get('bio') or user.get('bio') or '', 160),

        'birth_date': (partner.get('birth_date') or user.get('birth_date') or '').strip(),

        'avatar': _resolve_admin_avatar_url(partner, user),

        'avatar_updated_at': partner.get('avatar_updated_at') or user.get('avatar_updated_at') or 0,

        'commission_pct': partner.get('commission_pct') or '',

        'total_income': _amount_int(partner.get('total_income')),

        'referred_by_phone': (
            partner.get('referred_by_phone')
            or application.get('referred_by_phone')
            or ''
        ).strip(),

        'referred_by_name': '',

        'referral_grant_pending': bool(partner.get('referral_grant_pending')),

        'registered_at': (

            row.get('created_at')

            or partner.get('created_at')

            or user.get('registered_at')

            or user.get('created_at')

            or ''

        ),

    }


def _enrich_referrer_names(people: Dict[str, Dict[str, Any]]) -> None:
    """نام معرف را از همان فهرست اشخاص resolve می‌کند."""
    name_by_phone: Dict[str, str] = {}
    for row in people.values():
        ph = str(row.get('phone') or '').strip()
        if not ph:
            continue
        nm = str(row.get('name') or '').strip()
        if nm:
            name_by_phone[ph] = nm
    for row in people.values():
        prof = row.get('profile')
        if not isinstance(prof, dict):
            continue
        ref_ph = str(prof.get('referred_by_phone') or '').strip()
        prof['referred_by_name'] = name_by_phone.get(ref_ph, '') if ref_ph else ''


def resolve_admin_person_name(
    phone: str,
    *,
    normalize_phone,
    load_users,
    load_express_partners,
) -> str:
    """نام نمایشی یک شماره (برای معرف وقتی فقط از referrals آمده)."""
    raw = str(phone or '').strip()
    if not raw:
        return ''
    target = normalize_phone(raw) or raw
    for pr in load_express_partners() or []:
        if not isinstance(pr, dict):
            continue
        p = normalize_phone(pr.get('phone')) or str(pr.get('phone') or '').strip()
        if p == target:
            return str(pr.get('name') or '').strip()
    for u in load_users() or []:
        if not isinstance(u, dict):
            continue
        p = normalize_phone(u.get('phone') or u.get('mobile')) or str(
            u.get('phone') or u.get('mobile') or ''
        ).strip()
        if p == target:
            return str(u.get('name') or u.get('fullname') or '').strip()
    return ''


def _aggregate_activity_stats(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """جمع شمارنده‌های فعالیت برای لیست اشخاص."""
    agg = {
        'visits_total': 0,
        'visits_pending': 0,
        'assignments_active': 0,
        'assignments_total': 0,
        'commissions_total': 0,
        'commissions_approved': 0,
        'files': 0,
        'withdrawals_active': 0,
        'notes': 0,
        'routine_days': 0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        c = row.get('counts') or {}
        agg['visits_total'] += int(c.get('visits_total') or 0)
        agg['visits_pending'] += int(c.get('visits_pending') or 0)
        agg['assignments_active'] += int(c.get('assignments_active') or 0)
        agg['assignments_total'] += int(c.get('assignments_total') or 0)
        agg['commissions_total'] += int(c.get('commissions_total') or 0)
        agg['commissions_approved'] += int(c.get('commissions_approved') or 0)
        agg['files'] += int(c.get('files') or 0)
        agg['withdrawals_active'] += int(c.get('withdrawals_active') or 0)
        agg['notes'] += int(c.get('notes') or 0)
        routine = row.get('routine') or {}
        agg['routine_days'] += int(routine.get('days_count') or 0)
    return agg





def build_admin_people_directory(

    *,

    normalize_phone,

    load_users,

    load_express_partners,

    load_express_partner_apps,

    load_express_assignments,

    load_express_commissions,

    load_partner_files_meta,

    load_partner_withdrawals,

    load_partner_bank_accounts=None,

    get_online_partners_list,

    get_recent_online_partners_list=None,

    load_partner_notes=None,

    load_partner_routines_cached=None,

    load_express_visit_requests=None,

    lands_lookup: Optional[Dict[str, str]] = None,

    q: str = '',

    filter_kind: str = 'all',

    phone_only: str = '',

    detail_level: str = 'summary',

    recent_limit: int = 50,

) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:

    partners = load_express_partners() or []

    apps = load_express_partner_apps() or []

    users = load_users() or []

    assignments = load_express_assignments() or []

    commissions = load_express_commissions() or []

    files_meta = load_partner_files_meta() or []

    withdrawals = load_partner_withdrawals() or []

    bank_rows_raw = (load_partner_bank_accounts() or []) if load_partner_bank_accounts else []

    notes = (load_partner_notes() or []) if load_partner_notes else []

    routines = (load_partner_routines_cached() or []) if load_partner_routines_cached else []

    visits_raw = (load_express_visit_requests() or []) if load_express_visit_requests else []

    lands = lands_lookup or {}

    current_month = datetime.now().strftime('%Y-%m')

    full_detail = (detail_level or 'summary').strip().lower() == 'full'

    target_phone = ''

    if phone_only:

        target_phone = normalize_phone(str(phone_only).strip()) or str(phone_only).strip()



    online_entries = (
        (get_recent_online_partners_list() if get_recent_online_partners_list else get_online_partners_list()) or []
    )
    online_map = _build_online_partner_lookup(online_entries, normalize_phone)



    people: Dict[str, Dict[str, Any]] = {}



    def ensure(raw_phone: Any) -> Optional[Dict[str, Any]]:

        raw = str(raw_phone or '').strip()

        if not raw:

            return None

        phone = normalize_phone(raw) or raw

        if phone not in people:

            people[phone] = {

                'phone': phone,

                'name': '',

                'city': '',

                'email': '',

                'partner': None,

                'user': None,

                'application': None,

                'counts': {

                    'assignments_total': 0,

                    'assignments_active': 0,

                    'commissions_total': 0,

                    'commissions_approved': 0,

                    'files': 0,

                    'withdrawals_active': 0,

                    'visits_total': 0,

                    'visits_pending': 0,

                    'notes': 0,

                },

                'access': {},

                'profile': {},

                'financial': {},

                'assignments_recent': [],

                'commissions_recent': [],

                'withdrawals_recent': [],

                'files_recent': [],

                'visits_recent': [],

                'notes_recent': [],

                'routine': {'month': current_month, 'days_count': 0, 'steps_total': 0},

                'online': False,

                'last_activity': '',

                'ip': '',

                'created_at': '',

            }

        return people[phone]



    for u in users if isinstance(users, list) else []:

        if not isinstance(u, dict):

            continue

        row = ensure(u.get('phone') or u.get('mobile'))

        if not row:

            continue

        row['user'] = u

        row['name'] = (u.get('name') or u.get('fullname') or row['name'] or '').strip()

        row['email'] = (u.get('email') or row['email'] or '').strip()

        row['created_at'] = row['created_at'] or u.get('registered_at') or u.get('created_at') or ''



    for pr in partners if isinstance(partners, list) else []:

        if not isinstance(pr, dict):

            continue

        row = ensure(pr.get('phone'))

        if not row:

            continue

        row['partner'] = pr

        row['name'] = (pr.get('name') or row['name'] or '').strip()

        row['city'] = (pr.get('city') or row['city'] or '').strip()

        row['email'] = (pr.get('email') or row['email'] or '').strip()

        row['created_at'] = row['created_at'] or pr.get('created_at') or ''



    apps_sorted = sorted(

        [a for a in apps if isinstance(a, dict)],

        key=lambda x: str(x.get('created_at') or ''),

        reverse=True,

    )

    for app in apps_sorted:

        row = ensure(app.get('phone'))

        if not row:

            continue

        if not row['application']:

            row['application'] = app

        if not row['name']:

            row['name'] = (app.get('name') or '').strip()

        if not row['city']:

            row['city'] = (app.get('city') or '').strip()

        if not row['created_at']:

            row['created_at'] = app.get('created_at') or ''



    assign_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    assign_counts: Dict[str, Dict[str, int]] = {}

    for a in assignments if isinstance(assignments, list) else []:

        if not isinstance(a, dict):

            continue

        ph = _record_phone(normalize_phone, a, 'partner_phone', 'phone')

        if not ph:

            continue

        bucket = assign_counts.setdefault(ph, {'total': 0, 'active': 0})

        bucket['total'] += 1

        if str(a.get('status') or 'active').lower() in ('active', 'assigned', 'open'):

            bucket['active'] += 1

        land_code = str(a.get('land_code') or '').strip()

        assign_by_phone.setdefault(ph, []).append({

            'id': a.get('id'),

            'land_code': land_code,

            'land_title': _land_title(lands, land_code),

            'status': a.get('status') or 'active',

            'status_label': _assignment_status_label(a.get('status')),

            'commission_pct': a.get('commission_pct') or '',

            'created_at': a.get('created_at') or '',

        })



    comm_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    comm_counts: Dict[str, Dict[str, int]] = {}

    for c in commissions if isinstance(commissions, list) else []:

        if not isinstance(c, dict):

            continue

        ph = _record_phone(normalize_phone, c, 'partner_phone', 'phone')

        if not ph:

            continue

        bucket = comm_counts.setdefault(ph, {'total': 0, 'approved': 0})

        bucket['total'] += 1

        if str(c.get('status') or '').lower() == 'approved':

            bucket['approved'] += 1

        land_code = str(c.get('land_code') or '').strip()

        comm_by_phone.setdefault(ph, []).append({

            'id': c.get('id'),

            'land_code': land_code,

            'land_title': _land_title(lands, land_code),

            'commission_amount': _amount_int(c.get('commission_amount')),

            'status': c.get('status') or 'pending',

            'status_label': _commission_status_label(c.get('status')),

            'created_at': c.get('created_at') or '',

        })



    file_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    file_counts: Dict[str, int] = {}

    for f in files_meta if isinstance(files_meta, list) else []:

        if not isinstance(f, dict):

            continue

        ph = _record_phone(normalize_phone, f, 'phone', 'partner_phone')

        if not ph:

            continue

        file_counts[ph] = file_counts.get(ph, 0) + 1

        fname = str(f.get('filename') or f.get('name') or '').strip()

        if '__' in fname:

            fname = fname.split('__', 1)[-1]

        file_by_phone.setdefault(ph, []).append({

            'id': f.get('id'),

            'filename': fname or 'فایل',

            'stored_at': f.get('stored_at') or f.get('created_at') or '',

        })



    wd_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    wd_counts: Dict[str, int] = {}

    for w in withdrawals if isinstance(withdrawals, list) else []:

        if not isinstance(w, dict):

            continue

        ph = _record_phone(normalize_phone, w, 'phone', 'partner_phone')

        if not ph:

            continue

        st = str(w.get('status') or 'pending').strip().lower()

        if st in ACTIVE_WITHDRAWAL_STATUSES:

            wd_counts[ph] = wd_counts.get(ph, 0) + 1

        wd_by_phone.setdefault(ph, []).append({

            'id': w.get('id'),

            'amount': _amount_int(w.get('amount')),

            'status': w.get('status') or 'pending',

            'status_label': _withdrawal_status_label(w.get('status')),

            'created_at': w.get('created_at') or w.get('requested_at') or '',

            'bank_name': w.get('bank_name') or '',

            'masked_pan': w.get('masked_pan') or '',

            'bank_summary': w.get('bank_summary') or '',

        })



    banks_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    for b in bank_rows_raw if isinstance(bank_rows_raw, list) else []:

        if not isinstance(b, dict):

            continue

        ph = _record_phone(normalize_phone, b, 'phone', 'partner_phone')

        if not ph:

            continue

        banks_by_phone.setdefault(ph, []).append(_admin_bank_account_dict(b))



    for ph, rows in banks_by_phone.items():

        rows.sort(

            key=lambda x: (not bool(x.get('is_default')), str(x.get('created_at') or '')),

        )



    notes_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    for n in notes if isinstance(notes, list) else []:

        if not isinstance(n, dict):

            continue

        ph = _record_phone(normalize_phone, n, 'phone', 'partner_phone')

        if not ph:

            continue

        notes_by_phone.setdefault(ph, []).append({

            'id': n.get('id'),

            'content': _truncate(n.get('content') or n.get('text') or '', 200),

            'created_at': n.get('created_at') or '',

        })



    routine_map: Dict[str, Dict[str, Any]] = {}

    for r in routines if isinstance(routines, list) else []:

        if not isinstance(r, dict):

            continue

        ph = _record_phone(normalize_phone, r, 'phone', 'partner_phone')

        if ph:

            routine_map[ph] = r



    visits_by_phone: Dict[str, List[Dict[str, Any]]] = {}

    visit_counts: Dict[str, Dict[str, int]] = {}

    for v in visits_raw if isinstance(visits_raw, list) else []:

        if not isinstance(v, dict):

            continue

        ph = _record_phone(normalize_phone, v, 'partner_phone', 'phone')

        if not ph:

            continue

        bucket = visit_counts.setdefault(ph, {'total': 0, 'pending': 0})

        bucket['total'] += 1

        if str(v.get('status') or 'pending').strip().lower() == 'pending':

            bucket['pending'] += 1

        land_code = str(v.get('land_code') or '').strip()

        visits_by_phone.setdefault(ph, []).append({

            'id': v.get('id'),

            'land_code': land_code,

            'land_title': (v.get('land_title') or _land_title(lands, land_code)).strip(),

            'visit_date': v.get('visit_date') or '',

            'status': v.get('status') or 'pending',

            'status_label': _visit_status_label(v.get('status')),

            'created_at': v.get('created_at') or '',

        })



    def _recent(items: List[Dict[str, Any]], limit: int, *sort_keys: str) -> List[Dict[str, Any]]:

        rows = [x for x in items if isinstance(x, dict)]

        rows.sort(key=lambda x: _sort_ts(x, *sort_keys), reverse=True)

        return rows[:limit]



    for phone, row in people.items():

        if target_phone and phone != target_phone:

            continue

        ac = assign_counts.get(phone, {})

        cc = comm_counts.get(phone, {})

        vc = visit_counts.get(phone, {})

        notes_list = notes_by_phone.get(phone, [])

        rdata = routine_map.get(phone, {}) or {}

        days_all = rdata.get('days') or []

        steps_all = rdata.get('steps') or {}

        days_month = [

            d for d in days_all

            if isinstance(d, str) and d.startswith(current_month + '-')

        ]

        steps_month = {

            k: int(v)

            for k, v in (steps_all or {}).items()

            if isinstance(k, str) and k.startswith(current_month + '-')

            and isinstance(v, (int, float))

        }



        row['counts'] = {

            'assignments_total': int(ac.get('total') or 0),

            'assignments_active': int(ac.get('active') or 0),

            'commissions_total': int(cc.get('total') or 0),

            'commissions_approved': int(cc.get('approved') or 0),

            'files': int(file_counts.get(phone) or 0),

            'withdrawals_active': int(wd_counts.get(phone) or 0),

            'visits_total': int(vc.get('total') or 0),

            'visits_pending': int(vc.get('pending') or 0),

            'notes': len(notes_list),

        }

        row['profile'] = _build_profile(row)

        if full_detail:

            row['financial'] = partner_commission_dashboard(commissions, withdrawals, phone)

            row['bank_accounts'] = list(banks_by_phone.get(phone, []))

            row['counts']['bank_accounts'] = len(row['bank_accounts'])

            lim = max(int(recent_limit or 50), 1)

            row['assignments_recent'] = _recent(assign_by_phone.get(phone, []), lim, 'created_at')

            row['commissions_recent'] = _recent(comm_by_phone.get(phone, []), lim, 'created_at')

            row['withdrawals_recent'] = _recent(wd_by_phone.get(phone, []), lim, 'created_at')

            row['files_recent'] = _recent(file_by_phone.get(phone, []), lim, 'stored_at', 'created_at')

            row['visits_recent'] = _recent(visits_by_phone.get(phone, []), lim, 'visit_date', 'created_at')

            row['notes_recent'] = _recent(notes_list, lim, 'created_at')

        else:

            row['financial'] = {}

            row['bank_accounts'] = []

            row['assignments_recent'] = []

            row['commissions_recent'] = []

            row['withdrawals_recent'] = []

            row['files_recent'] = []

            row['visits_recent'] = []

            row['notes_recent'] = []

        row['routine'] = {

            'month': current_month,

            'days_count': len(days_month),

            'steps_total': sum(steps_month.values()) if steps_month else 0,

        }



        approved = partner_is_approved(row.get('partner'))

        app = row.get('application') or {}

        app_st = str(app.get('status') or '').strip().lower()

        pending_app = bool(app) and app_st not in ('approved', 'rejected') and not approved

        online = online_map.get(phone)

        if online:

            row['online'] = bool(online.get('online_now'))

            row['last_activity'] = online.get('last_activity') or ''

            row['ip'] = online.get('ip') or ''

            row['online_timestamp'] = float(online.get('timestamp') or 0)

        else:

            row['online_timestamp'] = 0

        fin = row.get('financial') or {}

        has_balance = bool(

            _amount_int(fin.get('withdrawable_balance'))

            or _amount_int(fin.get('approved_amount'))

            or _amount_int(fin.get('pending_amount'))

            or _amount_int(fin.get('total_confirmed_amount'))

        )

        row['access'] = {

            'site_user': bool(row.get('user')),

            'portal_login': bool(row.get('user')) or approved or pending_app,

            'partner_approved': approved,

            'partner_pending': pending_app,

            'application_rejected': app_st == 'rejected',

            'dashboard_files': approved and row['counts']['assignments_active'] > 0,

            'commissions': row['counts']['commissions_total'] > 0,

            'files_upload': row['counts']['files'] > 0,

            'withdrawals': row['counts']['withdrawals_active'] > 0,

            'balance': has_balance,

            'wallet': int(row['counts'].get('bank_accounts') or 0) > 0,

            'visits': row['counts']['visits_total'] > 0,

            'notes': row['counts']['notes'] > 0,

            'routine': row['routine']['days_count'] > 0,

            'online_now': bool(row.get('online')),

        }

    _enrich_referrer_names(people)

    items = list(people.values())

    if target_phone:

        row = people.get(target_phone)

        items = [row] if row else []

    q_norm = (q or '').strip().lower()

    if q_norm:

        def _hit(row: Dict[str, Any]) -> bool:

            prof = row.get('profile') or {}

            hay = ' '.join([

                str(row.get('phone') or ''),

                str(row.get('name') or ''),

                str(row.get('city') or ''),

                str(row.get('email') or ''),

                str(prof.get('landline') or ''),

                str(prof.get('bio') or ''),

                str(prof.get('referred_by_phone') or ''),

                str(prof.get('referred_by_name') or ''),

            ]).lower()

            return q_norm in hay

        items = [r for r in items if _hit(r)]



    fk = (filter_kind or 'all').strip().lower()

    if fk == 'partners':

        items = [r for r in items if r['access'].get('partner_approved')]

    elif fk == 'pending':

        items = [r for r in items if r['access'].get('partner_pending')]

    elif fk == 'users':

        items = [r for r in items if r['access'].get('site_user') and not r['access'].get('partner_approved')]

    elif fk == 'online':

        items = [r for r in items if float(r.get('online_timestamp') or 0) > 0]

        def _online_list_rank(row: Dict[str, Any]) -> tuple:
            acc = row.get('access') or {}
            if acc.get('partner_approved'):
                tier = 0
            elif acc.get('partner_pending'):
                tier = 1
            elif acc.get('site_user'):
                tier = 2
            else:
                tier = 3
            return (tier, -float(row.get('online_timestamp') or 0))

        items.sort(key=_online_list_rank)

    if fk != 'online':

        def _person_list_rank(row: Dict[str, Any]) -> tuple:
            acc = row.get('access') or {}
            if acc.get('partner_approved'):
                tier = 0
            elif acc.get('partner_pending'):
                tier = 1
            elif acc.get('site_user'):
                tier = 2
            else:
                tier = 3
            return (
                tier,
                0 if acc.get('online_now') else 1,
                str(row.get('name') or row.get('phone') or ''),
            )

        items.sort(key=_person_list_rank)



    stats = {

        'total': len(people),

        'shown': len(items),

        'partners': sum(1 for r in people.values() if r['access'].get('partner_approved')),

        'pending': sum(1 for r in people.values() if r['access'].get('partner_pending')),

        'site_users': sum(1 for r in people.values() if r['access'].get('site_user')),

        'online': sum(1 for r in people.values() if r['access'].get('online_now')),

        'recent_online': sum(1 for r in people.values() if float(r.get('online_timestamp') or 0) > 0),

        'agg': _aggregate_activity_stats(people.values()),

        'agg_shown': _aggregate_activity_stats(items),

    }

    return items, stats





def group_people_for_admin_list(
    people: List[Dict[str, Any]],
    filter_kind: str = 'all',
) -> List[Dict[str, Any]]:
    """گروه‌بندی لیست ادمین: همکاران بالا، کاربران پایین."""
    fk = (filter_kind or 'all').strip().lower()
    if fk != 'all':
        return [{'key': fk, 'label': None, 'people': list(people or [])}]

    partners: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    users: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []
    for person in people or []:
        if not isinstance(person, dict):
            continue
        acc = person.get('access') or {}
        if acc.get('partner_approved'):
            partners.append(person)
        elif acc.get('partner_pending'):
            pending.append(person)
        elif acc.get('site_user'):
            users.append(person)
        else:
            other.append(person)

    groups: List[Dict[str, Any]] = []
    if partners:
        groups.append({'key': 'partners', 'label': 'همکاران', 'people': partners})
    if pending:
        groups.append({'key': 'pending', 'label': 'در انتظار تأیید', 'people': pending})
    if users:
        groups.append({'key': 'users', 'label': 'کاربران', 'people': users})
    if other:
        groups.append({'key': 'other', 'label': 'سایر', 'people': other})
    return groups





def get_admin_person_by_phone(phone: str, **kwargs) -> Optional[Dict[str, Any]]:

    """بارگذاری یک شخص با جزئیات کامل برای صفحهٔ همکار."""

    raw = str(phone or '').strip()

    if not raw:

        return None

    norm_fn = kwargs.get('normalize_phone')

    target = (norm_fn(raw) if norm_fn else raw) or raw

    opts = dict(kwargs)

    opts['q'] = ''

    opts['filter_kind'] = 'all'

    opts['phone_only'] = target

    opts['detail_level'] = 'full'

    opts.setdefault('recent_limit', 100)

    items, _ = build_admin_people_directory(**opts)

    for row in items:

        if row.get('phone') == target:

            return row

    return None

