from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash, current_app, jsonify

from .blueprint import admin_bp
from .routes import counts_by_status, load_json, _lands_path, get_settings, save_settings  # reuse helpers
from .routes import login_required
from app.services.sms import send_sms_template
import time
import threading
import uuid
import random
def _normalize_for_sms_ir(mobile: str) -> str:
    """Convert various Iran mobile formats to 09xxxxxxxxx expected by sms.ir verify API."""
    if not mobile:
        return ''
    s = str(mobile).strip().replace(' ', '').replace('-', '')
    # +98XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('+98') and len(s) == 13 and s[3:].startswith('9'):
        return '0' + s[3:]
    # 0098XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('0098') and len(s) == 14 and s[4:].startswith('9'):
        return '0' + s[4:]
    # 98XXXXXXXXXX → 0XXXXXXXXXX
    if s.startswith('98') and len(s) == 12 and s[2:].startswith('9'):
        return '0' + s[2:]
    # 9XXXXXXXXX → 09XXXXXXXXX
    if s.startswith('9') and len(s) == 10:
        return '0' + s
    # already 09XXXXXXXXX
    if s.startswith('0') and len(s) == 11:
        return s
    return s


@admin_bp.route('/sms-campaign', methods=['GET', 'POST'])
@login_required
def sms_campaign():
    if request.method == 'GET':
        p, a, r = counts_by_status(load_json(_lands_path()) or [])
        phonebook = _load_phonebook()
        defaults = (get_settings() or {}).get('sms_defaults') or {}
        jobs = _list_jobs()
        return render_template('admin/sms_campaign.html', pending_count=p, approved_count=a, rejected_count=r,
                               phonebook=phonebook, defaults=defaults, jobs=jobs)

    _ = request.form.get('csrf_token')

    file = request.files.get('numbers_file')
    numbers_text = (request.form.get('numbers_text') or '').strip()
    template_id_raw = (request.form.get('template_id') or '').strip()
    delay_ms_raw = (request.form.get('delay_ms') or '1000').strip()

    params: dict[str, str] = {}
    # Support p[key] and p.name styles (legacy)
    for k, v in request.form.items():
        if k.startswith('p[') and k.endswith(']'):
            key = k[2:-1].strip()
            if key:
                params[key] = v
        elif k.startswith('p.'):
            key = k[2:].strip()
            if key:
                params[key] = v
    # Support new arrays param_key[]/param_value[]
    keys_arr = request.form.getlist('param_key[]')
    vals_arr = request.form.getlist('param_value[]')
    if keys_arr:
        for i, k in enumerate(keys_arr):
            key = (k or '').strip()
            if not key:
                continue
            val = (vals_arr[i] if i < len(vals_arr) else '')
            params[key] = (val or '').strip()

    # فایل اختیاری است؛ در صورت نبود فایل، از متن استفاده می‌شود

    try:
        template_id = int(template_id_raw)
    except Exception:
        flash('شناسهٔ قالب (template_id) نامعتبر است.', 'danger')
        return redirect(url_for('admin.sms_campaign'))

    try:
        delay_ms = max(0, int(delay_ms_raw))
    except Exception:
        delay_ms = 1000

    file_numbers: list[str] = []
    if file and file.filename:
        raw = b''
        try:
            raw = file.read()
        except Exception:
            raw = b''
        text = ''
        if raw:
            try:
                text = raw.decode('utf-8')
            except Exception:
                try:
                    text = raw.decode('cp1256', errors='ignore')
                except Exception:
                    text = raw.decode('latin1', errors='ignore')
        file_numbers = [line.strip() for line in (text.splitlines() if text else []) if line.strip()]

    text_numbers: list[str] = []
    if numbers_text:
        text_numbers = [line.strip() for line in numbers_text.splitlines() if line.strip()]

    numbers = file_numbers + text_numbers
    # حذف تکراری‌ها (اختیاری)
    if request.form.get('dedupe') == 'on':
        seen = set()
        uniq = []
        for n in numbers:
            if n not in seen:
                uniq.append(n)
                seen.add(n)
        numbers = uniq

    # اعتبارسنجی الگوی موبایل ایران (اختیاری ساده)
    if request.form.get('validate_ir') == 'on':
        filtered = []
        for n in numbers:
            s = n.replace(' ', '')
            if s.startswith('+98') and len(s) == 13:
                filtered.append(s)
            elif s.startswith('0098') and len(s) == 14:
                filtered.append('+98' + s[4:])
            elif s.startswith('0') and len(s) == 11:
                filtered.append('+98' + s[1:])
            elif s.startswith('9') and len(s) == 10:
                filtered.append('+98' + s)
            else:
                # عبور دادن شماره‌هایی که شاید فرمت دیگری داشته باشند
                filtered.append(s)
        numbers = filtered
    if not numbers:
        flash('هیچ شماره‌ای برای ارسال پیدا نشد.', 'warning')
        return redirect(url_for('admin.sms_campaign'))

    # حالت تاخیر تصادفی
    mode = request.form.get('delay_mode') or 'fixed'
    min_ms = max(0, int((request.form.get('delay_min_ms') or '800') or 800)) if mode == 'random' else None
    max_ms = max(0, int((request.form.get('delay_max_ms') or '1800') or 1800)) if mode == 'random' else None
    if min_ms is not None and max_ms is not None and min_ms > max_ms:
        min_ms, max_ms = max_ms, min_ms

    dry_run = request.form.get('dry_run') == 'on'

    # ذخیره تنظیمات پیش‌فرض (اختیاری) پس از محاسبه مقادیر
    if request.form.get('save_defaults') == 'on':
        save_settings({
            'sms_defaults': {
                'template_id': template_id,
                'delay_mode': mode,
                'delay_ms': delay_ms,
                'delay_min_ms': min_ms,
                'delay_max_ms': max_ms,
                'dedupe': request.form.get('dedupe') == 'on',
                'validate_ir': request.form.get('validate_ir') == 'on',
                'dry_run': request.form.get('dry_run') == 'on',
            }
        })
    # ایجاد Job پس‌زمینه و شروع Thread
    job_id = str(uuid.uuid4())
    _create_job(job_id, total=len(numbers), template_id=template_id, mode=mode,
                delay_ms=delay_ms, min_ms=min_ms, max_ms=max_ms)

    app_obj = current_app._get_current_object()
    t = threading.Thread(
        target=_run_sms_job,
        args=(app_obj, job_id, numbers, template_id, params, mode, delay_ms, min_ms, max_ms, dry_run),
        daemon=False,
        name=f"SMSJob-{job_id[:8]}"
    )
    t.start()

    flash(f'ارسال در پس‌زمینه آغاز شد. شناسه: {job_id}', 'success')
    return redirect(url_for('admin.sms_campaign'))


# ---------------------- Phonebook helpers & routes ----------------------
def _phonebook_path() -> str:
    return current_app.config.get(
        'PHONEBOOK_FILE',
        current_app.instance_path + '/data/phonebook.json'
    )

def _load_phonebook() -> dict:
    import os, json
    path = _phonebook_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    data.setdefault('groups', [])
                    return data
        except Exception:
            pass
    return {'groups': []}

def _save_phonebook(data: dict) -> None:
    import os, json
    path = _phonebook_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@admin_bp.post('/sms-campaign/phonebook')
def save_phonebook_group():
    name = (request.form.get('group_name') or '').strip() or 'گروه بدون نام'
    file = request.files.get('phonebook_file')
    text = (request.form.get('phonebook_text') or '').strip()

    items: list[str] = []
    # from file
    if file and file.filename:
        raw = b''
        try:
            raw = file.read()
        except Exception:
            raw = b''
        text = ''
        if raw:
            try:
                text = raw.decode('utf-8')
            except Exception:
                try:
                    text = raw.decode('cp1256', errors='ignore')
                except Exception:
                    text = raw.decode('latin1', errors='ignore')
        items.extend([line.strip() for line in (text.splitlines() if text else []) if line.strip()])
    # from textarea
    if text:
        items.extend([line.strip() for line in text.splitlines() if line.strip()])

    # normalize basic Iran format if requested
    if request.form.get('validate_ir') == 'on':
        norm = []
        for n in items:
            s = n.replace(' ','')
            if s.startswith('+98') and len(s) == 13:
                norm.append(s)
            elif s.startswith('0098') and len(s) == 14:
                norm.append('+98' + s[4:])
            elif s.startswith('0') and len(s) == 11:
                norm.append('+98' + s[1:])
            elif s.startswith('9') and len(s) == 10:
                norm.append('+98' + s)
            else:
                norm.append(s)
        items = norm

    if request.form.get('dedupe') == 'on':
        seen = set(); deduped = []
        for n in items:
            if n not in seen:
                seen.add(n); deduped.append(n)
        items = deduped

    if not items:
        flash('شماره‌ای برای ذخیره در دفترچه تلفن ارسال نشد.', 'warning')
        return redirect(url_for('admin.sms_campaign'))

    pb = _load_phonebook()
    pb['groups'].append({
        'name': name,
        'count': len(items),
        'numbers': items,
    })
    _save_phonebook(pb)
    flash(f'گروه «{name}» با {len(items)} شماره ذخیره شد.', 'success')
    return redirect(url_for('admin.sms_campaign'))


# ---------------------- Background Jobs ----------------------
def _sms_jobs_path() -> str:
    return current_app.config.get('SMS_JOBS_FILE', current_app.instance_path + '/data/sms_jobs.json')

def _load_jobs() -> dict:
    import os, json
    path = _sms_jobs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    data.setdefault('jobs', {})
                    return data
        except Exception:
            pass
    return {'jobs': {}}

def _save_jobs(data: dict) -> None:
    import os, json
    path = _sms_jobs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _create_job(job_id: str, total: int, template_id: int, mode: str, delay_ms: int, min_ms, max_ms) -> None:
    data = _load_jobs()
    data['jobs'][job_id] = {
        'id': job_id,
        'status': 'running',
        'total': total,
        'sent': 0,
        'failed': 0,
        'template_id': template_id,
        'mode': mode,
        'delay_ms': delay_ms,
        'min_ms': min_ms,
        'max_ms': max_ms,
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
    }
    _save_jobs(data)

def _update_job(job_id: str, **fields) -> None:
    data = _load_jobs()
    if job_id in data['jobs']:
        data['jobs'][job_id].update(fields)
        data['jobs'][job_id]['updated_at'] = int(time.time())
        _save_jobs(data)

def _list_jobs(limit: int = 10) -> list:
    data = _load_jobs()
    jobs = list(data['jobs'].values())
    jobs.sort(key=lambda j: j.get('created_at', 0), reverse=True)
    return jobs[:limit]

def _run_sms_job(app, job_id: str, numbers: list[str], template_id: int, params: dict, mode: str,
                 delay_ms: int, min_ms, max_ms, dry_run: bool) -> None:
    # Ensure we have Flask application context inside the thread
    with app.app_context():
        sent = failed = 0
        try:
            app.logger.info("[SMS_JOB %s] start: total=%d, mode=%s, dry_run=%s", job_id, len(numbers), mode, dry_run)
            for mobile in numbers:
                try:
                    to_send = _normalize_for_sms_ir(mobile)
                    if dry_run:
                        resp = {"ok": True, "status": 200}
                    else:
                        resp = send_sms_template(
                            mobile=to_send,
                            template_id=template_id,
                            parameters=params,
                            history_source='admin_sms_campaign',
                        )
                    if resp.get('ok'):
                        sent += 1
                    else:
                        failed += 1
                        try:
                            app.logger.error(
                                "[SMS_JOB %s] api failure to %s (norm=%s): status=%s body=%s",
                                job_id, mobile, to_send, resp.get('status'), str(resp.get('body'))[:800]
                            )
                        except Exception:
                            pass
                except Exception as e:
                    failed += 1
                    try:
                        app.logger.error("[SMS_JOB %s] error sending to %s: %s", job_id, mobile, e)
                    except Exception:
                        pass

                _update_job(job_id, sent=sent, failed=failed)

                if mode == 'fixed':
                    if delay_ms and delay_ms > 0:
                        time.sleep(delay_ms / 1000.0)
                else:
                    lo = min_ms or 0
                    hi = max_ms or lo
                    wait_ms = random.randint(lo, hi) if hi >= lo else lo
                    if wait_ms > 0:
                        time.sleep(wait_ms / 1000.0)

            _update_job(job_id, status='completed')
            app.logger.info("[SMS_JOB %s] completed: sent=%d, failed=%d", job_id, sent, failed)
        except Exception as e:
            _update_job(job_id, status='failed')
            try:
                app.logger.error("[SMS_JOB %s] fatal error: %s", job_id, e)
            except Exception:
                pass


@admin_bp.get('/sms-campaign/job/<string:job_id>')
def sms_job_status(job_id: str):
    data = _load_jobs()
    job = data['jobs'].get(job_id)
    if not job:
        return jsonify({'ok': False, 'error': 'NOT_FOUND'}), 404
    return jsonify({'ok': True, 'job': job})


@admin_bp.post('/sms-campaign/test-send')
@login_required
def sms_test_send():
    """Send a single test SMS with current parameters to verify API/key/template."""
    _ = request.form.get('csrf_token')
    phone = (request.form.get('test_mobile') or '').strip()
    template_id_raw = (request.form.get('template_id') or '').strip()

    if not phone:
        flash('شماره تست وارد نشده است.', 'warning')
        return redirect(url_for('admin.sms_campaign'))
    try:
        template_id = int(template_id_raw)
    except Exception:
        flash('شناسهٔ قالب (template_id) نامعتبر است.', 'danger')
        return redirect(url_for('admin.sms_campaign'))

    # collect params
    params: dict[str, str] = {}
    # legacy styles
    for k, v in request.form.items():
        if k.startswith('p[') and k.endswith(']'):
            key = k[2:-1].strip()
            if key:
                params[key] = v
        elif k.startswith('p.'):
            key = k[2:].strip()
            if key:
                params[key] = v
    # array style
    keys_arr = request.form.getlist('param_key[]')
    vals_arr = request.form.getlist('param_value[]')
    if keys_arr:
        for i, k in enumerate(keys_arr):
            key = (k or '').strip()
            if not key:
                continue
            val = (vals_arr[i] if i < len(vals_arr) else '')
            params[key] = (val or '').strip()

    to_send = _normalize_for_sms_ir(phone)
    try:
        resp = send_sms_template(
            mobile=to_send,
            template_id=template_id,
            parameters=params,
            history_source='admin_sms_campaign',
        )
        ok = bool(resp.get('ok'))
        code = resp.get('status')
        body = resp.get('body')
        if ok:
            flash(f'پیامک تست با موفقیت ارسال شد. status={code}', 'success')
        else:
            current_app.logger.error('[SMS_TEST] failure to %s (norm=%s): status=%s body=%s', phone, to_send, code, str(body)[:800])
            flash(f'ارسال تست ناموفق بود. status={code}', 'danger')
    except Exception as e:
        current_app.logger.error('[SMS_TEST] fatal: %s', e)
        flash('خطای غیرمنتظره در ارسال تست.', 'danger')

    return redirect(url_for('admin.sms_campaign'))
