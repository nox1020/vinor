# -*- coding: utf-8 -*-
"""استخراج متادیتای APK — نسخه از AndroidManifest بدون وابستگی خارجی."""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional

_VERSION_RE = re.compile(r"^(?:\d+)(?:\.\d+){1,3}$")
_VERSION_FIND_RE = re.compile(r"(?<![0-9.])(\d+\.\d+(?:\.\d+){0,3})(?![0-9.])")
_RES_STRING_POOL_TYPE = 0x0001


def _decode_axml_string_pool(data: bytes) -> List[str]:
    """خواندن string pool باینری AXML (AndroidManifest)."""
    if len(data) < 8:
        return []
    # XML header chunk
    try:
        _ctype, header_size, chunk_size = struct.unpack_from("<HHI", data, 0)
    except struct.error:
        return []
    if header_size < 8 or chunk_size > len(data):
        return []
    # String pool usually follows XML header
    off = header_size
    if off + 8 > len(data):
        return []
    try:
        stype, sheader, ssize = struct.unpack_from("<HHI", data, off)
    except struct.error:
        return []
    if stype != _RES_STRING_POOL_TYPE or sheader < 28 or ssize < sheader:
        return []
    try:
        string_count, _style_count, flags, strings_start, _styles_start = struct.unpack_from(
            "<IIIII", data, off + 8
        )
    except struct.error:
        return []
    is_utf8 = bool(flags & (1 << 8))
    offsets_base = off + sheader
    strings_base = off + strings_start
    out: List[str] = []
    for i in range(min(string_count, 20000)):
        opos = offsets_base + i * 4
        if opos + 4 > len(data):
            break
        try:
            (rel,) = struct.unpack_from("<I", data, opos)
        except struct.error:
            break
        spos = strings_base + rel
        if spos >= len(data):
            continue
        try:
            if is_utf8:
                # u16 char len, u16 byte len (each may be 1 or 2 bytes encoded)
                p = spos
                if p >= len(data):
                    continue
                char_len = data[p]
                p += 1
                if char_len & 0x80:
                    if p >= len(data):
                        continue
                    char_len = ((char_len & 0x7F) << 8) | data[p]
                    p += 1
                if p >= len(data):
                    continue
                byte_len = data[p]
                p += 1
                if byte_len & 0x80:
                    if p >= len(data):
                        continue
                    byte_len = ((byte_len & 0x7F) << 8) | data[p]
                    p += 1
                end = min(p + byte_len, len(data))
                s = data[p:end].decode("utf-8", errors="ignore")
            else:
                if spos + 2 > len(data):
                    continue
                (char_len,) = struct.unpack_from("<H", data, spos)
                # high bit may mark extended length
                if char_len & 0x8000:
                    if spos + 4 > len(data):
                        continue
                    (char_len2,) = struct.unpack_from("<H", data, spos + 2)
                    char_len = ((char_len & 0x7FFF) << 16) | char_len2
                    p = spos + 4
                else:
                    p = spos + 2
                end = min(p + char_len * 2, len(data))
                s = data[p:end].decode("utf-16le", errors="ignore")
            s = (s or "").strip("\x00").strip()
            if s:
                out.append(s)
        except Exception:
            continue
    return out


def _pick_best_version(candidates: Iterable[str]) -> str:
    scored: List[tuple[tuple[int, int, int], str]] = []
    for raw in candidates:
        s = str(raw or "").strip()
        if not s or not _VERSION_RE.match(s):
            continue
        parts = [int(p) for p in s.split(".")]
        # prefer more segments, then lexicographic version
        key = (len(parts), parts[0] if parts else 0, sum(parts))
        scored.append((key, s))
    if not scored:
        return ""
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1]


def _versions_from_manifest_bytes(data: bytes) -> List[str]:
    found: List[str] = []
    for s in _decode_axml_string_pool(data):
        if _VERSION_RE.match(s):
            found.append(s)
    if found:
        return found
    # fallback: UTF-16LE scan (versionName is often UTF-16 in binary XML)
    text = data.decode("utf-16le", errors="ignore")
    return _VERSION_FIND_RE.findall(text)


def _version_from_filename(name: str) -> str:
    base = Path(name or "").name
    m = re.search(r"(?<![0-9.])(\d+\.\d+(?:\.\d+){1,2})(?![0-9.])", base)
    return (m.group(1) if m else "").strip()


def extract_apk_version_name(apk_path: str | Path, *, original_name: str = "") -> str:
    """
    versionName را از AndroidManifest داخل APK می‌خواند.
    در صورت شکست، از نام فایل حدس می‌زند.
    """
    path = Path(apk_path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            # primary
            for candidate in ("AndroidManifest.xml", "androidmanifest.xml"):
                try:
                    data = zf.read(candidate)
                except KeyError:
                    continue
                ver = _pick_best_version(_versions_from_manifest_bytes(data))
                if ver:
                    return ver
    except Exception:
        pass
    return _version_from_filename(original_name or path.name)
