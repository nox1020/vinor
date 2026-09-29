# یادداشت فرانت — آنبوردینگ مشاور بعد از dry-run خاموش

قرارداد فیلدها در `docs/consultant-onboarding-api.md` است. این یادداشت فقط می‌گوید فرانت اندروید و وب چطور همان stub را بعد از پیش‌فرض `VINOR_CONSULTANT_DRY_RUN=0` براند.

نقش API همان `consultant` است. برچسب UI «بازاریاب وینور». فاز ۱ فقط `buy` و `sell`.

## dry-run پیش‌فرض خاموش است

همکار **نمی‌تواند** خودش را تأیید کند.

- `POST /api/consultant/simulate` برای نشست همکار `404` است و چیزی نمی‌نویسد، حتی با توکن CSRF.
- `GET /api/consultant/status?simulate=` و هدر `X-Vinor-Consultant-Simulate` نادیده گرفته می‌شوند. پاسخ، وضعیت ذخیره‌شده است.
- `VINOR_CONSULTANT_SIMULATE` روی خواندن اثری ندارد مگر dry-run صریحاً روشن باشد.

تا بررسی ادمین واقعی وصل شود، مسیر عادی روی `status=pending` می‌ماند. داشبورد و آنلاین‌شدن را با simulate باز نکنید.

## S1 تا S5 وقتی وضعیت `pending` است

`GET /status` تا قبل از تأیید واقعی همیشه `status` درشت را `pending` برمی‌گرداند (`approved` و `rejected` فقط بعد از بررسی). برای انتخاب صفحه از `next_step` استفاده کنید، نه از خود `pending`.

| گام | صفحه | شرط |
|-----|------|-----|
| S1 | شروع | بدون نشست: `401` و `error=unauthorized`. با نشست، اگر هنوز apply نشده: `GET /status` → `404` و `error=not_applied`. سپس `POST /apply` با بدنه خالی یا `{}`. |
| S2 | پروفایل | `next_step=profile`. پاسخ apply: `status=pending_profile`. |
| S3 | مدارک | `next_step=documents`. پاسخ profile: `status=pending_documents`. |
| S4 | انتظار بررسی | `next_step=status` و `status=pending`. آنلاین‌شدن اینجا `409` است. |
| S5 | داشبورد | فقط `next_step=dashboard` و `status=approved`. |

رد شدن روی همان صفحهٔ وضعیت می‌ماند: `status=rejected`، `next_step=status`، `reject_reason` فارسی. این S5 نیست.

`onboarding_slides_seen` در این stub همیشه `false` است. اسلاید را اگر نشان می‌دهید محلی نگه دارید؛ سرور دروازهٔ S2 تا S5 نیست.

`POST /apply` دوباره پیشرفت را پاک نمی‌کند. شناسه را از همان پاسخ اول نگه دارید (`consultant_id` و `partner_id` یکی‌اند). `GET /status` شناسه را تکرار نمی‌کند.

### فیلدهایی که فرانت باید همان‌طور بفرستد

- پروفایل: `name` (۲ تا ۴۰ نویسه)، `city` فقط `id` از `GET /cities` (برچسب فارسی شهر رد می‌شود)، `specialties` آرایه‌ای از `buy` و/یا `sell`. پاسخ همیشه `buy` سپس `sell` است. `rent` و هر مقدار دیگر `400` با `fields.specialties` است. شهر خارج از ۱۵ شناسه: `400` و `fields.city`.
- مدارک: `multipart/form-data` با نام فیلد `national_id` (اجباری) و `license` (اختیاری). jpg یا png یا pdf، هر کدام حداکثر ۵ مگابایت. پاسخ فقط `documents.*.uploaded` است؛ مسیر، پسوند و شماره در JSON نیست.
- آنلاین: `POST /availability` با `{ "online": true|false }` فقط در S5. قبل از تأیید: `409`، `error=not_approved`، پیام فارسی. `next_step` را از `GET /status` بگیرید.

۱۵ شناسه، به همین ترتیب: `tehran`, `rey`, `eslamshahr`, `baharestan`, `shahriar`, `malard`, `qods`, `robat_karim`, `pakdasht`, `varamin`, `qarchak`, `pardis`, `shemiranat`, `damavand`, `andisheh`.

شکل خطا همه‌جا: `{ "ok": false, "error": "<code>", "message": "<fa>", "fields"?: { ... } }`. موفق: `{ "ok": true, ... }`.

## CSRF برای APK و WebView

کوکی نشست `vinor_session` (همان OTP همکار) برای همهٔ مسیرها لازم است. این نوشتن‌ها توکن CSRF نمی‌خواهند:

- `POST /api/consultant/apply`
- `PATCH /api/consultant/profile`
- `POST /api/consultant/documents`
- `POST /api/consultant/availability`

`GET /cities` و `GET /status` متد امن‌اند.

`POST /api/consultant/simulate` معاف نیست. بدون `X-CSRFToken` یا فیلد `csrf_token` پاسخ `400` و `error=csrf_expired` است و وضعیتی نوشته نمی‌شود. این مسیر را از اپ همکار صدا نزنید.

## QA محلی اگر simulate لازم است

فقط روی محیط آزمایش، نه پیش‌فرض محصول:

```bash
VINOR_CONSULTANT_DRY_RUN=1
```

مقادیر روشن: `1`، `true`، `yes`، `on`. هر چیز دیگر، از جمله حذف متغیر، خاموش است.

با dry-run روشن، نشست همکار می‌تواند `GET /status?simulate=approved|rejected|pending` بزند. `POST /simulate` هنوز توکن CSRF می‌خواهد. پوشش خواندنِ بدون نوشتن روی دیسک:

```bash
VINOR_CONSULTANT_DRY_RUN=1
VINOR_CONSULTANT_SIMULATE=approved
```

`VINOR_CONSULTANT_SIMULATE` به‌تنهایی، وقتی dry-run خاموش است، وضعیت را `approved` نمی‌کند.
