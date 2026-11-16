import os

from .paths import data_path, load_config


class configBot:
    """تنظیمات ربات: پیش‌فرض‌ها + configs.json در پوشهٔ داده + env (PROBOT_*)."""

    def __init__(self):
        self.config = load_config()
        db_name = str(self.config.get("database") or "bot.db")
        # مسیر نسبی دیتابیس همیشه داخل پوشهٔ داده است، نه پوشهٔ جاری.
        self.database = db_name if os.path.isabs(db_name) else data_path(db_name)

        _tok = self.config.get("bale_token") or self.config.get("token")
        self.token = str(_tok).strip() if _tok is not None and str(_tok).strip() else None

        admin_value = self.config.get("admin")
        self.admin = None
        if admin_value is not None:
            try:
                self.admin = int(str(admin_value).strip())
            except (ValueError, TypeError):
                print("❌ [loadConfig] admin معتبر نیست (باید عدد باشد).")
                self.admin = None
        else:
            print("⚠️ [loadConfig] admin تعریف نشده است (configs.json یا PROBOT_ADMIN_ID).")
        self.times = self.config.get("times") or [8, 22]

        # برای سازگاری با کد قدیمی
        self.host = None
        self.user = None
        self.passwd = None
