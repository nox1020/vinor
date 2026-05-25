"""تنظیمات مدل آفلاین — دانلود و اجرا."""
from __future__ import annotations

import os

from .model_paths import DEFAULT_MODEL_FILENAME, models_dir

# Qwen2.5-0.5B — سبک (~۴۰۰MB)، مناسب لوکال و fallback
HF_REPO_ID = os.environ.get(
    "VINOR_AI_HF_REPO",
    "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
)
HF_MODEL_FILE = os.environ.get(
    "VINOR_AI_HF_FILE",
    DEFAULT_MODEL_FILENAME,
)


def offline_runtime_config() -> dict:
    return {
        "n_ctx": int(os.environ.get("VINOR_AI_OFFLINE_N_CTX", "4096")),
        "n_threads": int(os.environ.get("VINOR_AI_OFFLINE_THREADS", "4")),
        "max_tokens": int(os.environ.get("VINOR_AI_OFFLINE_MAX_TOKENS", "512")),
        "temperature": float(os.environ.get("VINOR_AI_OFFLINE_TEMPERATURE", "0.4")),
        "context_chars": int(os.environ.get("VINOR_AI_OFFLINE_CTX_CHARS", "3500")),
        "history": int(os.environ.get("VINOR_AI_OFFLINE_MAX_HISTORY", "8")),
    }
