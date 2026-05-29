import sys
import os

project_home = "/home/vinorir/public_html/vinor"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("INSTANCE_PATH", os.path.join(project_home, "instance"))

from run import app as application
