import { useState } from "react";
import { api, type GameDetailResponse } from "../api/client";
import type { GameCard, GameTeam, League, PlayerLine, TeamBox } from "../api/types";
import { formatOdds, LeagueBadge, StatusPill } from "../components/GameCard";
import { PredictionPanel } from "../components/Prediction";
import { GLOSSARY, Help } from "../components/Help";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { TeamLogo } from "../components/TeamLogo";
import { fmtMadeAtt, fmtNum, fmtPct, fmtPlusMinus, isDisrupted, isFinal, pct, shortDate } from "../format";
import { gameLeague, periodLabel, regulationPeriods } from "../league";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

export function Game({ id, league }: { id: string; league: League }) {
  const q = useApi<GameDetailResponse>(api.game(id, league), {
    refreshSeconds: (d) => (d.game.state === "post" ? null : d.refresh_seconds),
  });
  const g = q.data?.game;
  return (
    <>
      <PageHeader
        back={`#/?league=${league}`}
        title={g ? `${g.away.abbr} ${g.neutral_site ? "vs" : "@"} ${g.home.abbr}` : "Game"}
        subtitle={g ? shortDate(g.start_time) : undefined}
      />
      <main className="content">
        {q.data && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !q.data ? (
          <Skeleton rows={3} height={140} />
        ) : !q.data || !g ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : (
          <>
            <ScoreHeader game={g} />
            <PredictionPanel game={g} />
            <BoxScore data={q.data} />
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} live={g.state === "in"} />
          </>
        )}
      </main>
    </>
  );
}

function HeaderTeam({ team, game, side }: { team: GameTeam; game: GameCard; side: "away" | "home" }) {
  const other = side === "away" ? game.home : game.away;
  const lost = isFinal(game) && team.score != null && other.score != null && team.score < other.score;
  const inner = (
    <>
      <TeamLogo logo={team.logo} abbr={team.abbr} size={48} />
      <span className="hdr-abbr">
        {team.abbr}
        {team.followed && <span className="star" aria-label="followed team">★</span>}
      </span>
      <span className="hdr-record">{team.record ?? ""}</span>
    </>
  );
  // Team pages are NBA-only for now; a college team link would 404.
  if (gameLeague(game) !== "nba") {
    return <div className={`hdr-team${lost ? " lost" : ""}`} aria-label={team.name}>{inner}</div>;
  }
  return (
    <a className={`hdr-team${lost ? " lost" : ""}`} href={href.team(team.abbr)} aria-label={`${team.name}, team page`}>
      {inner}
    </a>
  );
}

function ScoreHeader({ game }: { game: GameCard }) {
  const showScore = game.state !== "pre" && game.away.score != null && game.home.score != null;
  const league = gameLeague(game);
  const periods = Math.max(regulationPeriods(league), game.away.linescores.length, game.home.linescores.length);
  return (
    <section className={`card score-header${game.state === "in" ? " is-live" : ""}`} aria-label="Score">
      <div className="hdr-row">
        <HeaderTeam team={game.away} game={game} side="away" />
        <div className="hdr-center">
          {showScore ? (
            <p className="hdr-score" aria-label={`${game.away.abbr} ${game.away.score}, ${game.home.abbr} ${game.home.score}`}>
              <span>{game.away.score}</span>
              <span className="hdr-dash" aria-hidden="true">–</span>
              <span>{game.home.score}</span>
            </p>
          ) : (
            <p className="hdr-vs" aria-hidden="true">{game.neutral_site ? "vs" : "@"}</p>
          )}
          <StatusPill game={game} />
          <LeagueBadge game={game} />
        </div>
        <HeaderTeam team={game.home} game={game} side="home" />
      </div>

      {showScore && (
        <div className="scroll-x">
          <table className="linescore">
            <caption className="sr-only">Points by {league === "ncaab" ? "half" : "quarter"}</caption>
            <thead>
              <tr>
                <th scope="col"><span className="sr-only">Team</span></th>
                {Array.from({ length: periods }, (_, i) => (
                  <th scope="col" key={i}>{periodLabel(i, league)}</th>
                ))}
                <th scope="col">T</th>
              </tr>
            </thead>
            <tbody>
              {[game.away, game.home].map((t) => (
                <tr key={t.id}>
                  <th scope="row">{t.abbr}</th>
                  {Array.from({ length: periods }, (_, i) => (
                    <td key={i}>{t.linescores[i] ?? "–"}</td>
                  ))}
                  <td className="total">{t.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="hdr-meta">
        {[game.venue, game.broadcasts.join(" · ")].filter(Boolean).join(" · ")}
      </p>
      {game.state === "pre" && game.odds && (
        <p className="hdr-meta odds">
          Odds: {formatOdds(game.odds)} <Help label="the odds">{GLOSSARY.odds}</Help>
        </p>
      )}
    </section>
  );
}

function BoxScore({ data }: { data: GameDetailResponse }) {
  const g = data.game;
  const away = data.teams.find((t) => t.team_id === g.away.id || t.abbr === g.away.abbr);
  const home = data.teams.find((t) => t.team_id === g.home.id || t.abbr === g.home.abbr);
  // Before tip-off the server may send team rows with every stat null; treat that as "no box score".
  const hasStats = (t: TeamBox | undefined) => !!t && Object.entries(t).some(([k, v]) => k !== "team_id" && typeof v === "number");
  if (!away || !home || g.state === "pre" || (!hasStats(away) && !hasStats(home))) {
    if (isDisrupted(g)) return <Empty title={`This game is ${g.status_text.toLowerCase()}`}><p>Check back for a new date.</p></Empty>;
    if (g.state === "pre") return <Empty title="Box score starts at tip-off"><p>Player and team stats appear here once the game begins. Tip-off is at {g.status_text}.</p></Empty>;
    return <Empty title="No box score yet" />;
  }
  return (
    <>
      <TeamComparison game={g} away={away} home={home} />
      <PlayerSection data={data} />
    </>
  );
}

type Stat = { key: string; label: string; help?: string; a: number | null; h: number | null; pct?: boolean; lowerIsBetter?: boolean };

function TeamComparison({ game, away, home }: { game: GameCard; away: TeamBox; home: TeamBox }) {
  const stats: Stat[] = [
    { key: "fg", label: "FG%", help: GLOSSARY.fgPct, a: pct(away.fgm, away.fga), h: pct(home.fgm, home.fga), pct: true },
    { key: "3p", label: "3P%", help: GLOSSARY.fg3Pct, a: pct(away.fg3m, away.fg3a), h: pct(home.fg3m, home.fg3a), pct: true },
    { key: "ft", label: "FT%", help: GLOSSARY.ftPct, a: pct(away.ftm, away.fta), h: pct(home.ftm, home.fta), pct: true },
    { key: "reb", label: "Rebounds", help: GLOSSARY.reb, a: away.reb, h: home.reb },
    { key: "oreb", label: "Offensive rebounds", a: away.oreb, h: home.oreb },
    { key: "ast", label: "Assists", help: GLOSSARY.ast, a: away.ast, h: home.ast },
    { key: "stl", label: "Steals", help: GLOSSARY.stl, a: away.stl, h: home.stl },
    { key: "blk", label: "Blocks", help: GLOSSARY.blk, a: away.blk, h: home.blk },
    { key: "tov", label: "Turnovers", help: GLOSSARY.tov, a: away.tov, h: home.tov, lowerIsBetter: true },
    { key: "paint", label: "Points in paint", help: GLOSSARY.paint, a: away.points_in_paint, h: home.points_in_paint },
    { key: "fb", label: "Fast-break points", help: GLOSSARY.fastBreak, a: away.fast_break_points, h: home.fast_break_points },
    { key: "pf", label: "Fouls", a: away.pf, h: home.pf, lowerIsBetter: true },
  ].filter((s) => s.a != null || s.h != null);

  return (
    <section className="card" aria-labelledby="cmp-h">
      <div className="cmp-head">
        <span className="cmp-team">{game.away.abbr}</span>
        <h2 id="cmp-h" className="card-title">Team stats</h2>
        <span className="cmp-team">{game.home.abbr}</span>
      </div>
      <ul className="cmp-list">
        {stats.map((s) => {
          const a = s.a ?? 0;
          const h = s.h ?? 0;
          const max = Math.max(a, h) || 1;
          const better = a === h ? null : (a > h) !== !!s.lowerIsBetter ? "a" : "h";
          const fmt = (v: number | null) => (s.pct ? fmtPct(v) : fmtNum(v));
          return (
            <li key={s.key} className="cmp-row">
              <div className="cmp-labels">
                <span className={`cmp-val${better === "a" ? " better" : ""}`}>{fmt(s.a)}</span>
                <span className="cmp-label">
                  {s.label}
                  {s.help && <Help label={s.label}>{s.help}</Help>}
                </span>
                <span className={`cmp-val${better === "h" ? " better" : ""}`}>{fmt(s.h)}</span>
              </div>
              <div className="cmp-bars" aria-hidden="true">
                <span className="cmp-track left"><span className={`cmp-fill${better === "a" ? " better" : ""}`} style={{ width: `${(a / max) * 100}%` }} /></span>
                <span className="cmp-track"><span className={`cmp-fill${better === "h" ? " better" : ""}`} style={{ width: `${(h / max) * 100}%` }} /></span>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="fine">Brighter bar = the better side for that stat (fewer is better for turnovers and fouls).</p>
    </section>
  );
}

function PlayerSection({ data }: { data: GameDetailResponse }) {
  const g = data.game;
  const sides = [g.away, g.home];
  const defaultIdx = g.away.followed && !g.home.followed ? 0 : g.home.followed && !g.away.followed ? 1 : 0;
  const [idx, setIdx] = useState(defaultIdx);
  const team = sides[idx];
  const players = data.players[team.id] ?? [];
  return (
    <section className="card" aria-labelledby="players-h">
      <h2 id="players-h" className="card-title">Players</h2>
      <div className="segmented" role="group" aria-label="Choose team">
        {sides.map((t, i) => (
          <button key={t.id} type="button" aria-pressed={i === idx} onClick={() => setIdx(i)}>
            {t.short_name}
          </button>
        ))}
      </div>
      <PlayerTable players={players} teamName={team.name} />
      <details className="explainer">
        <summary>What do these columns mean?</summary>
        <dl className="legend">
          <dt>MIN</dt><dd>Minutes played (a game is {gameLeague(g) === "ncaab" ? "40" : "48"})</dd>
          <dt>PTS</dt><dd>Points scored</dd>
          <dt>REB</dt><dd>{GLOSSARY.reb}</dd>
          <dt>AST</dt><dd>{GLOSSARY.ast}</dd>
          <dt>STL / BLK</dt><dd>Steals / blocks (defense)</dd>
          <dt>TO</dt><dd>{GLOSSARY.tov}</dd>
          <dt>PF</dt><dd>Personal fouls; {gameLeague(g) === "ncaab" ? "5" : "6"} and the player must sit out the rest of the game</dd>
          <dt>FG / 3PT / FT</dt><dd>Shots made-attempted: all field goals, three-pointers, and free throws</dd>
          <dt>+/-</dt><dd>{GLOSSARY.plusMinus}</dd>
        </dl>
      </details>
    </section>
  );
}

function PlayerRow({ p }: { p: PlayerLine }) {
  return (
    <tr>
      <th scope="row" className="sticky-col">
        <span aria-hidden="true">{shortName(p.name)}</span>
        <span className="sr-only">{p.name}</span>
      </th>
      <td>{fmtNum(p.minutes)}</td>
      <td className="strong">{fmtNum(p.pts)}</td>
      <td>{fmtNum(p.reb)}</td>
      <td>{fmtNum(p.ast)}</td>
      <td>{fmtNum(p.stl)}</td>
      <td>{fmtNum(p.blk)}</td>
      <td>{fmtNum(p.tov)}</td>
      <td>{fmtNum(p.pf)}</td>
      <td>{fmtMadeAtt(p.fgm, p.fga)}</td>
      <td>{fmtMadeAtt(p.fg3m, p.fg3a)}</td>
      <td>{fmtMadeAtt(p.ftm, p.fta)}</td>
      <td className={p.plus_minus != null && p.plus_minus > 0 ? "pos" : p.plus_minus != null && p.plus_minus < 0 ? "neg" : ""}>
        {fmtPlusMinus(p.plus_minus)}
      </td>
    </tr>
  );
}

/** "Jaylen Brown" -> "J. Brown" so more stat columns fit on a phone. */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length < 2 ? name : `${parts[0][0]}. ${parts.slice(1).join(" ")}`;
}

const COLS = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "PF", "FG", "3PT", "FT", "+/-"];

function PlayerTable({ players, teamName }: { players: PlayerLine[]; teamName: string }) {
  const played = players.filter((p) => !p.did_not_play);
  const starters = played.filter((p) => p.starter);
  const bench = played.filter((p) => !p.starter);
  const dnp = players.filter((p) => p.did_not_play);
  if (players.length === 0) return <Empty title="No player stats yet" />;
  const group = (label: string, rows: PlayerLine[]) =>
    rows.length > 0 && (
      <tbody>
        <tr className="group-row">
          <th scope="rowgroup" colSpan={COLS.length + 1}><span className="sticky-label">{label}</span></th>
        </tr>
        {rows.map((p) => <PlayerRow key={p.athlete_id} p={p} />)}
      </tbody>
    );
  return (
    <>
      <div className="scroll-x table-wrap" tabIndex={0} role="region" aria-label={`${teamName} player stats, scrolls sideways`}>
        <table className="stats-table">
          <caption className="sr-only">{teamName} player stats</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky-col">Player</th>
              {COLS.map((c) => <th scope="col" key={c}>{c}</th>)}
            </tr>
          </thead>
          {group("Starters", starters)}
          {group("Bench", bench)}
        </table>
      </div>
      {dnp.length > 0 && (
        <details className="dnp">
          <summary>Did not play ({dnp.length})</summary>
          <ul>
            {dnp.map((p) => (
              <li key={p.athlete_id}>
                <span>{p.name}</span>
                {p.dnp_reason && <span className="muted"> · {p.dnp_reason}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
