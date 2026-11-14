// BetDesk Worker: serves the PWA and proxies the app's read requests (and its one upload) to DeepSports' API on the
// owner's Mac through a Cloudflare Tunnel. Static assets are served by Workers Assets before this
// code runs, except for /api/* (`run_worker_first` in wrangler.jsonc).

import { identify, type AccessEnv } from "./access";
import {
  fetchOrigin,
  isAllowedPath,
  MAX_QUERY_CHARS,
  MAX_UPLOAD_BYTES,
  postOrigin,
  readCapped,
  UPLOAD_PATH,
  type OriginEnv,
  type OriginResult,
} from "./origin";

export interface Env extends AccessEnv, OriginEnv {
  ASSETS: Fetcher;
}

const BASE_HEADERS = {
  "Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow",
  "X-Content-Type-Options": "nosniff",
};

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...BASE_HEADERS, "Content-Type": "application/json" } });

const reply = (r: OriginResult) =>
  r.kind === "error"
    ? json(r.status, { error: r.error })
    : new Response(r.body, { status: r.status, headers: { ...BASE_HEADERS, "Content-Type": "application/json" } });

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** The only write: Circa screenshots, forwarded byte for byte after the size and type checks. */
async function upload(req: Request, url: URL, env: Env): Promise<Response> {
  // Browsers always send Origin on a POST: refuse uploads started by another site (local dev excepted,
  // where Vite's proxy keeps its own origin).
  const origin = req.headers.get("Origin");
  if (origin && origin !== url.origin && !LOCAL_HOSTS.has(url.hostname)) return json(403, { error: "bad_origin" });
  const type = req.headers.get("Content-Type") ?? "";
  if (!/^multipart\/form-data;\s*boundary=/i.test(type)) return json(415, { error: "unsupported_media_type" });
  const body = await readCapped(req, MAX_UPLOAD_BYTES);
  if (!body) return json(413, { error: "too_large" });
  return reply(await postOrigin(UPLOAD_PATH, body, type, env));
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(req);

    const who = await identify(req, env);
    if (!who?.email) return json(403, { error: "forbidden" }); // people only; no service tokens
    if (req.method === "POST" && url.pathname === UPLOAD_PATH && !url.search) return upload(req, url, env);
    if (req.method !== "GET") return json(405, { error: "method_not_allowed" });
    if (!isAllowedPath(url.pathname) || url.search.length > MAX_QUERY_CHARS) return json(404, { error: "not_found" });

    return reply(await fetchOrigin(url.pathname, url.search, env));
  },
} satisfies ExportedHandler<Env>;
