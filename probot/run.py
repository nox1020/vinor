"""python -m probot.run [foreground|ensure|restart|stop|status]"""
import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
