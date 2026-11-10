import { api, type BetsResponse } from "../api/client";
import { GameCardView } from "../components/GameCard";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { useApi } from "../hooks/useApi";

/** Every game with an open bet in one list, live scores updating, so several can be tracked at once. */
export function Bets() {
  const q = useApi<BetsResponse>(api.bets(), { refreshSeconds: (d) => d.refresh_seconds });
  const games = q.data?.games ?? [];
  const liveCount = games.filter((g) => g.state === "in").length;
  const live = games.filter((g) => g.state === "in");
  const upcoming = games.filter((g) => g.state === "pre");
  const done = games.filter((g) => g.state === "post");

  return (
    <PullToRefresh onRefresh={q.refresh}>
      <PageHeader
        title="Open bets"
        subtitle={
          q.data ? (
            <>
              {games.length} {games.length === 1 ? "game" : "games"}
              {liveCount > 0 && <span className="live-count"> · {liveCount} live</span>}
            </>
          ) : undefined
        }
      />
      <main className="content">
        {q.data && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !q.data ? (
          <Skeleton rows={3} />
        ) : !q.data ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : games.length === 0 ? (
          <Empty title="No open bets">
            <p>Games with a bet that hasn't been graded yet show up here.</p>
          </Empty>
        ) : (
          <>
            <Section id="live-h" title="Live" games={live} />
            <Section id="up-h" title="Upcoming" games={upcoming} />
            <Section id="done-h" title="Finished, not graded yet" games={done} />
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} live={q.data.live} />
          </>
        )}
      </main>
    </PullToRefresh>
  );
}

function Section({ id, title, games }: { id: string; title: string; games: BetsResponse["games"] }) {
  if (games.length === 0) return null;
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="section-title">{title}</h2>
      <ul className="card-list">
        {games.map((g) => (
          <li key={g.id}><GameCardView game={g} showBets /></li>
        ))}
      </ul>
    </section>
  );
}
