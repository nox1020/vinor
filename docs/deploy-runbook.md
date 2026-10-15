# ران‌بوک دیپلوی وینور

پروداکشن: cPanel + Passenger، مسیر `/home/vinorir/public_html/vinor`، venv در `/home/vinorir/virtualenv/vinor/3.11`. ری‌استارت با `tmp/restart.txt`. `INSTANCE_PATH` همان `<project>/instance` است (در `passenger_wsgi.py`).

سلامت عمومی: `GET https://vinor.ir/healthz` باید **204** باشد.

این سند مقدار هیچ سکرتی را ندارد. خروجی env و کلیدها را در تیکت یا git نگذارید.

## ترتیب مرج

هر مرج به `main` پروداکشن را خودکار دیپلوی می‌کند. سرور همان `scripts/deploy.sh` را اجرا می‌کند که از قبل روی آن دیپلوی شده است، نه نسخه‌ای که فقط روی گیت‌هاب است.

1. **این PR** باید قبل از PR #10 مرج و دیپلوی شود. اسکریپتِ فعلی روی سرور نام کلیدها را از `app/keys.py` و `api_keys.py` می‌خواند. اگر #10 زودتر برسد و آن فایل‌ها حذف شوند، دیپلوی به‌خاطر نبودن `DEEPSEEK_*` یا تنظیمات SMS که پیش‌فرض دارند، به‌اشتباه می‌ایستد.
2. PR کلاینت وب (VAPID و صفحهٔ ورود).
3. **PR #10** (حذف `app/keys.py` و `api_keys.py`) در کم‌ترافیک‌ترین ساعت، فقط وقتی env اجباری روی سرور هست. چرخش کلید پیامک: `SMS_API_KEY` جدید را در env بگذارید، PR #10 را دیپلوی کنید، OTP را تأیید کنید، و فقط بعد کلید قدیمی را در پنل sms.ir باطل کنید. `main` فعلی هنوز `SMS_API_KEY` را از `api_keys.py` می‌خواند.

PR #9 (`6897f1ca`) قبلاً مرج و دیپلوی شده است.

## چرا اولین بار دستی است

وب‌هوک فعلی عملاً دیپلوی نمی‌کند: مرج #2 و #4 به پروداکشن نرسیده‌اند. گیرندهٔ جدید (امضای اجباری، نادیده گرفتن `push`، دیپلوی فقط بعد از موفقیت ورک‌فلو CI) فقط با **همین یک نصب دستی** روی سرور می‌آید. بعد از آن، مرج به `main` با سبز شدن چک `pytest` خودش دیپلوی می‌شود.

## قبل از مرج (اجباری)

PR #9 مرج و دیپلوی شده است. متن زیر سابقهٔ همان قطع هوک است، نه شرط مرج این PR.

ست کردن env قبل از مرج جلوی گیرندهٔ قدیمی را نمی‌گیرد. `/git-webhook` قدیمی سکرت را اول از `app.keys` می‌خواند و `app.keys` آن را از `api_keys.py` می‌گیرد، جایی که خالی است. پس گیرندهٔ قدیمی صرف‌نظر از env همچنان fail-open است و روی `push` می‌تواند `git reset --hard` و `git clean` بزند.

قبل از مرج PR #9، مسعود باید در گیت‌هاب برود به Settings، بعد Webhooks، هوکی که به `vinor.ir/git-webhook` اشاره می‌کند را باز کند، و یا تیک رویداد Pushes را بردارد یا هوک را Inactive کند. اگر چنین هوکی وجود ندارد، به‌جای آن همان را تأیید کند. تا این تأیید نشود مرج ممنوع است.

روشن کردن دوبارهٔ هوک فقط در مرحلهٔ بعد از نصب دستی است: فقط Workflow runs، با همان سکرتی که در env سی‌پنل است.

نسخهٔ شناخته‌شدهٔ `main` هنگام نوشتن این سند: `d1a12fd` (وب `223` در `version.txt`). اولین دیپلوی دستی باید SHA مرج **همین PR** را بگیرد و با آن هر چه تا آن لحظه روی `main` است (از جمله `d1a12fd`) یک‌جا بالا می‌آید. APK جدا و دستی است؛ ورک‌فلو Invest Mobile Build فقط با `workflow_dispatch` اجرا می‌شود.

`https://vinor.ir/invest/api/v1/health` الان `api_version=f05f7ff` می‌دهد. این مهر `VERSION` اینوست است، نه لزوماً `HEAD` وب.

## آنچه سرور الان اجرا می‌کند

در Terminal سی‌پنل:

```bash
cd /home/vinorir/public_html/vinor
git rev-parse HEAD
git branch --show-current
git status --short
git log -1 --oneline
```

`git status --short` و `git diff --stat` را ببینید. اگر فایل trackشده روی سرور عوض شده، قبل از `reset` ذخیره کنید (دستورهای بکاپ پایین). `reset --hard` آن ویرایش‌ها را دور می‌ریزد. `instance/` و آپلودها untracked هستند و چون `git clean` نمی‌زنیم پاک نمی‌شوند، ولی باز هم tar می‌گیریم.

## متغیرهای محیطی

`DATABASE_URL` و همهٔ متغیرهای اجباری باید در env خودِ اپ پایتون باشند (cPanel → Setup Python App → Environment variables). هم پروسهٔ اپ و هم `deploy.sh` که وب‌هوک جدا بالا می‌آورد از همان env به ارث می‌برند. گذاشتن آن‌ها فقط در شل یا فایل `.env` کافی نیست.

`deploy.sh` قبل از هر `git fetch` / `reset` موارد اجباری را غیرخالی می‌خواهد. اگر `DATABASE_URL` با `sqlite:` شروع شود، فقط شکل مطلق `sqlite:////...` قبول است (مسیر بعد از سه اسلش باید با `/` شروع شود). مسیر نسبی رد می‌شود. فایل sqlite هم باید از قبل وجود داشته باشد. لاگ فقط کد دلیل است (`db_url_relative` یا `db_file_missing`) و خود URL یا مسیر را نمی‌نویسد. URL غیر sqlite فقط باید غیرخالی باشد.

`VINOR_DB_CREATE_ALL` نباید در env پروداکشن وجود داشته باشد؛ اگر هر مقدار غیرخالی داشته باشد دیپلوی اجرا نمی‌شود.

`INSTANCE_PATH` را خالی بگذارید یا به پوشهٔ instance فعلی اشاره دهید. اگر `lands.json` یا `users.json` نباشد یا خالی باشد، preflight دیپلوی را رد می‌کند.

بعد از PR #10، `app/utils/secrets.py` با `REQUIRED_ENV_VARS` بدون همان شش متغیر بالا نمی‌آید. نام‌های داخل `app/keys.py` و `api_keys.py` دیگر مبنای preflight نیستند.

اجباری:

- `SECRET_KEY`
- `SMS_API_KEY`
- `VAPID_PRIVATE_KEY`
- `VAPID_PUBLIC_KEY`
- `DATABASE_URL`
- `VINOR_WEBHOOK_SECRET`
- `VINOR_CONSULTANT_API_ENABLED=1`

توصیه‌شده:

- `VINOR_OTP_HMAC_SECRET`

اختیاری (برای این‌ها پیش‌فرض هست، جز `DEEPSEEK_API_KEY` که اگر نباشد هوش مصنوعی از آن مسیر کلید ندارد):

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `SMS_TEMPLATE_ID`
- `SMS_LINE_NUMBER`
- `SMS_RETRIEVER_HASH`
- `VAPID_SUB`

`VINOR_HEALTH_URL` پیش‌فرضش `https://vinor.ir/healthz` است و `VINOR_CI_WORKFLOW_PATH` پیش‌فرضش `.github/workflows/ci.yml`.

`SECRET_KEY` نباید مقدار سخت‌کد `config.py` یا fallback داخل `app/__init__.py` باشد. اسکریپت فقط sha256 آن‌ها را مقایسه می‌کند و خود مقدار را لاگ نمی‌کند. مقدار VAPID را همان کلیدی بگذارید که اپ امروز استفاده می‌کند تا push نشکند؛ متن کلید را اینجا کپی نکنید. چرخش VAPID با PR کلاینت وب است.

عوض کردن `SECRET_KEY` همهٔ نشست‌های فعلی را خارج می‌کند.

## قوانین env اپ روی cPanel

اپ بدون این شش نام بالا نمی‌آید. در Setup Python App این نام‌ها را بگذارید. مقدار را در این سند یا در git ننویسید.

- `SECRET_KEY`
- `SMS_API_KEY`
- `VAPID_PRIVATE_KEY`
- `VAPID_PUBLIC_KEY`
- `DATABASE_URL`
- `VINOR_WEBHOOK_SECRET`

- `DATABASE_URL` باید مسیر sqlite مطلق باشد (`sqlite:////home/...`) و به فایل دیتابیس موجود پروداکشن اشاره کند.
- `VINOR_DB_CREATE_ALL` هرگز در env پروداکشن ست نشود. این فلگ محافظ «فایل دیتابیس نیست» را دور می‌زند.
- `VINOR_OTP_HMAC_SECRET` پیشنهادی است. بدون آن، چرخش `SECRET_KEY` کدهای OTP در جریان را بی‌اعتبار می‌کند.

## اولین دیپلوی دستی

### ۱. بکاپ، بیرون از public_html

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="/home/vinorir/vinor-backups/${STAMP}"
mkdir -p "$DEST"
cd /home/vinorir/public_html/vinor

git rev-parse HEAD | tee "$DEST/running-sha.txt"
git branch --show-current | tee "$DEST/branch.txt"
git status --short | tee "$DEST/status.txt"
git log -1 --oneline | tee "$DEST/log.txt"
git diff --stat | tee "$DEST/tracked-stat.txt"
git diff > "$DEST/tracked-unstaged.diff"
git diff --cached > "$DEST/tracked-staged.diff"

tar -C /home/vinorir/public_html/vinor -czf "$DEST/instance.tgz" instance
if [[ -d app/data/uploads ]]; then
  tar -C /home/vinorir/public_html/vinor -czf "$DEST/uploads-app-data.tgz" app/data/uploads
fi
if [[ -d app/static/uploads ]]; then
  tar -C /home/vinorir/public_html/vinor -czf "$DEST/uploads-static.tgz" app/static/uploads
fi
find instance -name '*.db' -exec cp -a {} "$DEST/" \;
```

`instance.tgz` خودِ `instance/data/push_subs.json`، لاگ و sqlite داخل instance را دارد. اگر `DATABASE_URL` به فایل دیگری اشاره دارد، همان فایل را هم در `$DEST` کپی کنید. این tarها را داخل `public_html` نگذارید.

SHA داخل `$DEST/running-sha.txt` هدف رول‌بک این نصب دستی است.

### ۲. env

```bash
openssl rand -hex 32
```

یک بار برای `VINOR_WEBHOOK_SECRET`، یک بار جدا برای `SECRET_KEY`. در Setup Python App ذخیره کنید، بعد Restart تا پروسه env جدید را ببیند.

`DATABASE_URL` باید همان فایل دیتابیس فعلی باشد تا داده نپرد. اگر این نام خالی باشد اپ بالا نمی‌آید و به sqlite خالی داخل instance سقوط نمی‌کند:

```bash
ls -lh /home/vinorir/public_html/vinor/instance/*.db
```

برای فایل مطلق، چهار اسلش:

```text
DATABASE_URL=sqlite:////home/vinorir/public_html/vinor/instance/vinor.db
```

مسیر را با فایل واقعی عوض کنید اگر اسمش این نیست. بقیهٔ کلیدها (`SMS_*`، `DEEPSEEK_*`، VAPID) را از مقدار فعلی روی سرور به env ببرید، نه به این سند.

### ۳. fetch و checkout، بدون git clean

`<MERGE_SHA>` را بعد از مرج این PR از GitHub بگذارید (SHA مرج روی `main`، نه SHA برنچ).

```bash
cd /home/vinorir/public_html/vinor
git fetch origin main
git log -1 --oneline origin/main
MERGE_SHA="<MERGE_SHA>"
git merge-base --is-ancestor "$MERGE_SHA" origin/main
git reset --hard "$MERGE_SHA"
test -d instance
test -f instance/data/push_subs.json
test -d app/data/uploads
test -d app/static/uploads
```

این‌ها را نزنید: `git clean`، `rsync --delete`.

### ۴. pip و دیتابیس

```bash
/home/vinorir/virtualenv/vinor/3.11/bin/python -m pip install -r /home/vinorir/public_html/vinor/requirements.txt
```

مهاجرت جدا لازم نیست. Flask-Migrate و Alembic در این ریپو نیست و `scripts/deploy.sh` دستور migrate ندارد.

- sqlite: اگر فایل مطلق نباشد اپ بالا نمی‌آید، مگر `VINOR_DB_CREATE_ALL=1` که این محافظ را دور می‌زند. این فلگ را در env پروداکشن ست نکنید. دیتابیس موجود دوباره ساخته یا پاک نمی‌شود. دیپلوی نیز در صورت مقدار غیرخالی این متغیر متوقف می‌شود.
- `init_schema()` مربوط به OTP موقع بالا آمدن، جدول غایب را می‌سازد.
- `migrate_legacy` یک‌بار فایل قدیمی `data/` را به instance کپی می‌کند اگر مارکر نباشد؛ فایل موجود را بازنویسی نمی‌کند.
- اینوست مهاجرت غیرمخرب خودش را در `invest/invest_app/database/migrations.py` موقع استارت همان سرویس اعمال می‌کند، نه به‌صورت دستور دیپلوی.

### ۵. ری‌استارت و سلامت

دکمهٔ Restart در Setup Python App، یا:

```bash
mkdir -p /home/vinorir/public_html/vinor/tmp
touch /home/vinorir/public_html/vinor/tmp/restart.txt
curl -sI https://vinor.ir/healthz | head -n 1
```

خط اول باید 204 باشد (`HTTP/2 204`). اگر نبود، به مرحلهٔ رول‌بک بروید.

### ۶. رول‌بک همین نصب

فقط اگر سلامت خراب شد یا داده آسیب دید. اول کد؛ بازگرداندن tar فقط اگر داده خراب شده.

```bash
cd /home/vinorir/public_html/vinor
ROLLBACK_SHA="$(cat /home/vinorir/vinor-backups/${STAMP}/running-sha.txt)"
git reset --hard "$ROLLBACK_SHA"
/home/vinorir/virtualenv/vinor/3.11/bin/python -m pip install -r requirements.txt
touch tmp/restart.txt
curl -sI https://vinor.ir/healthz | head -n 1
```

بازگرداندن بکاپ، فقط در صورت آسیب داده:

```bash
cd /home/vinorir/public_html/vinor
tar -xzf "/home/vinorir/vinor-backups/${STAMP}/instance.tgz"
tar -xzf "/home/vinorir/vinor-backups/${STAMP}/uploads-app-data.tgz"
tar -xzf "/home/vinorir/vinor-backups/${STAMP}/uploads-static.tgz"
```

## وب‌هوک گیت‌هاب، بعد از سلامت سبز

روشن کردن دوباره فقط همین‌جاست، بعد از نصب دستی و 204 شدن `/healthz`. تا این لحظه هوک Inactive است یا Pushes ندارد. گیرندهٔ جدید روی سرور است؛ هوک را فعال کنید و رویداد دیگری جز Workflow runs نگذارید.

- Payload URL: `https://vinor.ir/git-webhook`
- Content type: `application/json`
- Secret: همان `VINOR_WEBHOOK_SECRET` در env سی‌پنل
- رویدادها: فقط **Workflow runs**. Pushes خاموش می‌ماند.

Ping با امضای درست باید 200 و `pong` بدهد. بدون سکرت یا با امضای غلط درخواست رد می‌شود و دیپلوی نمی‌شود. `push` خام با امضای درست 200 و `ignored` است و دیپلوی نمی‌کند.

بعدی: مرج به `main` باید ورک‌فلو CI (`.github/workflows/ci.yml`) را سبز کند. آن‌وقت گیت‌هاب `workflow_run` با `action=completed`، `conclusion=success`، `event=push`، `head_branch=main` می‌فرستد. وب‌هوک `scripts/deploy.sh <head_sha>` را در نشست جدا بالا می‌آورد و فوراً **202** می‌دهد. بدنهٔ پاسخ خروجی دستور، مسیر یا سکرت ندارد.

محافظت برنچ `main`: بعد از مرج این PR چک `pytest` را الزامی کنید.

## دیپلوی خودکار و رول‌بک

`scripts/deploy.sh` قفل `flock` می‌گیرد، HEAD فعلی را در `instance/deploy/previous_sha` می‌نویسد، `git fetch` می‌کند، SHA را با `git merge-base --is-ancestor` روی `origin/main` چک می‌کند، بعد `git reset --hard`. `git clean` ندارد. بعد از reset اگر `instance/`، `instance/data/push_subs.json`، `app/data/uploads/` یا `app/static/uploads/` که قبلش بودند گم شده باشند، شکست می‌خورد.

سپس `pip install -r requirements.txt` در venv، `touch tmp/restart.txt`، و چند بار `VINOR_HEALTH_URL` را برای 204 صدا می‌زند. اگر اپ بالا نیاید (مثلاً env کم باشد) سلامت 204 نیست، پس به SHA قبلی برمی‌گردد: reset، pip، ری‌استارت، سلامت دوباره. نتیجه در لاگ است.

دستی، روی سرور:

```bash
cd /home/vinorir/public_html/vinor
bash scripts/deploy.sh --rollback
bash scripts/deploy.sh <40-hex-sha>
```

`--rollback` همان `instance/deploy/previous_sha` است. SHA صریح باید روی `origin/main` باشد.

لاگ JSON بدون سکرت: `instance/logs/deploy.log`. اگر وب‌سرور محتوای `instance/` را سرو می‌کند، HTTP به `instance/logs` و `instance/*.db` را ببندید.

انتشار APK دستی می‌ماند.

## کارهای بعدی

- انجام شد: `_resolve_secret` فقط `VINOR_WEBHOOK_SECRET` را از env می‌خواند.
- بعد از مرج، چک `pytest` را در branch protection شاخهٔ `main` اجباری کنید.
- PR #10 فایل‌های کلید و fallback ‏`app.keys` را برمی‌دارد. این PR باید قبل از آن روی سرور باشد.

## نسخهٔ در حال اجرا

`GET /version` بدون ورود است و JSON با `Cache-Control: no-store` می‌دهد. `sha` هفت کاراکتر اول کامیت است؛ `full_sha` فقط وقتی SHA بلندتر از ۷ باشد می‌آید. `version` تعداد کامیت‌های `HEAD` است (`git rev-list --count HEAD`) و روی کلون کامل با هر کامیت جدید بالا می‌رود. اگر git این شمارش را ندهد، همان یک خط `version.txt` است. فایل‌های استاتیک همچنان با mtime کش‌باست می‌شوند؛ نسخهٔ APK از تنظیمات ادمین است و این عدد را نمی‌خواند.

SHA به این ترتیب خوانده می‌شود و اگر mtime فایل `current_sha` عوض شود دوباره خوانده می‌شود: `instance/deploy/current_sha` (۷ تا ۴۰ رقم hex)، بعد `VINOR_DEPLOYED_SHA`، بعد `.git` (HEAD / refs / packed-refs)، وگرنه `unknown`.

```bash
curl -s https://vinor.ir/version
git rev-parse --short=7 origin/main
```

`sha` باید با خروجی git یکی باشد. `GET /healthz` همچنان 204 بدون بدنه است.

<!-- deploy trigger 2026-10-15i -->
