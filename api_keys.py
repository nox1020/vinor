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
# قالب OTP — عیناً در پنل sms.ir (متغیرها: CODE و HASH):
#
#   کد ورود شما : (آن را در اختیار هیچ کس نگذارید)
#   https://vinor.ir
#   <#> #CODE#
#   @vinor.ir ##CODE#
#   #HASH#
#
# نمونه خروجی (CODE=38415):
#   <#> 38415
#   @vinor.ir #38415
#   4R707/AKLt0
#
# ##CODE# = یک # ثابت + مقدار CODE  |  #HASH# = SMS_RETRIEVER_HASH
SMS_API_KEY = "AcEcwFoGsqya9QdAii8QWhU51eie84sEbB9I4mJ0gknvm7lg"
SMS_TEMPLATE_ID = 878451
SMS_LINE_NUMBER = "300089930616"
SMS_RETRIEVER_HASH = "4R707/AKLt0"

# --- سایر (در صورت نیاز) ---
VINOR_WEBHOOK_SECRET = ""
