"""مسیر پوشهٔ مدل‌های آفلاین Vinor AI."""
from __future__ import annotations

import glob
import os

# ریشهٔ پروژه (پوشهٔ حاوی run.py)
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)

DEFAULT_MODEL_DIR = os.path.join(_PROJECT_ROOT, "ai_models")
DEFAULT_MODEL_FILENAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"


def models_dir() -> str:
    path = os.environ.get("VINOR_AI_MODELS_DIR", "").strip() or DEFAULT_MODEL_DIR
    os.makedirs(path, exist_ok=True)
    return path


def default_model_path() -> str:
    custom = os.environ.get("VINOR_AI_OFFLINE_MODEL_PATH", "").strip()
    if custom and os.path.isfile(custom):
        return custom
    path = os.path.join(models_dir(), DEFAULT_MODEL_FILENAME)
    if os.path.isfile(path):
        return path
    for gguf in sorted(glob.glob(os.path.join(models_dir(), "*.gguf"))):
        if os.path.isfile(gguf):
            return gguf
    return path
