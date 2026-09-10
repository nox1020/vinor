#!/usr/bin/env python3
"""Commit leftover work and push to origin when the agent loop ends."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SECRET_RE = re.compile(
    r"(?:^|[/\\])(?:"
    r"\.env(?:\..*)?"
    r"|[^/\\]+\.(?:pem|key|p12|jks|keystore|pkcs12)"
    r"|credentials\.json"
    r"|google-services\.json"
    r"|firebase-service-account\.json"
    r"|key\.properties"
    r"|\.git-token"
    r"|service-account[^/\\]*\.json"
    r")$",
    re.IGNORECASE,
)


def log(message: str) -> None:
    print(f"[auto-push] {message}", file=sys.stderr, flush=True)


def emit() -> None:
    sys.stdout.write("{}\n")
    sys.stdout.flush()


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def git_ok(*args: str) -> str:
    result = git(*args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return result.stdout


def in_progress_git_state(git_dir: Path) -> bool:
    # Only directory/lock markers — leftover refs like REBASE_HEAD can remain
    # after a finished rebase and would otherwise block auto-push.
    return any(
        (git_dir / name).exists()
        for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")
    )


def unstage_secrets() -> None:
    staged = git_ok("diff", "--cached", "--name-only", "-z").split("\0")
    secrets = [path for path in staged if path and SECRET_RE.search(path)]
    if not secrets:
        return
    git("reset", "-q", "HEAD", "--", *secrets)
    log("skipped secrets: " + ", ".join(secrets))


def main() -> int:
    raw = sys.stdin.read()
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {}

    if str(payload.get("status") or "").lower() == "aborted":
        log("skipped: agent aborted")
        emit()
        return 0

    if not (REPO / ".git").exists():
        log(f"skipped: not a git repo ({REPO})")
        emit()
        return 0

    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        log("skipped: not inside a work tree")
        emit()
        return 0

    git_dir = Path(git_ok("rev-parse", "--git-dir").strip())
    if not git_dir.is_absolute():
        git_dir = REPO / git_dir
    if in_progress_git_state(git_dir):
        log("skipped: merge/rebase in progress")
        emit()
        return 0

    symbolic = git("symbolic-ref", "-q", "HEAD")
    if symbolic.returncode != 0:
        log("skipped: detached HEAD")
        emit()
        return 0

    git("add", "-A")
    unstage_secrets()

    has_staged = git("diff", "--cached", "--quiet")
    if has_staged.returncode != 0:
        commit = git(
            "commit",
            "-m",
            "Auto-push remaining agent changes.",
        )
        if commit.returncode != 0:
            log((commit.stderr or commit.stdout or "commit failed").strip())
        else:
            log("committed leftover changes")
    else:
        log("nothing new to commit")

    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if ahead.returncode != 0:
        # No upstream yet — still push the current branch.
        should_push = True
    else:
        should_push = (ahead.stdout.strip() or "0") != "0" or has_staged.returncode != 0

    if not should_push:
        # Catch the case where commit succeeded but upstream comparison failed earlier.
        porcelain = git_ok("status", "-sb").splitlines()
        should_push = any("ahead" in line for line in porcelain[:1])

    if not should_push:
        log("already in sync with origin")
        emit()
        return 0

    push = git("push", "origin", "HEAD")
    if push.returncode != 0:
        log((push.stderr or push.stdout or "push failed").strip())
    else:
        log("pushed to origin")

    emit()
    return 0


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — fail open so the agent can still stop
        log(f"error: {exc}")
        emit()
        raise SystemExit(0)
