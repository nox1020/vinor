# -*- coding: utf-8 -*-
"""GitHub webhook: deploy only after CI succeeds on main.

Signature is checked before any event is acted on. The HTTP response never
includes command output, filesystem paths, or secrets. Git runs in
scripts/deploy.sh, detached, not in this request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import subprocess
import time
from typing import Any, Optional

from flask import Blueprint, jsonify, request

IS_WINDOWS = platform.system() == "Windows"
try:
    if not IS_WINDOWS:
        import fcntl
    else:
        fcntl = None  # type: ignore
except Exception:
    fcntl = None  # type: ignore

_DEFAULT_PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_PATH = os.getenv("VINOR_PROJECT_PATH") or (
    _DEFAULT_PROJECT
    if os.path.isdir(os.path.join(_DEFAULT_PROJECT, "app"))
    else "/home/vinorir/public_html/vinor"
)
_SHA_LEN = 40

webhook_bp = Blueprint("webhook", __name__)


def _instance_dir() -> str:
    configured = (os.environ.get("INSTANCE_PATH") or "").strip()
    if configured:
        return configured
    return os.path.join(PROJECT_PATH, "instance")


def _deploy_state_dir() -> str:
    return os.path.join(_instance_dir(), "deploy")


def _log(event: str, detail: str = "") -> None:
    """JSON line for operators. Never pass secret values as detail."""
    try:
        path = os.path.join(_instance_dir(), "logs", "deploy.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "detail": detail,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _resolve_secret() -> str:
    """VINOR_WEBHOOK_SECRET from the environment only. Empty is never valid."""
    return (os.environ.get("VINOR_WEBHOOK_SECRET") or "").strip()


def _signature_ok(secret: str, raw_body: bytes) -> bool:
    if not secret:
        return False
    header = request.headers.get("X-Hub-Signature-256", "") or ""
    if not header.startswith("sha256="):
        return False
    sent = header.split("=", 1)[1].strip().lower()
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(mac, sent)
    except Exception:
        return False


def _allowed_repo() -> str:
    return (os.environ.get("VINOR_DEPLOY_REPO") or "nox1020/vinor").strip()


def _workflow_path_expected() -> str:
    raw = (os.environ.get("VINOR_CI_WORKFLOW_PATH") or ".github/workflows/ci.yml").strip()
    return raw.lstrip("./")


def _payload_workflow_path(payload: dict) -> str:
    for key in ("workflow_run", "workflow"):
        block = payload.get(key) or {}
        if isinstance(block, dict):
            path = str(block.get("path") or "").strip().lstrip("./")
            if path:
                return path
    return ""


def _repo_full_name(payload: dict) -> str:
    repo = payload.get("repository") or {}
    if isinstance(repo, dict):
        return str(repo.get("full_name") or "").strip()
    return ""


def _normalize_sha(value: Any) -> str:
    sha = str(value or "").strip().lower()
    if len(sha) != _SHA_LEN:
        return ""
    if any(ch not in "0123456789abcdef" for ch in sha):
        return ""
    return sha


def _eligible_sha(payload: dict) -> str:
    """SHA to deploy, or empty when this delivery must be ignored."""
    if str(payload.get("action") or "") != "completed":
        return ""
    run = payload.get("workflow_run") or {}
    if not isinstance(run, dict):
        return ""
    if str(run.get("conclusion") or "") != "success":
        return ""
    if str(run.get("event") or "") != "push":
        return ""
    if str(run.get("head_branch") or "") != "main":
        return ""
    if _repo_full_name(payload) != _allowed_repo():
        return ""
    if _payload_workflow_path(payload) != _workflow_path_expected():
        return ""
    return _normalize_sha(run.get("head_sha"))


def _read_lines(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            return {line.strip().lower() for line in handle if line.strip()}
    except Exception:
        return set()


def _append_line(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(value.strip().lower() + "\n")


class _StateLock:
    def __init__(self, directory: str):
        self._fh = None
        self._directory = directory

    def __enter__(self) -> "_StateLock":
        try:
            os.makedirs(self._directory, exist_ok=True)
            self._fh = open(os.path.join(self._directory, "state.lock"), "a+b")
            if fcntl is not None:
                fcntl.flock(self._fh, fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass
        self._fh = None


def _already_handled(sha: str, delivery: str) -> bool:
    base = _deploy_state_dir()
    current = _read_lines(os.path.join(base, "current_sha"))
    if sha and sha in current:
        return True
    accepted = _read_lines(os.path.join(base, "accepted_shas"))
    if sha and sha in accepted:
        return True
    if delivery:
        seen = _read_lines(os.path.join(base, "delivery_ids"))
        if delivery.strip().lower() in seen:
            return True
    return False


def _remember(sha: str, delivery: str) -> None:
    base = _deploy_state_dir()
    if delivery:
        _append_line(os.path.join(base, "delivery_ids"), delivery)
    if sha:
        _append_line(os.path.join(base, "accepted_shas"), sha)


def spawn_deploy(sha: str) -> None:
    """Start scripts/deploy.sh in a new session. Stdout goes to the deploy log."""
    script = os.path.join(PROJECT_PATH, "scripts", "deploy.sh")
    log_path = os.path.join(_instance_dir(), "logs", "deploy.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_fh = open(log_path, "ab", buffering=0)
    try:
        subprocess.Popen(
            ["bash", script, sha],
            cwd=PROJECT_PATH,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_fh.close()


def _ignored():
    return jsonify(ok=True, result="ignored"), 200


@webhook_bp.route("/git-webhook", methods=["POST"])
def git_webhook():
    raw = request.get_data(cache=True) or b""
    secret = _resolve_secret()
    if not secret:
        _log("webhook_rejected", "secret")
        return jsonify(ok=False, error="rejected"), 403
    if not _signature_ok(secret, raw):
        _log("webhook_rejected", "signature")
        return jsonify(ok=False, error="invalid_signature"), 403

    event = (request.headers.get("X-GitHub-Event") or "").strip()
    if event == "ping":
        return jsonify(ok=True, result="pong"), 200
    if event == "push":
        return _ignored()
    if event != "workflow_run":
        return _ignored()

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _ignored()
    sha = _eligible_sha(payload)
    if not sha:
        return _ignored()
    if IS_WINDOWS:
        _log("webhook_skipped", "windows")
        return _ignored()

    delivery = (request.headers.get("X-GitHub-Delivery") or "").strip()
    with _StateLock(_deploy_state_dir()):
        if _already_handled(sha, delivery):
            _log("webhook_duplicate", sha)
            return _ignored()

    try:
        spawn_deploy(sha)
    except Exception:
        # Do not record the delivery. A 500 lets GitHub retry.
        _log("spawn_failed", "deploy")
        return jsonify(ok=False, error="rejected"), 500

    with _StateLock(_deploy_state_dir()):
        try:
            _remember(sha, delivery)
        except Exception:
            _log("webhook_state", "unwritable")
    _log("webhook_accepted", sha)
    return jsonify(ok=True, accepted=True), 202
