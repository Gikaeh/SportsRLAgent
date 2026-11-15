import { describe, expect, it } from "vitest";
import { isAllowedPath } from "../src/origin";

describe("isAllowedPath", () => {
  it.each(["/api/health", "/api/scoreboard", "/api/games/401811234", "/api/teams/LAL", "/api/bets", "/api/predictions/record", "/api/followed", "/api/standings", "/api/picks/today"])(
    "allows %s",
    (p) => expect(isAllowedPath(p)).toBe(true),
  );
  it.each(["/api/glance", "/api/teams/../x", "/api/stakes", "/ingest", "/api/games/a/b", "/api/health/x", "/docs", "/api/circa/screenshots", "/api/circa/screenshots/today", "/api/circa/screenshots/x", "/api/picks", "/api/picks/today/x"])(
    "rejects %s",
    (p) => expect(isAllowedPath(p)).toBe(false),
  );
});
