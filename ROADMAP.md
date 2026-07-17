# Vinor OS — ROADMAP

**معماری:** تبدیل Vinor از Partner Management Platform به Real Estate Operating System  
**تاریخ به‌روزرسانی:** ۱۴۰۵/۰۴/۲۶  
**وضعیت فاز ۰:** تکمیل‌شده (Additive · Backward Compatible)  
**وضعیت فاز ۱:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۲:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۳:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۴:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۵:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۶:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)  
**وضعیت فاز ۷:** تکمیل‌شده (Additive · Backward Compatible · flags default ON)

---

## هدف طلایی (North Star)

> **همه تصمیمات محصول، فازها، AI، Workflow، UI و اولویت‌بندی فقط حول این محور است:**

### ۱) فروش و افزایش فروش
هر قابلیت باید مستقیم یا غیرمستقیم به بسته‌شدن معامله کمک کند.

### ۲) بالا بردن نرخ تبدیل قیف
```
بازدیدکننده / لید  →  تماس  →  بازدید  →  پیشنهاد  →  قرارداد  →  معامله
```
هر مرحله باید اصطکاک کمتر و تبدیل بالاتر داشته باشد.

### ۳) افزایش تماس برای بازدید با شماره ثابت فروش
**شماره هدف تماس بازدید:** `09121471301`

معیار نهایی موفقیت سیستم:
- بیشتر شدن تعداد تماس‌های واقعی برای هماهنگی بازدید روی این شماره
- بیشتر شدن بازدیدهای انجام‌شده
- بیشتر شدن معاملات بسته‌شده و درآمد/پورسانت مرتبط

### قانون تصمیم‌گیری
قبل از پذیرش هر فیچر / فاز / تغییر، این سه سؤال باید «بله» باشد:

1. آیا فروش یا نرخ تبدیل را افزایش می‌دهد؟
2. آیا مسیر تا بازدید (و تماس `09121471301`) را کوتاه‌تر یا پرتر می‌کند؟
3. آیا بدون شکستن قیف فعلی همکار قابل اضافه‌شدن است؟

اگر جواب هر کدام منفی است، آن کار اولویت ندارد یا در این Roadmap جایی ندارد.

### KPIهای راهنما (برای سنجش فازها)
| KPI | معنی |
|-----|------|
| Visit Call Rate | سهم لیدهایی که به تماس برای بازدید روی `09121471301` می‌رسند |
| Visit Booking Rate | سهم تماس‌هایی که به بازدید ثبت‌شده تبدیل می‌شوند |
| Visit→Deal Rate | سهم بازدیدهای تکمیل‌شده که به درخواست معامله می‌رسند |
| Deal Close Rate | سهم معاملات تأیید/فروخته‌شده |
| Sales Volume | تعداد و مبلغ معاملات نهایی |

---

## قانون طلایی اجرا (فنی)

1. در هر نوبت **فقط یک فاز** اجرا شود.
2. هیچ قابلیت فعلی حذف یا بازنویسی نشود (فقط Additive).
3. Backward Compatibility باید ۱۰۰٪ حفظ شود.
4. Feature Flagهای قابلیت جدید به‌صورت پیش‌فرض **خاموش** باشند.
5. قبل از رفتن به فاز بعد، تست رگرسیون مسیرهای فعلی اجباری است:
   - Guest / User / Partner / Special Partner
   - Visit → Deal → Commission → Withdrawal
   - AI Chat / Workflow Engine / Conversation Engine
6. اگر تغییری مسیر فعلی را بشکند، آن تغییر انجام نشود.
7. اگر قابلیتی با هدف طلایی (فروش / تبدیل / تماس بازدید) هم‌راستا نباشد، وارد اسپرینت نشود.

---

## قیف هدف سیستم (در خدمت فروش)

```
Lead → Contact → Call(09121471301) → Visit → Offer → Contract
  → Deal / Commission → Withdrawal → Settlement
                  ▲
                  └── هدف عملیاتی: افزایش این تماس‌ها و تبدیل‌شان به بازدید و فروش
```

| بخش قیف | وضعیت فعلی |
|---------|------------|
| Lead / Contact / Call / Follow-up | موجود (فاز ۱ ✅) |
| Visit | موجود + Result/No-Show (فاز ۲ ✅) |
| Offer / Counter / Reservation | موجود (فاز ۳ ✅) |
| Contract / Payment | موجود (فاز ۴ ✅) |
| Deal / Commission / Withdrawal | موجود (Deal adapter فاز ۴ ✅؛ commissions/withdrawals حفظ) |
| Settlement چندطرفه | موجود (فاز ۴ ✅؛ withdrawal لینک اختیاری) |

---

## فازها (به ترتیب اجباری)

### فاز ۰ — Foundation ✅ انجام شد

**محدوده**
- Foundation Layer
- Activity Entity + Append-only Activity Store
- Timeline Entity + Timeline Store
- Workflow Commit Adapter
- Adapter بین Workflow Engine و Storage فعلی (shadow)
- Feature Flags

**مسیر کد**
- `app/foundation/`
- Hook اختیاری در `app/conversation/manager.py`
- تست: `tests/test_foundation_phase0.py`

**فلگ‌ها (پیش‌فرض OFF)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_FOUNDATION_ENABLED` | `0` | کلید اصلی |
| `VINOR_ACTIVITY_STORE_ENABLED` | `1` اگر Foundation روشن باشد | Activity |
| `VINOR_TIMELINE_STORE_ENABLED` | `1` اگر Foundation روشن باشد | Timeline |
| `VINOR_WORKFLOW_COMMIT_ENABLED` | `0` | ثبت commit روی complete |
| `VINOR_WORKFLOW_COMMIT_PERSIST` | `0` | نوشتن به JSON کسب‌وکار (در فاز ۰ حتی روشن هم shadow) |

**خروجی داده**
- `instance/data/foundation_activities.json`
- `instance/data/foundation_timeline.json`

---

### فاز ۱ — CRM سبک ✅ انجام شد

**هم‌راستا با هدف طلایی**
- ثبت و پیگیری لید/تماس تا تبدیل به بازدید
- کاهش از‌دست‌رفتن مشتری بین اولین تماس و ثبت بازدید
- آماده‌سازی مسیر اندازه‌گیری تماس به `09121471301`

**محدوده**
- Entity: Lead, Contact, Call Log, Follow-up, Task
- همگام‌سازی Contact از `customer_*` روی Visit (بدون شکستن Visit)
- UI همکار: مشتریان من + ثبت تماس / پیگیری
- AI tools جدید (کنار tools فعلی): `propose_log_call`, `propose_followup`
- اتصال رویدادهای CRM به Activity / Timeline
- فلگ‌های جدا برای CRM (پیش‌فرض OFF)

**مسیر کد**
- `app/crm/`
- Hook در `app/express_partner/routes.py` و `app/ai/agent_tools.py` (visit sync)
- UI: `/customers` + لینک تنظیمات (پشت `VINOR_CRM_UI_ENABLED`)
- تست: `tests/test_crm_phase1.py`

**فلگ‌ها (پیش‌فرض OFF)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_CRM_ENABLED` | `0` | کلید اصلی |
| `VINOR_CRM_UI_ENABLED` | `1` اگر CRM روشن باشد | صفحه مشتریان |
| `VINOR_CRM_AI_TOOLS_ENABLED` | `0` | propose_log_call / propose_followup |
| `VINOR_CRM_VISIT_SYNC_ENABLED` | `1` اگر CRM روشن باشد | Visit → Contact |
| `VINOR_CRM_ACTIVITY_HOOK_ENABLED` | `1` اگر CRM روشن باشد | Activity/Timeline |

**خروجی داده**
- `instance/data/crm_contacts.json`
- `instance/data/crm_leads.json`
- `instance/data/crm_call_logs.json`
- `instance/data/crm_followups.json`
- `instance/data/crm_tasks.json`

**قانون ایمنی**
- Visit / Deal / Commission / Withdrawal دست‌نخورده بمانند.

**معیار اتمام**
- CRUD/ذخیره CRM کار کند ✅
- رگرسیون قیف فعلی سبز باشد ✅
- AI tools جدید فقط با confirm و پشت فلگ ✅
- مسیر ثبت تماس/پیگیری به سمت بازدید روشن باشد ✅

---

### فاز ۲ — Visit کامل ✅ انجام شد

**محدوده**
- Visit Result
- No-Show (status جدید؛ statusهای قدیمی حفظ شوند)
- گسترش `tx_mode` و progress steps با شاخه‌های جدید
- Admin / Special inbox برای نتیجه بازدید
- AI: ثبت نتیجه بازدید / no-show با کارت تأیید

**مسیر کد**
- `app/visit_result/`
- Status bridge در `app/express_partner/visit_requests.py` (`NO_SHOW_STATUS`, `mark_visit_no_show`, `tx_mode=visit_no_show`)
- Special inbox + Admin filter/status (پشت UI flag)
- AI: `propose_visit_result` / `propose_no_show`
- تست: `tests/test_visit_result_phase2.py`

**فلگ‌ها (پیش‌فرض OFF)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_VISIT_RESULT_ENABLED` | `0` | کلید اصلی |
| `VINOR_VISIT_RESULT_UI_ENABLED` | `1` اگر master روشن | Admin/Special result actions |
| `VINOR_VISIT_RESULT_AI_TOOLS_ENABLED` | `0` | propose_visit_result / propose_no_show |
| `VINOR_VISIT_NO_SHOW_STATUS_ENABLED` | `1` اگر master روشن | نوشتن status=no_show |
| `VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED` | `1` اگر master روشن | Activity/Timeline |

**خروجی داده**
- `instance/data/visit_results.json`

**قانون ایمنی**
- `pending` / `approved` / `done_pending` / `completed` / `cancelled` حذف نشوند.
- Commission فقط روی `completed` — هرگز روی `no_show`.

---

### فاز ۳ — Commercial ✅ انجام شد

**محدوده**
- Negotiation (entity کسب‌وکار)
- Offer / Counter Offer
- Reservation
- اتصال Intent مذاکره به workflow واقعی
- UI Partner + Special Owner برای پیشنهاد/پاسخ
- Buyer portal حداقلی (یا User با نقش buyer)

**مسیر کد**
- `app/commercial/`
- Visit bridge از VisitResult `interested`
- Partner: `/negotiations` · Special: `/inbox-offers` · Buyer: `/my/offers`
- Workflow: `OfferWorkflow` (فلگ جدا)
- AI: `propose_offer` / `propose_counter_offer` / `propose_reservation`
- تست: `tests/test_commercial_phase3.py`

**فلگ‌ها (پیش‌فرض OFF)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_COMMERCIAL_ENABLED` | `0` | کلید اصلی |
| `VINOR_COMMERCIAL_UI_ENABLED` | `1` اگر master روشن | Partner + Special UI |
| `VINOR_COMMERCIAL_BUYER_UI_ENABLED` | `0` | `/my/offers` |
| `VINOR_COMMERCIAL_AI_TOOLS_ENABLED` | `0` | propose tools |
| `VINOR_COMMERCIAL_ACTIVITY_HOOK_ENABLED` | `1` اگر master روشن | Activity/Timeline |
| `VINOR_COMMERCIAL_WORKFLOW_ENABLED` | `0` | Offer form workflow |
| `VINOR_COMMERCIAL_VISIT_BRIDGE_ENABLED` | `1` اگر master روشن | interested → Negotiation |

**خروجی داده**
- `instance/data/commercial_negotiations.json`
- `instance/data/commercial_offers.json`
- `instance/data/commercial_counters.json`
- `instance/data/commercial_reservations.json`

**قانون ایمنی**
- `mark-in-transaction` و commission deal تا فاز ۴ مسیر بستن معامله بمانند.
- Reservation فقط soft hold است (بدون قفل assignment).

---

### فاز ۴ — Closing & Finance ✅ انجام شد

**محدوده**
- Deal Entity مستقل (با adapter روی assignment + commission فعلی)
- Contract + Document lifecycle
- Payment milestones
- Settlement چندطرفه
- Withdrawal فعلی زیرمجموعه Settlement همکار بماند

**مسیر کد**
- `app/closing/`
- Deal bridge از `mark_in_transaction` / commission approve|reject
- Reservation `converted` → لینک Deal (بدون mark-in-tx)
- Partner: `/deals` + لینک settings
- AI: `propose_contract` / `propose_payment_milestone` / `propose_settlement`
- تست: `tests/test_closing_phase4.py`

**فلگ‌ها (پیش‌فرض ON)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_CLOSING_ENABLED` | `1` | کلید اصلی |
| `VINOR_CLOSING_UI_ENABLED` | `1` اگر master روشن | Partner `/deals` |
| `VINOR_CLOSING_AI_TOOLS_ENABLED` | `1` | propose tools |
| `VINOR_CLOSING_ACTIVITY_HOOK_ENABLED` | `1` | Activity/Timeline |
| `VINOR_CLOSING_DEAL_BRIDGE_ENABLED` | `1` | sync از commission |
| `VINOR_CLOSING_RESERVATION_BRIDGE_ENABLED` | `1` | لینک reservation |

**خروجی داده**
- `instance/data/closing_deals.json`
- `instance/data/closing_contracts.json`
- `instance/data/closing_payments.json`
- `instance/data/closing_settlements.json`

**قانون ایمنی**
- صفحات و statusهای commissions/withdrawals deprecate نشدند.
- `propose_deal` / `mark_in_transaction` مسیر بستن معامله باقی ماند.

---

### فاز ۵ — Roles & Portals ✅ انجام شد

**محدوده**
- نقش‌های Buyer / Owner / Seller / Super Admin (علاوه بر guest/user/partner/premium)
- پنل‌های نقش‌محور جدید
- Owner می‌تواند special partner فعلی را شامل شود (بدون اجبار مهاجرت)

**مسیر کد**
- `app/roles/`
- Resolve موازی با conversation ROLE_* (دست‌نخورده)
- Portals: `/my` · `/portal/seller` · `/portal/owner`
- Super Admin: `/admin/super-admin` + badge داشبورد
- تست: `tests/test_roles_phase5.py`

**فلگ‌ها (پیش‌فرض ON)**
| Flag | پیش‌فرض | نقش |
|------|---------|-----|
| `VINOR_ROLES_ENABLED` | `1` | کلید اصلی |
| `VINOR_ROLES_UI_ENABLED` | `1` | portal hubs |
| `VINOR_ROLES_BUYER_PORTAL_ENABLED` | `1` | `/my` |
| `VINOR_ROLES_OWNER_PORTAL_ENABLED` | `1` | `/portal/owner` |
| `VINOR_ROLES_SELLER_PORTAL_ENABLED` | `1` | `/portal/seller` |
| `VINOR_ROLES_SUPER_ADMIN_ENABLED` | `1` | Super Admin gate |
| `VINOR_ROLES_ACTIVITY_HOOK_ENABLED` | `1` | Activity (آماده) |
| `VINOR_SUPER_ADMIN_PHONES` | خالی | CSV allowlist؛ خالی = هر ادمین لاگین‌شده |

**خروجی داده**
- `instance/data/role_assignments.json`

**قانون ایمنی**
- OTP و نقش‌های فعلی شکسته نشدند؛ گسترش Additive است.
- Special → Owner بدون مهاجرت اجباری.

---

### فاز ۶ — یکپارچه‌سازی ✅ انجام شد

**محدوده**
- همه workflowهای جدید در registry (نازک + gated)
- AI tools شکاف‌های کوچک (`propose_lead` / `propose_task`) با human-in-the-loop
- Timeline واحد روی Lead → Settlement (`app/integration/` + Partner `/journey`)
- Roles activity hook؛ مسیرهای موازی (`propose_deal` / commissions / mark_in_transaction) دست‌نخورده

**مسیر کد**
- `app/integration/`
- Workflow: `visit_result` / `crm_followup` / `closing_contract`
- Partner UI: `/journey`
- تست: `tests/test_integration_phase6.py`

**فلگ‌ها (پیش‌فرض ON)**
| Flag | نقش |
|------|-----|
| `VINOR_INTEGRATION_ENABLED` | کلید اصلی |
| `VINOR_INTEGRATION_UI_ENABLED` | Partner Journey UI |
| `VINOR_INTEGRATION_JOURNEY_ENABLED` | Aggregator تایم‌لاین |
| `VINOR_INTEGRATION_WORKFLOWS_ENABLED` | Thin workflows در registry |
| `VINOR_INTEGRATION_AI_TOOLS_ENABLED` | propose_lead / propose_task |
| `VINOR_INTEGRATION_ACTIVITY_HOOK_ENABLED` | رویدادهای integration |

**قانون ایمنی**
- `propose_deal`، `mark_in_transaction`، commissions/withdrawals deprecate نشدند.
- خاموش‌کردن تکراری‌ها به فاز ۷ موکول است.

---

### فاز ۷ — سخت‌سازی ✅ انجام شد

**محدوده**
- Audit / Activity اجباری برای ادمین (Foundation `source=admin`)
- RBAC دانه‌ریز روی mutateهای حساس ادمین
- شاخص‌های OS روی BI موجود (`os_*` در `get_bi_obs` + نوار داشبورد)
- Soft-cleanup: deprecate registry + prefer-new nav — بدون حذف `propose_deal` / commissions

**مسیر کد**
- `app/hardening/`
- Admin: `/audit` + wire در commissions / withdrawals / visits / partner tier
- تست: `tests/test_hardening_phase7.py`

**فلگ‌ها (پیش‌فرض ON)**
| Flag | نقش |
|------|-----|
| `VINOR_HARDENING_ENABLED` | کلید اصلی |
| `VINOR_HARDENING_AUDIT_ENABLED` | نوشتن audit ادمین |
| `VINOR_HARDENING_AUDIT_REQUIRED` | هشدار اگر audit ننویسد (fail-open) |
| `VINOR_HARDENING_RBAC_ENABLED` | enforce permissions |
| `VINOR_HARDENING_OS_KPIS_ENABLED` | KPIهای قیف روی BI/داشبورد |
| `VINOR_HARDENING_SOFT_CLEANUP_ENABLED` | registry + prefer-new nav |
| `VINOR_HARDENING_UI_ENABLED` | صفحه `/admin/audit` |

**قانون ایمنی**
- `propose_deal`، `mark_in_transaction`، commissions/withdrawals حذف نشدند.
- Cleanup فقط soft (registry + ترتیب UI).

---

## ترتیب اجرا (خلاصه)

```
فاز۰ Foundation ✓
  ↓
فاز۱ CRM ✓
  ↓
فاز۲ Visit Result + No-Show ✓
  ↓
فاز۳ Offer / Counter / Reservation ✓
  ↓
فاز۴ Contract / Payment / Deal Entity / Settlement ✓
  ↓
فاز۵ Roles & Portals ✓
  ↓
فاز۶ AI + Workflow + Timeline یکپارچه ✓
  ↓
فاز۷ RBAC / Audit / Cleanup ✓
```

---

## نقش‌ها — وضعیت

| نقش | وضعیت |
|-----|--------|
| Guest | موجود |
| User | موجود |
| Partner | موجود |
| Special Partner | موجود |
| Admin | موجود |
| Buyer | موجود (فاز ۵ ✅ — portal `/my`) |
| Seller / Owner | موجود (فاز ۵ ✅ — special→Owner؛ approved→Seller) |
| Super Admin | موجود (فاز ۵ ✅ — روی admin OTP) |

---

## موجودیت‌های هدف

| Entity | فاز |
|--------|-----|
| Activity / Timeline | ۰ ✅ |
| Lead / Contact / Call Log / Follow-up / Task | ۱ ✅ |
| Visit Result / No-Show | ۲ ✅ |
| Negotiation / Offer / Counter / Reservation | ۳ ✅ |
| Contract / Payment / Deal Entity / Settlement / Document lifecycle | ۴ ✅ |
| Reminder (تکمیل Task) | ۱–۲ |
| Unified Activity روی همه مراحل | ۶ ✅ |
| Admin Audit / RBAC / OS KPIs | ۷ ✅ |

---

## رگرسیون اجباری قبل از بستن هر فاز

- [ ] ورود OTP
- [ ] Guest (سقف AI / مشاهده)
- [ ] User (apply)
- [ ] Partner (visit → deal → commission)
- [ ] Special Partner (listings / inbox)
- [ ] Withdrawal
- [ ] AI Chat (public + partner tools)
- [ ] Workflow Engine + Conversation Engine
- [ ] Foundation flags default OFF (بدون اثر جانبی)

---

## وضعیت پیشرفت

| فاز | وضعیت |
|-----|--------|
| ۰ Foundation | ✅ انجام شد |
| ۱ CRM | ✅ انجام شد |
| ۲ Visit کامل | ✅ انجام شد |
| ۳ Commercial | ✅ انجام شد |
| ۴ Closing & Finance | ✅ انجام شد |
| ۵ Roles & Portals | ✅ انجام شد |
| ۶ یکپارچه‌سازی | ✅ انجام شد |
| ۷ سخت‌سازی | ✅ انجام شد |

---

*این سند نقشه اجرای تأییدشده است. جزئیات معماری وضعیت فعلی در `VINOR_ARCHITECTURE.txt` آمده است.*
