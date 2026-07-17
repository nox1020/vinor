# -*- coding: utf-8 -*-
import os, hmac, hashlib, shlex, subprocess, time, json, platform
from typing import List, Dict, Any, Optional
from flask import Blueprint, request, jsonify

# ───────── وابسته به پلتفرم: fcntl/msvcrt ─────────
IS_WINDOWS = platform.system() == "Windows"
try:
    if not IS_WINDOWS:
        import fcntl  # فقط لینوکس/یونیکس
except Exception:
    fcntl = None  # احتیاط

try:
    if IS_WINDOWS:
        import msvcrt  # فقط ویندوز
except Exception:
    msvcrt = None  # احتیاط

# ───────── کانفیگ از Env (ایمن‌تر) ─────────
# Derive default from this file: app/routes/webhook.py → project root
_DEFAULT_PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Prefer explicit env; else on-disk path (production: /home/vinorir/public_html/vinor)
PROJECT_PATH = os.getenv("VINOR_PROJECT_PATH") or (
    _DEFAULT_PROJECT
    if os.path.isdir(os.path.join(_DEFAULT_PROJECT, "app"))
    else "/home/vinorir/public_html/vinor"
)
ALLOWED_BRANCHES = set(os.getenv("VINOR_ALLOWED_BRANCHES", "main").split(","))
try:
    from app.keys import VINOR_WEBHOOK_SECRET as SECRET
except Exception:
    SECRET = os.getenv("VINOR_WEBHOOK_SECRET", "")
ALLOWED_REPO = os.getenv(
    "VINOR_ALLOWED_REPO",
    "nox1020/vinor,asman-trader/garmabsard-flask",
)  # owner/repo (comma-separated)
DEPLOY_LOG = os.getenv("VINOR_DEPLOY_LOG", f"{PROJECT_PATH}/deploy.log")
LOCK_FILE = os.getenv("VINOR_DEPLOY_LOCK", "/tmp/vinor_deploy.lock" if not IS_WINDOWS else os.path.join(os.getenv("TEMP", "."), "vinor_deploy.lock"))
TIMEOUT = int(os.getenv("VINOR_CMD_TIMEOUT", "300"))

# دستورات پسادیپلوی (Passenger/venv) — روی ویندوز برای توسعه محلی غیرفعال می‌کنیم
_DEFAULT_VENV = os.path.join(os.path.dirname(PROJECT_PATH.rstrip("/")), "virtualenv", "vinor", "3.11", "bin", "activate")
# common cPanel layout: /home/USER/virtualenv/APPNAME/3.11/bin/activate
_CPANEL_VENV = "/home/vinorir/virtualenv/vinor/3.11/bin/activate"
VENV_ACTIVATE = os.getenv(
    "VINOR_VENV_ACTIVATE",
    _CPANEL_VENV if os.path.isfile(_CPANEL_VENV) else (
        _DEFAULT_VENV if os.path.isfile(_DEFAULT_VENV) else _CPANEL_VENV
    ),
)
DEFAULT_POST_DEPLOY_COMMANDS: List[str] = [
    # نصب وابستگی‌ها اگر وجود داشت
    f"bash -lc 'source {shlex.quote(VENV_ACTIVATE)} && pip install --upgrade pip && "
    f"[ -f requirements.txt ] && pip install -r requirements.txt || true'",
    # Passenger restart
    "bash -lc 'mkdir -p tmp && touch tmp/restart.txt'",
]
POST_DEPLOY_COMMANDS: List[str] = [] if IS_WINDOWS else DEFAULT_POST_DEPLOY_COMMANDS

webhook_bp = Blueprint("webhook", __name__)

# ───────── Utilities ─────────
def log_line(msg: str, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "msg": msg}
        if extra: rec.update(extra)
        os.makedirs(os.path.dirname(DEPLOY_LOG), exist_ok=True)
        with open(DEPLOY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def run(cmd: str, cwd: Optional[str] = None, timeout: int = TIMEOUT) -> Dict[str, Any]:
    """
    اجرای امن دستور. توجه: روی ویندوز، دستورات bash کار نمی‌کنند؛
    ما از قبل POST_DEPLOY_COMMANDS را روی ویندوز خالی کرده‌ایم.
    """
    try:
        # shlex.split برای سازگاری لینوکس/یونیکس
        # اگر cmd شامل space در مسیر باشد، shlex.split درست مدیریت می‌کند.
        proc = subprocess.run(
            shlex.split(cmd),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        out = {
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip()
        }
        log_line("run", out)
        return out
    except Exception as e:
        out = {"cmd": cmd, "rc": -1, "stdout": "", "stderr": f"{type(e).__name__}: {e}"}
        log_line("run_exception", out)
        return out

def verify_signature(secret: str, raw_body: bytes) -> bool:
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not secret:  # برای تست/استیجینگ
        return True
    if not sig.startswith("sha256="):
        return False
    sent = sig.split("=", 1)[1].strip()
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sent)

def extract_branch(ref: str) -> str:
    return ref.split("/", 2)[-1] if ref and ref.startswith("refs/heads/") else ""

# ───────── Cross-platform file lock ─────────
class FileLock:
    """
    لاک فایل کراس‌پلتفرم:
      - روی لینوکس/یونیکس از fcntl.flock با LOCK_EX | LOCK_NB
      - روی ویندوز از msvcrt.locking با LK_NBLCK روی 1 بایت
    """
    def __init__(self, path: str):
        self.path = path
        self.fh = None

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True) if os.path.dirname(self.path) else None
        self.fh = open(self.path, "a+b")
        try:
            if not IS_WINDOWS and fcntl:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif IS_WINDOWS and msvcrt:
                # از ابتدای فایل یک بایت را قفل می‌کنیم
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                # اگر هیچ‌کدام در دسترس نبود، با ایجاد فایل به‌صورت best-effort ادامه می‌دهیم
                pass
            # نوشتن مهر زمان برای مشاهده دیباگ
            self.fh.seek(0)
            self.fh.write(str(time.time()).encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())
        except (BlockingIOError, OSError) as e:
            # آزادسازی هندل در صورت عدم موفقیت
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None
            raise BlockingIOError(str(e))

    def release(self) -> None:
        if not self.fh:
            return
        try:
            if not IS_WINDOWS and fcntl:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            elif IS_WINDOWS and msvcrt:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None

def acquire_lock() -> FileLock:
    lock = FileLock(LOCK_FILE)
    lock.acquire()
    return lock

# ───────── Route ─────────
@webhook_bp.route("/git-webhook", methods=["POST"])
def git_webhook():
    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    if event == "ping":
        return jsonify(ok=True, pong=True), 200
    if event != "push":
        return jsonify(ok=False, error="Unsupported event", event=event), 400

    raw = request.get_data()
    if not verify_signature(SECRET, raw):
        log_line("invalid_signature", {"delivery": delivery_id})
        return jsonify(ok=False, error="Invalid signature"), 403

    payload = request.get_json(silent=True) or {}
    repo_full = (payload.get("repository") or {}).get("full_name", "")
    allowed_repos = {r.strip() for r in str(ALLOWED_REPO or "").split(",") if r.strip()}
    if allowed_repos and repo_full not in allowed_repos:
        log_line("repo_not_allowed", {"got": repo_full, "want": sorted(allowed_repos)})
        return jsonify(ok=True, skipped=True, reason="Repo not allowed", repo=repo_full), 200

    ref = payload.get("ref", "")
    branch = extract_branch(ref)
    if not branch:
        return jsonify(ok=False, error="Invalid ref", ref=ref), 400
    if branch not in ALLOWED_BRANCHES:
        return jsonify(ok=True, skipped=True, reason="Branch not allowed", ref=ref), 200

    if not PROJECT_PATH or not os.path.isdir(PROJECT_PATH):
        return jsonify(ok=False, error="Project path not found", path=PROJECT_PATH), 500

    # جلوگیری از دیپلوی هم‌زمان
    try:
        lock_handle = acquire_lock()
    except BlockingIOError:
        log_line("deploy_locked", {"delivery": delivery_id})
        return jsonify(ok=True, skipped=True, reason="Another deploy in progress"), 200

    steps: List[Dict[str, Any]] = []
    try:
        # اطمینان از گیت
        steps.append(run("git rev-parse --is-inside-work-tree", cwd=PROJECT_PATH))
        if steps[-1]["rc"] != 0 or steps[-1]["stdout"] != "true":
            return jsonify(ok=False, step="check-git", results=steps), 500

        # همگام‌سازی با ریموت
        git_cmds = [
            "git config --global --add safe.directory " + PROJECT_PATH,
            "git fetch --all --prune",
            f"git reset --hard origin/{branch}",
            "git clean -fd -e instance -e instance/*",
        ]
        for cmd in git_cmds:
            steps.append(run(cmd, cwd=PROJECT_PATH))
            if steps[-1]["rc"] != 0:
                return jsonify(ok=False, step="git", results=steps), 500

        # دستورات پسادیپلوی (فقط لینوکس/سرور)
        for cmd in POST_DEPLOY_COMMANDS:
            steps.append(run(cmd, cwd=PROJECT_PATH))
            if steps[-1]["rc"] != 0:
                return jsonify(ok=False, step="post_deploy", results=steps), 500

        log_line("deploy_ok", {"branch": branch, "delivery": delivery_id})
        return jsonify(ok=True, branch=branch, results=steps), 200

    finally:
        try:
            lock_handle.release()
        except Exception:
            pass
