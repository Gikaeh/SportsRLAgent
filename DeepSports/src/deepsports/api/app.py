"""FastAPI app: live endpoints (ESPN via LiveService) + warehouse endpoints (read-only DuckDB),
and the built web app (web/dist) at `/`. Contract: docs/API.md."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from deepsports import config
from deepsports.api import views, warehouse
from deepsports.api.live import LEAGUES, LiveService, UnknownLeague
from deepsports.http import FetchError
from deepsports.pipeline import league_today

WEB_DIST = config.ROOT / "web" / "dist"
GLASSES_DIST = config.ROOT / "glasses" / "dist"


def followed_teams(league: str = "nba") -> set[str]:
    from deepsports.cli import followed_teams as follow_list
    from deepsports.cli import load_calendar_config

    return set(follow_list(load_calendar_config(), league))


PREDICTION_OPEN_TIMEOUT = 1.5  # live pages never wait long on the warehouse
# Version shown in the apps/calendar, per league. NBA: v1.1 (v1 + player availability) is a
# small, honest improvement over v1.0 (docs/results/2026-11-04-backtest-v1.1.md); both are
# graded side by side. College: ncaab-v1 (docs/results/2026-11-04-ncaab-v1.md), the only one.
# A game without the preferred version falls back to its latest pre-tip prediction.
DISPLAY_MODEL_VERSIONS = {"nba": "v1.1", "ncaab": "ncaab-v1"}


def create_app(
    live: LiveService | None = None,
    db_path: Path | str = config.DB_PATH,
    web_dist: Path = WEB_DIST,
    glasses_dist: Path = GLASSES_DIST,
) -> FastAPI:
    live = live or LiveService()
    app = FastAPI(title="DeepSports API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    # The G2 glasses app runs in the Even app's WebView under its own origin and must pass
    # browser CORS checks (docs/research/even-realities-g2.md). The API is read-only public
    # sports data, so any origin may GET it; no credentials.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    @app.exception_handler(warehouse.WarehouseBusy)
    async def _busy(_req, _exc):
        return JSONResponse({"error": "warehouse_busy"}, status_code=503)

    @app.exception_handler(warehouse.WarehouseUnavailable)
    async def _unavailable(_req, _exc):
        return JSONResponse({"error": "warehouse_unavailable"}, status_code=503)

    @app.exception_handler(UnknownLeague)
    async def _league(_req, exc):
        return JSONResponse({"error": "unknown_league", "detail": str(exc)}, 400)

    def attach_predictions(cards: list[dict]) -> None:
        """Fill `prediction` on NBA and college cards from the warehouse (left None if it's
        busy/unavailable), preferring each league's display version."""
        by_league: dict[str, list[str]] = {}
        for c in cards:
            if c["league"] in DISPLAY_MODEL_VERSIONS:
                by_league.setdefault(c["league"], []).append(c["id"])
        if not by_league:
            return
        rows: dict[str, dict] = {}
        try:
            with warehouse.connect(db_path, timeout=PREDICTION_OPEN_TIMEOUT) as con:
                for lg, ids in by_league.items():
                    rows |= warehouse.pre_tip_predictions(
                        con, ids, prefer_version=DISPLAY_MODEL_VERSIONS[lg]
                    )
        except (warehouse.WarehouseBusy, warehouse.WarehouseUnavailable):
            return
        for c in cards:
            if c["id"] in rows:
                c["prediction"] = views.prediction_view(rows[c["id"]], c)

    @app.exception_handler(FetchError)
    async def _upstream(_req, exc):
        return JSONResponse({"error": "upstream_unavailable", "detail": str(exc)}, 502)

    @app.get("/api/health")
    def health():
        try:
            with warehouse.connect(db_path):
                status = "ok"
        except warehouse.WarehouseBusy:
            status = "busy"
        except warehouse.WarehouseUnavailable:
            status = "unavailable"
        return {"ok": True, "warehouse": status, "now": datetime.now(UTC).isoformat()}

    @app.get("/api/followed")
    def followed():
        by_league = {lg: sorted(followed_teams(lg)) for lg in LEAGUES}
        return {"teams": by_league["nba"], "by_league": by_league}

    def next_followed_game(
        after: date, followed: set[str], league: str = "nba", days: int = 7
    ) -> dict | None:
        """First not-yet-started followed game from `after` through `days` ahead (cached ESPN)."""
        if not followed:
            return None
        for offset in range(days + 1):
            day = after + timedelta(days=offset)
            for card in views.scoreboard_cards(live.scoreboard(day, league), followed, league):
                if (
                    card["followed"]
                    and card["state"] == "pre"
                    and card["status"] != "STATUS_POSTPONED"
                ):
                    return card
        return None

    @app.get("/api/scoreboard")
    def scoreboard(
        day: Annotated[date | None, Query(alias="date")] = None,
        league: str = "nba",
    ):
        today = league_today()
        day = day or today
        followed = followed_teams(league)
        cards = views.scoreboard_cards(live.scoreboard(day, league), followed, league)
        attach_predictions(cards)
        is_live = any(c["state"] == "in" for c in cards)
        body = {
            "league": league,
            "date": day.isoformat(),
            "games": cards,
            "live": is_live,
            "refresh_seconds": live.refresh_seconds(is_live),
        }
        if day == today:
            try:
                body["next_followed_game"] = next_followed_game(today, followed, league)
                if body["next_followed_game"]:
                    attach_predictions([body["next_followed_game"]])
            except FetchError:
                body["next_followed_game"] = None
        return body

    @app.get("/api/games/{game_id}")
    def game(game_id: str, league: str = "nba"):
        if not game_id.isdigit():
            raise HTTPException(404, "unknown game")
        try:
            raw = live.summary(game_id, league)
        except FetchError as e:
            raise HTTPException(404, "unknown game") from e
        detail = views.game_detail(raw, followed_teams(league), league)
        attach_predictions([detail["game"]])
        detail["refresh_seconds"] = live.game_refresh_seconds(detail["game"]["state"] == "in")
        return detail

    @app.get("/api/glance")
    def glance():
        cards = []
        for lg in LEAGUES:
            followed = followed_teams(lg)
            if followed:
                cards += views.scoreboard_cards(live.scoreboard(league_today(), lg), followed, lg)
        cards.sort(key=lambda c: (c["state"] != "in", c["start_time"], c["id"]))
        is_live = any(c["state"] == "in" for c in cards)
        return {
            "lines": views.glance_lines(cards),
            "refresh_seconds": live.refresh_seconds(is_live),
        }

    @app.get("/api/predictions/record")
    def prediction_record(league: str = "nba", days: int = 30, model_version: str | None = None):
        """One league's record, for one model version (default: the league's display
        version). NBA and college are never mixed."""
        if league not in LEAGUES:
            raise UnknownLeague(league)
        try:
            from deepsports.analysis.record import prediction_record as record
        except ImportError:  # grading module not installed yet
            return JSONResponse({"error": "not_ready"}, status_code=503)
        version = model_version or DISPLAY_MODEL_VERSIONS.get(league)
        with warehouse.connect(db_path) as con:
            return record(con, league=league, days=days, model_version=version)

    @app.get("/api/standings")
    def standings():
        with warehouse.connect(db_path) as con:
            return warehouse.standings(con, followed_teams())

    @app.get("/api/teams/{abbr}")
    def team(abbr: str):
        with warehouse.connect(db_path) as con:
            page = warehouse.team_page(con, abbr.upper(), followed_teams())
        if page is None:
            raise HTTPException(404, "unknown team")
        return page

    # G2 glasses plugin (glasses/), served same-origin so the WebView needs no CORS/whitelist hop.
    if glasses_dist.exists():
        app.mount("/glasses", StaticFiles(directory=glasses_dist, html=True), "glasses")

    if web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets", check_dir=False), "assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = (web_dist / path).resolve()
            if path and target.is_file() and web_dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(web_dist / "index.html")

    return app
