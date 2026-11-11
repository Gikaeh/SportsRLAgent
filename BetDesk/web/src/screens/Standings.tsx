import { api, type StandingsResponse } from "../api/client";
import type { StandingRow } from "../api/types";
import { GLOSSARY, Help } from "../components/Help";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { ErrorState, Skeleton, StaleBanner } from "../components/States";
import { TeamLogo } from "../components/TeamLogo";
import { fmtGb, fmtWinPct } from "../format";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

export function Standings() {
  const q = useApi<StandingsResponse>(api.standings(), { refreshSeconds: () => 600 });
  return (
    <>
      <PageHeader title="Standings" subtitle={q.data ? `${q.data.season} season` : "NBA"} />
      <main className="content">
        {q.data && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !q.data ? (
          <Skeleton rows={2} height={360} />
        ) : !q.data ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : (
          <>
            {q.data.conferences.map((c) => (
              <ConferenceTable key={c.name} name={c.name} rows={c.teams} />
            ))}
            <Legend />
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} />
          </>
        )}
      </main>
    </>
  );
}

function ConferenceTable({ name, rows }: { name: string; rows: StandingRow[] }) {
  const id = `conf-${name}`;
  return (
    <section className="card card-flush" aria-labelledby={id}>
      <h2 id={id} className="card-title pad">{name}ern Conference</h2>
      <div className="scroll-x table-wrap" tabIndex={0} role="region" aria-label={`${name} standings, scrolls sideways`}>
        <table className="stats-table standings">
          <thead>
            <tr>
              <th scope="col" className="sticky-col">Team</th>
              <th scope="col">W</th>
              <th scope="col">L</th>
              <th scope="col">PCT</th>
              <th scope="col">GB</th>
              <th scope="col">L10</th>
              <th scope="col">STRK</th>
              <th scope="col">HOME</th>
              <th scope="col">AWAY</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const seed = i + 1;
              const cls = [r.followed && "is-followed", seed === 6 && "cut-playoff", seed === 10 && "cut-playin"].filter(Boolean).join(" ");
              return (
                <tr key={r.abbr} className={cls || undefined}>
                  <th scope="row" className="sticky-col">
                    <a className="team-cell" href={href.team(r.abbr)}>
                      <span className={`seed${seed <= 6 ? " seed-po" : seed <= 10 ? " seed-pi" : ""}`}>{seed}</span>
                      <TeamLogo logo={r.logo} abbr={r.abbr} size={24} />
                      <span className="team-cell-abbr">{r.abbr}</span>
                      {r.followed && <span className="star" aria-label="followed team">★</span>}
                    </a>
                  </th>
                  <td className="strong">{r.wins}</td>
                  <td>{r.losses}</td>
                  <td>{fmtWinPct(r.pct)}</td>
                  <td>{fmtGb(r.games_back)}</td>
                  <td>{r.last10}</td>
                  <td className={r.streak.startsWith("W") ? "pos" : r.streak.startsWith("L") ? "neg" : ""}>{r.streak}</td>
                  <td>{r.home}</td>
                  <td>{r.away}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Legend() {
  return (
    <section className="card" aria-labelledby="legend-h">
      <h2 id="legend-h" className="card-title">Reading the table</h2>
      <dl className="legend">
        <dt>W / L</dt><dd>Wins and losses this season (82 games each)</dd>
        <dt>PCT</dt><dd>Winning percentage: wins ÷ games played (.750 = 3 of every 4)</dd>
        <dt>GB <Help label="games back">{GLOSSARY.gamesBack}</Help></dt><dd>Games behind the conference leader</dd>
        <dt>L10</dt><dd>Record over the last 10 games, a sign of current form</dd>
        <dt>STRK</dt><dd>Current streak: W3 = won the last 3 in a row</dd>
        <dt>HOME / AWAY</dt><dd>Record in its own arena / on the road</dd>
      </dl>
      <p className="fine">
        <span className="seed seed-po">1</span> Seeds 1–6 go straight to the playoffs.{" "}
        <span className="seed seed-pi">7</span> Seeds 7–10 play a mini-tournament (the play-in) for the last spots.
        Rows with ★ are teams you follow.
      </p>
    </section>
  );
}
