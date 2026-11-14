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
const originCalls: { url: string; headers: Headers; method: string; body: unknown }[] = [];
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
      originCalls.push({ url: String(url), headers: new Headers(init?.headers), method: init?.method ?? "GET", body: init?.body });
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

  describe("Circa screenshot upload (the one write route)", () => {
    const form = () => {
      const fd = new FormData();
      fd.append("file", new File([new Uint8Array([137, 80, 78, 71, 1, 2, 3])], "board.png", { type: "image/png" }));
      return fd;
    };

    it("forwards the multipart body unchanged with the service token, and nothing of the user's", async () => {
      originCalls.length = 0;
      originReply = () => Response.json({ date: "2026-11-13", saved: [{ name: "a.png", bytes: 7 }], today_count: 1 });
      const sent = new Request("https://x/", { method: "POST", body: form() });
      const type = sent.headers.get("Content-Type")!;
      const bytes = await sent.arrayBuffer();
      const res = await call(makeEnv(), "/api/circa/screenshots", {
        method: "POST",
        body: bytes,
        headers: { ...(await owner()), "Content-Type": type, Origin: "https://betdesk.example.workers.dev" },
      });
      expect(res.status).toBe(200);
      expect(((await res.json()) as { today_count: number }).today_count).toBe(1);
      expect(originCalls).toHaveLength(1);
      const c = originCalls[0];
      expect(c.url).toBe(`${ORIGIN}/api/circa/screenshots`);
      expect(c.method).toBe("POST");
      expect(c.headers.get("Content-Type")).toBe(type);
      expect(c.headers.get("CF-Access-Client-Id")).toBe("cid");
      expect(c.headers.get("Cookie")).toBeNull();
      expect(c.headers.get("Cf-Access-Jwt-Assertion")).toBeNull();
      expect(new Uint8Array(c.body as ArrayBuffer)).toEqual(new Uint8Array(bytes));
    });

    it("passes DeepSports' JSON 4xx through (e.g. the daily limit)", async () => {
      originReply = () => Response.json({ detail: "daily limit reached" }, { status: 429 });
      const res = await call(makeEnv(), "/api/circa/screenshots", {
        method: "POST",
        body: form(),
        headers: await owner(),
      });
      expect(res.status).toBe(429);
      expect(await res.json()).toEqual({ detail: "daily limit reached" });
    });

    it("refuses other methods and paths, wrong types, oversized bodies and other sites without calling the Mac", async () => {
      originCalls.length = 0;
      const h = await owner();
      const post = (path: string, init: RequestInit = {}) =>
        call(makeEnv(), path, { method: "POST", body: form(), ...init, headers: { ...h, ...(init.headers as object) } });
      expect((await post("/api/circa/screenshots/today")).status).toBe(405);
      expect((await post("/api/circa")).status).toBe(405);
      expect((await post("/api/circa/screenshots?x=1")).status).toBe(405);
      expect((await call(makeEnv(), "/api/circa/screenshots", { method: "PUT", body: "x", headers: h })).status).toBe(405);
      expect((await call(makeEnv(), "/api/circa/screenshots", { method: "DELETE", headers: h })).status).toBe(405);
      expect((await call(makeEnv(), "/api/circa/screenshots", { headers: h })).status).toBe(404); // GET: not a read endpoint
      const json415 = await call(makeEnv(), "/api/circa/screenshots", {
        method: "POST",
        body: JSON.stringify({ a: 1 }),
        headers: { ...h, "Content-Type": "application/json" },
      });
      expect(json415.status).toBe(415);
      const big = new Uint8Array(35 * 1024 * 1024 + 1);
      const res413 = await call(makeEnv(), "/api/circa/screenshots", {
        method: "POST",
        body: big,
        headers: { ...h, "Content-Type": "multipart/form-data; boundary=abc" },
      });
      expect(res413.status).toBe(413);
      const lying = new Request("https://betdesk.example.workers.dev/api/circa/screenshots", {
        method: "POST",
        body: big,
        headers: { ...h, "Content-Type": "multipart/form-data; boundary=abc" },
      });
      lying.headers.delete("Content-Length");
      expect((await worker.fetch(lying, makeEnv())).status).toBe(413);
      expect((await post("/api/circa/screenshots", { headers: { Origin: "https://evil.example" } })).status).toBe(403);
      expect(originCalls).toHaveLength(0);
    });

    it("requires a valid Access identity like every other /api route", async () => {
      originCalls.length = 0;
      expect((await call(makeEnv(), "/api/circa/screenshots", { method: "POST", body: form() })).status).toBe(403);
      const other = { "Cf-Access-Jwt-Assertion": await jwt({ email: "stranger@example.com" }) };
      expect((await call(makeEnv(), "/api/circa/screenshots", { method: "POST", body: form(), headers: other })).status).toBe(403);
      expect(originCalls).toHaveLength(0);
    });
  });

  it("serves the app shell without touching Access", async () => {
    expect(await (await call(makeEnv(), "/")).text()).toBe("shell");
  });
});
