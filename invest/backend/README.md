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

## دسکتاپ

اپ PySide6 همچنان مستقل: `cd invest && python main.py`
