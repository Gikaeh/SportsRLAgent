// Snapshot keys and ingest validation. Pure functions, unit-tested in test/snapshots.test.ts.

/** Endpoints the mirror may store. Anything else is rejected at ingest (keeps stakes and odd paths out). */
const ALLOWED = [
  /^\/api\/scoreboard$/,
  /^\/api\/games\/[A-Za-z0-9_-]{1,32}$/,
  /^\/api\/predictions\/record$/,
  /^\/api\/bets$/,
  /^\/api\/standings$/,
  /^\/api\/teams\/[A-Za-z0-9]{1,8}$/,
  /^\/api\/followed$/,
];

export const MAX_ENTRIES = 40; // D1 free plan: 50 queries per invocation; leave room for meta + cleanup
export const MAX_BODY_CHARS = 1_500_000; // D1 rows are capped at 2 MB

/** `/api/x?b=2&a=1` and `/api/x?a=1&b=2` are the same snapshot. Empty params are dropped. */
export function canonicalKey(pathname: string, search: string): string {
  const params = [...new URLSearchParams(search)].filter(([, v]) => v !== "");
  params.sort(([a, av], [b, bv]) => (a === b ? av.localeCompare(bv) : a.localeCompare(b)));
  const qs = new URLSearchParams(params).toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

export function isAllowedPath(pathname: string): boolean {
  return ALLOWED.some((re) => re.test(pathname));
}

export type IngestEntry = { key: string; body: string };
/** `final`: the last chunk of a push; only it updates the "last synced" time. */
export type IngestPayload = { generated_at: string; warehouse: "ok" | "busy"; final: boolean; entries: IngestEntry[] };

/** Validate a pushed bundle. Returns the payload with canonical keys, or an error code. */
export function parseIngest(raw: unknown): { ok: true; payload: IngestPayload } | { ok: false; error: string } {
  if (!raw || typeof raw !== "object") return { ok: false, error: "bad_payload" };
  const r = raw as Record<string, unknown>;
  if (typeof r.generated_at !== "string" || Number.isNaN(Date.parse(r.generated_at))) {
    return { ok: false, error: "bad_generated_at" };
  }
  const warehouse = r.warehouse === "busy" ? "busy" : "ok";
  if (!Array.isArray(r.entries)) return { ok: false, error: "bad_entries" };
  if (r.entries.length > MAX_ENTRIES) return { ok: false, error: "too_many_entries" };
  const entries: IngestEntry[] = [];
  for (const e of r.entries as unknown[]) {
    if (!e || typeof e !== "object") return { ok: false, error: "bad_entry" };
    const { key, body } = e as Record<string, unknown>;
    if (typeof key !== "string" || typeof body !== "string") return { ok: false, error: "bad_entry" };
    if (body.length > MAX_BODY_CHARS) return { ok: false, error: "entry_too_large" };
    let url: URL;
    try {
      url = new URL(key, "https://mirror.invalid");
    } catch {
      return { ok: false, error: "bad_key" };
    }
    if (!isAllowedPath(url.pathname)) return { ok: false, error: "path_not_allowed" };
    entries.push({ key: canonicalKey(url.pathname, url.search), body });
  }
  return { ok: true, payload: { generated_at: new Date(r.generated_at).toISOString(), warehouse, final: r.final === true, entries } };
}

export const STALE_SECONDS = 20 * 60;

export function health(lastPush: { generated_at: string; warehouse: string } | null, now: Date) {
  const age = lastPush ? Math.max(0, Math.round((now.getTime() - Date.parse(lastPush.generated_at)) / 1000)) : null;
  return {
    ok: true,
    warehouse: lastPush?.warehouse === "busy" ? "busy" : "ok",
    now: now.toISOString(),
    generated_at: lastPush?.generated_at ?? null,
    age_seconds: age,
    stale: age == null || age > STALE_SECONDS,
  };
}
