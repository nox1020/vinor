# مدل‌های آفلاین Vinor AI

پوشهٔ پیش‌فرض برای فایل‌های **GGUF** (اجرای محلی بدون اینترنت برای inference).

## دانلود

```bash
pip install -r requirements-offline.txt
python scripts/download_offline_ai_model.py
```

مدل پیش‌فرض: **Qwen2.5-0.5B-Instruct** (حدود ۴۰۰ مگابایت، Q4_K_M).

## راه‌اندازی خودکار روی سرور

با استارت Flask/Passenger (`passenger_wsgi.py`):

1. نصب `requirements-offline.txt` (اگر نباشد)
2. دانلود مدل به `instance/ai_models/` (روی سرور)
3. بارگذاری مدل در حافظه (preload)

نیازی به اجرای دستی اسکریپت نیست؛ فقط اولین بار چند دقیقه صبر کنید.

## تنظیمات (متغیر محیطی)

| متغیر | معنی |
|--------|------|
| `VINOR_AI_PROVIDER` | `offline` (پیش‌فرض)، `api`، `auto` |
| `VINOR_AI_AUTO_BOOTSTRAP` | `1` = bootstrap در استارت |
| `VINOR_AI_AUTO_PIP` | `1` = نصب خودکار pip |
| `VINOR_AI_MODELS_DIR` | مسیر ذخیره مدل (سرور: `instance/ai_models`) |
| `VINOR_AI_MODELS_DIR` | مسیر جایگزین این پوشه |
| `VINOR_AI_OFFLINE_MODEL_PATH` | مسیر مستقیم فایل `.gguf` |
| `VINOR_AI_API_IF_LONGER_THAN` | پیام بلندتر از این → DeepSeek |
| `VINOR_AI_API_FALLBACK_OFFLINE` | بعد از خطای API → آفلاین (`1`) |
| `VINOR_AI_OFFLINE_FALLBACK_API` | بعد از خطای آفلاین → API (`1`) |

## اولویت پاسخ

- **همیشه اول:** مدل آفلاین
- **DeepSeek:** فقط اگر آفلاین خطا داد (`VINOR_AI_OFFLINE_FALLBACK_API=1`) یا `VINOR_AI_PROVIDER=api` یا کاربر `!api` بزند

برای استفاده از API در موضوعات پیچیده (اختیاری): `VINOR_AI_USE_API_FOR_COMPLEX=1` و `VINOR_AI_PROVIDER=auto`

فایل‌های `.gguf` در git commit نمی‌شوند (حجم زیاد).
