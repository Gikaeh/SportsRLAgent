import { describe, expect, it } from "vitest";
import { isAllowedPath } from "../src/origin";

describe("isAllowedPath", () => {
  it.each(["/api/health", "/api/scoreboard", "/api/games/401811234", "/api/teams/LAL", "/api/bets", "/api/predictions/record", "/api/followed", "/api/standings", "/api/circa/screenshots/today"])(
    "allows %s",
    (p) => expect(isAllowedPath(p)).toBe(true),
  );
  it.each(["/api/glance", "/api/teams/../x", "/api/stakes", "/ingest", "/api/games/a/b", "/api/health/x", "/docs", "/api/circa/screenshots", "/api/circa/screenshots/x"])(
    "rejects %s",
    (p) => expect(isAllowedPath(p)).toBe(false),
  );
});
