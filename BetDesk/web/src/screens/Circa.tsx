import { ApiError, api, type CircaTodayResponse } from "../api/client";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { ErrorState, Skeleton, StaleBanner } from "../components/States";
import { useApi } from "../hooks/useApi";

const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Circa's odds board isn't in any feed. Screenshots are added on the owner's Mac (LAN page or iCloud); this shows today's state. */
export function Circa() {
  const q = useApi<CircaTodayResponse>(api.circaToday(), {
    refreshSeconds: (d) => (d.read ? 600 : 120),
  });

  return (
    <PullToRefresh onRefresh={q.refresh}>
      <PageHeader title="Circa" subtitle="Odds-board screenshots for today's picks" />
      <main className="content">
        <p className="circa-intro">
          Circa's prices aren't in any odds feed. The owner adds screenshots of its board at home before{" "}
          <strong>2 PM</strong>; DeepSports reads them then and uses Circa's real prices in the day's picks.
        </p>
        <section aria-labelledby="circa-today-h">
          <h2 id="circa-today-h" className="section-title">Today</h2>
          {q.data && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
          {q.loading && !q.data ? (
            <Skeleton rows={1} height={88} />
          ) : !q.data ? (
            q.error instanceof ApiError && q.error.status === 404 ? (
              <div className="card">
                <p className="circa-status-main">Today's status isn't available yet.</p>
                <p className="fine">The Mac's DeepSports server doesn't have the Circa feature yet.</p>
              </div>
            ) : (
              <ErrorState error={q.error} onRetry={q.refresh} />
            )
          ) : (
            <TodayStatus d={q.data} />
          )}
          <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} />
        </section>
      </main>
    </PullToRefresh>
  );
}

function TodayStatus({ d }: { d: CircaTodayResponse }) {
  const addedAfterRead = d.read && d.latest_at && new Date(d.latest_at) > new Date(d.read.read_at);
  return (
    <div className="card circa-status">
      <p className="circa-status-main">
        {d.count === 0 ? "No screenshots yet today" : `${plural(d.count, "screenshot")} today`}
        {d.latest_at && d.count > 0 && <span className="circa-status-sub"> · last added {time(d.latest_at)}</span>}
      </p>
      {d.read ? (
        <p className="circa-read is-read">
          Read at {time(d.read.read_at)}: {d.read.matched} of {plural(d.read.lines, "line")} matched to games.
        </p>
      ) : (
        <p className="circa-read">Not read yet. DeepSports reads them at 2 PM, before the picks.</p>
      )}
      {d.read && <p className="fine">A "line" is one price read off the board; "matched" means it was tied to a game on today's schedule.</p>}
      {addedAfterRead && <p className="fine">Some screenshots came in after the read and may not be in today's picks.</p>}
    </div>
  );
}
