// The request handler: access rules (Access JWTs signed by a test key) and the proxy to a stubbed Mac.
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

const ORIGIN = "https://ds.example.test";
/** Requests that reached the "Mac", for asserting what left the Worker. */
const originCalls: { url: string; headers: Headers }[] = [];
let originReply: () => Response = () => Response.json({ games: [] });

function makeEnv() {
  return {
    ASSETS: { fetch: async () => new Response("shell") },
    ACCESS_TEAM_DOMAIN: TEAM,
    ACCESS_AUD: AUD,
    ALLOWED_EMAILS: OWNER,
    ORIGIN_URL: ORIGIN,
    ORIGIN_CLIENT_ID: "cid",
    ORIGIN_CLIENT_SECRET: "csecret",
  } as unknown as Env;
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
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (String(url).endsWith("/cdn-cgi/access/certs")) return Response.json({ keys: [jwk] });
    if (String(url).startsWith(ORIGIN)) {
      originCalls.push({ url: String(url), headers: new Headers(init?.headers) });
      return originReply();
    }
    return new Response(null, { status: 404 });
  });
});
afterAll(() => vi.unstubAllGlobals());

describe("worker handler", () => {
  const owner = async () => ({ "Cf-Access-Jwt-Assertion": await jwt({ email: OWNER }), Cookie: "CF_Authorization=x" });

  it("proxies an allowed GET to the Mac with the service token, and nothing of the user's", async () => {
    originCalls.length = 0;
    originReply = () => Response.json({ games: [] });
    const res = await call(makeEnv(), "/api/scoreboard?league=nba&date=2026-11-10", { headers: await owner() });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ games: [] });
    expect(res.headers.get("X-Robots-Tag")).toContain("noindex");
    expect(originCalls).toHaveLength(1);
    expect(originCalls[0].url).toBe(`${ORIGIN}/api/scoreboard?league=nba&date=2026-11-10`);
    expect(originCalls[0].headers.get("CF-Access-Client-Id")).toBe("cid");
    expect(originCalls[0].headers.get("Cookie")).toBeNull();
    expect(originCalls[0].headers.get("Cf-Access-Jwt-Assertion")).toBeNull();
  });

  it("passes DeepSports' JSON errors through (warehouse busy stays a 503 with its code)", async () => {
    originReply = () => Response.json({ error: "warehouse_busy" }, { status: 503 });
    const res = await call(makeEnv(), "/api/standings", { headers: await owner() });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "warehouse_busy" });
  });

  it("reports mac_offline when the tunnel is down, and origin_auth when Access redirects", async () => {
    originReply = () => new Response("<html>1033</html>", { status: 530, headers: { "Content-Type": "text/html" } });
    let res = await call(makeEnv(), "/api/bets", { headers: await owner() });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "mac_offline" });
    originReply = () => new Response(null, { status: 302, headers: { Location: "https://team.cloudflareaccess.com/login" } });
    res = await call(makeEnv(), "/api/bets", { headers: await owner() });
    expect(await res.json()).toEqual({ error: "origin_auth" });
    originReply = () => {
      throw new TypeError("network");
    };
    res = await call(makeEnv(), "/api/bets", { headers: await owner() });
    expect(await res.json()).toEqual({ error: "mac_offline" });
  });

  it("refuses paths outside the allowlist, long queries and non-GET methods without calling the Mac", async () => {
    originCalls.length = 0;
    const h = await owner();
    expect((await call(makeEnv(), "/api/glance", { headers: h })).status).toBe(404);
    expect((await call(makeEnv(), "/api/teams/../x", { headers: h })).status).toBe(404);
    expect((await call(makeEnv(), `/api/scoreboard?x=${"a".repeat(300)}`, { headers: h })).status).toBe(404);
    expect((await call(makeEnv(), "/api/bets", { method: "POST", headers: h })).status).toBe(405);
    expect(originCalls).toHaveLength(0);
  });

  it("refuses requests without a valid Access identity, from other emails, or from service tokens", async () => {
    originCalls.length = 0;
    expect((await call(makeEnv(), "/api/bets")).status).toBe(403);
    const other = { "Cf-Access-Jwt-Assertion": await jwt({ email: "stranger@example.com" }) };
    expect((await call(makeEnv(), "/api/bets", { headers: other })).status).toBe(403);
    const svc = { "Cf-Access-Jwt-Assertion": await jwt({ common_name: "svc.access" }) };
    expect((await call(makeEnv(), "/api/bets", { headers: svc })).status).toBe(403);
    expect(originCalls).toHaveLength(0);
  });

  it("fails closed when the origin isn't configured", async () => {
    const env = { ...makeEnv(), ORIGIN_URL: undefined } as unknown as Env;
    const res = await call(env, "/api/bets", { headers: await owner() });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "not_configured" });
  });

  it("serves the app shell without touching Access", async () => {
    expect(await (await call(makeEnv(), "/")).text()).toBe("shell");
  });
});
