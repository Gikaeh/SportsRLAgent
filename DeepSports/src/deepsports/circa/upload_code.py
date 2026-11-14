"""The LAN upload code for the temporary /circa page (home Wi-Fi, until BetDesk is deployed).

8 random digits kept in `~/.config/deepsports/circa-upload-code` (mode 600; env
DEEPSPORTS_CIRCA_CODE_FILE). Never logged, printed or returned by the server; only
`deepsports circa code`, run by the owner in their own terminal, shows it.
"""

from __future__ import annotations

import contextlib
import hmac
import os
import secrets
import tempfile
import time
from collections import deque
from pathlib import Path

HEADER = "x-circa-upload-code"
MAX_FAILURES = 10
FAILURE_WINDOW = 600.0  # seconds


def code_file() -> Path:
    default = Path.home() / ".config" / "deepsports" / "circa-upload-code"
    return Path(os.environ.get("DEEPSPORTS_CIRCA_CODE_FILE", default))


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _new_code() -> str:
    d = f"{secrets.randbelow(10**8):08d}"
    return f"{d[:4]} {d[4:]}"


def _write(path: Path, code: str, exclusive: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(code + "\n")
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".circa-code-")  # mkstemp: mode 600
    with os.fdopen(fd, "w") as f:
        f.write(code + "\n")
    os.replace(tmp, path)


def get_code(create: bool = True) -> str | None:
    """The code as typed ("1234 5678"); creates the file on first use."""
    path = code_file()
    try:
        code = path.read_text().strip()
    except FileNotFoundError:
        if not create:
            return None
        with contextlib.suppress(FileExistsError):  # created by another process meanwhile
            _write(path, _new_code(), exclusive=True)
        code = path.read_text().strip()
    return code if len(_digits(code)) == 8 else None


def rotate() -> str:
    code = _new_code()
    _write(code_file(), code, exclusive=False)
    return code


def matches(given: str | None) -> bool:
    if not given:
        return False
    expected = get_code()
    if expected is None:
        return False
    return hmac.compare_digest(_digits(given).encode(), _digits(expected).encode())


class FailureLimiter:
    """Wrong codes per client IP: MAX_FAILURES within FAILURE_WINDOW seconds -> limited."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.failures: dict[str, deque[float]] = {}

    def _recent(self, ip: str) -> deque[float]:
        q = self.failures.setdefault(ip, deque())
        cutoff = self.clock() - FAILURE_WINDOW
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self.failures.pop(ip, None)
        return q

    def limited(self, ip: str) -> bool:
        return len(self._recent(ip)) >= MAX_FAILURES

    def fail(self, ip: str) -> None:
        self._recent(ip)
        self.failures.setdefault(ip, deque()).append(self.clock())
