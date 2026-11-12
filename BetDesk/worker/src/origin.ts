// The Worker's proxy to DeepSports' read API on the owner's Mac, reached through a Cloudflare Tunnel
// whose hostname is itself behind Access (service token only). Pure helpers are unit-tested in
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
];

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
export async function fetchOrigin(
  pathname: string,
  search: string,
  env: OriginEnv,
  fetcher: typeof fetch = fetch,
): Promise<OriginResult> {
  if (!env.ORIGIN_URL) return { kind: "error", status: 503, error: "not_configured" };
  const target = new URL(pathname + search, env.ORIGIN_URL.replace(/\/+$/, "") + "/");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (env.ORIGIN_CLIENT_ID && env.ORIGIN_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = env.ORIGIN_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = env.ORIGIN_CLIENT_SECRET;
  }
  let res: Response;
  try {
    res = await fetcher(target.toString(), {
      headers,
      redirect: "manual",
      signal: AbortSignal.timeout(ORIGIN_TIMEOUT_MS),
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

const isJson = (res: Response) => (res.headers.get("Content-Type") ?? "").includes("application/json");
