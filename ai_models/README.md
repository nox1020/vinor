# مدل‌های آفلاین Vinor AI

پوشهٔ پیش‌فرض برای فایل‌های **GGUF** (اجرای محلی بدون اینترنت برای inference).

## دانلود

```bash
pip install -r requirements-offline.txt
python scripts/download_offline_ai_model.py
```

مدل پیش‌فرض: **Qwen2.5-0.5B-Instruct** (حدود ۴۰۰ مگابایت، Q4_K_M).

## تنظیمات (متغیر محیطی)

| متغیر | معنی |
|--------|------|
| `VINOR_AI_PROVIDER` | `auto` (پیش‌فرض)، `offline`، `api` |
| `VINOR_AI_MODELS_DIR` | مسیر جایگزین این پوشه |
| `VINOR_AI_OFFLINE_MODEL_PATH` | مسیر مستقیم فایل `.gguf` |
| `VINOR_AI_API_IF_LONGER_THAN` | پیام بلندتر از این → DeepSeek |
| `VINOR_AI_API_FALLBACK_OFFLINE` | بعد از خطای API → آفلاین (`1`) |
| `VINOR_AI_OFFLINE_FALLBACK_API` | بعد از خطای آفلاین → API (`1`) |

## حالت `auto`

- **آفلاین:** سلام، سوالات کوتاه، راهنمای عمومی.
- **DeepSeek:** سوال طولانی، مقایسه/پیشنهاد فایل، کد ملک، پاسخ ادمین معلق، موضوعات حقوقی/قرارداد.

فایل‌های `.gguf` در git commit نمی‌شوند (حجم زیاد).
