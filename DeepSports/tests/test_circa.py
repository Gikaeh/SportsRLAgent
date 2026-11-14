"""Circa screenshots: storage limits, multipart, the reply parser/validator, the game matcher, the
read flow with the Claude step faked, and the API. No Claude calls, no real drive."""

import json
import struct
import zlib
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepsports import config
from deepsports.api import app as app_module
from deepsports.api.live import LiveService
from deepsports.circa import load_lines, reader, storage
from deepsports.circa.lines import parse_output, validate_line
from deepsports.circa.match import load_candidates, match_game, match_lines, norm
from deepsports.circa.multipart import MultipartError, file_parts
from deepsports.parse_espn import parse_scoreboard, parse_scoreboard_teams
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"
REPLY = (FIX / "circa_claude_reply_20261108.txt").read_text()
SLATE_DAY = date(2026, 11, 8)


def png(w: int = 2, h: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def circa_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CIRCA_SCREENSHOTS_DIR", tmp_path / "circa" / "screenshots")
    monkeypatch.setattr(config, "CIRCA_LINES_DIR", tmp_path / "circa" / "lines")
    inbox = tmp_path / "icloud" / "DeepSports Circa"
    inbox.parent.mkdir()
    monkeypatch.setattr(config, "CIRCA_INBOX", str(inbox))
    monkeypatch.setattr(reader, "WORK_DIR", tmp_path / "work")
    return tmp_path


@pytest.fixture
def warehouse(tmp_path):
    raw = json.loads((FIX / "espn_ncaab_scoreboard_20261108_upcoming.json").read_text())
    games, _ = parse_scoreboard(raw, league="ncaab")
    path = tmp_path / "w.duckdb"
    st = Store(path)
    st.upsert_teams(parse_scoreboard_teams(raw, "ncaab"))
    st.upsert_games(games)
    st.close()
    return path


# ---------- storage ----------


def test_sniff_by_magic_bytes():
    assert storage.sniff(png()) == "png"
    assert storage.sniff(b"\xff\xd8\xff\xe0rest") == "jpg"
    assert storage.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert storage.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "heic"
    assert storage.sniff(b"<html>not an image") is None


def test_validate_rejects_bad_files():
    with pytest.raises(storage.RejectedImage) as e:
        storage.validate(b"GIF89a....")
    assert e.value.code == "unsupported_type"
    with pytest.raises(storage.RejectedImage) as e:
        storage.validate(b"\x89PNG\r\n\x1a\n" + b"\x00" * storage.MAX_BYTES)
    assert e.value.code == "file_too_large"
    with pytest.raises(storage.RejectedImage):
        storage.validate(b"")


def test_save_names_and_daily_limit(circa_dirs, monkeypatch):
    day = date(2026, 11, 14)
    saved = storage.save_images([png(), png()], day)
    names = [s["name"] for s in saved]
    assert all(storage.NAME_RE.match(n) for n in names)
    assert [n.split("-")[1] for n in names] == ["1.png", "2.png"]
    assert saved[0]["bytes"] == len(png())
    monkeypatch.setattr(storage, "MAX_PER_DAY", 3)
    with pytest.raises(storage.DailyLimit):
        storage.save_images([png(), png()], day)  # all or nothing
    assert len(storage.list_day(day)) == 2


def test_require_mounted_refuses_unmounted_volume():
    with pytest.raises(storage.DriveUnavailable):
        storage.require_mounted(Path("/Volumes/NoSuchDriveXYZ/DeepSports/circa"))


def test_ingest_moves_originals(circa_dirs):
    inbox = Path(config.CIRCA_INBOX)
    inbox.mkdir()
    (inbox / "IMG_0001.PNG").write_bytes(png())
    (inbox / "notes.txt").write_text("hello")
    (inbox / ".IMG_0002.PNG.icloud").write_bytes(b"x")
    res = storage.ingest(date(2026, 11, 14))
    assert res.state == "ok" and len(res.copied) == 1
    assert res.rejected == [("notes.txt", "not a PNG, JPEG, WebP or HEIC image")]
    assert res.pending_download == 1
    assert (inbox / "done" / "IMG_0001.PNG").exists()
    assert (inbox / "rejected" / "notes.txt").exists()
    assert len(storage.list_day(date(2026, 11, 14))) == 1
    assert storage.ingest(date(2026, 11, 14)).copied == []  # idempotent


def test_ingest_creates_missing_inbox_and_reports_blocked(circa_dirs, monkeypatch):
    assert storage.ingest().state == "ok"
    assert Path(config.CIRCA_INBOX).is_dir()

    def denied(self):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(Path, "iterdir", denied)
    res = storage.ingest()
    assert res.state == "blocked" and "Operation not permitted" in res.message
    assert storage.ingest(inbox="").state == "disabled"


# ---------- multipart ----------


def _multipart(files: list[bytes], field: str = "file") -> tuple[bytes, str]:
    b = "xXbOuNdArYx"
    body = b"preamble\r\n"
    for i, f in enumerate(files):
        body += (
            (
                f'--{b}\r\nContent-Disposition: form-data; name="{field}"; '
                f'filename="../../evil{i}.png"\r\nContent-Type: image/png\r\n\r\n'
            ).encode()
            + f
            + b"\r\n"
        )
    body += (
        f'--{b}\r\nContent-Disposition: form-data; name="note"\r\n\r\nhi\r\n--{b}--\r\n'.encode()
    )
    return body, f"multipart/form-data; boundary={b}"


def test_multipart_parts():
    body, ct = _multipart([png(), b"\r\n--tricky\r\n"])
    assert file_parts(body, ct) == [png(), b"\r\n--tricky\r\n"]
    with pytest.raises(MultipartError):
        file_parts(body, "application/json")
    with pytest.raises(MultipartError):
        file_parts(body[:-10], ct)


# ---------- parse + validate ----------


def test_parse_reply_fixture():
    lines, problems = parse_output(REPLY)
    assert len(lines) == 13
    by = {(ln["away"], ln["market"], ln["side"]): ln for ln in lines}
    assert by[("IONA", "spread", "home")]["line"] == -14.5  # the later -14.25 was invalid
    assert by[("SE MISSOURI ST", "spread", "home")] | {} == {
        "game_id": None,
        "league": "ncaab",
        "away": "SE MISSOURI ST",
        "home": "SOUTH CAROLINA",
        "market": "spread",
        "side": "home",
        "line": -19.5,
        "price": -115,
        "rotation": "806",
    }
    assert by[("IONA", "moneyline", "away")]["line"] is None
    assert ("HOUSTON", "spread", "home") not in by  # 9.5 / 8.5 don't mirror
    assert any("inconsistent spread" in p for p in problems)
    assert any("teamtotal" in p for p in problems)
    assert any(p.startswith("not JSON") for p in problems)


@pytest.mark.parametrize(
    "raw",
    [
        {"away": "A", "home": "B", "market": "spread", "side": "over", "line": 1.5, "price": -110},
        {"away": "A", "home": "B", "market": "total", "side": "over", "line": 15, "price": -110},
        {"away": "A", "home": "B", "market": "spread", "side": "home", "line": 1.5, "price": 50},
        {"away": "A", "home": "A", "market": "moneyline", "side": "home", "price": -110},
        {"away": "A", "home": "B", "market": "spread", "side": "home", "line": None, "price": -110},
    ],
)
def test_validate_line_rejects(raw):
    assert validate_line(raw)[0] is None


# ---------- match ----------


def test_norm_aliases():
    assert norm("Saint Mary's") == norm("ST MARYS") == "ST MARYS"
    assert norm("SE Missouri St.") == "SOUTHEAST MISSOURI ST"


def test_match_against_warehouse(warehouse):
    cands = load_candidates(SLATE_DAY, lock_wait=1, db_path=warehouse)
    assert len(cands) > 30
    game, swapped = match_game("IONA", "ST JOHNS", cands, "ncaab")
    assert game["game_id"] == "401924646" and not swapped
    lines, _ = parse_output(REPLY)
    out = {
        (ln["away"], ln["home"], ln["market"], ln["side"]): ln for ln in match_lines(lines, cands)
    }
    assert out[("IONA", "ST JOHNS", "spread", "home")]["game_id"] == "401924646"
    assert out[("SE MISSOURI ST", "SOUTH CAROLINA", "spread", "away")]["game_id"] == "401921820"
    # Circa listed the neutral-site game the other way round: names and side flip to ESPN's view
    smc = out[("SAINT MARYS", "NEVADA", "spread", "away")]
    assert smc["game_id"] == "401911453" and smc["line"] == -2.5 and smc["league"] == "ncaab"
    # "BTLR?" / "B0ISE" doesn't match by name; the rotation pair 821/822 does
    assert out[("BTLR?", "B0ISE", "total", "under")]["game_id"] == "401902277"
    assert out[("MADEUP U", "NOWHERE ST", "moneyline", "home")]["game_id"] is None


# ---------- read flow ----------


def test_read_day_with_fake_claude(circa_dirs, warehouse):
    day = storage.today()
    calls = []

    def fake_extract(images, workdir):
        calls.append([p.name for p in images])
        assert all(p.parent == workdir and p.exists() for p in images)
        return REPLY

    def cands(d):
        return load_candidates(SLATE_DAY, lock_wait=1, db_path=warehouse)

    assert reader.read_day(day, extract=fake_extract, candidates=cands).message.endswith(
        "no screenshots (inbox: copied 0)"
    )
    storage.save_images([png()], day)
    res = reader.read_day(day, extract=fake_extract, candidates=cands)
    assert res.ok and "13 lines, 12 matched" in res.message
    data = load_lines(day)
    assert data["date"] == day.isoformat() and data["files"] == calls[0]
    assert set(data["lines"][0]) == {
        "game_id", "league", "away", "home", "market", "side", "line", "price", "rotation"
    }  # fmt: skip
    assert load_lines(day.isoformat()) == data
    # nothing new: no second Claude call; --force reads again
    assert "already read" in reader.read_day(day, extract=fake_extract, candidates=cands).message
    reader.read_day(day, force=True, extract=fake_extract, candidates=cands)
    assert len(calls) == 2
    st = reader.status(day)
    assert st["count"] == 1 and st["read"]["lines"] == 13 and st["read"]["matched"] == 12
    assert list((circa_dirs / "work").iterdir()) == []  # temp work copies cleaned up


def test_read_day_failures_keep_previous(circa_dirs):
    day = storage.today()
    storage.save_images([png()], day)

    def broken(images, workdir):
        raise reader.ExtractFailed("claude timed out after 240 s")

    res = reader.read_day(day, extract=broken, candidates=lambda d: [])
    assert not res.ok and "timed out" in res.message and load_lines(day) is None
    res = reader.read_day(day, extract=lambda i, w: "sorry, I can't", candidates=lambda d: [])
    assert not res.ok and load_lines(day) is None

    def busy(d):
        raise RuntimeError("Could not set lock")

    res = reader.read_day(day, extract=lambda i, w: REPLY, candidates=busy)
    assert res.ok and "0 matched" in res.message  # lines kept, unmatched


# ---------- API ----------


@pytest.fixture
def client(circa_dirs, tmp_path, monkeypatch):
    from deepsports.api import circa as circa_api
    from deepsports.circa import upload_code

    monkeypatch.setenv("DEEPSPORTS_CIRCA_CODE_FILE", str(tmp_path / "cfg" / "circa-upload-code"))
    monkeypatch.setattr(circa_api, "_limiter", upload_code.FailureLimiter())
    monkeypatch.setattr(circa_api, "ALLOWED_HOSTS", {"testclient"})
    app = app_module.create_app(
        live=LiveService(src=object()), db_path=tmp_path / "none.duckdb", web_dist=tmp_path / "x"
    )
    return TestClient(app)


def test_api_upload_and_today(client):
    r = client.get("/api/circa/screenshots/today")
    assert r.status_code == 200 and r.json()["count"] == 0 and r.json()["read"] is None
    r = client.post(
        "/api/circa/screenshots",
        files=[("file", ("../x.png", png(), "image/png")), ("file", ("b.png", png(), "text/x"))],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today_count"] == 2 and len(body["saved"]) == 2
    assert body["saved"][0]["bytes"] == len(png()) and "/" not in body["saved"][0]["name"]
    assert set(body) == {"date", "saved", "today_count"}
    t = client.get("/api/circa/screenshots/today").json()
    assert t["count"] == 2 and t["latest_at"] and t["read"] is None


def test_api_upload_errors(client, monkeypatch):
    r = client.post("/api/circa/screenshots", files={"file": ("a.png", b"<svg/>", "image/png")})
    assert r.status_code == 415 and r.json()["error"] == "unsupported_type"
    r = client.post("/api/circa/screenshots", files={"other": ("a.png", png(), "image/png")})
    assert r.status_code == 400 and r.json()["error"] == "no_file"
    r = client.post("/api/circa/screenshots", json={"file": "x"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    monkeypatch.setattr(storage, "MAX_PER_DAY", 1)
    client.post("/api/circa/screenshots", files={"file": ("a.png", png(), "image/png")})
    r = client.post("/api/circa/screenshots", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 429 and r.json()["error"] == "daily_limit"
    from deepsports.api import circa as circa_api

    monkeypatch.setattr(circa_api, "MAX_REQUEST_BYTES", 100)
    r = client.post("/api/circa/screenshots", files={"file": ("a.png", png(64, 64), "image/png")})
    assert r.status_code == 413


def test_cli_status_json(circa_dirs, capsys):
    from deepsports import cli

    assert cli.main(["circa", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0


def test_api_upload_only_from_loopback_without_foreign_origin(client, monkeypatch):
    from deepsports.api import circa as circa_api

    files = {"file": ("a.png", png(), "image/png")}
    r = client.post(
        "/api/circa/screenshots", files=files, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    own = {"Origin": "http://localhost:8787", "Host": "localhost:8787"}
    r = client.post("/api/circa/screenshots", files=files, headers=own)
    assert r.status_code == 200  # the server's own origin, under a local host name
    # DNS rebinding: the attacker's name now points at 127.0.0.1, so Origin == Host
    evil = {"Origin": "http://evil.example:8787", "Host": "evil.example:8787"}
    r = client.post("/api/circa/screenshots", files=files, headers=evil)
    assert r.status_code == 403
    r = client.post("/api/circa/screenshots", files=files, headers={"Host": "evil.example:8787"})
    assert r.status_code == 200  # no Origin: the Worker through cloudflared
    monkeypatch.setattr(circa_api, "ALLOWED_HOSTS", {"127.0.0.1", "::1"})  # the real setting
    r = client.post("/api/circa/screenshots", files=files)  # TestClient's host is "testclient"
    assert r.status_code == 403 and r.json() == {
        "error": "forbidden",
        "detail": "a valid upload code is needed from this network",
    }
    assert client.get("/api/circa/screenshots/today").status_code == 200  # reads stay open


def test_api_upload_busy(client, monkeypatch):
    from deepsports.api import circa as circa_api

    monkeypatch.setattr(circa_api, "MAX_CONCURRENT", 0)
    r = client.post("/api/circa/screenshots", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 503 and r.json()["error"] == "busy"


def test_limits_checked_before_validate(circa_dirs, monkeypatch):
    day = date(2026, 11, 14)
    monkeypatch.setattr(storage, "MAX_PER_DAY", 1)
    storage.save_images([png()], day)

    def boom(data):
        raise AssertionError("validate (and sips) must not run")

    monkeypatch.setattr(storage, "validate", boom)
    with pytest.raises(storage.DailyLimit):
        storage.save_images([png()], day)
    with pytest.raises(storage.RejectedImage) as e:
        storage.save_images([b"\x00" * (storage.MAX_BYTES + 1)], day)
    assert e.value.code == "file_too_large"


def test_save_skips_taken_names(circa_dirs, monkeypatch):
    day = date(2026, 11, 14)

    class Frozen:
        @staticmethod
        def now(tz=None):
            from datetime import datetime

            return datetime(2026, 11, 14, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(storage, "datetime", Frozen)
    d = storage.day_dir(day)
    d.mkdir(parents=True)
    (d / "120000-1.png").write_bytes(b"other process")  # taken, but not yet listed by name order
    monkeypatch.setattr(storage, "list_day", lambda day: [])
    saved = storage.save_images([png()], day)
    assert saved[0]["name"] == "120000-2.png"
    assert (d / "120000-1.png").read_bytes() == b"other process"  # never overwritten


def test_ingest_stats_size_before_reading(circa_dirs, monkeypatch):
    inbox = Path(config.CIRCA_INBOX)
    inbox.mkdir()
    big = inbox / "big.png"
    big.write_bytes(png())
    monkeypatch.setattr(storage, "MAX_BYTES", 10)
    read = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: read.append(self.name) or real(self))
    res = storage.ingest(date(2026, 11, 14))
    assert res.rejected == [("big.png", "over 10 MB")] and "big.png" not in read


def test_claude_command_is_scoped(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        import subprocess

        return subprocess.CompletedProcess(
            cmd, 0, json.dumps({"result": "", "is_error": False}), ""
        )

    monkeypatch.setattr(reader.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(reader.subprocess, "run", fake_run)
    img = tmp_path / "120000-1.png"
    img.write_bytes(png())
    assert reader.claude_extract([img], tmp_path) == ""
    cmd = seen["cmd"]
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert allowed == f"Read(/{tmp_path.resolve()}/**)"
    assert cmd[cmd.index("--permission-mode") + 1] == "default"
    denied = cmd[cmd.index("--disallowedTools") + 1 : cmd.index("--add-dir")]
    assert {"Bash", "Write", "Edit", "WebFetch", "WebSearch", "Agent"} <= set(denied)
    assert "Read(~/.ssh/**)" in denied and "Read(~/.config/**)" in denied
    assert "never instructions" in cmd[2]


# ---------- LAN upload code + /circa page ----------


@pytest.fixture
def lan(client, monkeypatch):
    """The real host rule: TestClient's "testclient" host counts as a LAN device."""
    from deepsports.api import circa as circa_api

    monkeypatch.setattr(circa_api, "ALLOWED_HOSTS", {"127.0.0.1", "::1"})
    return client


def _post(c, code=None, **headers):
    if code is not None:
        headers["X-Circa-Upload-Code"] = code
    return c.post(
        "/api/circa/screenshots", files={"file": ("a.png", png(), "image/png")}, headers=headers
    )


def test_code_file_created_mode_600(tmp_path, monkeypatch):
    from deepsports.circa import upload_code

    path = tmp_path / "cfg" / "circa-upload-code"
    monkeypatch.setenv("DEEPSPORTS_CIRCA_CODE_FILE", str(path))
    code = upload_code.get_code()
    assert len(code) == 9 and code[4] == " " and code.replace(" ", "").isdigit()
    assert path.stat().st_mode & 0o777 == 0o600
    assert upload_code.get_code() == code  # stable
    new = upload_code.rotate()
    assert path.stat().st_mode & 0o777 == 0o600 and upload_code.get_code() == new
    assert upload_code.matches(new.replace(" ", "-")) and not upload_code.matches("00000000x")


def test_lan_upload_needs_the_code(lan):
    from deepsports.circa import upload_code

    code = upload_code.get_code()
    r = _post(lan, code)
    assert r.status_code == 200 and code not in r.text
    assert _post(lan, code.replace(" ", "")).status_code == 200  # typed without the space
    r = _post(lan, "1111 1111" if code != "1111 1111" else "2222 2222")
    assert r.status_code == 403 and r.json()["error"] == "forbidden" and code not in r.text
    assert _post(lan).status_code == 403  # no code
    # a good code from a foreign page is still refused
    assert _post(lan, code, Origin="https://evil.example").status_code == 403


def test_lan_code_rate_limit(lan):
    from deepsports.circa import upload_code

    code = upload_code.get_code()
    bad = "1111 1111" if code != "1111 1111" else "2222 2222"
    for _ in range(upload_code.MAX_FAILURES):
        assert _post(lan, bad).status_code == 403
    r = _post(lan, code)  # even the right code waits out the window
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"


def test_failure_window_expires():
    from deepsports.circa import upload_code

    now = [0.0]
    lim = upload_code.FailureLimiter(clock=lambda: now[0])
    for _ in range(upload_code.MAX_FAILURES):
        lim.fail("1.2.3.4")
    assert lim.limited("1.2.3.4") and not lim.limited("5.6.7.8")
    now[0] += upload_code.FAILURE_WINDOW + 1
    assert not lim.limited("1.2.3.4")


def test_cors_preflight_refuses_the_code_header(lan):
    r = lan.options(
        "/api/circa/screenshots",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-circa-upload-code",
        },
    )
    assert r.status_code >= 400 or "POST" not in r.headers.get("access-control-allow-methods", "")


def test_circa_page_is_self_contained(lan):
    import re

    r = lan.get("/circa")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert "<title>Circa Upload</title>" in html
    assert 'type="file" accept="image/*" multiple' in html
    assert not re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]", html, re.I)  # no external URLs
    assert "X-Circa-Upload-Code" in html and "?code" not in html


def test_cli_code_shows_and_rotates(tmp_path, monkeypatch, capsys):
    from deepsports import cli
    from deepsports.circa import upload_code

    monkeypatch.setenv("DEEPSPORTS_CIRCA_CODE_FILE", str(tmp_path / "c"))
    assert cli.main(["circa", "code"]) == 0
    first = capsys.readouterr().out
    assert upload_code.get_code() in first
    assert cli.main(["circa", "code", "--rotate"]) == 0
    assert upload_code.get_code() in capsys.readouterr().out


def test_serve_ignores_forwarded_headers(monkeypatch):
    """cloudflared sends X-Forwarded-For from 127.0.0.1; uvicorn must not swap in that address,
    or the tunnel upload loses its loopback check."""
    import uvicorn

    from deepsports import cli

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    assert cli.main(["serve"]) == 0
    assert seen["proxy_headers"] is False
