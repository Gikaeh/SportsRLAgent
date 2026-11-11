import type { StandingRow, TeamRef } from "../api/types";

// [espn id, abbr, full name, short name, conference, wins, losses, streak]
type Row = [string, string, string, string, "East" | "West", number, number, string];

const ROWS: Row[] = [
  ["1", "ATL", "Atlanta Hawks", "Hawks", "East", 4, 3, "W1"],
  ["2", "BOS", "Boston Celtics", "Celtics", "East", 4, 3, "W2"],
  ["17", "BKN", "Brooklyn Nets", "Nets", "East", 2, 5, "L3"],
  ["30", "CHA", "Charlotte Hornets", "Hornets", "East", 3, 4, "L1"],
  ["4", "CHI", "Chicago Bulls", "Bulls", "East", 3, 3, "W1"],
  ["5", "CLE", "Cleveland Cavaliers", "Cavaliers", "East", 6, 1, "W4"],
  ["8", "DET", "Detroit Pistons", "Pistons", "East", 5, 2, "L1"],
  ["11", "IND", "Indiana Pacers", "Pacers", "East", 2, 5, "L2"],
  ["14", "MIA", "Miami Heat", "Heat", "East", 4, 4, "L1"],
  ["15", "MIL", "Milwaukee Bucks", "Bucks", "East", 4, 3, "L1"],
  ["18", "NY", "New York Knicks", "Knicks", "East", 5, 3, "L1"],
  ["19", "ORL", "Orlando Magic", "Magic", "East", 5, 2, "W3"],
  ["20", "PHI", "Philadelphia 76ers", "76ers", "East", 3, 4, "W1"],
  ["28", "TOR", "Toronto Raptors", "Raptors", "East", 3, 4, "W2"],
  ["27", "WSH", "Washington Wizards", "Wizards", "East", 1, 6, "L5"],
  ["6", "DAL", "Dallas Mavericks", "Mavericks", "West", 4, 3, "W1"],
  ["7", "DEN", "Denver Nuggets", "Nuggets", "West", 5, 2, "W2"],
  ["9", "GS", "Golden State Warriors", "Warriors", "West", 5, 3, "W1"],
  ["10", "HOU", "Houston Rockets", "Rockets", "West", 5, 2, "L1"],
  ["12", "LAC", "LA Clippers", "Clippers", "West", 4, 3, "W1"],
  ["13", "LAL", "Los Angeles Lakers", "Lakers", "West", 5, 2, "W3"],
  ["29", "MEM", "Memphis Grizzlies", "Grizzlies", "West", 3, 4, "L2"],
  ["16", "MIN", "Minnesota Timberwolves", "Timberwolves", "West", 4, 3, "L1"],
  ["3", "NO", "New Orleans Pelicans", "Pelicans", "West", 1, 6, "L4"],
  ["25", "OKC", "Oklahoma City Thunder", "Thunder", "West", 7, 0, "W7"],
  ["21", "PHX", "Phoenix Suns", "Suns", "West", 3, 4, "W1"],
  ["22", "POR", "Portland Trail Blazers", "Trail Blazers", "West", 2, 5, "L1"],
  ["23", "SAC", "Sacramento Kings", "Kings", "West", 3, 5, "L2"],
  ["24", "SA", "San Antonio Spurs", "Spurs", "West", 4, 3, "W2"],
  ["26", "UTAH", "Utah Jazz", "Jazz", "West", 2, 5, "W1"],
];

export const FOLLOWED = ["LAL", "LAC", "GS", "BOS"];

export const logoUrl = (abbr: string) =>
  `https://a.espncdn.com/i/teamlogos/nba/500/${abbr.toLowerCase()}.png`;

export const TEAMS = ROWS.map(([id, abbr, name, short_name, conference, wins, losses, streak]) => ({
  id, abbr, name, short_name, conference, wins, losses, streak,
}));

export function teamByAbbr(abbr: string) {
  return TEAMS.find((t) => t.abbr.toLowerCase() === abbr.toLowerCase()) ?? null;
}

export function teamRef(abbr: string): TeamRef {
  const t = teamByAbbr(abbr);
  if (!t) throw new Error(`unknown team ${abbr}`);
  return {
    id: t.id,
    abbr: t.abbr,
    name: t.name,
    short_name: t.short_name,
    logo: logoUrl(t.abbr),
    record: `${t.wins}-${t.losses}`,
    followed: FOLLOWED.includes(t.abbr),
  };
}

function split(w: number, l: number, first: boolean) {
  const hw = first ? Math.ceil(w / 2) : Math.floor(w / 2);
  const hl = first ? Math.floor(l / 2) : Math.ceil(l / 2);
  return `${hw}-${hl}`;
}

export function standingRows(conference: "East" | "West"): StandingRow[] {
  const teams = TEAMS.filter((t) => t.conference === conference)
    .map((t) => ({ ...t, pct: t.wins / (t.wins + t.losses) }))
    .sort((a, b) => b.pct - a.pct || b.wins - a.wins);
  const lead = teams[0];
  return teams.map((t) => ({
    abbr: t.abbr,
    name: t.name,
    logo: logoUrl(t.abbr),
    conference,
    wins: t.wins,
    losses: t.losses,
    pct: Math.round(t.pct * 1000) / 1000,
    games_back: (lead.wins - t.wins + (t.losses - lead.losses)) / 2,
    home: split(t.wins, t.losses, true),
    away: split(t.wins, t.losses, false),
    last10: `${t.wins}-${t.losses}`,
    streak: t.streak,
    followed: FOLLOWED.includes(t.abbr),
  }));
}

// ---------- College (league=ncaab) ----------
// [espn id, abbr, full name, short name, wins, losses]
const NCAAB_ROWS: [string, string, string, string, number, number][] = [
  ["2440", "NEV", "Nevada Wolf Pack", "Wolf Pack", 2, 0],
  ["2608", "SMC", "Saint Mary's Gaels", "Gaels", 2, 0],
  ["150", "DUKE", "Duke Blue Devils", "Blue Devils", 2, 0],
  ["2305", "KU", "Kansas Jayhawks", "Jayhawks", 1, 1],
  ["41", "CONN", "UConn Huskies", "Huskies", 2, 0],
  ["2250", "GONZ", "Gonzaga Bulldogs", "Bulldogs", 2, 0],
  ["96", "UK", "Kentucky Wildcats", "Wildcats", 1, 1],
  ["153", "UNC", "North Carolina Tar Heels", "Tar Heels", 2, 0],
  ["2439", "UNLV", "UNLV Rebels", "Rebels", 1, 1],
  ["21", "SDSU", "San Diego State Aztecs", "Aztecs", 1, 0],
  ["248", "HOU", "Houston Cougars", "Cougars", 2, 0],
  ["2509", "PUR", "Purdue Boilermakers", "Boilermakers", 1, 1],
  ["12", "ARIZ", "Arizona Wildcats", "Wildcats", 1, 0],
  ["26", "UCLA", "UCLA Bruins", "Bruins", 2, 0],
];

export const FOLLOWED_NCAAB = ["NEV"];

export function collegeRef(abbr: string): TeamRef {
  const t = NCAAB_ROWS.find((r) => r[1] === abbr);
  if (!t) throw new Error(`unknown college team ${abbr}`);
  const [id, a, name, short_name, w, l] = t;
  return {
    id,
    abbr: a,
    name,
    short_name,
    logo: `https://a.espncdn.com/i/teamlogos/ncaa/500/${id}.png`,
    record: `${w}-${l}`,
    followed: FOLLOWED_NCAAB.includes(a),
  };
}
