// The request handler's access rules, with Access JWTs signed by a test key and a tiny in-memory D1.
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "../src/index";

const TEAM = "https://example-team.cloudflareaccess.com";
const AUD = "aud-tag-123";
const OWNER = "owner@example.com";
let privateKey: CryptoKey;

const b64url = (input: Uint8Array | string) =>
  btoa(String.fromCharCode(...(typeof input === "string" ? new TextEncoder().encode(input) : input)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

async function jwt(claims: Record<string, unknown>): Promise<string> {
  const head = b64url(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const body = b64url(JSON.stringify({ aud: [AUD], iss: TEAM, exp: Date.now() / 1000 + 600, ...claims }));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", privateKey, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64url(new Uint8Array(sig))}`;
}

/** Just enough of D1 for the handler: snapshot/meta lookups and recording batched writes. */
function fakeDb(rows: Record<string, string>) {
  const batches: unknown[][] = [];
  const stmt = (sql: string) => ({
    bind: (...args: unknown[]) => ({ ...stmt(sql), args }),
    first: async () => {
      if (sql.includes("FROM meta")) return { generated_at: new Date().toISOString(), warehouse: "ok" };
      return null;
    },
  });
  return {
    db: {
      prepare: (sql: string) => {
        const s = stmt(sql);
        return {
          ...s,
          bind: (...args: unknown[]) => ({
            ...s,
            args,
            first: async () => (sql.includes("FROM snapshots") && rows[args[0] as string] ? { body: rows[args[0] as string], generated_at: "t" } : s.first()),
          }),
        };
      },
      batch: async (b: unknown[]) => {
        batches.push(b);
        return [];
      },
    },
    batches,
  };
}

function makeEnv(rows: Record<string, string> = {}) {
  const { db, batches } = fakeDb(rows);
  const env = {
    DB: db,
    ASSETS: { fetch: async () => new Response("shell") },
    ACCESS_TEAM_DOMAIN: TEAM,
    ACCESS_AUD: AUD,
    ALLOWED_EMAILS: OWNER,
    INGEST_TOKEN: "tok",
  } as unknown as Env;
  return { env, batches };
}

const call = (env: Env, path: string, init: RequestInit = {}) =>
  worker.fetch(new Request(`https://betdesk.example.workers.dev${path}`, init), env);

beforeAll(async () => {
  const pair = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  privateKey = pair.privateKey;
  const jwk = { ...((await crypto.subtle.exportKey("jwk", pair.publicKey)) as JsonWebKey), kid: "k1" };
  vi.stubGlobal("fetch", async (url: string) =>
    String(url).endsWith("/cdn-cgi/access/certs") ? Response.json({ keys: [jwk] }) : new Response(null, { status: 404 }),
  );
});
afterAll(() => vi.unstubAllGlobals());

describe("worker handler", () => {
  it("serves a mirrored snapshot to an allowed user, and not_mirrored for a missing one", async () => {
    const { env } = makeEnv({ "/api/bets": '{"games":[]}' });
    const h = { "Cf-Access-Jwt-Assertion": await jwt({ email: OWNER }) };
    const ok = await call(env, "/api/bets", { headers: h });
    expect(ok.status).toBe(200);
    expect(await ok.text()).toBe('{"games":[]}');
    expect(ok.headers.get("X-Robots-Tag")).toContain("noindex");
    const miss = await call(env, "/api/teams/LAL", { headers: h });
    expect(miss.status).toBe(404);
    expect(await miss.json()).toEqual({ error: "not_mirrored" });
    expect((await call(env, "/api/glance", { headers: h })).status).toBe(404);
    expect((await call(env, "/api/health", { headers: h })).status).toBe(200);
  });

  it("refuses requests without a valid Access identity, or from other emails", async () => {
    const { env } = makeEnv({ "/api/bets": "{}" });
    expect((await call(env, "/api/bets")).status).toBe(403);
    const other = { "Cf-Access-Jwt-Assertion": await jwt({ email: "stranger@example.com" }) };
    expect((await call(env, "/api/bets", { headers: other })).status).toBe(403);
  });

  it("lets a service token push but not read", async () => {
    const { env, batches } = makeEnv({ "/api/bets": "{}" });
    const svc = { "Cf-Access-Jwt-Assertion": await jwt({ common_name: "pusher.access" }) };
    expect((await call(env, "/api/bets", { headers: svc })).status).toBe(403);
    const body = JSON.stringify({ generated_at: new Date().toISOString(), final: true, entries: [{ key: "/api/bets", body: "{}" }] });
    const res = await call(env, "/ingest", { method: "POST", headers: { ...svc, Authorization: "Bearer tok" }, body });
    expect(res.status).toBe(200);
    expect(batches).toHaveLength(1);
  });

  it("requires the ingest bearer token, even for a signed-in owner", async () => {
    const { env, batches } = makeEnv();
    const h = { "Cf-Access-Jwt-Assertion": await jwt({ email: OWNER }) };
    const body = JSON.stringify({ generated_at: new Date().toISOString(), entries: [] });
    expect((await call(env, "/ingest", { method: "POST", headers: h, body })).status).toBe(401);
    expect((await call(env, "/ingest", { method: "POST", headers: { ...h, Authorization: "Bearer nope" }, body })).status).toBe(401);
    expect((await call(env, "/ingest", { headers: h })).status).toBe(405);
    expect((await call(env, "/api/bets", { method: "POST", headers: h })).status).toBe(405);
    expect(batches).toHaveLength(0);
  });

  it("serves the app shell without touching Access", async () => {
    const { env } = makeEnv();
    expect(await (await call(env, "/")).text()).toBe("shell");
  });
});
