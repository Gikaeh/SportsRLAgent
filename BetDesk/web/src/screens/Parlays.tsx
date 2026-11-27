import type { Parlay, ParlayLeg, ParlaysResponse } from "../api/types";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { UpdatedAt } from "../components/Layout";
import type { ApiState } from "../hooks/useApi";

/** The owner's parlays with each leg's progress: ✓ won, ✗ lost, = push, ● live, ○ not started. */
export function ParlaysView({ q }: { q: ApiState<ParlaysResponse> }) {
  const parlays = q.data?.parlays ?? [];
  if (q.loading && !q.data) return <Skeleton rows={2} />;
  if (!q.data) return <ErrorState error={q.error} onRetry={q.refresh} />;
  return (
    <>
      {q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
      {parlays.length === 0 ? (
        <Empty title="No parlays">
          <p>Parlays you log show up here until they're graded (and for two days after).</p>
        </Empty>
      ) : (
        <ul className="card-list">
          {parlays.map((p) => (
            <li key={p.id}>
              <ParlayCard p={p} />
            </li>
          ))}
        </ul>
      )}
      <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} live={q.data.live} />
    </>
  );
}

const odds = (n: number) => `${n > 0 ? "+" : ""}${n.toLocaleString()}`;

function statusText(p: Parlay): { text: string; cls: string } {
  const s = p.status;
  if (s === "lost" || s === "loss") return { text: "Lost", cls: "parlay-lost" };
  if (s === "won" || s === "win") return { text: "Won", cls: "parlay-won" };
  if (s === "push" || s === "void") return { text: s === "push" ? "Push" : "Void", cls: "parlay-push" };
  return { text: `Alive · ${p.pending} to go`, cls: "parlay-alive" };
}

function ParlayCard({ p }: { p: Parlay }) {
  const st = statusText(p);
  const placed = new Date(p.placed_at).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  return (
    <article className="card parlay-card" aria-label={`${p.legs.length}-leg parlay, ${st.text}`}>
      <header className="parlay-head">
        <div>
          <h3 className="parlay-title">
            {p.legs.length}-leg parlay <span className="parlay-odds">{odds(p.price)}</span>
          </h3>
          <p className="parlay-sub">
            {[p.book, `placed ${placed}`].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className={`parlay-badge ${st.cls}`}>{st.text}</span>
      </header>
      <p className="parlay-tally">
        <span className="leg-won">✓ {p.won}</span> <span className="leg-lost">✗ {p.lost}</span>
        {p.push > 0 && <span> = {p.push}</span>} <span className="leg-pending">○ {p.pending}</span>
      </p>
      <ol className="parlay-legs">
        {p.legs.map((l) => (
          <LegRow key={l.game_id} l={l} />
        ))}
      </ol>
    </article>
  );
}

function legTime(l: ParlayLeg): string {
  if (!l.start_time) return "";
  const d = new Date(l.start_time);
  const today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return today ? time : `${d.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
}

function LegRow({ l }: { l: ParlayLeg }) {
  const live = l.state === "in" && l.status === "pending";
  const mark = l.status === "won" ? "✓" : l.status === "lost" ? "✗" : l.status === "push" ? "=" : live ? "●" : "○";
  const markLabel = l.status === "pending" ? (live ? "live" : "not started") : l.status;
  const score = l.away_score != null && l.home_score != null ? `${l.away_score}-${l.home_score}` : null;
  return (
    <li className={`parlay-leg leg-${l.status}${live ? " leg-live" : ""}`}>
      <span className="leg-mark" aria-label={markLabel}>
        {mark}
      </span>
      <div className="leg-body">
        <div className="leg-top">
          <span className="leg-time">{legTime(l)}</span>
          <span className="leg-label">{l.label}</span>
        </div>
        <div className="leg-matchup">{l.matchup ?? `Game ${l.game_id}`}</div>
        {(score || l.note || (l.state && l.state !== "pre")) && (
          <div className="leg-status">
            {[l.state !== "pre" ? l.status_text : null, score, l.note].filter(Boolean).join(" · ")}
          </div>
        )}
      </div>
    </li>
  );
}
