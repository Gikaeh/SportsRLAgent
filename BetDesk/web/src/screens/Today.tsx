import { api, type ScoreboardResponse } from "../api/client";
import { GameCardView } from "../components/GameCard";
import { COLLEGE_PREDICTION_NOTE, EarlyToggle } from "../components/Prediction";
import { GLOSSARY } from "../components/Help";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import type { GameCard, League } from "../api/types";
import { addDays, dayLabel, easternToday, longDate } from "../format";
import { useApi } from "../hooks/useApi";
import { gameLeague, setLeague } from "../league";
import { href } from "../router";

export function Today({ date, league }: { date: string | null; league: League }) {
  const q = useApi<ScoreboardResponse>(api.scoreboard(date ?? undefined, league), {
    refreshSeconds: (d) => d.refresh_seconds,
  });
  const college = league === "ncaab";
  const current = date ?? q.data?.date ?? easternToday();
  const isToday = current === easternToday();
  // A server without v2 ignores league= and returns NBA games; never show those as college.
  const games = (q.data?.games ?? []).filter((g) => gameLeague(g) === league);
  const mine = games.filter((g) => g.followed);
  const nextRaw = isToday ? q.data?.next_followed_game : null;
  const next = nextRaw && gameLeague(nextRaw) === league ? nextRaw : null;
  const rest = games.filter((g) => !g.followed);
  const unsupported = college && !!q.data && q.data.games.length > 0 && q.data.games.every((g) => g.league === undefined);
  const liveCount = games.filter((g) => g.state === "in").length;

  return (
    <PullToRefresh onRefresh={q.refresh}>
      <PageHeader
        title={dayLabel(current)}
        subtitle={
          <>
            {longDate(current)}
            {liveCount > 0 && <span className="live-count"> · {liveCount} live</span>}
          </>
        }
      />
      <div className="league-switch-wrap">
        <div className="segmented league-switch" role="group" aria-label="League">
          {(["nba", "ncaab"] as const).map((l) => (
            <button key={l} type="button" aria-pressed={l === league} onClick={() => pickLeague(l, date)}>
              {l === "nba" ? "NBA" : <><span aria-hidden="true">🎓</span> College</>}
            </button>
          ))}
        </div>
        {college && <EarlyToggle />}
      </div>
      <nav className="date-switcher" aria-label="Choose date">
        <a className="icon-btn" href={href.today(addDays(current, -1))} aria-label={`Previous day, ${dayLabel(addDays(current, -1))}`}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </a>
        <a className={`chip${isToday ? " chip-active" : ""}`} href={href.today()} aria-current={isToday ? "date" : undefined}>
          Today
        </a>
        <a className="icon-btn" href={href.today(addDays(current, 1))} aria-label={`Next day, ${dayLabel(addDays(current, 1))}`}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </a>
      </nav>

      <main className="content">
        {q.data && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !q.data ? (
          <Skeleton rows={4} />
        ) : !q.data ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : unsupported ? (
          <Empty title="College scores aren't available yet">
            <p>The DeepSports server needs its college update. NBA scores still work.</p>
            <button type="button" className="btn" onClick={() => pickLeague("nba", date)}>Show NBA</button>
          </Empty>
        ) : games.length === 0 ? (
          <Empty title={`No ${college ? "college " : ""}games ${isToday ? "today" : `on ${dayLabel(current)}`}`}>
            <p>Try another day with the arrows above{college ? ", or switch to NBA" : ""}.</p>
            {next && <NextUp game={next} />}
          </Empty>
        ) : (
          <>
            {mine.length === 0 && next && <NextUp game={next} />}
            {mine.length > 0 && (
              <section aria-labelledby="mine-h">
                <h2 id="mine-h" className="section-title">
                  <span className="star" aria-hidden="true">★</span> Your teams
                </h2>
                <ul className="card-list">
                  {mine.map((g) => (
                    <li key={g.id}><GameCardView game={g} /></li>
                  ))}
                </ul>
              </section>
            )}
            {rest.length > 0 && (
              <section aria-labelledby="rest-h">
                <h2 id="rest-h" className="section-title">{college ? "Around the country" : mine.length > 0 || next ? "Around the league" : "All games"}</h2>
                <ul className="card-list">
                  {rest.map((g) => (
                    <li key={g.id}><GameCardView game={g} /></li>
                  ))}
                </ul>
              </section>
            )}
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} live={q.data.live} />
            <details className="explainer">
              <summary>How to read a game card</summary>
              <ul>
                <li>The <strong>top team is the visitor</strong>, the bottom team is at home{college ? " (some college games are at a neutral site, where neither team is really at home)" : ""}.</li>
                <li><strong>5-2</strong> next to a team is its season record: wins, then losses.</li>
                {college ? (
                  <li>College games have <strong>two 20-minute halves</strong>, not four quarters. <strong>2nd 8:12</strong> means 8 minutes 12 seconds left in the second half. <strong>OT</strong> is overtime, an extra 5 minutes when tied.</li>
                ) : (
                  <li><strong>Q3 4:12</strong> means 4 minutes 12 seconds left in the 3rd of 4 quarters. <strong>OT</strong> is overtime, an extra 5 minutes when tied.</li>
                )}
                <li>{GLOSSARY.odds}</li>
                <li>{GLOSSARY.model}{college ? ` ${COLLEGE_PREDICTION_NOTE}` : ""}</li>
                <li>Scores update on their own while games are live. Pull down to refresh now.</li>
              </ul>
            </details>
          </>
        )}
      </main>
    </PullToRefresh>
  );
}

function NextUp({ game }: { game: GameCard }) {
  return (
    <section className="next-up" aria-labelledby="next-h">
      <h2 id="next-h" className="section-title">
        <span className="star" aria-hidden="true">★</span> Your teams' next game
      </h2>
      <GameCardView game={game} />
    </section>
  );
}

/** Remember the choice; drop a deep link's ?league= so it doesn't override the switch. */
function pickLeague(l: League, date: string | null) {
  setLeague(l);
  if (/[?&]league=/.test(window.location.hash)) window.location.hash = href.today(date);
}
