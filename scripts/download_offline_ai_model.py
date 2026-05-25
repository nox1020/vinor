#!/usr/bin/env python3
"""دانلود مدل GGUF آفلاین به پوشه ai_models/"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.ai.model_paths import models_dir  # noqa: E402
from app.ai.offline_config import HF_MODEL_FILE, HF_REPO_ID  # noqa: E402


def main() -> int:
    dest = models_dir()
    target = os.path.join(dest, HF_MODEL_FILE)
    if os.path.isfile(target):
        print(f"مدل از قبل موجود است: {target}")
        return 0

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("نصب وابستگی: pip install huggingface_hub")
        return 1

    print(f"در حال دانلود {HF_REPO_ID} / {HF_MODEL_FILE}")
    print(f"مقصد: {dest}")
    path = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=HF_MODEL_FILE,
        local_dir=dest,
    )
    print(f"انجام شد: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
