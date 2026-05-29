#!/usr/bin/env python3
"""دانلود مدل GGUF به ai_models/ — برای deploy یا تست لوکال."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("VINOR_AI_AUTO_DOWNLOAD", "1")
os.environ.setdefault("VINOR_AI_BOOTSTRAP_SYNC", "1")

from app import create_app
from app.ai.offline_bootstrap import run_bootstrap, bootstrap_status


def main() -> int:
    app = create_app()
    run_bootstrap(app)
    status = bootstrap_status()
    print("model_ready:", status.get("model_ready"))
    print("engine_ready:", status.get("engine_ready"))
    print("model_path:", status.get("model_path"))
    if status.get("engine_error"):
        print("engine_error:", status.get("engine_error"))
    return 0 if status.get("model_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
