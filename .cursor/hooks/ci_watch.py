#!/usr/bin/env python3
"""Watch GitHub Actions for HEAD and print failing job logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API = "https://api.github.com"
UA = "vinor-ci-watch"


def log(message: str) -> None:
    print(f"[ci-watch] {message}", file=sys.stderr, flush=True)


def git(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        input=input_text,
    )


def git_ok(*args: str) -> str:
    result = git(*args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def origin_owner_repo() -> tuple[str, str]:
    url = git_ok("remote", "get-url", "origin")
    url = re.sub(r"\.git$", "", url.strip())
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+)$", url)
    if not match:
        raise RuntimeError(f"cannot parse GitHub origin: {url}")
    return match.group("owner"), match.group("repo")


def github_token(*, allow_git_credential: bool = True) -> str | None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ADMIN_TOKEN"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    try:
        gh = subprocess.run(
            ["gh", "auth", "token"],
            cwd=REPO,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gh = subprocess.CompletedProcess(["gh"], 1, "", "")
    if gh.returncode == 0 and gh.stdout.strip():
        return gh.stdout.strip()
    if not allow_git_credential:
        return None
    try:
        filled = subprocess.run(
            ["git", "credential", "fill"],
            cwd=REPO,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            input="protocol=https\nhost=github.com\n\n",
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return None
    if filled.returncode != 0:
        return None
    data: dict[str, str] = {}
    for line in filled.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    password = data.get("password") or ""
    username = data.get("username") or ""
    if password:
        return password
    if username.startswith(("ghp_", "github_pat_", "gho_")):
        return username
    return None


class _DropAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        from urllib.parse import urlparse

        host = urlparse(newurl).netloc.lower()
        headers_out = {"User-Agent": UA}
        if "github.com" in host:
            headers_out["Accept"] = "application/vnd.github+json"
            auth = req.get_header("Authorization")
            if auth:
                headers_out["Authorization"] = auth
        else:
            headers_out["Accept"] = "application/octet-stream"
        return urllib.request.Request(newurl, headers=headers_out)


def api_request(url: str, token: str | None, *, timeout: int = 30) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read() or b""


def log_request(url: str, token: str | None, *, timeout: int = 60) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener(_DropAuthRedirect)
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read() or b""


def _runs_for_sha(owner: str, repo: str, sha: str, token: str | None) -> list[dict[str, Any]]:
    status, body = api_request(
        f"{API}/repos/{owner}/{repo}/actions/runs?per_page=30",
        token,
    )
    if status == 401:
        raise RuntimeError("GitHub API auth failed (need gh login or GH_TOKEN)")
    if status >= 400:
        raise RuntimeError(f"GitHub API {status}: {body.decode('utf-8', 'replace')[:300]}")
    payload = json.loads(body.decode("utf-8"))
    return [run for run in payload.get("workflow_runs") or [] if str(run.get("head_sha") or "") == sha]


def snapshot_ci(
    token: str | None = None,
    *,
    allow_git_credential: bool = True,
) -> dict[str, Any]:
    """Return none | pending | failure | success | unknown for HEAD workflows."""
    try:
        owner, repo = origin_owner_repo()
        sha = git_ok("rev-parse", "HEAD")
        resolved = token if token is not None else github_token(allow_git_credential=allow_git_credential)
        if not resolved:
            return {"state": "unknown", "reason": "no-token", "sha": sha, "runs": []}
        runs = _runs_for_sha(owner, repo, sha, resolved)
        if not runs:
            return {"state": "none", "sha": sha, "runs": []}
        conclusions = [str(run.get("conclusion") or "") for run in runs]
        statuses = [str(run.get("status") or "") for run in runs]
        if any(item in {"failure", "timed_out", "cancelled"} for item in conclusions):
            state = "failure"
        elif any(item in {"queued", "in_progress", "waiting", "requested", "pending"} for item in statuses):
            state = "pending"
        elif all(item == "success" for item in conclusions):
            state = "success"
        else:
            state = "pending"
        return {"state": state, "sha": sha, "runs": runs, "owner": owner, "repo": repo}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "reason": str(exc), "runs": []}


def _error_excerpt(text: str, limit: int = 80) -> str:
    lines = text.splitlines()
    interesting = [
        line
        for line in lines
        if re.search(r"(error|failed|failure|exception|fatal|##\[error\])", line, re.I)
    ]
    chosen = interesting[-limit:] if interesting else lines[-limit:]
    return "\n".join(chosen)


def _write_log(run_id: int, name: str, text: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60]
    path = Path(tempfile.gettempdir()) / f"ci-{run_id}-{safe}.log"
    path.write_text(text, encoding="utf-8", errors="replace")
    return path


def dump_failed_logs(owner: str, repo: str, run: dict[str, Any], token: str) -> list[Path]:
    run_id = int(run["id"])
    status, body = api_request(f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs", token)
    if status >= 400:
        log(f"could not list jobs for run {run_id}: HTTP {status}")
        return []
    jobs = json.loads(body.decode("utf-8")).get("jobs") or []
    paths: list[Path] = []
    for job in jobs:
        if str(job.get("conclusion") or "") not in {"failure", "timed_out", "cancelled"}:
            continue
        job_id = int(job["id"])
        job_name = str(job.get("name") or job_id)
        log_status, log_body = log_request(
            f"{API}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            token,
            timeout=60,
        )
        text = log_body.decode("utf-8", "replace") if log_body else ""
        if log_status >= 400:
            text = f"HTTP {log_status} fetching logs for {job_name}\n{text}"
        path = _write_log(run_id, job_name, text)
        paths.append(path)
        print(f"FAILED_JOB\t{job_name}\t{path}")
        print(_error_excerpt(text))
        print("---")
    return paths


def wait_for_ci(*, timeout: int, poll: int, appear_for: int) -> int:
    token = github_token()
    if not token:
        log("no GitHub token (install GitHub CLI / set GH_TOKEN); cannot read Actions logs")
        print("CI_STATE\tunknown\tno-token")
        return 2
    owner, repo = origin_owner_repo()
    sha = git_ok("rev-parse", "HEAD")
    deadline = time.time() + timeout
    appear_deadline = time.time() + appear_for
    log(f"watching {owner}/{repo} SHA {sha[:7]} (timeout {timeout}s)")

    while time.time() < deadline:
        runs = _runs_for_sha(owner, repo, sha, token)
        if not runs:
            if time.time() < appear_deadline:
                log("no workflow run yet for this commit; waiting")
                time.sleep(poll)
                continue
            log("no workflow ran for this commit (path filters or skipped CI)")
            print("CI_STATE\tnone")
            return 0

        pending = [
            run
            for run in runs
            if str(run.get("status") or "") in {"queued", "in_progress", "waiting", "requested", "pending"}
        ]
        failed = [
            run
            for run in runs
            if str(run.get("conclusion") or "") in {"failure", "timed_out", "cancelled"}
        ]
        names = ", ".join(
            f"{run.get('name')}={run.get('status')}/{run.get('conclusion') or '-'}" for run in runs
        )
        log(names)

        if pending:
            time.sleep(poll)
            continue
        if failed:
            print("CI_STATE\tfailure")
            for run in failed:
                html = run.get("html_url") or ""
                print(f"FAILED_RUN\t{run.get('name')}\t{html}")
                dump_failed_logs(owner, repo, run, token)
            return 1
        print("CI_STATE\tsuccess")
        return 0

    log("timed out waiting for GitHub Actions")
    print("CI_STATE\tpending\ttimeout")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch GitHub Actions for the current HEAD commit")
    parser.add_argument("--wait", action="store_true", default=True, help="wait until runs finish (default)")
    parser.add_argument("--timeout", type=int, default=2400, help="seconds to wait for completion")
    parser.add_argument("--poll", type=int, default=20, help="seconds between polls")
    parser.add_argument("--appear-for", type=int, default=90, help="seconds to wait for a run to appear")
    args = parser.parse_args()
    return wait_for_ci(timeout=args.timeout, poll=args.poll, appear_for=args.appear_for)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"error: {exc}")
        print("CI_STATE\tunknown")
        raise SystemExit(2)
