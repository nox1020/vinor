# آنبوردینگ مشاور — stub فاز ۱

مسیر واحد اندروید و وب: `/api/consultant/*`

نقش API برابر `consultant` است. برچسب UI «بازاریاب وینور» روی **همان رکورد Express Partner** نگاشت می‌شود (`api_role` و `consultant_onboarding`). سیستم apply دوم ساخته نشده است. تخصیص لید خارج از این stub است.

احراز هویت همان نشست همکار است (کوکی `vinor_session` بعد از OTP موجود). بدون نشست: `401`. این مسیرها از CSRF معاف‌اند تا WebView و APK با همان کوکی صدا بزنند.

موفق: `{ "ok": true, ... }`  
خطا: `{ "ok": false, "error": "<code>", "message": "<fa>", "fields"?: { ... } }`

`consultant_id` و `partner_id` هر دو شناسهٔ همان رکورد Partner هستند.

## فراخوانی

وب (همان origin، کوکی نشست):

```javascript
await fetch("/api/consultant/apply", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: "{}",
});
```

اندروید: همان `Cookie` / cookie jar ورود همکار (`vinor_session`). بدنهٔ JSON با `Content-Type: application/json`. مدارک با `multipart/form-data` و نام فیلدهای `national_id` (اجباری) و `license` (اختیاری).

| روش | مسیر | نکته |
|-----|------|------|
| POST | `/api/consultant/apply` | بدنه خالی یا `{}` → `pending_profile` |
| PATCH | `/api/consultant/profile` | `name` (۲–۴۰)، `city` (فقط id)، `specialties` زیرمجموعهٔ `buy`/`sell` |
| POST | `/api/consultant/documents` | jpg، png یا pdf، هر فایل حداکثر ۵ مگابایت |
| GET | `/api/consultant/status` | `pending` \| `approved` \| `rejected` |
| POST | `/api/consultant/availability` | `{ "online": true }` فقط بعد از تأیید؛ وگرنه `409` |
| GET | `/api/consultant/cities` | ۱۵ شهر قفل‌شدهٔ فاز ۱ |

`specialties` در پاسخ به ترتیب پایدار `buy` سپس `sell` برمی‌گردد. شناسهٔ شهر روی فیلد سراسری `city` همکار (برچسب فارسی پنل) نوشته نمی‌شود.

`next_step`: پروفایل ناقص → `profile`، مدرک ناقص → `documents`، در انتظار بررسی یا رد → `status`، تأیید → `dashboard`.

ورود مجدد با `POST /apply` پیشرفت قبلی را پاک نمی‌کند. بارگذاری دوبارهٔ مدرک، درخواستِ تأییدشده را به صف انتظار برنمی‌گرداند.

## شهرهای فاز ۱

| id | label |
|----|-------|
| tehran | تهران |
| rey | شهرری |
| eslamshahr | اسلامشهر |
| baharestan | بهارستان |
| shahriar | شهریار |
| malard | ملارد |
| qods | قدس |
| robat_karim | رباط‌کریم |
| pakdasht | پاکدشت |
| varamin | ورامین |
| qarchak | قرچک |
| pardis | پردیس |
| shemiranat | شمیرانات |
| damavand | دماوند |
| andisheh | اندیشه |

شهر خارج از این فهرست: `400` و `fields.city`.

## شبیه‌سازی dry-run

بررسی ادمین واقعی وصل نیست. تا آن زمان وضعیت تأیید را می‌توان شبیه‌سازی کرد.

1. `POST /api/consultant/simulate` با `{ "status": "approved" }` یا `"rejected"` یا `"pending"`. برای رد، `reject_reason` فارسی اختیاری است. پاسخ همان شکل `GET /status` است و روی رکورد نوشته می‌شود.
2. `GET /api/consultant/status?simulate=approved` (یا هدر `X-Vinor-Consultant-Simulate`) همان نوشتن را انجام می‌دهد.
3. متغیر محیطی `VINOR_CONSULTANT_SIMULATE=approved|rejected|pending` نتیجه را برای همهٔ خواندن‌ها عوض می‌کند و روی دیسک به‌عنوان تأیید دائمی ذخیره نمی‌شود. اگر ست باشد، بر مقدار ذخیره‌شده اولویت دارد.

این سه راه فقط وقتی باز است که `VINOR_CONSULTANT_DRY_RUN` روشن باشد (پیش‌فرض `1`) یا نشست ادمین (`logged_in` + `admin_phone`) وجود داشته باشد. ادمین می‌تواند در بدنهٔ `POST /simulate` فیلد `phone` بگذارد و رکورد همان همکار را هدف بگیرد.

قبل از وصل شدن بررسی واقعی، در محیط عملیاتی `VINOR_CONSULTANT_DRY_RUN=0` بگذارید تا همکار نتواند خودش را تأیید کند.

`VINOR_CONSULTANT_API_ENABLED` پیش‌فرض `1` است. با `0` همهٔ این مسیرها `404` می‌دهند.

فایل مدارک زیر `instance/data/consultant_private/` می‌ماند و در پاسخ کلاینت برنمی‌گردد. پاسخ کلاینت شماره، مسیر فایل، یا راز ندارد.

`onboarding_slides_seen` در این stub همیشه `false` است تا مسیر اسلایدها جدا اضافه شود.
