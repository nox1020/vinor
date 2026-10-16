#!/usr/bin/env python3
"""Commit leftover work on a feature branch and push that branch when the agent stops.

Never pushes main or master. A rejected push is reported on stderr and exits
non-zero. This is a Cursor ``stop`` hook: stdout is a JSON object with an
optional ``followup_message`` (https://cursor.com/docs/hooks)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from ci_watch import snapshot_ci  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CI_FOLLOWUP = (
    "After this push, run `python .cursor/hooks/ci_watch.py --wait` in this repo. "
    "If it reports failure, read the FAILED_JOB log file, fix the root cause "
    "(do not weaken or skip the workflow), commit, push, and repeat until green. "
    "If CI_STATE is none, no workflow ran for this commit — stop. "
    "If blocked by missing secrets/auth, report that and stop."
)
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


REFUSAL = "auto_push: refusing to push main; use a PR branch"
PROTECTED_BRANCHES = {"main", "master"}


def log(message: str) -> None:
    print(f"[auto-push] {message}", file=sys.stderr, flush=True)


def fail(message: str) -> int:
    """Surface a push failure. Exit non-zero so a rejected push is not silent."""
    print(message, file=sys.stderr, flush=True)
    emit(message)
    return 1


def emit(followup: str | None = None) -> None:
    payload: dict[str, str] = {}
    if followup:
        payload["followup_message"] = followup
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    if any(arg in {"--force", "--force-with-lease", "-f"} for arg in args):
        raise RuntimeError("auto_push: force-push is not allowed")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        env=env,
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


def current_branch() -> str | None:
    symbolic = git("symbolic-ref", "-q", "HEAD")
    if symbolic.returncode != 0:
        return None
    ref = symbolic.stdout.strip()
    prefix = "refs/heads/"
    if not ref.startswith(prefix):
        return None
    branch = ref[len(prefix):]
    return branch or None


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

    loop_count = int(payload.get("loop_count") or 0)
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
        return fail("auto_push: refusing to push during merge/rebase")

    # main is protected (PR-only). Detached HEAD has no branch to publish.
    # Do not fetch, commit, or push in either case.
    branch = current_branch()
    if branch is None or branch in PROTECTED_BRANCHES:
        return fail(REFUSAL)

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

    fetch = git("fetch", "origin")
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout or "fetch failed").strip()
        return fail(f"auto_push: fetch failed: {detail}")

    # Same branch only. -u sets upstream on the first push. Never --force.
    destination = f"HEAD:refs/heads/{branch}"
    if destination in {"HEAD:refs/heads/main", "HEAD:refs/heads/master"}:
        return fail(REFUSAL)
    push = git("push", "-u", "origin", destination)
    if push.returncode != 0:
        detail = (push.stderr or push.stdout or "push failed").strip()
        return fail(f"auto_push: push rejected: {detail}")

    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if ahead.returncode != 0:
        detail = (ahead.stderr or ahead.stdout or "upstream check failed").strip()
        return fail(f"auto_push: upstream check failed: {detail}")
    ahead_count = ahead.stdout.strip() or "0"
    if ahead_count != "0":
        return fail(
            f"auto_push: branch still ahead of upstream after push ({ahead_count} commits)"
        )
    log(f"pushed origin/{branch}")
    did_push = True

    followup = None
    if loop_count < 8:
        ci = snapshot_ci(allow_git_credential=False)
        state = str(ci.get("state") or "unknown")
        log(f"ci state={state}")
        if did_push or state in {"pending", "failure"}:
            followup = CI_FOLLOWUP
        elif state == "unknown" and loop_count == 0:
            followup = CI_FOLLOWUP
    emit(followup)
    return 0


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — a failed push must not look like success
        print(f"auto_push: error: {exc}", file=sys.stderr, flush=True)
        emit(f"auto_push: error: {exc}")
        raise SystemExit(1)
