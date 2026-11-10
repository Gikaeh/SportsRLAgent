// Plausible rosters for teams that appear in the mock box scores. Last two are DNPs.
export const ROSTERS: Record<string, string[]> = {
  LAL: ["Luka Doncic", "Austin Reaves", "LeBron James", "Rui Hachimura", "Deandre Ayton", "Marcus Smart", "Jarred Vanderbilt", "Jaxson Hayes", "Dalton Knecht", "Gabe Vincent", "Maxi Kleber", "Bronny James"],
  SAC: ["De'Aaron Fox", "Zach LaVine", "DeMar DeRozan", "Keegan Murray", "Domantas Sabonis", "Malik Monk", "Keon Ellis", "Trey Lyles", "Devin Carter", "Jake LaRavia", "Isaac Jones", "Doug McDermott"],
  GS: ["Stephen Curry", "Brandin Podziemski", "Jimmy Butler", "Draymond Green", "Quinton Post", "Buddy Hield", "Moses Moody", "Jonathan Kuminga", "Gary Payton II", "Trayce Jackson-Davis", "Gui Santos", "Pat Spencer"],
  MIA: ["Tyler Herro", "Andrew Wiggins", "Norman Powell", "Bam Adebayo", "Kel'el Ware", "Davion Mitchell", "Jaime Jaquez Jr.", "Nikola Jovic", "Duncan Robinson", "Pelle Larsson", "Simone Fontecchio", "Kasparas Jakucionis"],
  BOS: ["Jaylen Brown", "Derrick White", "Payton Pritchard", "Sam Hauser", "Neemias Queta", "Anfernee Simons", "Jordan Walsh", "Baylor Scheierman", "Luka Garza", "Hugo Gonzalez", "Xavier Tillman", "Chris Boucher"],
  NY: ["Jalen Brunson", "Mikal Bridges", "OG Anunoby", "Josh Hart", "Karl-Anthony Towns", "Mitchell Robinson", "Miles McBride", "Jordan Clarkson", "Guerschon Yabusele", "Tyler Kolek", "Landry Shamet", "Pacome Dadiet"],
  MIL: ["Giannis Antetokounmpo", "Kevin Porter Jr.", "Kyle Kuzma", "Bobby Portis", "Myles Turner", "Gary Trent Jr.", "AJ Green", "Ryan Rollins", "Taurean Prince", "Andre Jackson Jr.", "Cole Anthony", "Jericho Sims"],
  CLE: ["Donovan Mitchell", "Darius Garland", "Evan Mobley", "Jarrett Allen", "De'Andre Hunter", "Max Strus", "Sam Merrill", "Lonzo Ball", "Dean Wade", "Jaylon Tyson", "Craig Porter Jr.", "Larry Nance Jr."],
  LAC: ["James Harden", "Kris Dunn", "Kawhi Leonard", "John Collins", "Ivica Zubac", "Bradley Beal", "Derrick Jones Jr.", "Nicolas Batum", "Bogdan Bogdanovic", "Brook Lopez", "Kobe Sanders", "Jordan Miller"],
  DEN: ["Jamal Murray", "Christian Braun", "Cameron Johnson", "Aaron Gordon", "Nikola Jokic", "Bruce Brown", "Peyton Watson", "Jonas Valanciunas", "Tim Hardaway Jr.", "Julian Strawther", "Zeke Nnaji", "DaRon Holmes II"],
  DAL: ["Kyrie Irving", "Klay Thompson", "Cooper Flagg", "Anthony Davis", "Dereck Lively II", "P.J. Washington", "Daniel Gafford", "Naji Marshall", "D'Angelo Russell", "Max Christie", "Caleb Martin", "Dante Exum"],
  PHX: ["Devin Booker", "Jalen Green", "Dillon Brooks", "Ryan Dunn", "Mark Williams", "Grayson Allen", "Royce O'Neale", "Collin Gillespie", "Nick Richards", "Oso Ighodaro", "Khaman Maluach", "Jordan Goodwin"],
};

export function rosterFor(abbr: string): string[] {
  return ROSTERS[abbr] ?? Array.from({ length: 12 }, (_, i) => `${abbr} Player ${i + 1}`);
}
