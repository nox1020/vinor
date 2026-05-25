import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# داده‌های JSON (سوالات AI، تنظیمات، چت) همیشه در instance پایدار پروژه
os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))

# AI آفلاین: اولویت محلی، دانلود/نصب خودکار در استارت
os.environ.setdefault("VINOR_AI_PROVIDER", "offline")
os.environ.setdefault("VINOR_AI_AUTO_BOOTSTRAP", "1")
os.environ.setdefault("VINOR_AI_AUTO_PIP", "1")
os.environ.setdefault("VINOR_AI_PRELOAD", "1")
os.environ.setdefault(
    "VINOR_AI_MODELS_DIR",
    os.path.join(project_home, "instance", "ai_models"),
)

from run import app as application





