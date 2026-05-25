"""دانلود مدل GGUF — مشترک بین اسکریپت و bootstrap سرور."""
from __future__ import annotations

import os
import shutil

from .model_paths import default_model_path, models_dir, model_file_valid
from .offline_config import HF_MODEL_FILE, HF_REPO_ID


def _ensure_hf_timeout() -> None:
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "1200")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "120")


def download_offline_model(*, force: bool = False) -> tuple[bool, str]:
    """
    دانلود مدل به پوشه models_dir (با resume).
    برمی‌گرداند: (موفقیت, پیام)
    """
    dest = models_dir()
    target = os.path.join(dest, HF_MODEL_FILE)
    if not force and model_file_valid(target):
        return True, f"مدل موجود است: {target}"

    _ensure_hf_timeout()

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return False, "huggingface_hub نصب نیست"

    try:
        path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=HF_MODEL_FILE,
            local_dir=dest,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
    except Exception as exc:
        return False, str(exc)

    final = path if path and os.path.isfile(path) else target
    if not model_file_valid(final) and os.path.isfile(target):
        final = target

    # اگر فقط در کش باشد، به مسیر نهایی کپی شود
    if not model_file_valid(final):
        cache_glob = os.path.join(dest, ".cache", "**", HF_MODEL_FILE)
        import glob

        for hit in glob.glob(cache_glob, recursive=True):
            if model_file_valid(hit):
                try:
                    shutil.copy2(hit, target)
                    final = target
                    break
                except OSError:
                    continue

    if model_file_valid(final):
        return True, f"دانلود شد: {final}"
    try:
        partial = os.path.getsize(final) if os.path.isfile(final) else 0
    except OSError:
        partial = 0
    return False, (
        f"فایل مدل ناقص است ({partial // (1024 * 1024)}MB). "
        "دانلود دوباره از سرور ادامه می‌یابد."
    )
