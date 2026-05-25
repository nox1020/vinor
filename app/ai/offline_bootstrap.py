"""راه‌اندازی خودکار مدل آفلاین هنگام استارت سرور."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

from .model_paths import default_model_path, models_dir, model_file_valid
from .offline_download import download_offline_model

_STATE = "idle"
_STATE_MSG = ""
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
_REQ_OFFLINE = os.path.join(_PROJECT_ROOT, "requirements-offline.txt")


def _bootstrap_enabled() -> bool:
    return os.environ.get("VINOR_AI_AUTO_BOOTSTRAP", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def should_start_bootstrap(app) -> bool:
    """
    در حالت Flask debug فقط در process اصلی (نه watcher) bootstrap اجرا شود
    تا pip/دانلود با reload قطع نشود.
    """
    if not _bootstrap_enabled():
        return False
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return True
    if not app.debug:
        return True
    return False


def _status_path() -> str:
    instance = os.environ.get("INSTANCE_PATH", "").strip()
    if instance:
        base = os.path.join(instance, "data")
    else:
        from app.utils.storage import data_dir

        base = data_dir()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "ai_offline_bootstrap.json")


def _save_status(state: str, message: str = "", extra: dict | None = None) -> None:
    global _STATE, _STATE_MSG
    _STATE = state
    _STATE_MSG = message
    payload: dict[str, Any] = {
        "state": state,
        "message": message,
        "updated_at": time.time(),
        "models_dir": models_dir(),
        "model_path": default_model_path(),
    }
    if extra:
        payload.update(extra)
    try:
        with open(_status_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_bootstrap_state() -> dict[str, Any]:
    path = _status_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "state": _STATE,
        "message": _STATE_MSG,
        "models_dir": models_dir(),
    }


def bootstrap_state() -> str:
    return str(get_bootstrap_state().get("state") or _STATE)


def is_offline_ready() -> bool:
    return model_file_valid(default_model_path())


def _packages_ready() -> bool:
    try:
        import llama_cpp  # noqa: F401
        import huggingface_hub  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_pip_packages(app) -> bool:
    if _packages_ready():
        return True

    if os.environ.get("VINOR_AI_AUTO_PIP", "1").lower() in ("0", "false", "no"):
        app.logger.warning(
            "Offline AI: install manually: pip install -r requirements-offline.txt"
        )
        return False

    if not os.path.isfile(_REQ_OFFLINE):
        app.logger.error("Offline AI: requirements-offline.txt not found")
        return False

    app.logger.info("Offline AI: installing requirements-offline.txt …")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                _REQ_OFFLINE,
                "--disable-pip-version-check",
            ],
            cwd=_PROJECT_ROOT,
            timeout=int(os.environ.get("VINOR_AI_PIP_TIMEOUT_SEC", "900")),
            check=False,
        )
        if _packages_ready():
            app.logger.info("Offline AI: pip packages installed")
            return True
        app.logger.error("Offline AI: pip finished but packages still missing")
        return False
    except Exception as exc:
        app.logger.error("Offline AI: pip install failed: %s", exc)
        return False


def _preload_model(app) -> None:
    if os.environ.get("VINOR_AI_PRELOAD", "1").lower() in ("0", "false", "no"):
        return
    if not is_offline_ready():
        return
    try:
        from .offline_engine import _get_llm

        llm = _get_llm()
        if llm:
            app.logger.info("Offline AI: model preloaded into memory")
    except Exception as exc:
        app.logger.warning("Offline AI: preload failed: %s", exc)


def _bootstrap_worker(app) -> None:
    with app.app_context():
        _save_status("running", "شروع bootstrap")
        try:
            os.makedirs(models_dir(), exist_ok=True)
            app.logger.info("Offline AI bootstrap | models_dir=%s", models_dir())

            if not _ensure_pip_packages(app):
                _save_status("error", "نصب وابستگی‌های آفلاین ناموفق بود")
                return

            attempts = int(os.environ.get("VINOR_AI_DOWNLOAD_RETRIES", "5"))
            last_err = ""
            for n in range(1, attempts + 1):
                if is_offline_ready():
                    break
                _save_status("downloading", f"در حال دانلود مدل … (تلاش {n}/{attempts})")
                app.logger.info("Offline AI: downloading GGUF (attempt %s/%s)", n, attempts)
                ok, msg = download_offline_model()
                if ok:
                    app.logger.info("Offline AI: %s", msg)
                    break
                last_err = msg
                app.logger.warning("Offline AI download attempt %s failed: %s", n, msg)
                time.sleep(min(30, 5 * n))

            if not is_offline_ready():
                _save_status("error", last_err or "فایل مدل پس از دانلود یافت نشد")
                return

            _preload_model(app)
            _save_status(
                "ready",
                "مدل آفلاین آماده است",
                extra={"model_path": default_model_path()},
            )
            app.logger.info("Offline AI bootstrap complete")
        except Exception as exc:
            app.logger.exception("Offline AI bootstrap failed: %s", exc)
            _save_status("error", str(exc))


def _thread_alive() -> bool:
    return _THREAD is not None and _THREAD.is_alive()


def start_offline_bootstrap(app) -> None:
    """یک‌بار هنگام create_app — thread پس‌زمینه."""
    global _THREAD

    if not should_start_bootstrap(app):
        return

    with _LOCK:
        if is_offline_ready():
            _save_status("ready", "مدل از قبل موجود است")

            def _quick_preload():
                with app.app_context():
                    _ensure_pip_packages(app)
                    _preload_model(app)

            if not _thread_alive():
                threading.Thread(
                    target=_quick_preload,
                    name="vinor-ai-preload",
                    daemon=True,
                ).start()
            return

        if _thread_alive():
            return

        app.logger.info("Offline AI: starting background bootstrap …")
        _THREAD = threading.Thread(
            target=_bootstrap_worker,
            args=(app,),
            name="vinor-ai-bootstrap",
            daemon=True,
        )
        _THREAD.start()
