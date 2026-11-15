import { ApiError, api, type PicksTodayResponse } from "../api/client";
import type { BookQuote, ModelPick } from "../api/types";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

const BOOKS: [keyof ModelPick["books"], string][] = [
  ["circa", "Circa"],
  ["williamhill", "William Hill"],
];

const price = (n: number) => (n > 0 ? `+${n}` : `${n}`);
const line = (market: ModelPick["market"], n: number | null) =>
  n === null ? "" : market === "spread" ? (n > 0 ? `+${n}` : n === 0 ? "PK" : `${n}`) : `${n}`;
const quote = (market: ModelPick["market"], q: BookQuote) => [line(market, q.line), price(q.price)].filter(Boolean).join(" ");

function tipLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? time : `${d.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
}

/** Today's models-only picks (watch-only): the top 5 with Circa's and William Hill's prices. */
export function Picks() {
  const q = useApi<PicksTodayResponse>(api.picksToday(), { refreshSeconds: () => 600 });
  const d = q.data;
  const made = d?.run_at
    ? new Date(d.run_at).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
    : null;
  return (
    <PullToRefresh onRefresh={q.refresh}>
      <PageHeader back="#/" title="Today's picks" subtitle={made ? `Made ${made} · watch-only` : "Watch-only"} />
      <main className="content">
        {d && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !d ? (
          <Skeleton rows={5} height={96} />
        ) : !d ? (
          q.error instanceof ApiError && q.error.status === 404 ? (
            <Empty title="Picks aren't available yet">
              <p>The Mac's DeepSports server doesn't have the picks feature yet.</p>
            </Empty>
          ) : (
            <ErrorState error={q.error} onRetry={q.refresh} />
          )
        ) : !d.available ? (
          <Empty title="No picks yet">
            <p>Picks come out at 2 PM on weekdays and 8 AM on Saturday and Sunday.</p>
            <a className="btn" href={href.today()}>Back to Today</a>
          </Empty>
        ) : d.top.length === 0 ? (
          <Empty title="No bet today">
            <p>The two models don't agree 3+ points past any line.</p>
          </Empty>
        ) : (
          <>
            <section aria-labelledby="picks-top-h">
              <h2 id="picks-top-h" className="section-title">Top {d.top.length} · 1 unit each, one per game</h2>
              <ol className="card-list picks-list">
                {d.top.map((p, i) => (
                  <li key={`${p.game_id}:${p.market}`}>
                    <PickCard p={p} rank={i + 1} />
                  </li>
                ))}
              </ol>
            </section>
            {d.more.length > 0 && (
              <details className="explainer">
                <summary>
                  More picks ({d.counts.strong} strong, {d.counts.lean} lean in all)
                </summary>
                <ul className="card-list picks-list">
                  {d.more.map((p) => (
                    <li key={`${p.game_id}:${p.market}`}>
                      <PickCard p={p} />
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} />
            <p className="fine">
              Watch-only: you place every bet yourself. Neither model has beaten the closing line, so check the line
              before betting. Book prices are grabbed before the picks; William Hill's come from Caesars' feed.
            </p>
          </>
        )}
      </main>
    </PullToRefresh>
  );
}

function PickCard({ p, rank }: { p: ModelPick; rank?: number }) {
  const started = p.tip_utc != null && new Date(p.tip_utc) <= new Date();
  const matchup = `${p.away.abbr ?? "?"} @ ${p.home.abbr ?? "?"}`;
  const books = BOOKS.filter(([k]) => p.books[k]);
  return (
    <a className={`card pick-card${started ? " pick-started" : ""}`} href={href.game(p.game_id, p.league)}>
      <div className="pick-head">
        {rank !== undefined && <span className="pick-rank" aria-hidden="true">{rank}</span>}
        <span className="pick-label">
          {p.label} <span className="pick-price">{price(p.price)}</span>
        </span>
        <span className={`pick-tier tier-${p.tier}`}>{p.tier}</span>
      </div>
      <p className="pick-game">
        {p.league === "ncaab" && <span aria-label="College">🎓 </span>}
        {matchup}
        {p.tip_utc && ` · ${started ? "started" : tipLabel(p.tip_utc)}`}
        {p.early && " · early season"}
      </p>
      <p className="pick-books">
        {books.length === 0
          ? "Not on Circa or William Hill yet"
          : books.map(([k, name]) => (
              <span key={k} className="pick-book">
                {name} <strong>{quote(p.market, p.books[k]!)}</strong>
              </span>
            ))}
      </p>
      <p className="fine pick-edges">
        Past the line: DeepSports +{p.ds_edge}, ManualBets +{p.mb_edge} pts
      </p>
    </a>
  );
}
