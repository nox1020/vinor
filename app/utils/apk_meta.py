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


_RES_STRING_POOL = 0x0001
_RES_XML_RESOURCE_MAP = 0x0180
_RES_XML_START_ELEMENT = 0x0102
_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11
_ATTR_VERSION_CODE = 0x0101021B
_ATTR_VERSION_NAME = 0x0101021C


def version_code_from_name(version: str) -> int:
    """همان فرمول Gradle وینور: MMmmpp — مثلاً 1.0.4 → 10004، 1.0.272 → 10272."""
    parts: List[int] = []
    for piece in str(version or "").strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[0], parts[1], parts[2]
    code = major * 10000 + minor * 100 + patch
    return code if code > 0 else 0


def _u16(data: bytes, off: int) -> int:
    if off + 2 > len(data):
        return 0
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    if off + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, off)[0]


def _s32(data: bytes, off: int) -> int:
    if off + 4 > len(data):
        return -1
    return struct.unpack_from("<i", data, off)[0]


def _decode_string_pool_at(data: bytes, off: int) -> List[str]:
    if off + 28 > len(data):
        return []
    stype = _u16(data, off)
    sheader = _u16(data, off + 2)
    ssize = _u32(data, off + 4)
    if stype != _RES_STRING_POOL or sheader < 28 or ssize < sheader:
        return []
    string_count = _u32(data, off + 8)
    flags = _u32(data, off + 16)
    strings_start = _u32(data, off + 20)
    is_utf8 = bool(flags & (1 << 8))
    offsets_base = off + sheader
    strings_base = off + strings_start
    out: List[str] = []
    for i in range(min(string_count, 20000)):
        opos = offsets_base + i * 4
        if opos + 4 > len(data):
            break
        rel = _u32(data, opos)
        spos = strings_base + rel
        if spos >= len(data):
            continue
        try:
            if is_utf8:
                p = spos
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
                (char_len,) = struct.unpack_from("<H", data, spos)
                if char_len & 0x8000:
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
            else:
                out.append("")
        except Exception:
            out.append("")
    return out


def _parse_axml_version_meta(data: bytes) -> tuple[str, int]:
    """(versionName, versionCode) از AndroidManifest باینری."""
    if len(data) < 8:
        return "", 0
    xml_hs = _u16(data, 2)
    xml_size = _u32(data, 4)
    if xml_hs < 8 or xml_size > len(data):
        xml_size = len(data)
    strings: List[str] = []
    resource_ids: List[int] = []
    version_name = ""
    version_code = 0
    off = xml_hs
    while off + 8 <= len(data) and off < xml_size:
        ctype = _u16(data, off)
        csize = _u32(data, off + 4)
        if csize < 8 or off + csize > len(data):
            break
        if ctype == _RES_STRING_POOL:
            decoded = _decode_string_pool_at(data, off)
            if decoded:
                strings = decoded
        elif ctype == _RES_XML_RESOURCE_MAP:
            n = (csize - 8) // 4
            resource_ids = [_u32(data, off + 8 + i * 4) for i in range(max(0, n))]
        elif ctype == _RES_XML_START_ELEMENT:
            hs = _u16(data, off + 2)
            attr_ext = off + hs
            if attr_ext + 20 <= off + csize:
                attr_start = _u16(data, attr_ext + 8)
                attr_size = _u16(data, attr_ext + 10) or 20
                attr_count = _u16(data, attr_ext + 12)
                attr_ptr = attr_ext + attr_start
                for _ in range(attr_count):
                    if attr_ptr + 20 > off + csize:
                        break
                    name_idx = _s32(data, attr_ptr + 4)
                    raw_idx = _s32(data, attr_ptr + 8)
                    data_type = data[attr_ptr + 15]
                    typed = _u32(data, attr_ptr + 16)
                    res_id = resource_ids[name_idx] if 0 <= name_idx < len(resource_ids) else 0
                    name_str = strings[name_idx] if 0 <= name_idx < len(strings) else ""
                    if res_id == _ATTR_VERSION_CODE or name_str == "versionCode":
                        if data_type in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                            version_code = int(typed)
                        elif data_type == _TYPE_STRING and 0 <= typed < len(strings):
                            digits = "".join(ch for ch in strings[typed] if ch.isdigit())
                            if digits:
                                version_code = int(digits)
                    if res_id == _ATTR_VERSION_NAME or name_str == "versionName":
                        idx = raw_idx if raw_idx >= 0 else typed
                        if data_type == _TYPE_STRING:
                            if 0 <= typed < len(strings) and strings[typed]:
                                version_name = strings[typed]
                            elif 0 <= idx < len(strings) and strings[idx]:
                                version_name = strings[idx]
                    attr_ptr += attr_size if attr_size >= 20 else 20
            if version_code or version_name:
                break
        off += csize
        if off % 4:
            off += 4 - (off % 4)
    return (version_name or "").strip(), int(version_code or 0)


def extract_apk_version_meta(apk_path: str | Path, *, original_name: str = "") -> tuple[str, int]:
    """(versionName, versionCode) از APK. code=0 یعنی خوانده نشد."""
    path = Path(apk_path)
    name = ""
    code = 0
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for candidate in ("AndroidManifest.xml", "androidmanifest.xml"):
                try:
                    data = zf.read(candidate)
                except KeyError:
                    continue
                parsed_name, parsed_code = _parse_axml_version_meta(data)
                if parsed_code > 0:
                    code = parsed_code
                if parsed_name:
                    name = parsed_name
                if not name:
                    name = _pick_best_version(_versions_from_manifest_bytes(data)) or ""
                if name or code:
                    break
    except Exception:
        pass
    if not name:
        name = _version_from_filename(original_name or path.name)
    if code <= 0 and name:
        code = version_code_from_name(name)
    return name, code


def extract_apk_version_code(apk_path: str | Path) -> int:
    _name, code = extract_apk_version_meta(apk_path)
    return int(code or 0)


def extract_apk_version_name(apk_path: str | Path, *, original_name: str = "") -> str:
    """
    versionName را از AndroidManifest داخل APK می‌خواند.
    در صورت شکست، از نام فایل حدس می‌زند.
    """
    name, _code = extract_apk_version_meta(apk_path, original_name=original_name)
    return name
