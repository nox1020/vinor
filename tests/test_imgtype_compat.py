"""imghdr was removed in Python 3.13; app.utils.imgtype must still detect types."""
from app.utils import imgtype

SAMPLES = {
    "jpeg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20,
    "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,
    "gif": b"GIF89a" + b"\x00" * 20,
    "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 20,
}


def test_detects_common_types_both_paths(monkeypatch):
    for kind, raw in SAMPLES.items():
        assert imgtype.what(None, raw) == kind
    monkeypatch.setattr(imgtype, "_imghdr", None)
    for kind, raw in SAMPLES.items():
        assert imgtype.what(None, raw) == kind
    assert imgtype.what(None, b"not an image at all") is None
