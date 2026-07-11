import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))

# LiteSpeed/LSAPI: هرگز scheduler داخل ورکر روشن نکن — ورکر را نگه می‌دارد و
# با SIGTERM باعث «OSError: LSAPI: File error» در stderr می‌شود.
# پیگیری فروش / SMS زمان‌بندی‌شده فقط با cron:
#   */10 * * * * cd ~/public_html/vinor && ./venv/bin/python scripts/run_sales_coach_nudge.py
#   * * * * *     cd ~/public_html/vinor && ./venv/bin/python scripts/run_admin_sms_scheduled_jobs.py
os.environ.setdefault("VINOR_SALES_COACH_SCHEDULER", "0")
os.environ.setdefault("VINOR_CELEBRATION_SMS_SCHEDULER", "0")
os.environ.setdefault("VINOR_ADMIN_SMS_SCHEDULER", "0")
# Optional: in cPanel Python App env set LSAPI_CHILDREN=12 if host allows.

from run import app as application
