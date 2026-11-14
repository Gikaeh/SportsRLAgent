// Cloudflare Access check inside the Worker (defense in depth: Access already blocks at the edge,
// but if the Access app were removed or misconfigured, the Worker must still refuse data).
// Verifies the RS256 JWT Access attaches as `Cf-Access-Jwt-Assertion`.

export interface AccessEnv {
  /** e.g. https://<team>.cloudflareaccess.com (secret, set with `wrangler secret put`) */
  ACCESS_TEAM_DOMAIN?: string;
  /** The Access application's AUD tag (secret) */
  ACCESS_AUD?: string;
  /** Required comma-separated email allowlist, checked on top of the Access policy (secret) */
  ALLOWED_EMAILS?: string;
  /** "1" only in local `.dev.vars`: skip the check for `wrangler dev` (honored on localhost only) */
  DEV_NO_ACCESS?: string;
}

export type Identity = { email: string | null; service: boolean };
export type Jwk = JsonWebKey & { kid?: string };
export type KeyFetcher = (teamDomain: string, fresh?: boolean) => Promise<Jwk[]>;

const b64urlToBytes = (s: string): Uint8Array => {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};
const b64urlJson = (s: string): Record<string, unknown> => JSON.parse(new TextDecoder().decode(b64urlToBytes(s)));

let certCache: { domain: string; keys: Jwk[]; at: number } | null = null;

/** Team signing keys, cached for an hour. `fresh` refetches (after a key rotation), at most once a minute. */
export const fetchAccessKeys = async (teamDomain: string, fresh = false): Promise<Jwk[]> => {
  if (certCache && certCache.domain === teamDomain) {
    const age = Date.now() - certCache.at;
    if (age < (fresh ? 60_000 : 3600_000)) return certCache.keys;
  }
  const res = await fetch(`${teamDomain}/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error(`access certs: HTTP ${res.status}`);
  const body = (await res.json()) as { keys?: Jwk[] };
  const keys = body.keys ?? [];
  certCache = { domain: teamDomain, keys, at: Date.now() };
  return keys;
};

/** Verify an Access JWT. Returns the identity, or null when it isn't valid for this app. */
export async function verifyAccessJwt(
  token: string,
  opts: { teamDomain: string; aud: string; now?: number; getKeys?: KeyFetcher; why?: (r: string) => void },
): Promise<Identity | null> {
  const no = (r: string): null => (opts.why?.(r), null);
  const parts = token.split(".");
  if (parts.length !== 3) return no("malformed");
  let header: Record<string, unknown>;
  let payload: Record<string, unknown>;
  try {
    header = b64urlJson(parts[0]);
    payload = b64urlJson(parts[1]);
  } catch {
    return no("malformed");
  }
  if (header.alg !== "RS256") return no("alg");
  const getKeys = opts.getKeys ?? fetchAccessKeys;
  let ok = false;
  try {
    let jwk = (await getKeys(opts.teamDomain)).find((k) => k.kid === header.kid);
    if (!jwk) jwk = (await getKeys(opts.teamDomain, true)).find((k) => k.kid === header.kid); // key rotated?
    if (!jwk) return no("unknown_key");
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlToBytes(parts[2]), signed);
  } catch {
    return no("certs_or_signature"); // certs unreachable, malformed key or signature: refuse, don't 500
  }
  if (!ok) return no("signature");

  const now = Math.floor((opts.now ?? Date.now()) / 1000);
  if (typeof payload.exp !== "number" || payload.exp < now) return no("expired");
  if (typeof payload.nbf === "number" && payload.nbf > now + 60) return no("not_yet_valid");
  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(opts.aud)) return no("aud_mismatch");
  if (payload.iss !== opts.teamDomain) return no("iss_mismatch");

  const email = typeof payload.email === "string" && payload.email ? payload.email.toLowerCase() : null;
  return { email, service: email == null };
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/**
 * Identity for a request, or null to refuse it. Fails closed unless the team domain, AUD and email
 * allowlist are all set. `DEV_NO_ACCESS=1` lets everything through, but only on localhost.
 */
export async function identify(req: Request, env: AccessEnv, getKeys?: KeyFetcher): Promise<Identity | null> {
  if (env.DEV_NO_ACCESS === "1" && LOCAL_HOSTS.has(new URL(req.url).hostname)) {
    return { email: "dev@localhost", service: false };
  }
  const allowed = (env.ALLOWED_EMAILS ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  // Why a request was refused, as one word (never a value), in `wrangler tail`.
  const no = (r: string): null => (console.warn(`access_refused ${r}`), null);
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD || allowed.length === 0) return no("not_configured");
  const token = req.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return no("no_token");
  const id = await verifyAccessJwt(token, {
    teamDomain: env.ACCESS_TEAM_DOMAIN.replace(/\/+$/, ""),
    aud: env.ACCESS_AUD,
    getKeys,
    why: no,
  });
  if (!id) return null;
  if (id.email && !allowed.includes(id.email)) return no("email_not_allowed");
  if (!id.email) console.warn("access_refused no_email_in_token");
  return id;
}
