#!/usr/bin/env python3
"""دانلود مدل GGUF آفلاین به پوشه ai_models/"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.ai.offline_download import download_offline_model  # noqa: E402
from app.ai.model_paths import models_dir, default_model_path  # noqa: E402


def main() -> int:
    os.makedirs(models_dir(), exist_ok=True)
    print(f"پوشه مدل: {models_dir()}")
    ok, msg = download_offline_model()
    print(msg)
    if ok:
        print(f"مسیر: {default_model_path()}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
