"""`deepsports books grab --early`: the night-before snapshot (watch-only forward test)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from test_books import CANDS, FakeClient, _by

from deepsports.books import cli as books_cli
from deepsports.books import grab

DAY = date(2026, 11, 15)  # the fixtures' games tip on 2026-11-15 (local)


def test_early_grab_writes_the_early_file_only(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    fake = FakeClient()
    res = grab.grab_day(
        DAY,
        {"williamhill": "caesars"},
        client=fake,
        key="SECRETKEY",
        candidates=lambda d: CANDS,
        early=True,
    )
    assert res.ok, res.message
    assert res.message.startswith("books early 2026-11-15: williamhill ")
    assert (tmp_path / "williamhill" / "early" / "2026-11-15.json").exists()
    assert grab.load("williamhill", DAY) is None  # the day file the picks read is untouched
    assert grab.load_early("circa", DAY) is None
    data = grab.load_early("williamhill", DAY)
    assert set(data) == {"date", "grabbed_at", "book", "source", "source_book", "lines"}
    assert data["date"] == "2026-11-15" and data["book"] == "williamhill"
    assert data["source"] == "oddspapi" and data["source_book"] == "caesars"
    assert datetime.fromisoformat(data["grabbed_at"]).tzinfo is not None
    assert _by(data["lines"], "403", "spread", "away")["line"] == 4.5
    keys = {"game_id", "league", "away", "home", "market", "side", "line", "price", "rotation"}
    assert all(set(q) == keys for q in data["lines"])
    assert fake.network_requests == 2  # markets + one book
    assert "SECRETKEY" not in (tmp_path / "williamhill" / "early" / "2026-11-15.json").read_text()


def test_early_grab_keeps_only_the_target_days_games(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    # Grabbing for the 14th: the candidate window (14th + 15th) matches the 15th's games, but a
    # night-before file for the 14th must not carry them.
    res = grab.grab_day(
        date(2026, 11, 14),
        {"williamhill": "caesars"},
        client=FakeClient(),
        key="K",
        candidates=lambda d: CANDS,
        early=True,
    )
    assert res.ok and "0 lines" in res.message
    assert grab.load_early("williamhill", date(2026, 11, 14))["lines"] == []


def test_early_raw_cache_key_is_separate(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    keys = []

    class Recording(FakeClient):
        def get_json(self, url, params=None, *, cache_key, cache_ok=None):
            keys.append(cache_key)
            return super().get_json(url, params, cache_key=cache_key, cache_ok=cache_ok)

    grab.grab_day(
        DAY, {"williamhill": "caesars"}, client=Recording(), key="K",
        candidates=lambda d: CANDS, early=True,
    )  # fmt: skip
    assert any(k.startswith("2026-11-15/early-caesars-") for k in keys)


def test_early_defaults_to_tomorrow_and_williamhill(monkeypatch, capsys):
    seen = {}

    def fake_grab(day, books, early=False):
        seen.update(day=day, books=dict(books), early=early)
        return grab.GrabResult(True, "ok")

    monkeypatch.setattr(grab, "today", lambda: date(2026, 11, 14))
    monkeypatch.setattr(books_cli, "today", lambda: date(2026, 11, 14))
    monkeypatch.setattr(grab, "grab_day", fake_grab)
    assert books_cli.main(["grab", "--early"]) == 0
    assert seen == {"day": date(2026, 11, 15), "books": {"williamhill": "caesars"}, "early": True}
    assert books_cli.main(["grab", "--early", "--date", "2026-11-20", "--book", "circa"]) == 0
    assert seen == {"day": date(2026, 11, 20), "books": {"circa": "circasports"}, "early": True}
    assert books_cli.main(["grab"]) == 0  # the day grab is unchanged: today, both books
    assert seen["day"] == date(2026, 11, 14) and not seen["early"]
    assert set(seen["books"]) == {"circa", "williamhill"}


def test_status_early(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    grab.grab_day(
        DAY, {"williamhill": "caesars"}, client=FakeClient(), key="K",
        candidates=lambda d: CANDS, early=True,
    )  # fmt: skip
    assert books_cli.main(["status", "--early", "--date", "2026-11-15"]) == 0
    out = capsys.readouterr().out
    assert "williamhill early 2026-11-15: " in out and "circa early 2026-11-15: no file" in out


def test_local_day():
    assert grab._local_day(datetime(2026, 11, 16, 3, tzinfo=UTC)) == date(2026, 11, 15)  # 7 PM PT
    assert grab._local_day("2026-11-15T17:00:00Z") == date(2026, 11, 15)
    assert grab._local_day(None) is None
