import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))

# LiteSpeed/LSAPI: هرگز scheduler thread ماندگار داخل ورکر روشن نکن.
# به‌جایش lazy tick خودکار روی درخواست‌های وب همه نوبت‌ها را اجرا می‌کند
# (reach · sales_coach · celebration · admin SMS · optimization) — بدون cron.
os.environ.setdefault("VINOR_SALES_COACH_SCHEDULER", "0")
os.environ.setdefault("VINOR_REACH_SCHEDULER", "0")
os.environ.setdefault("VINOR_CELEBRATION_SMS_SCHEDULER", "0")
os.environ.setdefault("VINOR_ADMIN_SMS_SCHEDULER", "0")
os.environ.setdefault("VINOR_OPTIMIZATION_SCHEDULER", "0")
# Optional: in cPanel Python App env set LSAPI_CHILDREN=12 if host allows.

from run import app as application
