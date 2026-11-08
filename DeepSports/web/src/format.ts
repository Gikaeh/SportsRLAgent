import type { GameCard } from "./api/types";

/** Parse "YYYY-MM-DD" as a local calendar day (not UTC midnight) or a full ISO timestamp. */
export function parseDate(s: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T12:00:00`) : new Date(s);
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The NBA "game day" is US/Eastern, matching the API's default for /api/scoreboard. */
export function easternToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

export function dayLabel(date: string): string {
  const today = easternToday();
  if (date === today) return "Today";
  if (date === addDays(today, -1)) return "Yesterday";
  if (date === addDays(today, 1)) return "Tomorrow";
  return parseDate(date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function longDate(date: string): string {
  return parseDate(date).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

export function shortDate(iso: string): string {
  return parseDate(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function timeOfDay(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export const isLive = (g: GameCard) => g.state === "in";
export const isFinal = (g: GameCard) => g.state === "post" && g.status.startsWith("STATUS_FINAL");
/** Postponed, canceled, suspended, delayed... anything that isn't a normal pre/in/final. */
export const isDisrupted = (g: GameCard) =>
  /POSTPONED|CANCELED|CANCELLED|SUSPENDED|DELAYED|FORFEIT/.test(g.status);

export function pct(made: number | null, att: number | null): number | null {
  if (made == null || att == null) return null;
  return att === 0 ? 0 : (made / att) * 100;
}

export const fmtPct = (v: number | null) => (v == null ? "–" : `${v.toFixed(1)}%`);
export const fmtNum = (v: number | null | undefined) => (v == null ? "–" : String(v));
export const fmtPlusMinus = (v: number | null) => (v == null ? "–" : v > 0 ? `+${v}` : String(v));
export const fmtMadeAtt = (m: number | null, a: number | null) =>
  m == null || a == null ? "–" : `${m}-${a}`;
export const fmtGb = (gb: number) => (gb === 0 ? "–" : Number.isInteger(gb) ? String(gb) : gb.toFixed(1));
export const fmtWinPct = (p: number) => p.toFixed(3).replace(/^0/, "");
