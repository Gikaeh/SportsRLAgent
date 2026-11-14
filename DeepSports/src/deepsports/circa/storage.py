"""Screenshot storage: validate an image, save it under today's folder, ingest the iCloud inbox.

Every path is server-chosen: `<CIRCA_SCREENSHOTS_DIR>/<YYYY-MM-DD>/<HHMMSS>-<n>.<ext>` (local
date and time). Nothing a client sends (file name, content type) reaches the file system. Never
touches DuckDB.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from deepsports import config

MAX_BYTES = 10 * 1024 * 1024  # per file
MAX_PER_DAY = 30
EXTENSIONS = ("png", "jpg", "webp")
NAME_RE = re.compile(r"^\d{6}-\d{1,3}\.(png|jpg|webp)$")
SIPS = "/usr/bin/sips"
SIPS_TIMEOUT = 60

_save_lock = threading.Lock()  # the API may get two uploads at once; count + name under one lock


class RejectedImage(ValueError):
    """Not an accepted image. `code` is the API error code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class DailyLimit(RejectedImage):
    pass


class DriveUnavailable(OSError):
    """The Circa folder is on an external volume that isn't mounted."""


def require_mounted(path: Path) -> Path:
    """Refuse to create folders under /Volumes/<name> when that volume isn't mounted (a mkdir there
    would land on the internal disk)."""
    parts = path.resolve().parts if path.exists() else path.parts
    if len(parts) > 2 and parts[1] == "Volumes" and not os.path.ismount(f"/Volumes/{parts[2]}"):
        raise DriveUnavailable(f"/Volumes/{parts[2]} is not mounted (external drive?)")
    return path


def today() -> date:
    return datetime.now(config.LOCAL_TZ).date()


def day_dir(day: date) -> Path:
    return config.CIRCA_SCREENSHOTS_DIR / day.isoformat()


def sniff(data: bytes) -> str | None:
    """Image kind from the magic bytes: png | jpg | webp | heic, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
        and data[8:12]
        in (
            b"heic",
            b"heix",
            b"heim",
            b"heis",
            b"hevc",
            b"hevx",
            b"mif1",
            b"msf1",
        )
    ):
        return "heic"
    return None


def heic_to_jpeg(data: bytes) -> bytes:
    """Convert with macOS `sips` in a temp dir on the internal disk (under launchd only uv's Python
    may write to the drive, so the caller writes the result). Raises RejectedImage if it can't."""
    if not Path(SIPS).exists():
        raise RejectedImage("unsupported_type", "HEIC needs macOS sips; send PNG or JPEG instead")
    with tempfile.TemporaryDirectory(prefix="circa-heic-") as tmp:
        src, out = Path(tmp) / "in.heic", Path(tmp) / "out.jpg"
        src.write_bytes(data)
        try:
            subprocess.run(
                [SIPS, "-s", "format", "jpeg", str(src), "--out", str(out)],
                check=True,
                capture_output=True,
                timeout=SIPS_TIMEOUT,
            )
            converted = out.read_bytes()
        except (OSError, subprocess.SubprocessError) as e:
            raise RejectedImage(
                "unsupported_type", "couldn't convert HEIC; send PNG or JPEG"
            ) from e
    if sniff(converted) != "jpg":
        raise RejectedImage("unsupported_type", "couldn't convert HEIC; send PNG or JPEG")
    return converted


def validate(data: bytes) -> tuple[bytes, str]:
    """(bytes to store, extension). HEIC becomes JPEG. Raises RejectedImage."""
    if not data:
        raise RejectedImage("empty_file", "empty file")
    if len(data) > MAX_BYTES:
        raise RejectedImage("file_too_large", f"over {MAX_BYTES // (1024 * 1024)} MB")
    kind = sniff(data)
    if kind == "heic":
        data, kind = heic_to_jpeg(data), "jpg"
        if len(data) > MAX_BYTES:
            raise RejectedImage("file_too_large", "over 10 MB after HEIC conversion")
    if kind not in EXTENSIONS:
        raise RejectedImage("unsupported_type", "not a PNG, JPEG, WebP or HEIC image")
    return data, kind


def list_day(day: date) -> list[Path]:
    """The day's saved screenshots, oldest first (names sort by time)."""
    d = day_dir(day)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and NAME_RE.match(p.name))


def _check_room(day: date, adding: int) -> list[Path]:
    existing = list_day(day)
    if len(existing) + adding > MAX_PER_DAY:
        raise DailyLimit(
            "daily_limit", f"{len(existing)} saved today; at most {MAX_PER_DAY} per day"
        )
    return existing


@contextmanager
def _day_lock(d: Path):
    """Thread lock + an flock on `<day dir>/.lock`, so the API and a CLI ingest never race."""
    with _save_lock, open(d / ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _create_exclusive(d: Path, stamp: str, n: int, ext: str, data: bytes) -> tuple[str, int]:
    """Write with O_CREAT|O_EXCL, moving to the next n if the name is taken."""
    for _ in range(1000):
        name = f"{stamp}-{n}.{ext}"
        try:
            fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return name, n
    raise FileExistsError(f"no free name for {stamp}-* in {d}")


def save_images(images: list[bytes], day: date | None = None) -> list[dict]:
    """Size and daily-limit checks first (cheap), then validate all (magic bytes, HEIC via sips),
    then save all under a cross-process lock with the count re-checked (all or nothing).
    Returns [{name, bytes}]. Raises RejectedImage (or DailyLimit) without saving anything."""
    day = day or today()
    for b in images:
        if len(b) > MAX_BYTES:
            raise RejectedImage("file_too_large", f"over {MAX_BYTES // (1024 * 1024)} MB")
    _check_room(day, len(images))
    prepared = [validate(b) for b in images]
    d = require_mounted(day_dir(day))
    d.mkdir(parents=True, exist_ok=True)
    with _day_lock(d):
        existing = _check_room(day, len(prepared))
        n = max((int(p.stem.split("-")[1]) for p in existing), default=0)
        stamp = datetime.now(config.LOCAL_TZ).strftime("%H%M%S")
        saved = []
        for data, ext in prepared:
            name, n = _create_exclusive(d, stamp, n + 1, ext, data)
            saved.append({"name": name, "bytes": len(data)})
    return saved


# ---------- iCloud inbox ----------


@dataclass
class IngestResult:
    state: str  # ok | disabled | missing | blocked | error
    message: str = ""
    copied: list[str] = field(default_factory=list)  # saved names
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (inbox file, reason)
    pending_download: int = 0  # iCloud placeholders not on this Mac yet
    left_for_limit: int = 0

    def summary(self) -> str:
        if self.state != "ok":
            return f"inbox {self.state}: {self.message}"
        parts = [f"inbox: copied {len(self.copied)}"]
        if self.rejected:
            parts.append(f"rejected {len(self.rejected)} ({self.rejected[0][1]})")
        if self.pending_download:
            parts.append(f"{self.pending_download} still downloading from iCloud")
        if self.left_for_limit:
            parts.append(f"{self.left_for_limit} left in inbox (daily limit)")
        return ", ".join(parts)


BLOCKED_HELP = (
    "macOS refused access to iCloud Drive (Operation not permitted). Under launchd this needs "
    "Files and Folders / Full Disk Access for uv's Python; see docs/PIPELINE.md (Circa)."
)


def _move_unique(src: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(exist_ok=True)
    target = dest_dir / src.name
    i = 1
    while target.exists():
        target = dest_dir / f"{src.stem}-{i}{src.suffix}"
        i += 1
    shutil.move(str(src), str(target))


def ingest(day: date | None = None, inbox: str | os.PathLike | None = None) -> IngestResult:
    """Copy new images from the iCloud inbox into the day folder, then move each original to
    `done/` (or `rejected/` if it isn't an accepted image). Files beyond the daily limit stay."""
    day = day or today()
    inbox = config.CIRCA_INBOX if inbox is None else inbox
    if not str(inbox):
        return IngestResult("disabled", "DEEPSPORTS_CIRCA_INBOX is empty")
    root = Path(inbox)
    try:
        if not root.is_dir():
            if root.parent.is_dir():  # iCloud Drive is there: create the folder the phone saves to
                root.mkdir()
            else:
                return IngestResult("missing", f"{root} not found (iCloud Drive not set up?)")
        entries = sorted(root.iterdir())
    except PermissionError:
        return IngestResult("blocked", BLOCKED_HELP)
    except OSError as e:
        if e.errno == 1:  # EPERM
            return IngestResult("blocked", BLOCKED_HELP)
        return IngestResult("error", f"can't read {root}: {e}")
    res = IngestResult("ok")
    for p in entries:
        if not p.is_file():
            continue
        if p.name.startswith("."):
            if p.name.endswith(".icloud"):  # placeholder: the file is in the cloud, not here yet
                res.pending_download += 1
            continue
        try:
            if p.stat().st_size > MAX_BYTES:  # before reading it
                raise RejectedImage("file_too_large", "over 10 MB")
            data = p.read_bytes()
            res.copied += [s["name"] for s in save_images([data], day)]
            _move_unique(p, root / "done")
        except DailyLimit:
            res.left_for_limit += 1
        except FileExistsError:  # a name race we couldn't resolve: leave it for the next run
            res.left_for_limit += 1
        except RejectedImage as e:
            res.rejected.append((p.name, e.detail))
            _move_unique(p, root / "rejected")
        except PermissionError:
            return IngestResult("blocked", BLOCKED_HELP, res.copied, res.rejected)
    return res
