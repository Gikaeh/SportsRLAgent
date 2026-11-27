import { useState } from "react";
import { api, type BetsResponse, type ParlaysResponse } from "../api/client";
import { GameCardView } from "../components/GameCard";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { useApi } from "../hooks/useApi";
import { ParlaysView } from "./Parlays";

type Tab = "games" | "parlays";

/** Every game with an open bet in one list, live scores updating, so several can be tracked at once. */
export function Bets() {
  const [tab, setTab] = useState<Tab>(() => {
    const fromLink = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("tab");
    return (fromLink ?? sessionStorage.getItem("bets-tab")) === "parlays" ? "parlays" : "games";
  });
  const pick = (t: Tab) => {
    setTab(t);
    sessionStorage.setItem("bets-tab", t);
  };
  const q = useApi<BetsResponse>(tab === "games" ? api.bets() : null, { refreshSeconds: (d) => d.refresh_seconds });
  const pq = useApi<ParlaysResponse>(tab === "parlays" ? api.parlays() : null, { refreshSeconds: (d) => d.refresh_seconds });
  const games = q.data?.games ?? [];
  const liveCount = games.filter((g) => g.state === "in").length;
  const live = games.filter((g) => g.state === "in");
  const upcoming = games.filter((g) => g.state === "pre");
  const done = games.filter((g) => g.state === "post");

  return (
    <PullToRefresh onRefresh={tab === "games" ? q.refresh : pq.refresh}>
      <PageHeader
        title="Open bets"
        subtitle={
          tab === "parlays" ? (
            pq.data ? <>{pq.data.parlays.length} {pq.data.parlays.length === 1 ? "parlay" : "parlays"}</> : undefined
          ) : q.data ? (
            <>
              {games.length} {games.length === 1 ? "game" : "games"}
              {liveCount > 0 && <span className="live-count"> · {liveCount} live</span>}
            </>
          ) : undefined
        }
      />
      <main className="content">
        <div className="bets-tabs" role="tablist" aria-label="Bets view">
          {(["games", "parlays"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={`chip${tab === t ? " chip-active" : ""}`}
              onClick={() => pick(t)}
            >
              {t === "games" ? "Games" : "Parlays"}
            </button>
          ))}
        </div>
        {tab === "parlays" ? (
          <ParlaysView q={pq} />
        ) : (
        <>
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
