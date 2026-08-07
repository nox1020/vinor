# app/api/sms.py
# -*- coding: utf-8 -*-
"""
SMS API endpoints for communication with sms.ir
"""

from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from app.services.sms import send_sms_template
from app.services.sms_config import get_sms_api_key
from app.utils.storage import load_sms_history, save_sms_history

sms_api_bp = Blueprint('sms_api', __name__, url_prefix='/api/sms')

def _normalize_phone_for_sms(mobile: str) -> str:
    """Normalize phone number to 09xxxxxxxxx format"""
    if not mobile:
        return ''
    s = str(mobile).strip().replace(' ', '').replace('-', '')
    if s.startswith('+98') and len(s) == 13 and s[3:].startswith('9'):
        return '0' + s[3:]
    if s.startswith('0098') and len(s) == 14 and s[4:].startswith('9'):
        return '0' + s[4:]
    if s.startswith('98') and len(s) == 12 and s[2:].startswith('9'):
        return '0' + s[2:]
    if s.startswith('9') and len(s) == 10:
        return '0' + s
    if s.startswith('0') and len(s) == 11:
        return s
    return s

def _save_sms_record(mobile: str, template_id: int, parameters: dict, result: dict, 
                     source: str = 'api', recipient_name: str = None):
    """ذخیره سابقه ارسال پیامک"""
    try:
        history = load_sms_history(current_app) or []
        record = {
            'id': len(history) + 1,
            'mobile': mobile,
            'recipient_name': recipient_name,
            'template_id': template_id,
            'parameters': parameters or {},
            'success': result.get('ok', False),
            'status_code': result.get('status', 0),
            'response': result.get('body', {}),
            'source': source,  # 'api', 'admin_colleagues', 'admin_campaign'
            'created_at': datetime.now().isoformat(),
            'error': None if result.get('ok') else str(result.get('body', {}).get('message', 'Unknown error'))
        }
        history.append(record)
        # نگه داشتن فقط 10000 رکورد آخر
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception as e:
        try:
            current_app.logger.error(f"Failed to save SMS history: {e}")
        except Exception:
            pass

@sms_api_bp.route('/send', methods=['POST'])
def send_sms():
    """
    ارسال پیامک با استفاده از sms.ir
    
    Body (JSON):
    {
        "mobile": "09123456789",
        "template_id": 123456,
        "parameters": {
            "CODE": "1234",
            "NAME": "علی"
        },
        "api_key": "optional_custom_api_key"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'بدنه درخواست باید JSON باشد'
            }), 400
        
        mobile = data.get('mobile')
        template_id = data.get('template_id')
        parameters = data.get('parameters', {})
        api_key = data.get('api_key')
        
        if not mobile:
            return jsonify({
                'success': False,
                'error': 'شماره موبایل الزامی است'
            }), 400
        
        if not template_id:
            return jsonify({
                'success': False,
                'error': 'شناسه قالب (template_id) الزامی است'
            }), 400
        
        # Normalize phone number
        mobile = _normalize_phone_for_sms(mobile)
        
        if not mobile or len(mobile) != 11 or not mobile.startswith('09'):
            return jsonify({
                'success': False,
                'error': 'شماره موبایل نامعتبر است'
            }), 400
        
        # ارسال پیامک
        result = send_sms_template(
            mobile=mobile,
            template_id=int(template_id),
            parameters=parameters if parameters else None,
            api_key=api_key,
            record_history=False,
        )
        
        # ذخیره سابقه
        _save_sms_record(mobile, int(template_id), parameters, result, source='api')
        
        if result.get('ok'):
            current_app.logger.info(f"SMS sent successfully to {mobile} with template {template_id}")
            return jsonify({
                'success': True,
                'message': 'پیامک با موفقیت ارسال شد',
                'data': {
                    'mobile': mobile,
                    'template_id': template_id,
                    'status': result.get('status'),
                    'response': result.get('body')
                }
            }), 200
        else:
            current_app.logger.error(f"SMS send failed to {mobile}: {result.get('body')}")
            return jsonify({
                'success': False,
                'error': 'خطا در ارسال پیامک',
                'details': result.get('body'),
                'status_code': result.get('status', 0)
            }), 400
            
    except ValueError as e:
        current_app.logger.error(f"Invalid input in SMS API: {e}")
        return jsonify({
            'success': False,
            'error': f'ورودی نامعتبر: {str(e)}'
        }), 400
    except Exception as e:
        current_app.logger.error(f"Error in SMS API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'خطای داخلی سرور'
        }), 500


@sms_api_bp.route('/status', methods=['GET'])
def sms_status():
    """
    بررسی وضعیت سرویس SMS
    
    Returns:
        - API key status
        - Service availability
    """
    try:
        has_api_key = bool(get_sms_api_key())
        history = load_sms_history(current_app) or []
        total_sent = len([h for h in history if h.get('success')])
        total_failed = len([h for h in history if not h.get('success')])
        
        return jsonify({
            'success': True,
            'service': 'sms.ir',
            'api_key_configured': has_api_key,
            'endpoint': 'https://api.sms.ir/v1/send/verify',
            'stats': {
                'total_records': len(history),
                'total_sent': total_sent,
                'total_failed': total_failed
            }
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error checking SMS status: {e}")
        return jsonify({
            'success': False,
            'error': 'خطا در بررسی وضعیت'
        }), 500


@sms_api_bp.route('/history', methods=['GET'])
def sms_history():
    """
    دریافت سابقه ارسال پیامک‌ها
    
    Query Parameters:
        - limit: تعداد رکوردها (پیش‌فرض: 100)
        - offset: شروع از رکورد (پیش‌فرض: 0)
        - mobile: فیلتر بر اساس شماره موبایل
        - success: فیلتر بر اساس موفقیت (true/false)
    """
    try:
        history = load_sms_history(current_app) or []
        
        # فیلتر بر اساس شماره موبایل
        mobile_filter = request.args.get('mobile')
        if mobile_filter:
            mobile_filter = _normalize_phone_for_sms(mobile_filter)
            history = [h for h in history if h.get('mobile') == mobile_filter]
        
        # فیلتر بر اساس موفقیت
        success_filter = request.args.get('success')
        if success_filter is not None:
            success_bool = success_filter.lower() == 'true'
            history = [h for h in history if h.get('success') == success_bool]
        
        # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
        history.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        total = len(history)
        history = history[offset:offset + limit]
        
        return jsonify({
            'success': True,
            'total': total,
            'limit': limit,
            'offset': offset,
            'history': history
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error loading SMS history: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'خطا در بارگذاری سابقه'
        }), 500


@sms_api_bp.route('/bulk-send', methods=['POST'])
def bulk_send_sms():
    """
    ارسال پیامک به چند شماره به صورت گروهی
    
    Body (JSON):
    {
        "mobiles": ["09123456789", "09187654321"],
        "template_id": 123456,
        "parameters": {
            "CODE": "1234"
        },
        "api_key": "optional_custom_api_key"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'بدنه درخواست باید JSON باشد'
            }), 400
        
        mobiles = data.get('mobiles', [])
        template_id = data.get('template_id')
        parameters = data.get('parameters', {})
        api_key = data.get('api_key')
        
        if not mobiles or not isinstance(mobiles, list):
            return jsonify({
                'success': False,
                'error': 'لیست شماره موبایل الزامی است'
            }), 400
        
        if not template_id:
            return jsonify({
                'success': False,
                'error': 'شناسه قالب (template_id) الزامی است'
            }), 400
        
        results = {
            'success': [],
            'failed': [],
            'total': len(mobiles),
            'sent': 0,
            'failed_count': 0
        }
        
        for mobile in mobiles:
            try:
                # Normalize phone number
                mobile_str = _normalize_phone_for_sms(mobile)
                
                if not mobile_str or len(mobile_str) != 11 or not mobile_str.startswith('09'):
                    results['failed'].append({
                        'mobile': str(mobile),
                        'error': 'Invalid phone format'
                    })
                    results['failed_count'] += 1
                    continue
                
                result = send_sms_template(
                    mobile=mobile_str,
                    template_id=int(template_id),
                    parameters=parameters if parameters else None,
                    api_key=api_key,
                    record_history=False,
                )
                
                # ذخیره سابقه
                _save_sms_record(mobile_str, int(template_id), parameters, result, source='api_bulk')
                
                if result.get('ok'):
                    results['success'].append({
                        'mobile': mobile_str,
                        'status': 'sent'
                    })
                    results['sent'] += 1
                else:
                    results['failed'].append({
                        'mobile': mobile_str,
                        'error': result.get('body', 'Unknown error')
                    })
                    results['failed_count'] += 1
                    
            except Exception as e:
                results['failed'].append({
                    'mobile': str(mobile),
                    'error': str(e)
                })
                results['failed_count'] += 1
                current_app.logger.error(f"Error sending SMS to {mobile}: {e}")
        
        return jsonify({
            'success': True,
            'message': f'ارسال انجام شد: {results["sent"]} موفق، {results["failed_count"]} ناموفق',
            'results': results
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error in bulk SMS API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'خطای داخلی سرور'
        }), 500
