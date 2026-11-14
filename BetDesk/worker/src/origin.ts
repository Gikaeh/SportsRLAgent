// The Worker's proxy to DeepSports' read API on the owner's Mac, reached through a Cloudflare Tunnel
// whose hostname is itself behind Access (service token only). Reads are GET on an allowlist; the one write is the Circa
// screenshot upload (`postOrigin`). Pure helpers are unit-tested in
// test/origin.test.ts; the handler's behavior in test/handler.test.ts.

/** Read endpoints the app may reach on the Mac. Everything else is refused before leaving Cloudflare. */
const ALLOWED = [
  /^\/api\/health$/,
  /^\/api\/scoreboard$/,
  /^\/api\/games\/[A-Za-z0-9_-]{1,32}$/,
  /^\/api\/predictions\/record$/,
  /^\/api\/bets$/,
  /^\/api\/standings$/,
  /^\/api\/teams\/[A-Za-z0-9]{1,8}$/,
  /^\/api\/followed$/,
  /^\/api\/circa\/screenshots\/today$/,
];

/** The one write route: Circa odds-board screenshots from the owner's phone (multipart/form-data). */
export const UPLOAD_PATH = "/api/circa/screenshots";
/** Total body cap for one upload request. DeepSports caps each image at 10 MB; the app sends batches under 30 MB. */
export const MAX_UPLOAD_BYTES = 35 * 1024 * 1024;
/** Uploads carry megabytes from the Worker to the Mac, so they get longer than reads. */
export const UPLOAD_TIMEOUT_MS = 60_000;

/** Query strings the app sends are short (league, date, days); anything longer is refused. */
export const MAX_QUERY_CHARS = 200;
/** A Mac that hasn't answered by then counts as offline. */
export const ORIGIN_TIMEOUT_MS = 15_000;

export function isAllowedPath(pathname: string): boolean {
  return ALLOWED.some((re) => re.test(pathname));
}

export interface OriginEnv {
  /** Tunnel hostname, e.g. https://<name>.<your domain> (secret: keeps the domain out of the repo) */
  ORIGIN_URL?: string;
  /** Access service token for the tunnel hostname (secrets) */
  ORIGIN_CLIENT_ID?: string;
  ORIGIN_CLIENT_SECRET?: string;
}

export type OriginResult =
  | { kind: "ok"; status: number; body: string }
  | { kind: "error"; status: number; error: "not_configured" | "mac_offline" | "origin_auth" };

/**
 * GET `pathname + search` from the Mac. Only the Accept header and the service token are sent:
 * the user's cookies and Access JWT never leave the Worker.
 */
export function fetchOrigin(
  pathname: string,
  search: string,
  env: OriginEnv,
  fetcher: typeof fetch = fetch,
): Promise<OriginResult> {
  return callOrigin(pathname + search, env, fetcher, {}, ORIGIN_TIMEOUT_MS);
}

/**
 * POST an upload body to the Mac unchanged. Sends only Accept, the body's Content-Type (with its
 * multipart boundary) and the service token, same as GETs: nothing of the user's.
 */
export function postOrigin(
  pathname: string,
  body: ArrayBuffer,
  contentType: string,
  env: OriginEnv,
  fetcher: typeof fetch = fetch,
): Promise<OriginResult> {
  return callOrigin(pathname, env, fetcher, { method: "POST", body, contentType }, UPLOAD_TIMEOUT_MS);
}

async function callOrigin(
  pathAndSearch: string,
  env: OriginEnv,
  fetcher: typeof fetch,
  write: { method?: "POST"; body?: ArrayBuffer; contentType?: string },
  timeoutMs: number,
): Promise<OriginResult> {
  if (!env.ORIGIN_URL) return { kind: "error", status: 503, error: "not_configured" };
  const target = new URL(pathAndSearch, env.ORIGIN_URL.replace(/\/+$/, "") + "/");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (write.contentType) headers["Content-Type"] = write.contentType;
  if (env.ORIGIN_CLIENT_ID && env.ORIGIN_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = env.ORIGIN_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = env.ORIGIN_CLIENT_SECRET;
  }
  let res: Response;
  try {
    res = await fetcher(target.toString(), {
      method: write.method ?? "GET",
      body: write.body,
      headers,
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    return { kind: "error", status: 503, error: "mac_offline" };
  }
  // Access redirects to its login page when the service token is missing or wrong.
  if (res.status >= 300 && res.status < 400) return { kind: "error", status: 502, error: "origin_auth" };
  if (res.status === 401 || res.status === 403) {
    if (!isJson(res)) return { kind: "error", status: 502, error: "origin_auth" };
  }
  // Cloudflare's own error pages (tunnel down: 502/530/1033) are HTML; DeepSports' errors are JSON.
  if (res.status >= 500 && !isJson(res)) return { kind: "error", status: 503, error: "mac_offline" };
  return { kind: "ok", status: res.status, body: await res.text() };
}

/**
 * Read a request body up to `max` bytes. Returns null as soon as it is bigger, whatever
 * Content-Length claims, so an oversized upload never reaches the Mac.
 */
export async function readCapped(req: Request, max: number): Promise<ArrayBuffer | null> {
  const declared = Number(req.headers.get("Content-Length") ?? "0");
  if (declared > max) return null;
  if (!req.body) return new ArrayBuffer(0);
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.byteLength;
  }
  return out.buffer;
}

const isJson = (res: Response) => (res.headers.get("Content-Type") ?? "").includes("application/json");
