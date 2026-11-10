import { beforeAll, describe, expect, it } from "vitest";
import { identify, verifyAccessJwt, type Jwk } from "../src/access";

const TEAM = "https://example-team.cloudflareaccess.com";
const AUD = "aud-tag-123";
let privateKey: CryptoKey;
let jwks: Jwk[];

const b64url = (input: Uint8Array | string) =>
  btoa(String.fromCharCode(...(typeof input === "string" ? new TextEncoder().encode(input) : input)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

async function sign(payload: Record<string, unknown>, kid = "k1"): Promise<string> {
  const head = b64url(JSON.stringify({ alg: "RS256", kid, typ: "JWT" }));
  const body = b64url(JSON.stringify(payload));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", privateKey, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64url(new Uint8Array(sig))}`;
}

const now = Date.parse("2026-11-10T22:00:00Z");
const base = { aud: [AUD], iss: TEAM, exp: now / 1000 + 3600, iat: now / 1000 };
const getKeys = async () => jwks;

beforeAll(async () => {
  const pair = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  privateKey = pair.privateKey;
  jwks = [{ ...((await crypto.subtle.exportKey("jwk", pair.publicKey)) as JsonWebKey), kid: "k1" }];
});

describe("verifyAccessJwt", () => {
  const opts = () => ({ teamDomain: TEAM, aud: AUD, now, getKeys });

  it("accepts a valid user token and lowercases the email", async () => {
    const id = await verifyAccessJwt(await sign({ ...base, email: "Owner@Example.com" }), opts());
    expect(id).toEqual({ email: "owner@example.com", service: false });
  });
  it("treats a token without email as a service token", async () => {
    expect(await verifyAccessJwt(await sign({ ...base, common_name: "abc.access" }), opts())).toEqual({
      email: null,
      service: true,
    });
  });
  it("rejects expired, wrong-audience, wrong-issuer and unknown-key tokens", async () => {
    expect(await verifyAccessJwt(await sign({ ...base, exp: now / 1000 - 1, email: "a@b.c" }), opts())).toBeNull();
    expect(await verifyAccessJwt(await sign({ ...base, aud: ["other"], email: "a@b.c" }), opts())).toBeNull();
    expect(await verifyAccessJwt(await sign({ ...base, iss: "https://evil.example", email: "a@b.c" }), opts())).toBeNull();
    expect(await verifyAccessJwt(await sign({ ...base, email: "a@b.c" }, "k2"), opts())).toBeNull();
  });
  it("refetches the keys once when the key id is unknown (rotation)", async () => {
    const calls: boolean[] = [];
    const rotating = async (_d: string, fresh?: boolean) => {
      calls.push(Boolean(fresh));
      return fresh ? jwks : [];
    };
    const id = await verifyAccessJwt(await sign({ ...base, email: "a@b.c" }), { teamDomain: TEAM, aud: AUD, now, getKeys: rotating });
    expect(id).toMatchObject({ email: "a@b.c" });
    expect(calls).toEqual([false, true]);
  });
  it("refuses (no throw) on a malformed key", async () => {
    const bad = async () => [{ kid: "k1", kty: "RSA", n: "!!", e: "AQAB" }];
    expect(await verifyAccessJwt(await sign({ ...base, email: "a@b.c" }), { teamDomain: TEAM, aud: AUD, now, getKeys: bad })).toBeNull();
  });
  it("rejects a tampered payload", async () => {
    const [h, , s] = (await sign({ ...base, email: "a@b.c" })).split(".");
    const forged = `${h}.${b64url(JSON.stringify({ ...base, email: "mallory@x.y" }))}.${s}`;
    expect(await verifyAccessJwt(forged, opts())).toBeNull();
  });
});

describe("identify", () => {
  const req = (token?: string) =>
    new Request("https://betdesk.example/api/bets", token ? { headers: { "Cf-Access-Jwt-Assertion": token } } : {});

  it("fails closed when Access or the email allowlist isn't configured", async () => {
    const tok = await sign({ ...base, exp: Date.now() / 1000 + 3600, email: "a@b.c" });
    expect(await identify(req(tok), {}, getKeys)).toBeNull();
    expect(await identify(req(tok), { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD }, getKeys)).toBeNull();
    expect(await identify(req(tok), { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, ALLOWED_EMAILS: "a@b.c" }, getKeys)).toMatchObject({
      email: "a@b.c",
    });
  });
  it("requires the header", async () => {
    expect(await identify(req(), { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, ALLOWED_EMAILS: "a@b.c" }, getKeys)).toBeNull();
  });
  it("applies the email allowlist", async () => {
    const env = { ACCESS_TEAM_DOMAIN: TEAM + "/", ACCESS_AUD: AUD, ALLOWED_EMAILS: "owner@example.com, other@example.com" };
    const mk = async (email: string) => req(await sign({ ...base, exp: Date.now() / 1000 + 3600, email }));
    expect(await identify(await mk("owner@example.com"), env, getKeys)).toMatchObject({ email: "owner@example.com" });
    expect(await identify(await mk("stranger@example.com"), env, getKeys)).toBeNull();
  });
  it("honors DEV_NO_ACCESS=1 on localhost only", async () => {
    const local = new Request("http://127.0.0.1:8788/api/bets");
    expect(await identify(local, { DEV_NO_ACCESS: "1" })).toMatchObject({ service: false });
    expect(await identify(req(), { DEV_NO_ACCESS: "1" })).toBeNull();
  });
});
