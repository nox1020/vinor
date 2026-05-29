import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))

# AI آفلاین: bootstrap خودکار — اولویت offline
os.environ.setdefault("VINOR_AI_PROVIDER", "offline")
os.environ.setdefault("VINOR_AI_OFFLINE_ENABLED", "1")
os.environ.setdefault("VINOR_AI_OFFLINE_BOOTSTRAP", "1")
os.environ.setdefault("VINOR_AI_AUTO_DOWNLOAD", "1")
os.environ.setdefault("VINOR_AI_AUTO_PIP", "0")
os.environ.setdefault("VINOR_AI_AUTO_PIP_NETWORK", "0")

from run import app as application
