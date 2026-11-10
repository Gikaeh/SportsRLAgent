import { useApi } from "../hooks/useApi";
import type { MirrorHealth } from "../api/types";

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/**
 * BetDesk serves snapshots pushed from the owner's Mac. Show when the data is from, and warn
 * loudly once it's stale (Mac asleep, drive unplugged, DeepSports server or pusher stopped).
 */
export function MirrorStatus() {
  const q = useApi<MirrorHealth>("/api/health", { refreshSeconds: () => 60, retrySeconds: 60 });
  const h = q.data;
  if (!h) return null;
  if (!h.generated_at) {
    return (
      <div className="mirror mirror-stale" role="status">
        No data synced yet. The owner's Mac hasn't pushed a snapshot.
      </div>
    );
  }
  if (h.stale) {
    const mins = Math.round((h.age_seconds ?? 0) / 60);
    const ago = mins >= 120 ? `${Math.round(mins / 60)} h` : `${mins} min`;
    return (
      <div className="mirror mirror-stale" role="status">
        Data is {ago} old (last sync {clock(h.generated_at)}). The owner's Mac isn't syncing right now.
      </div>
    );
  }
  return <div className="mirror">Synced {clock(h.generated_at)}</div>;
}
