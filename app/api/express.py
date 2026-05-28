# app/api/express.py
# -*- coding: utf-8 -*-
"""
Express Listings API endpoints for Vinor Express feature
"""

from flask import Blueprint, jsonify, request, current_app, make_response, session, url_for
from app.utils.storage import load_express_lands_cached, get_lands_file_stats, load_express_reposts, load_express_partners, load_settings
from app.utils.images import prepare_variants_dict
from app.services.notifications import add_notification
from app.utils.share_tokens import encode_partner_ref

express_api_bp = Blueprint('express_api', __name__, url_prefix='/api')

@express_api_bp.route('/app/version', methods=['GET'])
def get_app_version():
    """
    آخرین نسخه اپ اندروید (براساس تنظیمات پنل ادمین)
    """
    try:
        settings = load_settings() or {}
        payload = {
            "success": True,
            "android_apk_version": settings.get("android_apk_version") or "",
            "android_apk_url": settings.get("android_apk_url") or "",
            "android_apk_updated_at": settings.get("android_apk_updated_at") or "",
            "android_apk_size_bytes": settings.get("android_apk_size_bytes") or "",
            "android_apk_sha256": settings.get("android_apk_sha256") or "",
            "android_apk_original_name": settings.get("android_apk_original_name") or "",
        }
        resp = make_response(jsonify(payload))
        resp.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
        resp.headers["Vary"] = "Accept-Encoding"
        return resp
    except Exception as e:
        current_app.logger.error("Error reading app version: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "version_unavailable"}), 500

@express_api_bp.route('/express/app-version', methods=['GET'])
def get_app_version_alias():
    """
    Alias برای سازگاری با SW اکسپرس: /api/express/app-version
    """
    return get_app_version()

@express_api_bp.route('/express-listings')
def get_express_listings():
    """Get all express listings (بهینه شده)"""
    try:
        express_lands = load_express_lands_cached()
        stats = get_lands_file_stats()
        etag = stats.get("etag")

        # ETag short-circuit
        inm = request.headers.get("If-None-Match")
        if inm and etag and inm == etag:
            resp = make_response(("", 304))
            resp.headers['ETag'] = etag
            resp.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
            return resp

        # فیلتر فقط approved
        express_lands = [l for l in express_lands if l.get('express_status') == 'approved']
        
        response = make_response(jsonify({
            'success': True,
            'lands': express_lands,
            'count': len(express_lands)
        }))
        response.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
        if etag:
            response.headers['ETag'] = etag
        return response
    except Exception as e:
        current_app.logger.error(f"Error loading express listings: {e}")
        return jsonify({
            'success': False,
            'error': 'خطا در بارگذاری آگهی‌های اکسپرس'
        }), 500

@express_api_bp.route('/express-search')
def express_search():
    """جستجوی زنده در فایل‌های اکسپرس (بهینه شده)"""
    try:
        query = request.args.get('q', '').strip().lower()
        
        # استفاده از کش بهینه شده
        express_lands = load_express_lands_cached() or []
        stats = get_lands_file_stats()
        # ETag را به پارامتر جستجو وابسته می‌کنیم
        base_etag = stats.get("etag") or 'W/"lands"'
        etag = f'{base_etag}-search-{hash(query) & 0xffff:x}'
        inm = request.headers.get("If-None-Match")
        if inm and etag and inm == etag:
            resp = make_response(("", 304))
            resp.headers['ETag'] = etag
            resp.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=60'
            return resp
        
        # جستجو (بهینه شده)
        if query:
            search_terms = query.split()
            def _matches(land):
                search_text = ' '.join([
                    str(land.get('title', '')),
                    str(land.get('location', '')),
                    str(land.get('category', '')),
                    str(land.get('description', ''))
                ]).lower()
                return all(term in search_text for term in search_terms)
            express_lands = [l for l in express_lands if _matches(l)]
        
        # کاهش حجم داده + افزودن لینک thumb/full برای کاور
        minimal_lands = []
        for land in express_lands[:50]:  # محدود کردن به 50 نتیجه اول
            images = land.get('images', []) or []
            cover = images[0] if images else None
            cover_variants = prepare_variants_dict(cover)
            minimal_lands.append({
                'code': land.get('code'),
                'title': land.get('title'),
                'location': land.get('location'),
                'images': images[:1],
                'image_thumb': cover_variants.get('thumb'),
                'image_full': cover_variants.get('full'),
                'image_raw': cover_variants.get('raw'),
                'images_v2': [prepare_variants_dict(i) for i in images],
                'video': land.get('video')
            })
        
        response = make_response(jsonify({
            'success': True,
            'lands': minimal_lands,
            'count': len(express_lands)
        }))
        response.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=60'
        response.headers['Vary'] = 'Accept-Encoding'
        if etag:
            response.headers['ETag'] = etag
        return response
    except Exception as e:
        current_app.logger.error(f"Error in express search: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'خطا در جستجو'
        }), 500

@express_api_bp.route('/express-list')
def express_list():
    """API برای infinite scroll - لیست فایل‌های اکسپرس با صفحه‌بندی (بهینه شده برای سرعت)"""
    try:
        page = int(request.args.get('page', 1) or 1)
        per_page = int(request.args.get('per_page', 30) or 30)
        search_query = request.args.get('q', '').strip().lower()
        
        # استفاده از کش بهینه شده برای فایل‌های اکسپرس
        express_lands = load_express_lands_cached() or []
        stats = get_lands_file_stats()
        base_etag = stats.get("etag") or 'W/"lands"'
        etag = f'{base_etag}-list-p{page}-pp{per_page}-q{hash(search_query) & 0xffff:x}'
        inm = request.headers.get("If-None-Match")
        if inm and etag and inm == etag:
            resp = make_response(("", 304))
            resp.headers['ETag'] = etag
            resp.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
            return resp
        
        # جستجو (فقط در صورت نیاز)
        if search_query:
            # بهینه‌سازی: استفاده از list comprehension سریع‌تر
            search_terms = search_query.split()
            def _matches(land):
                # ساخت یک رشته واحد برای جستجوی سریع‌تر
                search_text = ' '.join([
                    str(land.get('title', '')),
                    str(land.get('location', '')),
                    str(land.get('category', '')),
                    str(land.get('description', ''))
                ]).lower()
                return all(term in search_text for term in search_terms)
            express_lands = [l for l in express_lands if _matches(l)]
        
        # تزریق بازنشرها در ابتدای لیست (سبک ریتوییت)
        try:
            reposts = load_express_reposts() or []
        except Exception:
            reposts = []
        if reposts:
            # ساخت آیتم‌های boost از بازنشرها
            code_to_land = {str(l.get('code')): l for l in express_lands}
            try:
                partners = load_express_partners() or []
            except Exception:
                partners = []
            phone_to_name = {str(p.get('phone') or ''): (p.get('name') or 'همکار') for p in partners if isinstance(p, dict)}
            boost_items = []
            for r in reposts[-100:][::-1]:
                c = str(r.get('code') or '')
                phone = str(r.get('partner_phone') or '')
                land = code_to_land.get(c)
                if land and phone:
                    item = dict(land)
                    try:
                        item['_share_token'] = encode_partner_ref(phone)
                    except Exception:
                        item['_share_token'] = ''
                    item['_repost_by_name'] = phone_to_name.get(phone) or 'همکار'
                    boost_items.append(item)
            express_lands = boost_items + express_lands

        # صفحه‌بندی
        total = len(express_lands)
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_lands = express_lands[start_idx:end_idx]
        
        # کاهش حجم داده: فقط فیلدهای ضروری + thumb/full
        minimal_lands = []
        for land in paginated_lands:
            images = land.get('images', []) or []
            cover = images[0] if images else None
            cover_variants = prepare_variants_dict(cover)
            minimal_lands.append({
                'code': land.get('code'),
                'title': land.get('title'),
                'location': land.get('location'),
                'category': land.get('category'),
                'images': images[:1],  # فقط اولین تصویر
                'image_thumb': cover_variants.get('thumb'),
                'image_full': cover_variants.get('full'),
                'image_raw': cover_variants.get('raw'),
                'images_v2': [prepare_variants_dict(i) for i in images],
                'video': land.get('video'),
                'price_total': land.get('price_total'),
                'created_at': land.get('created_at'),
                '_share_token': land.get('_share_token',''),
                '_repost_by_name': land.get('_repost_by_name',''),
            })
        
        response = make_response(jsonify({
            'success': True,
            'lands': minimal_lands,
            'pagination': {
                'page': page,
                'pages': pages,
                'total': total,
                'per_page': per_page,
                'has_next': page < pages,
                'has_prev': page > 1
            }
        }))
        
        # اضافه کردن cache headers برای سرعت بیشتر
        response.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=120'
        response.headers['Vary'] = 'Accept-Encoding'
        if etag:
            response.headers['ETag'] = etag
        
        return response
    except Exception as e:
        current_app.logger.error(f"Error in express list API: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'خطا در بارگذاری فایل‌ها'
        }), 500

@express_api_bp.route('/express/<string:code>')
def get_express_detail(code):
    """Get express listing detail (بهینه شده)"""
    try:
        express_lands = load_express_lands_cached()
        stats = get_lands_file_stats()
        base_etag = stats.get("etag") or 'W/"lands"'
        express_land = next((land for land in express_lands if land.get('code') == code), None)
        
        if not express_land:
            return jsonify({
                'success': False,
                'error': 'آگهی اکسپرس یافت نشد'
            }), 404
        
        etag = f'{base_etag}-detail-{code}'
        inm = request.headers.get("If-None-Match")
        if inm and etag and inm == etag:
            resp = make_response(("", 304))
            resp.headers['ETag'] = etag
            resp.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=600'
            return resp

        images = express_land.get('images') or []
        cover_variants = prepare_variants_dict(images[0] if images else None)
        express_land = dict(express_land)
        express_land.update({
            'image_thumb': cover_variants.get('thumb'),
            'image_full': cover_variants.get('full'),
            'image_raw': cover_variants.get('raw'),
            'images_v2': [prepare_variants_dict(i) for i in images],
        })

        response = make_response(jsonify({
            'success': True,
            'land': express_land
        }))
        response.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=600'
        response.headers['Vary'] = 'Accept-Encoding'
        response.headers['ETag'] = etag
        return response
    except Exception as e:
        current_app.logger.error(f"Error loading express detail: {e}")
        return jsonify({
            'success': False,
            'error': 'خطا در بارگذاری جزئیات آگهی'
        }), 500

@express_api_bp.route('/express/<string:code>/contact', methods=['POST'])
def express_contact_request(code):
    """Handle contact request for express listing"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        message = data.get('message', '').strip()
        
        if not name or not phone:
            return jsonify({
                'success': False,
                'error': 'نام و شماره تماس الزامی است'
            }), 400
        
        # Get express land details (بهینه شده)
        express_lands = load_express_lands_cached()
        express_land = next((land for land in express_lands if land.get('code') == code), None)
        
        if not express_land:
            return jsonify({
                'success': False,
                'error': 'آگهی اکسپرس یافت نشد'
            }), 404
        
        # Add notification for admin
        # نیاز به user_id برای ارسال نوتیفیکیشن
        # در صورت نیاز می‌توان به ادمین یا کاربر خاصی ارسال کرد
        # add_notification(
        #     user_id="admin",
        #     title="درخواست مشاوره اکسپرس",
        #     body=f"درخواست مشاوره برای آگهی {express_land.get('title', '')} از {name} ({phone})",
        #     ntype="info",
        #     ad_id=code
        # )
        
        return jsonify({
            'success': True,
            'message': 'درخواست شما با موفقیت ارسال شد. تیم پشتیبانی وینور با شما تماس خواهد گرفت.'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error handling express contact request: {e}")
        return jsonify({
            'success': False,
            'error': 'خطا در ارسال درخواست'
        }), 500

@express_api_bp.route('/menu', methods=['GET'])
def get_menu():
    """API endpoint برای دریافت منوی فوتر - هماهنگ با بک‌اند"""
    try:
        # بررسی اینکه آیا کاربر لاگین است یا نه
        is_logged_in = bool(session.get('user_id') or session.get('user_phone'))
        
        # بررسی اینکه آیا کاربر همکار اکسپرس است یا نه
        is_express_partner = False
        if session.get('user_phone'):
            try:
                me = str(session.get("user_phone") or "").strip()
                _partners = load_express_partners()
                is_express_partner = any(
                    isinstance(p, dict)
                    and str(p.get("phone") or "").strip() == me
                    and (str(p.get("status") or "").lower() == "approved" or p.get("status") is True)
                    for p in (_partners or [])
                )
            except Exception:
                is_express_partner = False
        
        # منوی همکار اکسپرس - نمایش در هر دو حالت (وارد شده و وارد نشده)
        # دسترسی‌ها بعداً تنظیم می‌شوند
        partner_menu = [
            {'key': 'dashboard', 'endpoint': 'express_partner.dashboard', 'icon': 'fa-home', 'label': 'وینور'},
            {'key': 'commissions', 'endpoint': 'express_partner.commissions', 'icon': 'fa-chart-line', 'label': 'پورسانت', 'disabled': not is_express_partner},
            {'key': 'routine', 'endpoint': 'express_partner.routine', 'icon': 'fa-list-check', 'label': 'روتین', 'disabled': not is_express_partner},
            {'key': 'profile', 'endpoint': 'express_partner.profile', 'icon': 'fa-user', 'label': 'من'}
        ]
        
        # همیشه منوی همکار را نمایش بده (در هر دو حالت وارد شده و وارد نشده)
        # تبدیل endpoint به URL
        menu_items = []
        for item in partner_menu:
            menu_item = dict(item)
            try:
                # استفاده از url_for برای ساخت URL از endpoint
                # request context از قبل موجود است
                menu_item['url'] = url_for(item['endpoint'])
            except Exception as url_error:
                # در صورت خطا، از endpoint به عنوان URL استفاده کن
                current_app.logger.debug(f"Error generating URL for {item['endpoint']}: {url_error}")
                menu_item['url'] = f"/express/partner/{item['key']}"
            # حذف endpoint از دیکشنری نهایی (فقط url را نگه دار)
            if 'endpoint' in menu_item:
                del menu_item['endpoint']
            menu_items.append(menu_item)
        
        response = make_response(jsonify({
            'success': True,
            'menu': menu_items,
            'is_logged_in': is_logged_in,
            'is_express_partner': is_express_partner
        }))
        # غیرفعال کردن cache برای منو تا تغییرات وضعیت لاگین فوراً اعمال شود
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
        
    except Exception as e:
        current_app.logger.error(f"Error loading menu: {e}", exc_info=True)
        # در صورت خطا، منوی پیش‌فرض همکار را برگردان
        return jsonify({
            'success': True,
            'menu': [
                {'key': 'dashboard', 'url': '/express/partner/dashboard', 'icon': 'fa-home', 'label': 'وینور'},
                {'key': 'commissions', 'url': '/express/partner/commissions', 'icon': 'fa-chart-line', 'label': 'پورسانت', 'disabled': True},
                {'key': 'routine', 'url': '/express/partner/routine', 'icon': 'fa-list-check', 'label': 'روتین', 'disabled': True},
                {'key': 'profile', 'url': '/express/partner/profile', 'icon': 'fa-user', 'label': 'من'}
            ],
            'is_logged_in': False,
            'is_express_partner': False
        }), 200
