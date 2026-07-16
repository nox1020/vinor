from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import asdict
from typing import Any

from flask import current_app

from .models import LandDocument

_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]{2,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(str(text or ""))]


def _norm(vec: dict[str, float]) -> dict[str, float]:
    if not vec:
        return {}
    n2 = sum(v * v for v in vec.values())
    if n2 <= 0:
        return vec
    den = math.sqrt(n2)
    return {k: (v / den) for k, v in vec.items()}


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    total = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb is not None:
            total += va * vb
    return total


class LandsVectorStore:
    """Disk-persisted TF-IDF vector store for lands.json."""

    def __init__(self, index_path: str):
        self._index_path = index_path
        self._index: dict[str, Any] = {}

    def _ensure_parent(self) -> None:
        os.makedirs(os.path.dirname(self._index_path), exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if self._index:
            return self._index
        if not os.path.isfile(self._index_path):
            self._index = {}
            return self._index
        try:
            with open(self._index_path, encoding="utf-8") as f:
                self._index = json.load(f)
        except Exception:
            self._index = {}
        return self._index

    def build(self, docs: list[LandDocument], *, source_mtime: float) -> None:
        self._ensure_parent()
        df: dict[str, int] = {}
        tokens_by_code: dict[str, list[str]] = {}
        for d in docs:
            toks = _tokenize(d.text)
            tokens_by_code[d.code] = toks
            seen = set(toks)
            for t in seen:
                df[t] = df.get(t, 0) + 1
        n_docs = max(1, len(docs))
        idf = {t: math.log((1.0 + n_docs) / (1.0 + c)) + 1.0 for t, c in df.items()}
        vectors: dict[str, dict[str, float]] = {}
        meta: dict[str, dict[str, Any]] = {}
        for d in docs:
            tf: dict[str, float] = {}
            for t in tokens_by_code.get(d.code, []):
                tf[t] = tf.get(t, 0.0) + 1.0
            vec = {t: (cnt * idf.get(t, 1.0)) for t, cnt in tf.items()}
            vectors[d.code] = _norm(vec)
            meta[d.code] = asdict(d)
        payload = {
            "version": 1,
            "built_at": int(time.time()),
            "source_mtime": float(source_mtime),
            "idf": idf,
            "vectors": vectors,
            "meta": meta,
        }
        tmp = f"{self._index_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, self._index_path)
        self._index = payload

    def needs_rebuild(self, source_mtime: float) -> bool:
        idx = self._load()
        if not idx:
            return True
        try:
            return float(idx.get("source_mtime") or 0.0) < float(source_mtime)
        except Exception:
            return True

    def query(
        self,
        query_text: str,
        *,
        top_k: int,
        allowed_codes: set[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[str]:
        idx = self._load()
        if not idx:
            return []
        idf = idx.get("idf") if isinstance(idx.get("idf"), dict) else {}
        vectors = idx.get("vectors") if isinstance(idx.get("vectors"), dict) else {}
        meta = idx.get("meta") if isinstance(idx.get("meta"), dict) else {}
        q_tf: dict[str, float] = {}
        for t in _tokenize(query_text):
            q_tf[t] = q_tf.get(t, 0.0) + 1.0
        q_vec = _norm({t: c * float(idf.get(t, 1.0)) for t, c in q_tf.items()})
        if not q_vec:
            return []
        scored: list[tuple[float, str]] = []
        for code, dvec in vectors.items():
            if allowed_codes is not None and code not in allowed_codes:
                continue
            if not _meta_match(meta.get(code) or {}, metadata_filter or {}):
                continue
            sim = _dot(q_vec, dvec if isinstance(dvec, dict) else {})
            if sim <= 0:
                continue
            # Hybrid boost: direct code/title/category mention
            boost = _lexical_boost(query_text, meta.get(code) or {})
            scored.append((sim + boost, code))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [c for _, c in scored[: max(1, top_k)]]


def _lexical_boost(query: str, meta: dict[str, Any]) -> float:
    q = str(query or "").strip().lower()
    if not q:
        return 0.0
    code = str(meta.get("code") or "").lower()
    city = str(meta.get("city") or "").lower()
    location = str(meta.get("location") or "").lower()
    category = str(meta.get("category") or "").lower()
    score = 0.0
    if code and code in q:
        score += 0.2
    if city and city in q:
        score += 0.08
    if location and location in q:
        score += 0.08
    if category and category in q:
        score += 0.08
    return score


def _meta_match(meta: dict[str, Any], filt: dict[str, Any]) -> bool:
    if not filt:
        return True
    city = str(meta.get("city") or "").lower()
    category = str(meta.get("category") or "").lower()
    status = str(meta.get("status") or "").lower()
    price = int(meta.get("price_total") or 0)
    area = int(meta.get("area_total") or 0)
    tags = set(str(x).lower() for x in (meta.get("tags") or []) if str(x).strip())

    wanted_city = str(filt.get("city") or "").strip().lower()
    if wanted_city and wanted_city not in city:
        return False
    wanted_category = str(filt.get("category") or "").strip().lower()
    if wanted_category and wanted_category not in category:
        return False
    wanted_status = str(filt.get("status") or "").strip().lower()
    if wanted_status and wanted_status != status:
        return False
    max_price = int(filt.get("max_price") or 0)
    if max_price > 0 and (price <= 0 or price > max_price):
        return False
    min_price = int(filt.get("min_price") or 0)
    if min_price > 0 and price < min_price:
        return False
    min_area = int(filt.get("min_area") or 0)
    if min_area > 0 and area < min_area:
        return False
    required_tags = set(str(x).lower() for x in (filt.get("tags") or []) if str(x).strip())
    if required_tags and not (required_tags & tags):
        return False
    return True


def default_index_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "instance"))
    return os.path.join(base, "data", "rag", "lands_index.json")


def lands_source_mtime() -> float:
    try:
        from app.utils.storage import ensure_file

        path = ensure_file("LANDS_FILE", "lands.json", [])
        return os.path.getmtime(path)
    except Exception:
        return 0.0

