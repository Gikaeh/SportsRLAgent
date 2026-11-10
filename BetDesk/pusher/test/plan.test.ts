import { describe, expect, it } from "vitest";
import { chunk, clampRefresh, decide, easternDate, gameKeys, isLive, scoreboardKeys } from "../src/plan.ts";

const now = new Date("2026-11-11T03:30:00Z"); // 10:30 PM Eastern on Nov 10

describe("easternDate", () => {
  it("uses the Eastern calendar day, not UTC", () => {
    expect(easternDate(now)).toBe("2026-11-10");
    expect(easternDate(now, -1)).toBe("2026-11-09");
    expect(easternDate(now, 1)).toBe("2026-11-11");
  });
});

describe("decide", () => {
  it("does a full push first, then every 15 min; live pushes in between", () => {
    expect(decide({}, now, false, false)).toEqual({ push: true, full: true });
    const recent = { lastFullAt: new Date(now.getTime() - 5 * 60_000).toISOString() };
    expect(decide(recent, now, false, false)).toEqual({ push: false, full: false });
    expect(decide(recent, now, true, false)).toEqual({ push: true, full: false });
    expect(decide(recent, now, false, true)).toEqual({ push: true, full: true });
    const old = { lastFullAt: new Date(now.getTime() - 16 * 60_000).toISOString() };
    expect(decide(old, now, false, false)).toEqual({ push: true, full: true });
  });
});

describe("decide after a failed push", () => {
  it("backs off for 5 minutes, then retries", () => {
    const failed = { lastFailAt: new Date(now.getTime() - 2 * 60_000).toISOString() };
    expect(decide(failed, now, true, false)).toEqual({ push: false, full: false });
    expect(decide(failed, now, true, true)).toEqual({ push: true, full: true });
    const older = { lastFailAt: new Date(now.getTime() - 6 * 60_000).toISOString() };
    expect(decide(older, now, false, false)).toEqual({ push: true, full: true });
  });
});

describe("scoreboardKeys", () => {
  it("covers yesterday + today on live runs and the app's window on full runs", () => {
    const live = scoreboardKeys(now, false);
    expect(live).toContain("/api/scoreboard?league=nba");
    expect(live).toContain("/api/scoreboard?league=ncaab&date=2026-11-09");
    expect(live).not.toContain("/api/scoreboard?league=nba&date=2026-11-11");
    expect(scoreboardKeys(now, true)).toContain("/api/scoreboard?league=nba&date=2026-11-13");
  });
});

describe("isLive", () => {
  it("is true when a list says live or holds an in-progress game", () => {
    expect(isLive([{ live: false, games: [{ id: "1", state: "post" }] }])).toBe(false);
    expect(isLive([{ live: true }])).toBe(true);
    expect(isLive([{ games: [{ id: "1", state: "in" }] }])).toBe(true);
  });
});

describe("gameKeys", () => {
  const nba = { league: "nba" as const, body: { games: [
    { id: "n1", state: "in" }, { id: "n2", state: "post" }, { id: "n3", state: "pre" },
  ] } };
  const ncaab = { league: "ncaab" as const, body: { games: [
    { id: "c1", state: "in" }, { id: "c2", state: "in", followed: true }, { id: "c3", state: "post", bets: ["NEV -3.5"] },
  ] } };

  it("takes every NBA game but only followed or bet college games", () => {
    const keys = gameKeys([nba, ncaab], null, true, new Set());
    expect(keys).toEqual(expect.arrayContaining([
      "/api/games/n1?league=nba", "/api/games/n2?league=nba", "/api/games/n3?league=nba",
      "/api/games/c2?league=ncaab", "/api/games/c3?league=ncaab",
    ]));
    expect(keys).not.toContain("/api/games/c1?league=ncaab");
  });
  it("skips upcoming games on live runs and finals already pushed", () => {
    const keys = gameKeys([nba], null, false, new Set(["/api/games/n2?league=nba"]));
    expect(keys).toEqual(["/api/games/n1?league=nba"]);
  });
  it("includes games from the bets list in their own league", () => {
    const bets = { games: [{ id: "c9", state: "in", league: "ncaab" }] };
    expect(gameKeys([], bets, false, new Set())).toEqual(["/api/games/c9?league=ncaab"]);
  });
});

describe("clampRefresh", () => {
  it("raises fast polling to 30 s and leaves other bodies alone", () => {
    expect(JSON.parse(clampRefresh('{"refresh_seconds":10,"x":1}'))).toEqual({ refresh_seconds: 30, x: 1 });
    expect(clampRefresh('{"refresh_seconds":300}')).toBe('{"refresh_seconds":300}');
    expect(clampRefresh("not json")).toBe("not json");
  });
});

describe("chunk", () => {
  it("splits by entry count and by size", () => {
    const e = (n: number) => ({ key: `/k${n}`, body: "x".repeat(10) });
    expect(chunk([e(1), e(2), e(3)], 2, 1000).map((c) => c.length)).toEqual([2, 1]);
    expect(chunk([e(1), e(2), e(3)], 10, 20).map((c) => c.length)).toEqual([1, 1, 1]);
    expect(chunk([])).toEqual([]);
  });
});
