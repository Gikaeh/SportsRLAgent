import { useMemo } from "react";
import type { GameCard, Play } from "../../api/types";
import { gameLeague, periodShort } from "../../league";
import { playText } from "./useLiveFx";

const HOOP_INSET = 1.6; // drawing room behind the hoop, so a shot at y=0 stays on the floor
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** One team's half, hoop on the left, measured from the hoop as the play coordinates are. */
function Half({ arc, corner, flip }: { arc: number; corner: number; flip?: boolean }) {
  const hx = HOOP_INSET;
  const run = Math.sqrt(arc * arc - corner * corner); // how far the straight corner three runs from the hoop
  return (
    <g transform={flip ? "rotate(180 47 25)" : undefined}>
      <rect x={0} y={17} width={hx + 13.75} height={16} />
      <circle cx={hx + 13.75} cy={25} r={6} />
      <path d={`M0 ${25 - corner}H${hx + run}A${arc} ${arc} 0 0 1 ${hx + run} ${25 + corner}H0`} />
      <circle className="court-hoop" cx={hx} cy={25} r={0.9} />
    </g>
  );
}

/** A schematic court: each team's half shows its own last shot. The teams' real ends swap at half-time. */
export function LiveCourt({ game, plays, freshIds }: { game: GameCard; plays: Play[]; freshIds: ReadonlySet<string> }) {
  const shot = useMemo(() => {
    for (let i = plays.length - 1; i >= 0; i--) {
      const p = plays[i];
      if (p.coord && (p.kind === "shot_made" || p.kind === "shot_missed") && (p.team_id === game.away.id || p.team_id === game.home.id)) return p;
    }
    return null;
  }, [plays, game.away.id, game.home.id]);
  if (!shot || !shot.coord) return null; // no court spot to show yet (or an older server)

  const league = gameLeague(game);
  const college = league === "ncaab";
  const isAway = shot.team_id === game.away.id;
  const team = isAway ? game.away : game.home;
  const made = shot.kind === "shot_made";
  const across = clamp(shot.coord.x, 0, 50);
  const along = clamp(shot.coord.y, 0, 45);
  // The home half is the away half turned 180 degrees.
  const cx = isAway ? HOOP_INSET + along : 94 - HOOP_INSET - along;
  const cy = isAway ? across : 50 - across;
  const when = [periodShort(shot.period, league), shot.clock].filter(Boolean).join(" ");

  return (
    <section className="card live-court" aria-labelledby="court-h">
      <h2 id="court-h" className="card-title">Last shot</h2>
      <svg
        className="court"
        viewBox="-0.5 -0.5 95 51"
        role="img"
        aria-label={`Court diagram: ${team.short_name} ${made ? "made" : "missed"} this shot in their half of the court.`}
      >
        <rect className="court-floor" x={0} y={0} width={94} height={50} rx={1} />
        <rect className="court-side" x={isAway ? 0 : 47} y={0} width={47} height={50} />
        <g className="court-lines">
          <rect x={0} y={0} width={94} height={50} rx={1} />
          <path d="M47 0V50" />
          <circle cx={47} cy={25} r={6} />
          <Half arc={college ? 22.15 : 23.75} corner={college ? 21.65 : 22} />
          <Half arc={college ? 22.15 : 23.75} corner={college ? 21.65 : 22} flip />
        </g>
        <text className={`court-team${isAway ? " active" : ""}`} x={36} y={8}>{game.away.abbr}</text>
        <text className={`court-team${isAway ? "" : " active"}`} x={58} y={8}>{game.home.abbr}</text>
        <g key={shot.id} className={freshIds.has(shot.id) ? "shot shot-new" : "shot"}>
          <circle className="shot-pulse" cx={cx} cy={cy} r={2} />
          <circle className={made ? "shot-dot made" : "shot-dot missed"} cx={cx} cy={cy} r={1.8} />
        </g>
      </svg>
      <p className="court-meta">
        <strong>{team.abbr} {made ? "made it" : "missed"}</strong> · {when}
      </p>
      <p className="court-text">{playText(shot)}</p>
      <p className="fine court-key">Filled dot = made, hollow dot = missed. Teams are drawn on the side they shoot at; free throws aren't shown.</p>
    </section>
  );
}
