import { useEffect, useState } from "react";
import type { League } from "./api/types";
import { isLeague } from "./league";

export type Route =
  | { name: "today"; date: string | null; league: League | null }
  | { name: "game"; id: string; league: League }
  | { name: "bets" }
  | { name: "standings" }
  | { name: "model" }
  | { name: "circa" }
  | { name: "team"; abbr: string }
  | { name: "notfound" };

// Hash routing keeps the Python server simple (it only needs to serve index.html at `/`).
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query);
  const lg = params.get("league");
  const league = isLeague(lg) ? lg : null;
  if (parts.length === 0) {
    const date = params.get("date");
    return { name: "today", date: date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null, league };
  }
  // Game links carry the league so calendar/deep links open the right scoreboard; default nba.
  if (parts[0] === "game" && parts[1]) return { name: "game", id: parts[1], league: league ?? "nba" };
  if (parts[0] === "bets") return { name: "bets" };
  if (parts[0] === "standings") return { name: "standings" };
  if (parts[0] === "model") return { name: "model" };
  if (parts[0] === "circa") return { name: "circa" };
  if (parts[0] === "team" && parts[1]) return { name: "team", abbr: parts[1].toUpperCase() };
  return { name: "notfound" };
}

export const href = {
  today: (date?: string | null) => (date ? `#/?date=${date}` : "#/"),
  game: (id: string, league: League = "nba") =>
    `#/game/${encodeURIComponent(id)}?league=${league}`,
  bets: () => "#/bets",
  standings: () => "#/standings",
  model: () => "#/model",
  circa: () => "#/circa",
  team: (abbr: string) => `#/team/${encodeURIComponent(abbr)}`,
};

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

// A best-effort stack of in-app hashes so "Back" never leaves the app on a deep link.
const stack: string[] = [window.location.hash || "#/"];
window.addEventListener("hashchange", () => {
  const h = window.location.hash || "#/";
  if (stack.length > 1 && stack[stack.length - 2] === h) stack.pop();
  else stack.push(h);
});

/** Go back within the app if we navigated here, else fall back to a sensible parent. */
export function goBack(fallback: string) {
  if (stack.length > 1) window.history.back();
  else window.location.hash = fallback;
}
