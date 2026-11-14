"""A small, strict multipart/form-data parser for the screenshot upload (no python-multipart in the
lock). Pure: bytes in, file parts out. Only the parts' bytes are used; client file names and
content types are ignored."""

from __future__ import annotations

import re

MAX_PARTS = 40
_BOUNDARY_RE = re.compile(r'boundary="?([^";]{1,70})"?', re.IGNORECASE)
_NAME_RE = re.compile(r'(?:^|;)\s*name="([^"]*)"', re.IGNORECASE)


class MultipartError(ValueError):
    pass


def boundary(content_type: str | None) -> bytes:
    ct = content_type or ""
    if not ct.lower().startswith("multipart/form-data"):
        raise MultipartError("expected multipart/form-data")
    m = _BOUNDARY_RE.search(ct)
    if not m:
        raise MultipartError("multipart boundary missing")
    return m.group(1).encode("latin-1")


def file_parts(body: bytes, content_type: str | None, field: str = "file") -> list[bytes]:
    """Bytes of every part whose form field name is `field`. Other fields are ignored."""
    delim = b"--" + boundary(content_type)
    if not body.startswith(delim):
        # tolerate a preamble, as RFC 2046 allows
        i = body.find(b"\r\n" + delim)
        if i < 0:
            raise MultipartError("malformed multipart body")
        body = body[i + 2 :]
    chunks = body.split(b"\r\n" + delim)
    # chunks[0] starts with delim + CRLF; the last chunk is "--" (+ epilogue)
    first = chunks[0][len(delim) :]
    chunks = [first, *chunks[1:]]
    if not chunks[-1].startswith(b"--"):
        raise MultipartError("multipart body not terminated")
    parts = chunks[:-1]
    if len(parts) > MAX_PARTS:
        raise MultipartError(f"too many parts (max {MAX_PARTS})")
    out = []
    for part in parts:
        if not part.startswith(b"\r\n"):
            raise MultipartError("malformed multipart part")
        head, sep, data = part[2:].partition(b"\r\n\r\n")
        if not sep:
            raise MultipartError("malformed multipart part headers")
        disposition = ""
        for line in head.split(b"\r\n"):
            key, _, value = line.decode("latin-1").partition(":")
            if key.strip().lower() == "content-disposition":
                disposition = value
        m = _NAME_RE.search(disposition)
        if m and m.group(1) == field:
            out.append(data)
    return out
