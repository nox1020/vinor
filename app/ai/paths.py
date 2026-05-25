"""مسیرهای داده Vinor AI — هماهنگ با storage.data_dir (سرور + لوکال)."""
from __future__ import annotations

import os
import shutil

from app.utils.storage import data_dir, legacy_dir


def ai_data_file(filename: str) -> str:
    """مسیر فایل داخل <instance>/data — قابل نوشتن روی Passenger."""
    path = os.path.join(data_dir(), filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def escalations_path() -> str:
    return ai_data_file("ai_escalations.json")


def ensure_escalations_file() -> str:
    """ایجاد/مهاجرت فایل سوالات AI از مسیرهای قدیمی."""
    path = escalations_path()
    if os.path.isfile(path):
        return path

    candidates = [
        os.path.join(legacy_dir(), "ai_escalations.json"),
        os.path.join(os.path.dirname(data_dir()), "ai_escalations.json"),
    ]
    try:
        from flask import current_app

        alt = os.path.join(current_app.instance_path, "data", "ai_escalations.json")
        if alt not in candidates:
            candidates.append(alt)
    except Exception:
        pass

    for old in candidates:
        if old and os.path.isfile(old) and os.path.abspath(old) != os.path.abspath(path):
            try:
                shutil.copy2(old, path)
                return path
            except OSError:
                continue

    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("[]")
    return path
