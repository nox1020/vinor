import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))
# LiteSpeed LSAPI: in-process schedulers + blocking SMS tie up workers (see stderr.log).
# Scheduled admin SMS: cron → scripts/run_admin_sms_scheduled_jobs.py (every minute).
# Optional: in cPanel Python App env set LSAPI_CHILDREN=12 if host allows.

from run import app as application
