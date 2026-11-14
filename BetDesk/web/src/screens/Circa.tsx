import { useEffect, useRef, useState } from "react";
import { ApiError, api, isWarehouseBusy, uploadCircaScreenshots, type CircaTodayResponse } from "../api/client";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { PullToRefresh } from "../components/PullToRefresh";
import { ErrorState, Skeleton, StaleBanner } from "../components/States";
import { useApi } from "../hooks/useApi";

// Limits from DeepSports' upload endpoint (docs/API.md); the Worker caps one request at 35 MB.
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const DAILY_LIMIT = 30;
const BATCH_BYTES = 30 * 1024 * 1024;
const TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"]);
const EXT = /\.(png|jpe?g|webp|heic|heif)$/i;

type Picked = { id: string; file: File; url: string; problem: string | null };
type Upload =
  | { kind: "idle" }
  | { kind: "sending"; sent: number; total: number }
  | { kind: "done"; saved: number; today: number }
  | { kind: "error"; message: string; saved: number };

const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const mb = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function problemWith(f: File): string | null {
  // iPhone Photos may hand over HEIC with an empty type; trust the extension then.
  if (!(TYPES.has(f.type) || (!f.type && EXT.test(f.name)))) return "Not a PNG, JPEG, WebP or HEIC image";
  if (f.size > MAX_FILE_BYTES) return `Too big (${mb(f.size)}); the limit is 10 MB`;
  return null;
}

/** Split files into requests under the Worker's size cap, keeping the order. */
function batches(files: File[]): File[][] {
  const out: File[][] = [];
  let cur: File[] = [];
  let size = 0;
  for (const f of files) {
    if (cur.length && size + f.size > BATCH_BYTES) {
      out.push(cur);
      cur = [];
      size = 0;
    }
    cur.push(f);
    size += f.size;
  }
  if (cur.length) out.push(cur);
  return out;
}

function uploadMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "mac_offline") return "The owner's Mac isn't reachable, so these weren't saved. Try again when it's back.";
    if (isWarehouseBusy(e)) return "The Mac is busy updating stats. Try again in a few minutes.";
    if (e.status === 413) return "Too big: each screenshot must be under 10 MB.";
    if (e.status === 415) return "Only images can be uploaded (PNG, JPEG, WebP or HEIC).";
    if (e.status === 429) return `Today's limit of ${DAILY_LIMIT} screenshots is reached.`;
    if (e.status === 404 || e.status === 405) return "Uploads aren't switched on on the Mac yet.";
    if (e.status === 401 || e.status === 403) return "Your login has expired. Reload the page and sign in again.";
    if (e.status >= 400 && e.status < 500 && e.code) return `The Mac refused the upload: ${e.code}`;
    return `Something went wrong (error ${e.status}). Try again in a moment.`;
  }
  if (typeof navigator !== "undefined" && !navigator.onLine) return "You're offline. Reconnect and try again.";
  return "Couldn't reach the server. Check your connection and try again.";
}

/** Circa's odds board isn't in any feed: the owner adds screenshots here before 2 PM for the daily picks. */
export function Circa() {
  const q = useApi<CircaTodayResponse>(api.circaToday(), {
    refreshSeconds: (d) => (d.read ? 600 : 120),
  });
  const [picked, setPicked] = useState<Picked[]>([]);
  const [upload, setUpload] = useState<Upload>({ kind: "idle" });
  const input = useRef<HTMLInputElement>(null);
  const urls = useRef(new Set<string>());

  // Free the preview images when leaving the screen.
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);

  const drop = (ids: Set<string>) =>
    setPicked((cur) =>
      cur.filter((p) => {
        if (!ids.has(p.id)) return true;
        URL.revokeObjectURL(p.url);
        urls.current.delete(p.url);
        return false;
      }),
    );

  const onPick = (list: FileList | null) => {
    if (!list?.length) return;
    const add = Array.from(list).map((file) => {
      const url = URL.createObjectURL(file);
      urls.current.add(url);
      return { id: `${file.name}:${file.size}:${file.lastModified}:${Math.random()}`, file, url, problem: problemWith(file) };
    });
    setPicked((cur) => [...cur, ...add]);
    if (upload.kind !== "sending") setUpload({ kind: "idle" });
    if (input.current) input.current.value = ""; // so picking the same photo again still fires
  };

  const good = picked.filter((p) => !p.problem);
  const todayCount = q.data?.count ?? 0;
  const left = Math.max(0, DAILY_LIMIT - todayCount);
  const overLimit = q.data != null && good.length > left;
  const sending = upload.kind === "sending";

  const send = async () => {
    const files = good.map((p) => p.file);
    const total = files.reduce((n, f) => n + f.size, 0);
    let done = 0;
    let saved = 0;
    let today = todayCount;
    setUpload({ kind: "sending", sent: 0, total });
    for (const batch of batches(files)) {
      try {
        const r = await uploadCircaScreenshots(batch, (sent) =>
          setUpload({ kind: "sending", sent: Math.min(total, done + sent), total }),
        );
        done += batch.reduce((n, f) => n + f.size, 0);
        saved += r.saved.length;
        today = r.today_count;
        const sentNow = new Set(batch);
        drop(new Set(good.filter((p) => sentNow.has(p.file)).map((p) => p.id)));
      } catch (e) {
        setUpload({ kind: "error", message: uploadMessage(e), saved });
        if (saved) void q.refresh();
        return;
      }
    }
    setUpload({ kind: "done", saved, today });
    void q.refresh();
  };

  const pct = upload.kind === "sending" && upload.total ? Math.round((upload.sent / upload.total) * 100) : 0;

  return (
    <PullToRefresh onRefresh={q.refresh}>
      <PageHeader title="Circa" subtitle="Odds-board screenshots for today's picks" />
      <main className="content">
        <section className="card" aria-labelledby="circa-add-h">
          <h2 id="circa-add-h" className="card-title">Add today's screenshots</h2>
          <p className="circa-intro">
            Circa's prices aren't in any odds feed. Screenshot its odds board and add the pictures here
            before <strong>2 PM</strong>; DeepSports reads them then and uses Circa's real prices in the day's picks.
          </p>
          <label className={`btn circa-pick${sending ? " is-disabled" : ""}`}>
            <input
              ref={input}
              type="file"
              accept="image/*"
              multiple
              disabled={sending}
              className="sr-only"
              onChange={(e) => onPick(e.currentTarget.files)}
            />
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
              <rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" strokeWidth="2" />
              <circle cx="9" cy="10" r="1.6" fill="currentColor" />
              <path d="M4 17l5-5 4 4 2.5-2.5L20 17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            </svg>
            Add screenshots
          </label>

          {picked.length > 0 && (
            <ul className="circa-previews" aria-label="Screenshots to upload">
              {picked.map((p) => (
                <li key={p.id} className={`circa-preview${p.problem ? " has-problem" : ""}`}>
                  <img src={p.url} alt="" loading="lazy" />
                  <div className="circa-preview-text">
                    <span className="circa-preview-name">{p.file.name}</span>
                    <span className={p.problem ? "circa-problem" : "circa-size"}>{p.problem ?? mb(p.file.size)}</span>
                  </div>
                  <button
                    type="button"
                    className="circa-remove"
                    disabled={sending}
                    aria-label={`Remove ${p.file.name}`}
                    onClick={() => drop(new Set([p.id]))}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}

          {overLimit && (
            <p className="circa-warn" role="status">
              Only {plural(left, "more screenshot")} fit today (limit {DAILY_LIMIT}). Remove{" "}
              {good.length - left} to upload.
            </p>
          )}

          {good.length > 0 && (
            <button type="button" className="btn circa-send" disabled={sending || overLimit} onClick={send}>
              {sending ? "Uploading…" : `Upload ${plural(good.length, "screenshot")}`}
            </button>
          )}

          <div aria-live="polite">
            {upload.kind === "sending" && (
              <div className="circa-progress">
                <progress max={100} value={pct} aria-label="Upload progress" />
                <span>{pct}%</span>
              </div>
            )}
            {upload.kind === "done" && (
              <p className="circa-ok">
                Saved {plural(upload.saved, "screenshot")}. {plural(upload.today, "screenshot")} today so far.
              </p>
            )}
            {upload.kind === "error" && (
              <p className="circa-err" role="alert">
                {upload.saved > 0 && `Saved ${plural(upload.saved, "screenshot")}, but the rest didn't go through. `}
                {upload.message}
              </p>
            )}
          </div>
        </section>

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
