# -*- coding: utf-8 -*-
"""Revision reported by GET /version.

SHA resolution (first valid 7–40 hex wins):

1. ``<instance_path>/deploy/current_sha``
2. env ``VINOR_DEPLOYED_SHA``
3. ``.git`` HEAD, loose refs, then packed-refs (no subprocess)
4. ``unknown``

The result is cached per instance path. The ``current_sha`` file is stat'd on
each call and re-read when its mtime changes, so a deploy can publish a new
SHA without restarting the process.

Web ``version`` is the commit count of HEAD (monotonic, changes on every new
commit). ``version.txt`` is used only when that count cannot be read.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

_HEX_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
# instance path -> (current_sha mtime_ns or None, env token, payload)
_CACHE: dict[str, tuple[int | None, str, dict]] = {}


def release_payload(instance_path: str | os.PathLike, repo_root: str | os.PathLike | None = None) -> dict:
    """JSON-ready ``sha`` / optional ``full_sha`` / ``version`` for this process."""
    instance = os.path.abspath(instance_path)
    root = os.path.abspath(repo_root) if repo_root is not None else str(_REPO_ROOT)
    sha_file = os.path.join(instance, "deploy", "current_sha")
    token = _cache_token(sha_file)
    with _LOCK:
        hit = _CACHE.get(instance)
        if hit is not None and hit[0] == token[0] and hit[1] == token[1]:
            return dict(hit[2])
    payload = _build_payload(sha_file, root)
    with _LOCK:
        _CACHE[instance] = (token[0], token[1], payload)
    return dict(payload)


def _cache_token(sha_file: str) -> tuple[int | None, str]:
    mtime: int | None
    try:
        mtime = os.stat(sha_file).st_mtime_ns
    except OSError:
        mtime = None
    env = (os.environ.get("VINOR_DEPLOYED_SHA") or "").strip()
    return mtime, env


def _build_payload(sha_file: str, repo_root: str) -> dict:
    raw = (
        _read_sha_file(sha_file)
        or _valid_sha(os.environ.get("VINOR_DEPLOYED_SHA") or "")
        or _read_git_sha(repo_root)
    )
    payload: dict[str, str] = {"sha": raw[:7] if raw else "unknown"}
    if raw and len(raw) > 7:
        payload["full_sha"] = raw
    payload["version"] = _web_version(repo_root)
    return payload


def _valid_sha(text: str) -> str | None:
    candidate = (text or "").strip().lower()
    if _HEX_SHA.fullmatch(candidate):
        return candidate
    return None


def _read_sha_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(256)
    except OSError:
        return None
    return _valid_sha(text)


def _web_version(repo_root: str) -> str:
    count = _commit_count(repo_root)
    if count is not None:
        return str(count)
    fallback = _read_version_file(repo_root)
    return fallback if fallback else "unknown"


def _commit_count(repo_root: str) -> int | None:
    git_marker = os.path.join(repo_root, ".git")
    if not (os.path.isdir(git_marker) or os.path.isfile(git_marker)):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    if text.isdigit():
        return int(text)
    return None


def _read_version_file(repo_root: str) -> str | None:
    path = os.path.join(repo_root, "version.txt")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            line = handle.readline()
    except OSError:
        return None
    text = line.strip()
    if not text or len(text) > 64 or any(ord(ch) < 32 for ch in text):
        return None
    return text


def _read_git_sha(repo_root: str) -> str | None:
    git_dir = _resolve_git_dir(Path(repo_root) / ".git")
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        return _resolve_ref(git_dir, ref, depth=0)
    return _valid_sha(head)


def _resolve_git_dir(git_path: Path) -> Path | None:
    if git_path.is_dir():
        return git_path
    if not git_path.is_file():
        return None
    try:
        line = git_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    raw = line.split(":", 1)[1].strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (git_path.parent / candidate).resolve()
    return candidate if candidate.is_dir() else None


def _common_dir(git_dir: Path) -> Path | None:
    marker = git_dir / "commondir"
    if not marker.is_file():
        return None
    try:
        raw = marker.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (git_dir / candidate).resolve()
    return candidate if candidate.is_dir() else None


def _resolve_ref(git_dir: Path, ref: str, depth: int) -> str | None:
    if depth > 5:
        return None
    found = _read_ref_file(git_dir, ref)
    if found is None:
        common = _common_dir(git_dir)
        if common is not None and common != git_dir:
            found = _read_ref_file(common, ref)
    if found is None:
        return None
    if found.startswith("ref:"):
        nxt = found.split(":", 1)[1].strip()
        return _resolve_ref(git_dir, nxt, depth + 1)
    return _valid_sha(found)


def _read_ref_file(git_dir: Path, ref: str) -> str | None:
    if not ref or ref.startswith("/") or ".." in Path(ref).parts:
        return None
    root = git_dir.resolve()
    ref_path = (git_dir / ref).resolve()
    if not _is_relative_to(ref_path, root):
        return None
    if ref_path.is_file():
        try:
            return ref_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
    packed = git_dir / "packed-refs"
    if not packed.is_file():
        return None
    try:
        lines = packed.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line[0] in "#^":
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            return parts[0].strip()
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
