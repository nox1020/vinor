"""اجرای تک‌نمونهٔ ربات بله (polling) جدا از ورکرهای وب وینور.

    python -m probot.run              # اجرا در پیش‌زمینه (همان پروسهٔ ربات)
    python -m probot.run ensure       # اگر بالا نیست، در پس‌زمینه بالا بیاور (برای cron)
    python -m probot.run restart      # توقف و اجرای دوباره (بعد از deploy)
    python -m probot.run stop
    python -m probot.run status

تک‌نمونه بودن با flock روی فایل قفل در پوشهٔ داده تضمین می‌شود؛ پس cron، deploy و
autostart وب هم‌زمان هم فقط یک polling می‌سازند (بله در غیر این صورت Conflict می‌دهد).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from .paths import REPO_ROOT, data_dir, data_path, is_configured, seed_data_config

try:
    import fcntl  # type: ignore
except ImportError:  # ویندوز
    fcntl = None

LOCK_NAME = ".run.flock"
PID_NAME = ".run.pid"
STAMP_NAME = ".autostart.stamp"
LOG_DIR_NAME = "logs"
OUT_LOG = "bot_run_out.txt"
ERR_LOG = "bot_run_err.txt"
MAX_LOG_BYTES = 5 * 1024 * 1024
AUTOSTART_INTERVAL_SEC = 60.0

_last_autostart_check = 0.0


def _lock_path() -> str:
    return data_path(LOCK_NAME)


def _pid_path() -> str:
    return data_path(PID_NAME)


def _read_pid() -> int:
    try:
        with open(_pid_path(), "r", encoding="utf-8") as f:
            raw = (f.read() or "").strip()
        return int(raw) if raw.isdigit() else 0
    except OSError:
        return 0


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\x00", b" ").decode(errors="ignore")
    except OSError:
        return ""


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_running() -> bool:
    """True اگر پروسه‌ای قفل اجرا را نگه داشته باشد."""
    path = _lock_path()
    if fcntl is None:
        pid = _read_pid()
        return _alive(pid)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def python_executable() -> str | None:
    """مفسر پایتون venv؛ زیر LiteSpeed، sys.executable ممکن است lswsgi باشد نه python."""
    for env_name in ("PROBOT_PYTHON", "VINOR_VENV_PYTHON"):
        cand = (os.environ.get(env_name) or "").strip()
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    exe = sys.executable or ""
    if exe and os.path.basename(exe).lower().startswith("python"):
        return exe
    for name in ("python3", "python"):
        cand = os.path.join(sys.prefix, "bin", name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PROBOT_DATA_DIR"] = data_dir()
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _rotate(path: str) -> None:
    try:
        if os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


def spawn_detached() -> int | None:
    py = python_executable()
    if not py:
        print("probot: python venv پیدا نشد (PROBOT_PYTHON را تنظیم کنید).", file=sys.stderr)
        return None
    log_dir = data_path(LOG_DIR_NAME)
    os.makedirs(log_dir, exist_ok=True)
    out_p = os.path.join(log_dir, OUT_LOG)
    err_p = os.path.join(log_dir, ERR_LOG)
    _rotate(out_p)
    _rotate(err_p)
    with open(out_p, "ab") as out, open(err_p, "ab") as err, open(os.devnull, "rb") as devnull:
        proc = subprocess.Popen(
            [py, "-m", "probot.run", "foreground"],
            cwd=REPO_ROOT,
            env=_child_env(),
            stdin=devnull,
            stdout=out,
            stderr=err,
            close_fds=True,
            start_new_session=True,
        )
    return proc.pid


def ensure() -> int:
    if not is_configured():
        print("probot: تنظیم نشده (توکن/ادمین)؛ کاری انجام نشد.")
        return 0
    if is_running():
        print("probot: در حال اجراست.")
        return 0
    pid = spawn_detached()
    if pid:
        print(f"probot: اجرا شد (pid={pid}).")
        return 0
    return 1


def _kill_tree(pid: int, marker: str, timeout: float = 10.0) -> bool:
    if not _alive(pid):
        return True
    cmd = _cmdline(pid)
    if cmd and marker not in cmd:
        return True  # PID بازیافت شده؛ مال ما نیست
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.3)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    return not _alive(pid)


def stop() -> int:
    pid = _read_pid()
    if pid:
        _kill_tree(pid, "probot.run")
    try:
        with open(data_path(".worker.lock"), "r", encoding="utf-8") as f:
            wpid = int((f.read() or "0").strip() or 0)
        if wpid:
            _kill_tree(wpid, "probot.worker", timeout=5.0)
    except (OSError, ValueError):
        pass
    for _ in range(20):
        if not is_running():
            break
        time.sleep(0.3)
    print("probot: متوقف شد." if not is_running() else "probot: هنوز قفل آزاد نشده.")
    return 0 if not is_running() else 1


def status() -> int:
    running = is_running()
    info = {"configured": is_configured(), "running": running, "pid": _read_pid() if running else None}
    try:
        with open(data_path("bale_status.json"), "r", encoding="utf-8") as f:
            st = json.load(f)
        info["bale_state"] = st.get("state")
        info["updated_at"] = st.get("updated_at")
    except (OSError, ValueError):
        pass
    try:
        with open(data_path("divar_payment_check.json"), "r", encoding="utf-8") as f:
            pc = json.load(f)
        info["divar_payment"] = pc.get("state")
        info["divar_payment_checked_at"] = pc.get("checked_at")
    except (OSError, ValueError):
        pass
    print(json.dumps(info, ensure_ascii=False))
    return 0


def foreground() -> int:
    if not is_configured():
        print("probot: توکن بله یا شناسهٔ ادمین تنظیم نشده؛ ربات اجرا نشد.", file=sys.stderr)
        return 0
    lock_fd = None
    if fcntl is not None:
        lock_fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("probot: نمونهٔ دیگری در حال اجراست؛ خروج.")
            return 0
    with open(_pid_path(), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    # توابع ذخیرهٔ ساعت‌ها configs.json پوشهٔ داده را می‌خوانند و بازنویسی می‌کنند.
    # اگر فایل نباشد، پیش‌فرض بسته‌شده کپی می‌شود — نه یک {} خالی که توکن را بپوشاند.
    seed_data_config()
    try:
        from . import bot  # import = chdir به پوشهٔ داده + مقداردهی

        bot.serve()
    finally:
        try:
            if _read_pid() == os.getpid():
                os.remove(_pid_path())
        except OSError:
            pass
        if lock_fd is not None:
            os.close(lock_fd)
    return 0


def maybe_autostart() -> None:
    """از درخواست‌های وب وینور صدا زده می‌شود: حداکثر هر ۶۰ ثانیه یک بررسی سبک.
    polling هرگز داخل ورکر وب اجرا نمی‌شود؛ فقط یک پروسهٔ جدا (detached) ساخته می‌شود."""
    global _last_autostart_check
    if (os.environ.get("PROBOT_AUTOSTART") or "1").strip() == "0":
        return
    now = time.monotonic()
    if now - _last_autostart_check < AUTOSTART_INTERVAL_SEC:
        return
    _last_autostart_check = now
    try:
        stamp = data_path(STAMP_NAME)
        try:
            if time.time() - os.path.getmtime(stamp) < AUTOSTART_INTERVAL_SEC:
                return
        except OSError:
            pass
        if not is_configured() or is_running():
            return
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
        spawn_detached()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = (args[0] if args else "foreground").strip().lower()
    if cmd in ("foreground", "run"):
        return foreground()
    if cmd in ("ensure", "start"):
        return ensure()
    if cmd == "stop":
        return stop()
    if cmd == "restart":
        stop()
        return ensure()
    if cmd == "status":
        return status()
    print(__doc__)
    return 2
