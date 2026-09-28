# آنبوردینگ مشاور — stub فاز ۱

مسیر واحد اندروید و وب: `/api/consultant/*`

نقش API برابر `consultant` است. برچسب UI «بازاریاب وینور» روی **همان رکورد Express Partner** نگاشت می‌شود (`api_role` و `consultant_onboarding`). سیستم apply دوم ساخته نشده است. تخصیص لید خارج از این stub است.

احراز هویت همان نشست همکار است (کوکی `vinor_session` بعد از OTP موجود). بدون نشست: `401`. نوشتن‌های آنبوردینگ کلاینت از CSRF معاف‌اند تا WebView و APK با همان کوکی صدا بزنند. جزئیات در بخش CSRF است.

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

بررسی ادمین واقعی وصل نیست. شبیه‌سازی وضعیت تأیید **پیش‌فرض خاموش** است.

`VINOR_CONSULTANT_DRY_RUN` پیش‌فرض `0` است. فقط با مقدار صریح `1` (یا `true` / `yes` / `on`) روشن می‌شود. در حالت خاموش، نشست همکار نمی‌تواند وضعیت بررسی را با هیچ‌کدام از راه‌های زیر بنویسد یا روی خواندن ببیند.

1. `POST /api/consultant/simulate` با `{ "status": "approved" }` یا `"rejected"` یا `"pending"`. برای رد، `reject_reason` فارسی اختیاری است. پاسخ همان شکل `GET /status` است و روی رکورد نوشته می‌شود. این مسیر از CSRF معاف نیست.
2. `GET /api/consultant/status?simulate=approved` (یا هدر `X-Vinor-Consultant-Simulate`) همان نوشتن را انجام می‌دهد، فقط اگر dry-run روشن باشد یا نشست ادمین باشد. در غیر این صورت پارامتر نادیده گرفته می‌شود و پاسخ، وضعیت ذخیره‌شده است (بدون نوشتن).
3. متغیر محیطی `VINOR_CONSULTANT_SIMULATE=approved|rejected|pending` نتیجهٔ خواندن را عوض می‌کند و روی دیسک به‌عنوان تأیید دائمی ذخیره نمی‌شود. این پوشش فقط وقتی dry-run روشن است اعمال می‌شود. در پیش‌فرض `0` نادیده گرفته می‌شود، حتی اگر متغیر ست شده باشد.

راه‌های ۱ و ۲ برای نشست همکار فقط با `VINOR_CONSULTANT_DRY_RUN=1` باز هستند. نشست ادمین (`logged_in` به‌همراه `admin_phone`، بعد از OTP ادمین) حتی وقتی dry-run خاموش است می‌تواند شبیه‌سازی کند. نشست همکار این دو کلید را ندارد. ادمین می‌تواند در بدنهٔ `POST /simulate` فیلد `phone` بگذارد و رکورد همان همکار را هدف بگیرد؛ همکار نمی‌تواند شمارهٔ کس دیگری را بفرستد.

`VINOR_CONSULTANT_API_ENABLED` پیش‌فرض `1` است. با `0` همهٔ این مسیرها `404` می‌دهند.

## CSRF

همهٔ مسیرها نشست می‌خواهند. معافیت CSRF فقط برای نوشتن‌هایی است که APK و WebView بدون توکن CSRF، با کوکی نشست، صدا می‌زنند و وضعیت بررسی را به تأیید تغییر نمی‌دهند.

| مسیر | CSRF | چرا |
|------|------|-----|
| POST `/api/consultant/apply` | معاف | ثبت درخواست از APK/WebView؛ وضعیت را approved نمی‌کند |
| PATCH `/api/consultant/profile` | معاف | همان کلاینت؛ فقط پروفایل |
| POST `/api/consultant/documents` | معاف | multipart همان کلاینت؛ حداکثر وضعیت را `pending` می‌گذارد |
| POST `/api/consultant/availability` | معاف | فقط بعد از تأیید واقعی؛ آنلاین/آفلاین |
| GET `/api/consultant/cities` | لازم نیست (متد امن) | فقط فهرست شهر |
| GET `/api/consultant/status` | لازم نیست (متد امن) | خواندن. `simulate` و هدر `X-Vinor-Consultant-Simulate` فقط با dry-run یا نشست ادمین می‌نویسند |
| POST `/api/consultant/simulate` | **معاف نیست** | وضعیت بررسی را می‌نویسد. علاوه بر نشست (dry-run یا ادمین) توکن CSRF لازم است (`X-CSRFToken` یا فیلد `csrf_token`) |

درخواست نوشتنِ بدون توکن به `/simulate` وضعیت را عوض نمی‌کند و `400` با `error=csrf_expired` برمی‌گرداند. اگر توکن معتبر باشد ولی dry-run خاموش است و نشست ادمین نیست، پاسخ `404` است و باز هم چیزی نوشته نمی‌شود. نشست همکار حتی با توکن CSRF نمی‌تواند وضعیت بررسی را بنویسد.

فایل مدارک زیر `instance/data/consultant_private/` می‌ماند و در پاسخ کلاینت برنمی‌گردد. پاسخ کلاینت شماره، مسیر فایل، یا راز ندارد.

`onboarding_slides_seen` در این stub همیشه `false` است تا مسیر اسلایدها جدا اضافه شود.
