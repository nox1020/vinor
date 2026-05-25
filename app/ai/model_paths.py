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
# حداقل حجم فایل معتبر (جلوگیری از دانلود ناقص)
MIN_MODEL_BYTES = int(os.environ.get("VINOR_AI_MIN_MODEL_BYTES", str(80 * 1024 * 1024)))


def _default_models_dir() -> str:
    custom = os.environ.get("VINOR_AI_MODELS_DIR", "").strip()
    if custom:
        return custom
    instance = os.environ.get("INSTANCE_PATH", "").strip()
    if instance:
        return os.path.join(instance, "ai_models")
    return DEFAULT_MODEL_DIR


def models_dir() -> str:
    path = _default_models_dir()
    os.makedirs(path, exist_ok=True)
    return path


def model_file_valid(path: str) -> bool:
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) >= MIN_MODEL_BYTES
    except OSError:
        return False


def default_model_path() -> str:
    custom = os.environ.get("VINOR_AI_OFFLINE_MODEL_PATH", "").strip()
    if custom and os.path.isfile(custom):
        return custom
    path = os.path.join(models_dir(), DEFAULT_MODEL_FILENAME)
    if model_file_valid(path):
        return path
    for gguf in sorted(glob.glob(os.path.join(models_dir(), "*.gguf"))):
        if model_file_valid(gguf):
            return gguf
    return path
