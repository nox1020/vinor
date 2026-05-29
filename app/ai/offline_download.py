"""دانلود مدل GGUF به ai_models/ — HuggingFace یا HTTP مستقیم."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import requests

from .model_paths import ensure_ai_models_dir, load_manifest, model_file_path


def _log(msg: str) -> None:
    try:
        from flask import current_app

        current_app.logger.info("[AI offline] %s", msg)
    except Exception:
        print(f"[AI offline] {msg}")


def _download_hf_hub(dest) -> bool:
    manifest = load_manifest()
    repo_id = str(manifest.get("repo_id") or "")
    hf_file = str(manifest.get("hf_file") or manifest.get("filename") or "")
    if not repo_id or not hf_file:
        return False
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return False
    try:
        cached = hf_hub_download(repo_id=repo_id, filename=hf_file)
        cached_path = Path(cached)
        if not cached_path.is_file():
            return False
        if cached_path.resolve() != dest.resolve():
            shutil.copy2(cached_path, dest)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception as exc:
        _log(f"hf_hub_download failed: {exc}")
        return False


def _download_http(dest, url: str, expected_size: int = 0) -> bool:
    tmp = dest.with_suffix(dest.suffix + ".part")
    headers: dict[str, str] = {}
    mode = "wb"
    downloaded = 0
    if tmp.is_file():
        downloaded = tmp.stat().st_size
        if expected_size and downloaded >= expected_size:
            tmp.replace(dest)
            return True
        headers["Range"] = f"bytes={downloaded}-"
        mode = "ab"

    try:
        with requests.get(url, stream=True, timeout=120, headers=headers) as resp:
            if resp.status_code not in (200, 206):
                _log(f"HTTP {resp.status_code} for {url}")
                return False
            with open(tmp, mode) as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        if expected_size and tmp.stat().st_size < int(expected_size * 0.98):
            _log(f"incomplete download: {tmp.stat().st_size} / {expected_size}")
            return False
        tmp.replace(dest)
        return True
    except Exception as exc:
        _log(f"HTTP download failed: {exc}")
        return False


def ensure_model_file(on_progress: Callable[[str], None] | None = None) -> bool:
    """اگر مدل نباشد دانلود می‌کند. True = فایل آماده."""
    from .model_paths import model_is_ready

    if model_is_ready():
        return True

    ensure_ai_models_dir()
    manifest = load_manifest()
    dest = Path(model_file_path())
    repo_id = str(manifest.get("repo_id") or "")
    filename = str(manifest.get("filename") or manifest.get("hf_file") or "")
    hf_file = str(manifest.get("hf_file") or filename)
    expected = int(manifest.get("size_bytes") or 0)
    part = dest.with_suffix(dest.suffix + ".part")

    if on_progress:
        on_progress("checking model")

    if part.is_file() and expected and part.stat().st_size >= int(expected * 0.98):
        try:
            part.replace(dest)
            _log(f"resumed partial download: {dest.name}")
            return model_is_ready()
        except Exception as exc:
            _log(f"finalize partial failed: {exc}")

    if dest.is_file() and expected and dest.stat().st_size >= int(expected * 0.98):
        return True

    if on_progress:
        on_progress("downloading model")

    if repo_id and hf_file:
        url = f"https://huggingface.co/{repo_id}/resolve/main/{hf_file}"
        if _download_http(dest, url, expected):
            _log(f"model ready via HTTP: {dest.name}")
            return model_is_ready()

    if not model_is_ready() and _download_hf_hub(dest):
        _log(f"model ready via huggingface_hub: {dest.name}")
        return model_is_ready()

    return model_is_ready()
