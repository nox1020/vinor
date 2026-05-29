"""راه‌اندازی AI آفلاین — بدون pip در Passenger (فقط warm-up + دانلود)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from .offline_config import (
    auto_bootstrap,
    auto_download,
    auto_pip,
    auto_pip_network,
    is_passenger,
    offline_enabled,
)
from .offline_download import ensure_model_file
from .offline_engine import is_ready, last_error, warmup
from .model_paths import model_file_path

_bootstrap_lock = threading.Lock()
_bootstrap_started = False
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_WHEELS_DIR = _PROJECT_ROOT / "packages"


def _log(app, msg: str) -> None:
    try:
        app.logger.info("[AI bootstrap] %s", msg)
    except Exception:
        print(f"[AI bootstrap] {msg}")


def _missing_packages() -> list[str]:
    missing: list[str] = []
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        missing.append("llama-cpp-python")
    return missing


def _local_wheel_paths(packages: list[str]) -> list[Path]:
    if not _LOCAL_WHEELS_DIR.is_dir():
        return []
    patterns = {
        "llama-cpp-python": ("llama_cpp*.whl", "llama-cpp*.whl"),
        "huggingface_hub": ("huggingface_hub*.whl",),
    }
    found: list[Path] = []
    for pkg in packages:
        for pattern in patterns.get(pkg, (f"{pkg.replace('-', '_')}*.whl",)):
            found.extend(sorted(_LOCAL_WHEELS_DIR.glob(pattern)))
    return found


def _pip_install_local(packages: list[str], app=None) -> bool:
    local = _local_wheel_paths(packages)
    if not local:
        return False
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-index",
        "--find-links",
        str(_LOCAL_WHEELS_DIR),
        *[str(w) for w in local],
    ]
    try:
        r = subprocess.run(cmd, check=False, timeout=120, capture_output=True, text=True)
        if r.returncode == 0 and not _missing_packages():
            if app:
                _log(app, f"local wheels ok: {[w.name for w in local]}")
            return True
        if app:
            tail = (r.stderr or r.stdout or "").strip()[-300:]
            _log(app, f"local wheel pip failed: {tail}")
    except Exception as exc:
        if app:
            _log(app, f"local wheel exception: {exc}")
    return False


def _pip_install_network(packages: list[str], app=None) -> bool:
    if not auto_pip_network():
        return False
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--prefer-binary"]
    if "llama-cpp-python" in packages:
        cmd.extend([
            "--extra-index-url",
            "https://abetlen.github.io/llama-cpp-python/whl/cpu",
        ])
    cmd.extend(packages)
    try:
        r = subprocess.run(cmd, check=False, timeout=900, capture_output=True, text=True)
        if r.returncode != 0:
            if app:
                tail = (r.stderr or r.stdout or "").strip()[-500:]
                _log(app, f"network pip failed ({r.returncode}): {tail}")
            return False
        return True
    except Exception as exc:
        if app:
            _log(app, f"network pip exception: {exc}")
        return False


def _ensure_dependencies(app=None) -> None:
    missing = _missing_packages()
    if not missing:
        return

    if _pip_install_local(missing, app=app):
        return

    if not auto_pip():
        if app:
            _log(
                app,
                f"llama-cpp missing — install via SSH: "
                f"pip install --no-index --find-links packages/ packages/llama_cpp*.whl",
            )
        return

    if is_passenger():
        if app:
            _log(app, "skip network pip on Passenger (prevents worker SIGTERM)")
        return

    if app:
        _log(app, f"network pip install: {', '.join(missing)}")
    _pip_install_network(missing, app=app)
    still = _missing_packages()
    if still and app:
        _log(app, f"still missing: {', '.join(still)}")


def ensure_engine_ready(*, sync_pip: bool = False) -> bool:
    """warm-up موتور — بدون pip در مسیر درخواست وب."""
    if not offline_enabled():
        return False
    if is_ready():
        return True

    with _bootstrap_lock:
        if is_ready():
            return True
        if sync_pip and auto_pip() and not is_passenger():
            _ensure_dependencies()
        from .model_paths import model_is_ready

        if auto_download() and not model_is_ready():
            ensure_model_file()
        if not model_is_ready():
            return False
        return warmup()


def run_bootstrap(app) -> None:
    if not offline_enabled() or not auto_bootstrap():
        return
    with app.app_context():
        try:
            _log(app, "start")
            missing = _missing_packages()
            _log(
                app,
                f"env passenger={is_passenger()} auto_pip={auto_pip()} "
                f"auto_download={auto_download()} missing={missing or 'none'}",
            )
            if is_passenger():
                _log(app, "Passenger mode: no network pip")
            _ensure_dependencies(app)
            from .model_paths import model_is_ready

            if not model_is_ready():
                if auto_download():
                    _log(app, "model missing — starting download (may take several minutes)")
                    ok = ensure_model_file()
                    _log(app, f"model download: {'ok' if ok else 'pending/failed'}")
                else:
                    _log(app, "model missing — upload GGUF to ai_models/ or set VINOR_AI_AUTO_DOWNLOAD=1")
            else:
                _log(app, "model file already present")
            if not model_is_ready():
                _log(app, f"offline engine not ready: model file missing ({model_file_path()})")
                return
            _log(app, "loading model into memory (warm-up)...")
            if warmup():
                _log(app, "offline engine ready")
            else:
                _log(app, f"offline engine not ready: {last_error()}")
        except Exception as exc:
            _log(app, f"bootstrap error: {exc}")


def start_offline_bootstrap(app) -> None:
    global _bootstrap_started
    if not offline_enabled() or not auto_bootstrap():
        return
    if os.environ.get("VINOR_AI_BOOTSTRAP_SYNC", "").strip() == "1":
        run_bootstrap(app)
        _bootstrap_started = True
        return
    with _bootstrap_lock:
        if _bootstrap_started:
            return
        _bootstrap_started = True
    t = threading.Thread(target=run_bootstrap, args=(app,), name="vinor-ai-bootstrap", daemon=True)
    t.start()


def bootstrap_status() -> dict:
    from .model_paths import model_file_path, model_is_ready

    return {
        "offline_enabled": offline_enabled(),
        "passenger": is_passenger(),
        "model_path": str(model_file_path()),
        "model_ready": model_is_ready(),
        "engine_ready": is_ready(),
        "engine_error": last_error(),
        "missing_packages": _missing_packages(),
    }
