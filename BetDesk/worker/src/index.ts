// BetDesk Worker: serves the mirrored DeepSports read API from D1 and accepts snapshot pushes
// from the owner's Mac. Static assets (the PWA) are served by Workers Assets before this code runs,
// except for /api/* and /ingest (`run_worker_first` in wrangler.jsonc).

import { identify, type AccessEnv } from "./access";
import { canonicalKey, health, isAllowedPath, parseIngest } from "./snapshots";

export interface Env extends AccessEnv {
  DB: D1Database;
  ASSETS: Fetcher;
  /** Bearer token the pusher sends on /ingest (secret) */
  INGEST_TOKEN?: string;
}

const BASE_HEADERS = {
  "Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow",
  "X-Content-Type-Options": "nosniff",
};

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...BASE_HEADERS, "Content-Type": "application/json" } });

/** Snapshots older than this are deleted on ingest (old scoreboards and finished games). */
const RETENTION_DAYS = 10;

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/ingest") return env.ASSETS.fetch(req);

    const who = await identify(req, env);
    if (!who) return json(403, { error: "forbidden" });

    if (url.pathname === "/ingest") {
      if (req.method !== "POST") return json(405, { error: "method_not_allowed" });
      return ingest(req, env);
    }
    if (req.method !== "GET") return json(405, { error: "method_not_allowed" });
    if (!who.email) return json(403, { error: "forbidden" }); // service tokens may only push

    if (url.pathname === "/api/health") {
      const row = await env.DB.prepare("SELECT generated_at, warehouse FROM meta WHERE id = 1").first<{
        generated_at: string;
        warehouse: string;
      }>();
      return json(200, health(row ?? null, new Date()));
    }
    if (!isAllowedPath(url.pathname)) return json(404, { error: "not_found" });

    const key = canonicalKey(url.pathname, url.search);
    const row = await env.DB.prepare("SELECT body, generated_at FROM snapshots WHERE key = ?")
      .bind(key)
      .first<{ body: string; generated_at: string }>();
    if (!row) return json(404, { error: "not_mirrored" });
    return new Response(row.body, {
      headers: { ...BASE_HEADERS, "Content-Type": "application/json", "X-BetDesk-Generated-At": row.generated_at },
    });
  },
} satisfies ExportedHandler<Env>;

async function ingest(req: Request, env: Env): Promise<Response> {
  if (!env.INGEST_TOKEN || !(await sameSecret(req.headers.get("Authorization") ?? "", `Bearer ${env.INGEST_TOKEN}`))) {
    return json(401, { error: "unauthorized" });
  }
  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return json(400, { error: "bad_json" });
  }
  const parsed = parseIngest(raw);
  if (!parsed.ok) return json(400, { error: parsed.error });
  const { generated_at, warehouse, entries, final } = parsed.payload;

  const upsert = env.DB.prepare(
    `INSERT INTO snapshots (key, body, generated_at) VALUES (?1, ?2, ?3)
     ON CONFLICT (key) DO UPDATE SET body = excluded.body, generated_at = excluded.generated_at
     WHERE snapshots.body IS NOT excluded.body`,
  );
  const cutoff = new Date(Date.now() - RETENTION_DAYS * 86400_000).toISOString();
  // meta (the app's "Synced" time) moves only with the last chunk of a push, so a push that
  // fails halfway still shows as stale.
  const markPushed = env.DB.prepare(
      `INSERT INTO meta (id, generated_at, warehouse) VALUES (1, ?1, ?2)
       ON CONFLICT (id) DO UPDATE SET generated_at = excluded.generated_at, warehouse = excluded.warehouse
       WHERE excluded.generated_at >= meta.generated_at`,
  ).bind(generated_at, warehouse);
  await env.DB.batch([
    ...entries.map((e) => upsert.bind(e.key, e.body, generated_at)),
    ...(final ? [markPushed] : []),
    // Only date-scoped snapshots expire; standings or team pages may legitimately stay unchanged for days.
    env.DB.prepare(
      "DELETE FROM snapshots WHERE generated_at < ?1 AND (key LIKE '/api/games/%' OR key LIKE '/api/scoreboard?date=%')",
    ).bind(cutoff),
  ]);
  return json(200, { ok: true, stored: entries.length });
}

/** Constant-time comparison via HMAC digests (equal-length outputs whatever the input lengths). */
async function sameSecret(a: string, b: string): Promise<boolean> {
  const key = (await crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, ["sign"])) as CryptoKey;
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([crypto.subtle.sign("HMAC", key, enc.encode(a)), crypto.subtle.sign("HMAC", key, enc.encode(b))]);
  const xa = new Uint8Array(x);
  const ya = new Uint8Array(y);
  let diff = 0;
  for (let i = 0; i < xa.length; i++) diff |= xa[i] ^ ya[i];
  return diff === 0;
}
