import { api, type TeamResponse } from "../api/client";
import type { GameResult } from "../api/types";
import { GLOSSARY, Help } from "../components/Help";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { TeamLogo } from "../components/TeamLogo";
import { fmtGb, fmtWinPct, shortDate } from "../format";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

export function Team({ abbr }: { abbr: string }) {
  const q = useApi<TeamResponse>(api.team(abbr), { refreshSeconds: () => 600 });
  const d = q.data;
  return (
    <>
      <PageHeader back="#/standings" title={d ? d.team.short_name : abbr} subtitle={d ? d.standing.conference + "ern Conference" : undefined} />
      <main className="content">
        {d && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !d ? (
          <Skeleton rows={3} height={120} />
        ) : !d ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : (
          <>
            <section className={`card team-hero${d.team.followed ? " is-followed" : ""}`} aria-label="Season summary">
              <TeamLogo logo={d.team.logo} abbr={d.team.abbr} size={64} />
              <div>
                <p className="team-hero-name">
                  {d.team.name}
                  {d.team.followed && <span className="star" aria-label="followed team">★</span>}
                </p>
                <p className="team-hero-record">
                  {d.standing.wins}-{d.standing.losses}
                  <span className="muted"> ({fmtWinPct(d.standing.pct)})</span>
                </p>
              </div>
            </section>
            <section className="card" aria-label="Season details">
              <dl className="tiles">
                <div><dt>Games back <Help label="games back">{GLOSSARY.gamesBack}</Help></dt><dd>{fmtGb(d.standing.games_back)}</dd></div>
                <div><dt>Streak</dt><dd>{d.standing.streak}</dd></div>
                <div><dt>Last 10</dt><dd>{d.standing.last10}</dd></div>
                <div><dt>Home</dt><dd>{d.standing.home}</dd></div>
                <div><dt>Away</dt><dd>{d.standing.away}</dd></div>
              </dl>
            </section>

            <section className="card" aria-labelledby="recent-h">
              <h2 id="recent-h" className="card-title">Last {d.recent.length} games</h2>
              {d.recent.length === 0 ? (
                <Empty title="No games played yet" />
              ) : (
                <>
                  <p className="form-strip" aria-label={`Results, most recent first: ${d.recent.map((r) => (r.result === "W" ? "win" : r.result === "L" ? "loss" : "no result")).join(", ")}`}>
                    {d.recent.map((r) => (
                      <span key={r.id} className={`form-dot ${r.result === "W" ? "w" : r.result === "L" ? "l" : ""}`} aria-hidden="true">
                        {r.result ?? "·"}
                      </span>
                    ))}
                  </p>
                  <p className="fine form-caption">Most recent on the left</p>
                  <ResultList games={d.recent} />
                </>
              )}
            </section>

            <section className="card" aria-labelledby="next-h">
              <h2 id="next-h" className="card-title">Next {d.upcoming.length} games</h2>
              {d.upcoming.length === 0 ? <Empty title="No upcoming games scheduled" /> : <ResultList games={d.upcoming} />}
            </section>
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} />
          </>
        )}
      </main>
    </>
  );
}

function ResultList({ games }: { games: GameResult[] }) {
  return (
    <ul className="result-list">
      {games.map((r) => (
        <li key={r.id}>
          <a className="result-row" href={href.game(r.id)}>
            <span className="result-date">{shortDate(r.date)}</span>
            <span className="result-opp">
              <span className="muted">{r.home ? "vs" : "@"}</span> {r.opponent}
            </span>
            {r.result ? (
              <span className="result-score">
                <span className={`badge ${r.result === "W" ? "badge-w" : "badge-l"}`}>{r.result}</span> {r.score}
              </span>
            ) : (
              <span className="result-score muted">{r.status_text}</span>
            )}
          </a>
        </li>
      ))}
    </ul>
  );
}
