"""اجرای مدل GGUF آفلاین با llama-cpp-python."""
from __future__ import annotations

import os
import threading
from typing import Any

from flask import current_app

from .model_paths import default_model_path, models_dir
from .offline_config import HF_MODEL_FILE, HF_REPO_ID, offline_runtime_config

_llm = None
_llm_lock = threading.Lock()
_load_error: str | None = None


def offline_available() -> bool:
    path = default_model_path()
    return bool(path and os.path.isfile(path))


def offline_status() -> dict[str, Any]:
    path = default_model_path()
    return {
        "available": offline_available(),
        "model_path": path if offline_available() else "",
        "models_dir": models_dir(),
        "expected_file": HF_MODEL_FILE,
        "hf_repo": HF_REPO_ID,
        "loaded": _llm is not None,
        "load_error": _load_error or "",
    }


def _get_llm():
    global _llm, _load_error
    if _llm is not None:
        return _llm
    path = default_model_path()
    if not path or not os.path.isfile(path):
        _load_error = "فایل مدل GGUF در پوشه ai_models یافت نشد."
        return None

    with _llm_lock:
        if _llm is not None:
            return _llm
        try:
            from llama_cpp import Llama
        except ImportError:
            _load_error = (
                "پکیج llama-cpp-python نصب نیست. "
                "اجرا: pip install -r requirements-offline.txt"
            )
            return None

        cfg = offline_runtime_config()
        try:
            _llm = Llama(
                model_path=path,
                n_ctx=cfg["n_ctx"],
                n_threads=cfg["n_threads"],
                verbose=False,
            )
            _load_error = None
            try:
                current_app.logger.info("Vinor offline AI loaded: %s", path)
            except Exception:
                pass
        except Exception as exc:
            _load_error = str(exc)
            try:
                current_app.logger.error("Offline AI load failed: %s", exc)
            except Exception:
                pass
            return None
    return _llm


def call_offline_chat(messages: list[dict[str, str]]) -> dict[str, Any]:
    llm = _get_llm()
    if llm is None:
        err = _load_error or "مدل آفلاین در دسترس نیست."
        return {"ok": False, "error": err, "error_code": "offline_unavailable"}

    cfg = offline_runtime_config()
    path = default_model_path()
    model_name = os.path.basename(path) or "gguf"

    try:
        out = llm.create_chat_completion(
            messages=messages,
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            stream=False,
        )
    except Exception as exc:
        try:
            current_app.logger.error("Offline AI inference failed: %s", exc)
        except Exception:
            pass
        return {
            "ok": False,
            "error": "خطا در اجرای مدل آفلاین. لطفاً دوباره تلاش کنید.",
            "error_code": "offline_inference",
        }

    reply = ""
    if isinstance(out, dict):
        choices = out.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                reply = str(msg.get("content") or "").strip()

    if not reply:
        return {"ok": False, "error": "پاسخی از مدل آفلاین دریافت نشد."}

    usage = out.get("usage") if isinstance(out, dict) else None
    return {
        "ok": True,
        "reply": reply,
        "meta": {
            "provider": "offline",
            "model": model_name,
            "usage": usage,
        },
    }
