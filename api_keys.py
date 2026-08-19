# -*- coding: utf-8 -*-
"""
کلیدهای API وینور — فایل مرکزی (ریشه پروژه).
همه سرویس‌ها از همین فایل می‌خوانند؛ در git commit می‌شود.
"""

# --- DeepSeek (Vinor AI) ---
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# پیش‌فرض سازگار با DeepSeek V4 (deepseek-chat از ۱۴۰۵/۰۵/۰۲ منسوخ می‌شود)
DEEPSEEK_MODEL = "deepseek-v4-flash"

# --- sms.ir (OTP و پیامک) ---
#
# OTP با متد Verify (ارسال سریع خدماتی) و قالب ۸۷۸۴۵۱ — نه bulk.
# متن قالب:
#   کد تایید:
#   <#> 32564
#   @vinor.ir #32564
#   4R707/AKLt0
SMS_API_KEY = "AcEcwFoGsqya9QdAii8QWhU51eie84sEbB9I4mJ0gknvm7lg"
SMS_TEMPLATE_ID = 878451
SMS_LINE_NUMBER = "09981801922"
SMS_RETRIEVER_HASH = "4R707/AKLt0"

# --- سایر (در صورت نیاز) ---
VINOR_WEBHOOK_SECRET = ""
