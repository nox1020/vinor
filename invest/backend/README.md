# Invest Backend (Vinor)

بک‌اند REST اپ **V+ Invest** داخل وینور — جدا از هستهٔ اصلی.

## مسیرها

- **OTP:** همان `/auth/request-otp` و `/auth/verify-otp` (session کوکی `vinor_session`)
- **API:** `/invest/api/v1/*`

## داده

- DB هر کاربر: `instance/invest/users/{phone}/invest.db`
- پروفایل: `instance/invest/profiles/{phone}.json`
- همگام با `users.json` وینور (نام، ثبت‌نام)

## فلگ

- `VINOR_INVEST_ENABLED=1` (پیش‌فرض روشن)

## نمونه

```http
POST /auth/request-otp  {"phone":"09101234567"}
POST /auth/verify-otp   {"phone":"09101234567","code":"12345"}
GET  /invest/api/v1/me
GET  /invest/api/v1/dashboard
```

## نسخه API

- فایل `invest/backend/VERSION` — با هر push به `invest/**` در CI به SHA کوتاه commit به‌روز می‌شود
- `GET /invest/api/v1/health` و `/app-version` → `api_version`
- اپ Flutter با تغییر `api_version` داده را خودکار refresh می‌کند

## CI → اپ موبایل

Push به `main` با تغییر `invest/**` workflow **Invest Mobile Build** را اجرا می‌کند:

1. `VERSION` را stamp می‌کند
2. `repository_dispatch` به [nox1020/invest](https://github.com/nox1020/invest) می‌فرستد → build APK

**Secret لازم در repo وینور:** `INVEST_REPO_DISPATCH_TOKEN` (PAT با scope `repo` روی invest)

## دسکتاپ

اپ PySide6 همچنان مستقل: `cd invest && python main.py`
