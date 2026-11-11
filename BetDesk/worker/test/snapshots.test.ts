import { describe, expect, it } from "vitest";
import { canonicalKey, health, isAllowedPath, MAX_ENTRIES, parseIngest, STALE_SECONDS } from "../src/snapshots";

describe("canonicalKey", () => {
  it("sorts params so the app's order and the pusher's order match", () => {
    expect(canonicalKey("/api/scoreboard", "?league=nba&date=2026-11-10")).toBe(
      canonicalKey("/api/scoreboard", "?date=2026-11-10&league=nba"),
    );
    expect(canonicalKey("/api/scoreboard", "?league=nba&date=2026-11-10")).toBe(
      "/api/scoreboard?date=2026-11-10&league=nba",
    );
  });
  it("drops empty params and keeps bare paths bare", () => {
    expect(canonicalKey("/api/bets", "")).toBe("/api/bets");
    expect(canonicalKey("/api/scoreboard", "?league=ncaab&date=")).toBe("/api/scoreboard?league=ncaab");
  });
});

describe("isAllowedPath", () => {
  it.each(["/api/scoreboard", "/api/games/401811234", "/api/teams/LAL", "/api/bets", "/api/predictions/record"])(
    "allows %s",
    (p) => expect(isAllowedPath(p)).toBe(true),
  );
  it.each(["/api/health", "/api/glance", "/api/teams/../x", "/api/stakes", "/ingest", "/api/games/a/b"])(
    "rejects %s",
    (p) => expect(isAllowedPath(p)).toBe(false),
  );
});

describe("parseIngest", () => {
  const good = {
    generated_at: "2026-11-10T22:00:00Z",
    warehouse: "ok",
    entries: [{ key: "/api/scoreboard?league=nba&date=2026-11-10", body: "{}" }],
  };
  it("accepts a valid bundle and canonicalizes keys", () => {
    const r = parseIngest(good);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.payload.entries[0].key).toBe("/api/scoreboard?date=2026-11-10&league=nba");
      expect(r.payload.generated_at).toBe("2026-11-10T22:00:00.000Z");
    }
  });
  it("rejects paths outside the allowlist", () => {
    expect(parseIngest({ ...good, entries: [{ key: "/api/stakes", body: "{}" }] })).toEqual({
      ok: false,
      error: "path_not_allowed",
    });
  });
  it("rejects bad timestamps, non-string bodies and oversize bundles", () => {
    expect(parseIngest({ ...good, generated_at: "nope" }).ok).toBe(false);
    expect(parseIngest({ ...good, entries: [{ key: "/api/bets", body: {} }] }).ok).toBe(false);
    const many = Array.from({ length: MAX_ENTRIES + 1 }, () => ({ key: "/api/bets", body: "{}" }));
    expect(parseIngest({ ...good, entries: many })).toEqual({ ok: false, error: "too_many_entries" });
  });
});

describe("health", () => {
  const now = new Date("2026-11-10T22:30:00Z");
  it("is stale before the first push", () => {
    expect(health(null, now)).toMatchObject({ generated_at: null, age_seconds: null, stale: true });
  });
  it("is fresh within the window and stale after it", () => {
    const fresh = health({ generated_at: "2026-11-10T22:29:00Z", warehouse: "ok" }, now);
    expect(fresh).toMatchObject({ age_seconds: 60, stale: false, warehouse: "ok" });
    const old = new Date(now.getTime() - (STALE_SECONDS + 1) * 1000).toISOString();
    expect(health({ generated_at: old, warehouse: "busy" }, now)).toMatchObject({ stale: true, warehouse: "busy" });
  });
});
