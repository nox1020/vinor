# -*- coding: utf-8 -*-
"""
کلیدهای API وینور — فایل مرکزی (ریشه پروژه).
همه سرویس‌ها از همین فایل می‌خوانند؛ در git commit می‌شود.
"""

# --- DeepSeek (Vinor AI) ---
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# --- sms.ir (OTP و پیامک) ---
#
# قالب OTP در پنل sms.ir:
#   کد تایید:
#   <#> #CODE#
#   @vinor.ir ##CODE#
#   #HASH#
#
# نمونه (CODE=36423):
#   کد تایید:
#   <#> 36423
#   @vinor.ir #36423
#   4R707/AKLt0
#
# با «کد تایید:» قبل از <#> — auto-fill در APK via User Consent (یک‌بار «اجازه دادن»).
SMS_API_KEY = "AcEcwFoGsqya9QdAii8QWhU51eie84sEbB9I4mJ0gknvm7lg"
SMS_TEMPLATE_ID = 878451
SMS_LINE_NUMBER = "09981801922"
SMS_RETRIEVER_HASH = "4R707/AKLt0"

# --- سایر (در صورت نیاز) ---
VINOR_WEBHOOK_SECRET = ""
