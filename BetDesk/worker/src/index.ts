// BetDesk Worker: serves the PWA and proxies the app's read requests to DeepSports' API on the
// owner's Mac through a Cloudflare Tunnel. Static assets are served by Workers Assets before this
// code runs, except for /api/* (`run_worker_first` in wrangler.jsonc).

import { identify, type AccessEnv } from "./access";
import { fetchOrigin, isAllowedPath, MAX_QUERY_CHARS, type OriginEnv } from "./origin";

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

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(req);

    const who = await identify(req, env);
    if (!who?.email) return json(403, { error: "forbidden" }); // people only; no service tokens
    if (req.method !== "GET") return json(405, { error: "method_not_allowed" });
    if (!isAllowedPath(url.pathname) || url.search.length > MAX_QUERY_CHARS) return json(404, { error: "not_found" });

    const r = await fetchOrigin(url.pathname, url.search, env);
    if (r.kind === "error") return json(r.status, { error: r.error });
    return new Response(r.body, { status: r.status, headers: { ...BASE_HEADERS, "Content-Type": "application/json" } });
  },
} satisfies ExportedHandler<Env>;
