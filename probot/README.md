# 1probot داخل وینور

ربات نردبان دیوار روی **بله** (python-telegram-bot 20.7 روی `tapi.bale.ai`) که حالا بخشی از بک‌اند وینور است.

## ساختار

| فایل | کار |
|---|---|
| `bot.py` | ربات بله، polling، زمان‌بندی نردبان (APScheduler) |
| `worker.py` | اجرای فرمان‌های صف‌شدهٔ پنل وب (جدول `web_commands`) |
| `web_app.py` | پنل وب به‌صورت Blueprint زیر `https://vinor.ir/probot/` |
| `dapi.py` | API دیوار و رلهٔ پرداخت |
| `curds.py` | دیتابیس SQLite (`bot.db`) |
| `tokens_manager.py` | `tokens.json` |
| `loadConfig.py`، `paths.py` | تنظیمات: پیش‌فرض‌ها ← `configs.json` ← env |
| `runner.py`، `run.py` | اجرای تک‌نمونه: `python -m probot.run` |
| `configs.json.example` | نمونهٔ تنظیمات، بدون مقدار واقعی |
| `configs.json` | پیش‌فرض داخل بسته؛ فقط وقتی فایل پوشهٔ داده نباشد خوانده می‌شود |

پیش‌فرض `probot/configs.json` (توکن بله، شناسهٔ ادمین، رمز پنل) در گیت است تا ربات روی سرور بدون تنظیم دستی بالا بیاید. `bot.db`، `tokens.json`، لاگ‌ها و نشست‌های دیوار در گیت نیستند و فقط در پوشهٔ داده می‌مانند.

## پوشهٔ داده (خارج از گیت)

رونوشت قابل‌نوشتن `configs.json`، به‌علاوهٔ `bot.db`، `tokens.json`، `web_message_logs.json`، `bale_status.json`، `logs/` و فایل‌های قفل اینجا هستند:

- اگر `PROBOT_DATA_DIR` تنظیم شده باشد، همان مسیر؛
- وگرنه `$INSTANCE_PATH/probot`. روی سرور این می‌شود `/home/vinorir/public_html/vinor/instance/probot`.

deploy به پوشهٔ `instance` دست نمی‌زند و این پوشه gitignore شده است.

## تنظیمات

env بر `configs.json` اولویت دارد:

| env | کلید در configs.json |
|---|---|
| `PROBOT_BALE_TOKEN` | `token` |
| `PROBOT_ADMIN_ID` | `admin` |
| `PROBOT_WEB_PASSWORD` | `web_password` |
| `PROBOT_DIVAR_RELAY_URL` / `PROBOT_DIVAR_RELAY_SECRET` | `divar_relay_url` / `divar_relay_secret` |
| `PROBOT_DATA_DIR` | — |
| `PROBOT_ENABLED=0` | خاموش کردن کامل ربات |
| `PROBOT_AUTOSTART=0` | خاموش کردن روشن‌شدن خودکار از وب |
| `PROBOT_PYTHON` | مسیر پایتون venv (پیش‌فرض `VINOR_VENV_PYTHON` یا خود venv) |

ساعت‌ها و روزهای فعال را خود ربات و پنل در `configs.json` همان پوشهٔ داده ذخیره می‌کنند.

اگر فایل پوشهٔ داده نباشد، پیش‌فرض `probot/configs.json` خوانده می‌شود و ربات با همان بالا می‌آید. نوشتن ساعت‌ها و روزها همیشه روی فایل پوشهٔ داده است تا deploy درخت بسته را عوض کند ولی تنظیمات زمان اجرا از بین نرود. env همچنان بر هر دو فایل اولویت دارد.

اگر توکن و ادمین موجود نباشند (یا `PROBOT_ENABLED=0` باشد)، ربات خاموش است و `/probot` صفحهٔ «فعال نشده» (کد 503) نشان می‌دهد؛ وینور خودش اثری نمی‌بیند.

## اجرا

```bash
python -m probot.run            # اجرا در پیش‌زمینه
python -m probot.run ensure     # اگر بالا نیست، در پس‌زمینه بالا بیاور
python -m probot.run restart
python -m probot.run stop
python -m probot.run status     # JSON: configured / running / bale_state
```

- قفل `flock` روی `instance/probot/.run.flock` نمی‌گذارد بیش از یک polling اجرا شود. بله برای polling دوم Conflict می‌دهد.
- worker را خود ربات اجرا می‌کند. اگر ربات بمیرد، worker هم خارج می‌شود.
- polling هیچ‌وقت داخل ورکرهای Passenger اجرا نمی‌شود.

### روشن ماندن خودکار

1. **از وب:** هر ورکر وینور حداکثر هر ۶۰ ثانیه یک بار بررسی می‌کند که ربات بالاست یا نه. اگر تنظیم شده باشد و بالا نباشد، یک پروسهٔ جدا (detached) اجرا می‌کند. این همان روشی است که `/git-webhook` با آن deploy را اجرا می‌کند.
2. **بعد از deploy:** `scripts/deploy.sh` بعد از سالم شدن سایت ربات را restart می‌کند تا کد جدید اجرا شود. شکست این مرحله deploy را خراب نمی‌کند.
3. **cron (پیشنهادی، برای اطمینان):** در cPanel → Cron Jobs، هر ۵ دقیقه:

   ```
   */5 * * * * /bin/bash /home/vinorir/public_html/vinor/scripts/probot_cron.sh >/dev/null 2>&1
   ```

   cron متغیرهای env اپ پایتون cPanel را ندارد. اگر از cron استفاده می‌کنید، توکن و ادمین را در `instance/probot/configs.json` بگذارید.

## راه‌اندازی روی سرور (یک بار)

1. پیش‌فرض بسته‌شده کافی است تا ربات بالا بیاید. در صورت نیاز همچنان می‌توانید:
   - cPanel → Setup Python App → اپ vinor → Environment variables: `PROBOT_BALE_TOKEN` و `PROBOT_ADMIN_ID` را بگذارید و Restart بزنید (env برنده است)، یا
   - `configs.json` را در `/home/vinorir/public_html/vinor/instance/probot/` بگذارید (این فایل بر پیش‌فرض بسته اولویت دارد).
2. **انتقال داده از هاست قبلی (اختیاری):** `bot.db` و `tokens.json` را در همان پوشه کپی کنید. این کار باید وقتی انجام شود که ربات قبلی متوقف شده است.
3. **ربات قبلی را خاموش کنید.** دو نمونه با یک توکن Conflict می‌دهند.
4. یک بار `https://vinor.ir/probot/` را باز کنید. ربات ظرف یک دقیقه بالا می‌آید. وضعیت «ربات بله» در پنل دیده می‌شود.
5. (اختیاری) cron بالا را اضافه کنید.

## پنل وب

- آدرس: `https://vinor.ir/probot/`
- ورود با شمارهٔ دیوار ثبت‌شده در ربات و رمز پنلی که ربات می‌فرستد.
- کلیدهای session با پیشوند `probot_` جدا هستند و ورود و خروج پنل روی ورود وینور اثری ندارد.
- فرم‌ها توکن CSRF وینور دارند.
- فقط `/probot/divar-relay` که ماشین‌به‌ماشین است و با `X-Relay-Secret` محافظت می‌شود، از CSRF معاف است.
