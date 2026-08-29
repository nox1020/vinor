# V+

اپلیکیشن دسکتاپ **Python + PySide6** با پایگاه داده **SQLite** محلی، رابط **فارسی RTL**، داشبورد، گزارش، بینش‌های سرمایه، پشتیبان‌گیری و خروجی Excel/PDF/CSV.

## قابلیت‌ها

- داشبورد (متریک‌ها + نمودار + بینش‌های برتر)
- صفحه **بینش‌ها** با فیلتر دسته و سطح اهمیت
- مدیریت دارایی‌ها و معاملات باز/بسته
- گزارش‌های دوره‌ای مبتنی بر Analytics Engine
- هدف بازده سالانه در تنظیمات
- تم روشن/تاریک، تقویم جلالی/میلادی، واحد نمایش
- نرخ زنده اختیاری تتر (Wallex) و طلا (PersianToolbox)
- بکاپ/بازیابی و export (معاملات + تحلیل)

## پیش‌نیاز

- Python 3.11+

## نصب

```bash
cd invest
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## اجرا

```bash
python main.py
```

Windows: `start.bat` یا `run.bat` (هر دو ابتدا `.venv\Scripts\pythonw.exe` را استفاده می‌کنند). میانبر: `python scripts/create_shortcut.py` (فایل `V+.lnk`)

## تست

```bash
python -m pytest
```

## لاگ

`data/logs/invest.log` (چرخش روزانه، ۱۴ روز)

## داده و Migration

- DB: `data/invest.db`
- `schema_migrations`: v1 baseline، **v2** جداول `portfolio_snapshots` + `portfolio_snapshot_assets`
- Dual-write: `capital_snapshots` (قدیمی) + snapshot غنی

## ساختار

```
app/
  analytics/     # موتور تحلیل
  insights/      # موتور بینش (rule-based)
  database/ models/ repositories/ services/ utils/ ui/
tests/
docs/            # ANALYTICS, INSIGHTS, ARCHITECTURE, SNAPSHOT
main.py
```

## اسکریپت‌ها

```bash
python -m app.seed
python scripts/create_shortcut.py
```

## مستندات

| فایل | موضوع |
|------|--------|
| `docs/ARCHITECTURE.md` | لایه‌ها و threading |
| `docs/ANALYTICS.md` | فرمول‌ها |
| `docs/INSIGHTS.md` | قوانین بینش |
| `docs/SNAPSHOT_PROPOSAL.md` | snapshot غنی (اعمال‌شده v2) |

## Packaging / انتشار

1. نصب وابستگی‌ها از `requirements.txt`
2. اجرای تست‌ها (`python -m pytest`)
3. اجرای `python main.py` یا `run.bat`
4. (اختیاری آینده) PyInstaller برای exe — هنوز در repo نیست

نسخه ابزار توسعه: `requirements-dev.txt` (pytest)، تنظیمات در `pyproject.toml`.
