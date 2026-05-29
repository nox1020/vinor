"""اجرای مدل GGUF با llama-cpp-python."""
from __future__ import annotations

import threading
from typing import Any

from .credits import budget_config
from .offline_config import offline_max_tokens, offline_n_ctx, offline_threads
from .model_paths import model_file_path, model_is_ready

_lock = threading.Lock()
_llm: Any = None
_ready = False
_last_error = ""


def is_ready() -> bool:
    return _ready and _llm is not None


def last_error() -> str:
    return _last_error


def warmup(force: bool = False) -> bool:
    global _llm, _ready, _last_error
    if _ready and _llm is not None and not force:
        return True
    if not model_is_ready():
        _last_error = "model file missing"
        return False
    with _lock:
        if _ready and _llm is not None and not force:
            return True
        try:
            from llama_cpp import Llama
        except ImportError:
            _last_error = "llama_cpp not installed"
            _ready = False
            return False
        try:
            _llm = Llama(
                model_path=str(model_file_path()),
                n_ctx=offline_n_ctx(),
                n_threads=offline_threads(),
                n_batch=512,
                verbose=False,
            )
            _ready = True
            _last_error = ""
            return True
        except Exception as exc:
            _llm = None
            _ready = False
            _last_error = str(exc)
            return False


def generate(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not warmup():
        return {"ok": False, "error": _last_error or "offline engine not ready"}

    bcfg = budget_config()
    max_tok = min(offline_max_tokens(), int(bcfg.get("max_tokens") or 512))
    temperature = float(bcfg.get("temperature") or 0.5)

    with _lock:
        if _llm is None:
            return {"ok": False, "error": "offline engine not loaded"}
        try:
            out = _llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tok,
                temperature=temperature,
                stream=False,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    reply = ""
    if isinstance(out, dict):
        choices = out.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                reply = str(msg.get("content") or "").strip()

    if not reply:
        return {"ok": False, "error": "empty offline reply"}

    return {
        "ok": True,
        "reply": reply,
        "meta": {
            "provider": "offline",
            "model": model_file_path().name,
        },
    }
