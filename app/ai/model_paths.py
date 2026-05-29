"""مسیر مدل GGUF آفلاین — پوشه ai_models در ریشه پروژه."""
from __future__ import annotations

import json
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_MODELS_DIR = _PROJECT_ROOT / "ai_models"
MANIFEST_PATH = AI_MODELS_DIR / "model_manifest.json"

DEFAULT_MANIFEST = {
    "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "repo_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    "hf_file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "size_bytes": 491400032,
    "bundled": True,
}


def load_manifest() -> dict:
    if MANIFEST_PATH.is_file():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_MANIFEST, **data}
        except Exception:
            pass
    return dict(DEFAULT_MANIFEST)


def model_file_path() -> Path:
    manifest = load_manifest()
    return AI_MODELS_DIR / str(manifest["filename"])


def ensure_ai_models_dir() -> Path:
    AI_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return AI_MODELS_DIR


def model_is_ready(min_ratio: float = 0.98) -> bool:
    path = model_file_path()
    if not path.is_file():
        return False
    expected = int(load_manifest().get("size_bytes") or 0)
    if expected <= 0:
        return path.stat().st_size > 1_000_000
    return path.stat().st_size >= int(expected * min_ratio)
