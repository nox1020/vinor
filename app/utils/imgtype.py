"""Image type sniffing compatible with the stdlib ``imghdr`` module.

``imghdr`` was removed in Python 3.13. When it exists we keep using it so
behaviour is unchanged; otherwise a small port of its checks is used.
"""
from __future__ import annotations

try:  # Python <= 3.12
    import imghdr as _imghdr  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    _imghdr = None


def _sniff(h: bytes):
    if h[6:10] in (b"JFIF", b"Exif") or h[:4] == b"\xff\xd8\xff\xdb":
        return "jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:2] in (b"MM", b"II"):
        return "tiff"
    if h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "webp"
    if h.startswith(b"BM"):
        return "bmp"
    if h.startswith(b"\x76\x2f\x31\x01"):
        return "exr"
    return None


def what(file, h: bytes | None = None):
    """Same signature/semantics as ``imghdr.what``."""
    if _imghdr is not None:
        return _imghdr.what(file, h)
    if h is None:
        if isinstance(file, (str, bytes)) or hasattr(file, "__fspath__"):
            with open(file, "rb") as f:
                h = f.read(32)
        else:
            pos = file.tell()
            h = file.read(32)
            file.seek(pos)
    return _sniff(bytes(h[:32]))
