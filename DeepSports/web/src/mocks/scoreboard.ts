import type { GameCard, GameState, League, Prediction } from "../api/types";
import { FOLLOWED, FOLLOWED_NCAAB, collegeRef, teamRef } from "./teams";

const TZ_OFFSET = "-08:00"; // server-local time (Pacific, standard time in November)

type Spec = {
  id: string;
  away: string;
  home: string;
  time: string; // "HH:MM" server-local
  state: GameState;
  status: string;
  status_text?: string;
  period?: number | null;
  clock?: string | null;
  awayLines?: number[];
  homeLines?: number[];
  broadcasts?: string[];
  odds?: string | null;
  venue?: string | null;
  /** false = no pre-tip prediction exists for this game (common in college: both teams need >= 5 games). */
  predicted?: boolean;
  /** the owner's open bets on this game */
  bets?: string[];
  /** college: an early-season prediction (`ncaab-v1-early`), hidden unless the toggle is on */
  early?: boolean;
};

const VENUES: Record<string, string> = {
  LAL: "Crypto.com Arena", LAC: "Intuit Dome", BOS: "TD Garden", MIA: "Kaseya Center",
  MIL: "Fiserv Forum", ORL: "Kia Center", PHX: "PHX Arena", NY: "Madison Square Garden",
  GS: "Chase Center", DEN: "Ball Arena",
};

export function etToday(): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function dayDiff(a: string, b: string): number {
  return Math.round((Date.parse(`${a}T12:00:00Z`) - Date.parse(`${b}T12:00:00Z`)) / 86400000);
}

export function timeLabel(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

function hash(s: string) {
  let h = 7;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0;
  return Math.abs(h);
}

/** Deterministic fake prediction (NBA: "v1.1", college: "ncaab-v1"), graded once the card is final. */
export function predictionFor(card: GameCard): Prediction | null {
  if (/POSTPONED|CANCEL/.test(card.status)) return null;
  const college = card.league === "ncaab";
  const h = hash(card.id);
  const p = 0.22 + (h % 64) / 100; // 0.22 .. 0.85
  const margin = Math.round((p - 0.5) * 28 * 2) / 2;
  const total = (college ? 134 : 216) + (h % 24) + 0.5;
  const fav = p >= 0.5 ? card.home.abbr : card.away.abbr;
  const pred: Prediction = {
    model: college ? "ncaab_ridge" : "elo_box_v1",
    model_version: college ? "ncaab-v1" : "v1.1",
    created_at: new Date(Date.parse(card.start_time) - 3 * 3600_000).toISOString(),
    p_home_win: Math.round(p * 1000) / 1000,
    pred_home_margin: margin,
    pred_total: total,
    favorite_abbr: fav,
    favorite_prob: Math.round(Math.max(p, 1 - p) * 1000) / 1000,
  };
  const { home, away } = card;
  if (card.state === "post" && card.status.startsWith("STATUS_FINAL") && home.score != null && away.score != null) {
    const actual = home.score - away.score;
    pred.result = {
      winner_correct: (actual > 0) === (margin > 0),
      margin_error: Math.round(Math.abs(actual - margin) * 10) / 10,
      total_error: Math.round(Math.abs(home.score + away.score - total) * 10) / 10,
    };
  }
  return pred;
}

export function makeCard(date: string, s: Spec, league: League = "nba"): GameCard {
  const awayLines = s.awayLines ?? [];
  const homeLines = s.homeLines ?? [];
  const hasScore = s.state !== "pre" && awayLines.length > 0;
  const ref = league === "ncaab" ? collegeRef : teamRef;
  const followed = league === "ncaab" ? FOLLOWED_NCAAB : FOLLOWED;
  const away = ref(s.away);
  const home = ref(s.home);
  const card: GameCard = {
    id: s.id,
    state: s.state,
    status: s.status,
    status_text: s.status_text ?? timeLabel(s.time),
    period: s.period ?? null,
    clock: s.clock ?? null,
    start_time: `${date}T${s.time}:00${TZ_OFFSET}`,
    away: { ...away, score: hasScore ? sum(awayLines) : null, linescores: awayLines },
    home: { ...home, score: hasScore ? sum(homeLines) : null, linescores: homeLines },
    broadcasts: s.broadcasts ?? [],
    odds: s.state === "pre" ? (s.odds ?? null) : null,
    venue: s.venue === undefined ? (VENUES[s.home] ?? null) : s.venue,
    followed: followed.includes(s.away) || followed.includes(s.home),
    league,
    prediction: null,
    ...(s.bets ? { bets: s.bets } : {}),
  };
  if (s.predicted !== false) card.prediction = predictionFor(card);
  if (s.early && card.prediction) card.prediction = { ...card.prediction, model_version: "ncaab-v1-early", early: true };
  return card;
}

const T0 = Date.now();

/** The in-progress game advances every 30s so auto-refresh is visible in mock mode. */
function liveSpec(): Spec {
  const ticks = Math.floor((Date.now() - T0) / 30000);
  const clockSecs = Math.max(0, 252 - ticks * 22);
  const ended = clockSecs === 0;
  const clock = `${Math.floor(clockSecs / 60)}:${String(clockSecs % 60).padStart(2, "0")}`;
  return {
    id: "401810101",
    away: "SAC",
    home: "LAL",
    time: "17:30",
    state: "in",
    status: ended ? "STATUS_END_PERIOD" : "STATUS_IN_PROGRESS",
    status_text: ended ? "End of 3rd" : `Q3 ${clock}`,
    period: 3,
    clock,
    awayLines: [28, 25, 19 + Math.floor((Math.min(ticks, 12) * 3) / 2)],
    homeLines: [31, 27, 22 + Math.min(ticks, 12) * 2],
    broadcasts: ["Spectrum SN", "NBCS-CA"],
  };
}

function todaySpecs(): Spec[] {
  return [
    {
      id: "401810103", away: "NY", home: "BOS", time: "16:00", state: "post",
      status: "STATUS_FINAL", status_text: "Final/OT", period: 5, clock: "0.0",
      awayLines: [29, 24, 28, 27, 10], homeLines: [27, 30, 26, 25, 13], broadcasts: ["ESPN"],
    },
    {
      id: "401810102", away: "GS", home: "MIA", time: "16:30", state: "post",
      status: "STATUS_FINAL", status_text: "Final", period: 4, clock: "0.0",
      awayLines: [30, 26, 28, 28], homeLines: [24, 29, 27, 24], broadcasts: ["NBCS-BA", "FDSSUN"],
    },
    liveSpec(),
    {
      id: "401810104", away: "DEN", home: "LAC", time: "19:30", state: "pre",
      status: "STATUS_SCHEDULED", broadcasts: ["FDSN SoCal", "Altitude"], odds: "LAC -1.5, O/U 229.5", bets: ["LAC -1.5"],
    },
    {
      id: "401810105", away: "CHI", home: "ORL", time: "16:00", state: "post",
      status: "STATUS_POSTPONED", status_text: "Postponed", broadcasts: ["FDSFL", "CHSN"],
    },
    {
      id: "401810106", away: "CLE", home: "MIL", time: "17:00", state: "post",
      status: "STATUS_FINAL", status_text: "Final", period: 4, clock: "0.0",
      awayLines: [31, 28, 30, 25], homeLines: [26, 27, 24, 30], broadcasts: ["FDSOH", "FDSWI"],
    },
    {
      id: "401810107", away: "DAL", home: "PHX", time: "19:00", state: "pre",
      status: "STATUS_SCHEDULED", broadcasts: ["NBA TV"], odds: "DAL -3.5, O/U 226.5", predicted: false,
    },
  ];
}

function yesterdaySpecs(): Spec[] {
  return [
    {
      id: "401810091", away: "DEN", home: "GS", time: "19:00", state: "post",
      status: "STATUS_FINAL", status_text: "Final", period: 4, clock: "0.0",
      awayLines: [27, 31, 29, 31], homeLines: [33, 25, 30, 32], broadcasts: ["TNT"],
    },
    {
      id: "401810092", away: "DAL", home: "LAC", time: "19:30", state: "post",
      status: "STATUS_FINAL", status_text: "Final", period: 4, clock: "0.0",
      awayLines: [25, 26, 24, 27], homeLines: [28, 22, 30, 29], broadcasts: ["FDSN SoCal"],
    },
    {
      id: "401810093", away: "MIL", home: "NY", time: "16:30", state: "post",
      status: "STATUS_FINAL", status_text: "Final", period: 4, clock: "0.0",
      awayLines: [22, 30, 25, 28], homeLines: [29, 27, 24, 31], broadcasts: ["MSG"],
    },
  ];
}

function tomorrowSpecs(): Spec[] {
  return [
    { id: "401810111", away: "BOS", home: "MIL", time: "17:00", state: "pre", status: "STATUS_SCHEDULED", broadcasts: ["NBC", "Peacock"], odds: "MIL -2.5, O/U 224.5" },
    { id: "401810112", away: "LAL", home: "PHX", time: "19:00", state: "pre", status: "STATUS_SCHEDULED", broadcasts: ["Spectrum SN"], odds: "LAL -4, O/U 231" },
    { id: "401810113", away: "MIA", home: "CLE", time: "16:00", state: "pre", status: "STATUS_SCHEDULED", broadcasts: ["FDSOH"], odds: "CLE -8.5, O/U 223.5" },
  ];
}

function sortCards(cards: GameCard[]): GameCard[] {
  return [...cards].sort(
    (a, b) => Number(b.followed) - Number(a.followed) || a.start_time.localeCompare(b.start_time),
  );
}

// ---------- College ----------
// College games are two 20-minute halves, so linescores have 2 entries (3+ = overtime).
const COLLEGE_VENUES: Record<string, string> = {
  KU: "Allen Fieldhouse", GONZ: "McCarthey Athletic Center", UNC: "Dean E. Smith Center",
  NEV: "Lawlor Events Center", UCLA: "Pauley Pavilion", HOU: "Fertitta Center",
};

const T1 = Date.now();

function collegeLive(): Spec {
  const ticks = Math.floor((Date.now() - T1) / 30000);
  const secs = Math.max(0, 492 - ticks * 25);
  const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  return {
    id: "401830201", away: "DUKE", home: "KU", time: "16:30", state: "in",
    status: "STATUS_IN_PROGRESS", status_text: `2nd ${clock}`, period: 2, clock,
    awayLines: [36, 24 + Math.min(ticks, 10) * 2], homeLines: [33, 27 + Math.floor(Math.min(ticks, 10) * 1.5)],
    broadcasts: ["ESPN"], venue: COLLEGE_VENUES.KU,
  };
}

function collegeTodaySpecs(): Spec[] {
  return [
    // Nevada's followed game. Neutral site: the API has no neutral flag, ESPN still lists a "home" team.
    {
      id: "401830200", away: "SMC", home: "NEV", time: "13:30", state: "pre", status: "STATUS_SCHEDULED",
      broadcasts: ["CBSSN"], odds: "SMC -4.5, O/U 141.5", venue: "T-Mobile Arena (neutral site)",
    },
    collegeLive(),
    {
      id: "401830202", away: "UNLV", home: "SDSU", time: "16:00", state: "post", status: "STATUS_FINAL",
      status_text: "Final/OT", period: 3, clock: "0.0", awayLines: [30, 34, 6], homeLines: [33, 31, 9],
      broadcasts: ["FS1"], venue: "Viejas Arena",
    },
    {
      id: "401830203", away: "UK", home: "UNC", time: "17:00", state: "pre", status: "STATUS_SCHEDULED",
      broadcasts: ["ESPN2"], odds: "UNC -2.5, O/U 151.5", venue: COLLEGE_VENUES.UNC,
      predicted: false, // too early in the season for one team: no college prediction
    },
    {
      id: "401830205", away: "DUKE", home: "KU", time: "17:30", state: "pre", status: "STATUS_SCHEDULED",
      broadcasts: ["ESPN"], odds: "KU -1.5, O/U 148.5", venue: null,
      early: true, // early-season prediction: shows only with the toggle on
    },
    {
      id: "401830204", away: "CONN", home: "GONZ", time: "18:00", state: "pre", status: "STATUS_SCHEDULED",
      broadcasts: ["ESPN"], odds: "GONZ -1, O/U 147.5", venue: COLLEGE_VENUES.GONZ,
    },
    {
      id: "401830205", away: "PUR", home: "HOU", time: "15:00", state: "post", status: "STATUS_FINAL",
      status_text: "Final", period: 2, clock: "0.0", awayLines: [29, 33], homeLines: [35, 36],
      broadcasts: ["ESPN+"], venue: COLLEGE_VENUES.HOU,
    },
  ];
}

function collegeYesterdaySpecs(): Spec[] {
  return [
    {
      id: "401830190", away: "ARIZ", home: "NEV", time: "19:00", state: "post", status: "STATUS_FINAL",
      status_text: "Final", period: 2, clock: "0.0", awayLines: [31, 35], homeLines: [38, 34],
      broadcasts: ["MWN"], venue: COLLEGE_VENUES.NEV,
    },
    {
      id: "401830191", away: "UCLA", home: "SMC", time: "18:00", state: "post", status: "STATUS_FINAL",
      status_text: "Final", period: 2, clock: "0.0", awayLines: [34, 37], homeLines: [30, 35],
      broadcasts: ["ESPNU"], venue: "University Credit Union Pavilion", predicted: false,
    },
  ];
}

function collegeTomorrowSpecs(): Spec[] {
  return [
    { id: "401830211", away: "ARIZ", home: "UCLA", time: "19:30", state: "pre", status: "STATUS_SCHEDULED", broadcasts: ["FS1"], odds: "UCLA -3, O/U 152.5", venue: COLLEGE_VENUES.UCLA },
  ];
}

/** Nevada's next game, 3 days out: shown as "next game" on days without a followed game. */
function collegeLaterSpecs(): Spec[] {
  return [
    { id: "401830230", away: "NEV", home: "UNLV", time: "19:00", state: "pre", status: "STATUS_SCHEDULED", broadcasts: ["CBSSN"], odds: "NEV -2.5, O/U 139.5", venue: "Thomas & Mack Center" },
  ];
}

export function slateFor(date: string, league: League = "nba"): GameCard[] {
  const diff = dayDiff(date, etToday());
  if (league === "ncaab") {
    const specs =
      diff === 0 ? collegeTodaySpecs() : diff === -1 ? collegeYesterdaySpecs() : diff === 1 ? collegeTomorrowSpecs() : diff === 3 ? collegeLaterSpecs() : [];
    return sortCards(specs.map((s) => makeCard(date, s, "ncaab")));
  }
  const specs = diff === 0 ? todaySpecs() : diff === -1 ? yesterdaySpecs() : diff === 1 ? tomorrowSpecs() : [];
  return sortCards(specs.map((s) => makeCard(date, s)));
}

/** next_followed_game: first followed game not yet started, up to 7 days ahead (today only). */
export function nextFollowedGame(league: League): GameCard | null {
  const today = etToday();
  const now = Date.now();
  for (let d = 0; d <= 7; d++) {
    const g = slateFor(addDays(today, d), league).find(
      (c) => c.followed && c.state === "pre" && c.status === "STATUS_SCHEDULED" && Date.parse(c.start_time) > now,
    );
    if (g) return g;
  }
  return null;
}

export function allKnownCards(): GameCard[] {
  const today = etToday();
  return (["nba", "ncaab"] as const).flatMap((lg) => [-1, 0, 1, 3].flatMap((d) => slateFor(addDays(today, d), lg)));
}
