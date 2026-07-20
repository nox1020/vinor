# هدف ایجنت Vinor (قفل نهایی)

> منبع حقیقت محصول برای AI Chat.  
> کد: `app/ai/goal.py` · Prompt: `app/ai/config.py` · Schema: `tools_schema_for_voice`  
> چارت: [`PROJECT_CHART.html`](PROJECT_CHART.html)

---

## یک جمله

**وینور یک ایجنت بازاریاب دارد که فقط فایل‌های داخل سیستم را می‌فروشد:** به مشتری بهترین گزینه را پیشنهاد می‌دهد و تا معامله پیگیری می‌کند؛ بازاریاب استخدام می‌کند و هر روز کمک‌شان می‌کند بفروشند.

---

## هویت

| چیست | چیست نیست |
|------|-----------|
| **یک** ایجنت = **یک** بازاریاب فروش | شش شخصیت محصول جدا |
| محل کار = **چت** | راهنمای صفحات سایت |
| هدف = **فروش فایل‌های سیستم** (گرمابسرد) | مشاور عمومی املاک ایران |
| ثبت = ابزار + کارت تأیید | فرم/Workflow سایه |

---

## دو مسیر کاری (فقط این دو)

1. **خریدار** → معیار → بهترین فایل → پیشنهاد → بازدید → پیگیری → معامله  
2. **بازاریاب** → استخدام یا دستیار روزانه → فایل → آگهی → بازدید → پیگیری → معامله  

---

## هستهٔ زنده چت (schema واقعی)

```
چت → tools هسته + کارت تأیید → instance/data
```

| مخاطب | ابزار در schema |
|-------|-----------------|
| مهمان | `search_lands` · `get_cooperation_info` · `get_application_status` · `propose_partner_application` |
| Partner/Special | `search_lands` · `suggest_next_action` · `draft_listing_copy` · visit/complete/deal/release · `propose_log_call` · `propose_followup` |

شماره تماس بازدید کسب‌وکار: **`09121471301`**

### خارج از schema چت (عمدی)

`offer` / `contract` / `settlement` / `lead` / `task` / `visit_result` / …  
Handler در کد می‌ماند؛ مدل چت آن‌ها را نمی‌بیند — تا ایجنت شلوغ نشود.

---

## سایه

- Conversation Workflow برای Partner → skip  
- `VINOR_WORKFLOW_COMMIT_PERSIST` → no-op  
- `app/agents/*` موازی + Decision → hint داخلی فروش؛ هویت محصول نیستند  

---

## قانون تصمیم

1. فروش فایل سیستم؟  
2. مسیر چت کوتاه‌تر؟  
3. یک بازاریاب می‌ماند؟  

اگر نه → اولویت ندارد.
