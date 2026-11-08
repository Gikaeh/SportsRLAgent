import { useId, useState, type ReactNode } from "react";

/** A small "?" that expands a plain-language explanation inline. */
export function Help({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="help">
      <button
        type="button"
        className="help-btn"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`What is ${label}?`}
        onClick={() => setOpen((o) => !o)}
      >
        ?
      </button>
      {open && (
        <span id={id} className="help-text" role="note">
          {children}
        </span>
      )}
    </span>
  );
}

export const GLOSSARY = {
  fgPct: "Field goal percentage: the share of shots (not free throws) that went in.",
  fg3Pct: "Three-point percentage: the share of shots from behind the three-point line that went in.",
  ftPct: "Free throw percentage: the share of unguarded foul shots that went in. Each is worth 1 point.",
  reb: "Rebounds: grabbing the ball after a missed shot. Offensive rebounds give your team another try.",
  ast: "Assists: passes that lead directly to a teammate's basket.",
  tov: "Turnovers: losing the ball to the other team without shooting. Fewer is better.",
  stl: "Steals: taking the ball away from the other team.",
  blk: "Blocks: deflecting an opponent's shot.",
  paint: "Points in the paint: points scored close to the basket, inside the painted area.",
  fastBreak: "Fast-break points: points scored quickly in transition, before the defense sets up.",
  plusMinus:
    "+/- (plus-minus): how much the team outscored (+) or was outscored (−) by while this player was on the court.",
  gamesBack:
    "Games back (GB): how far a team trails the conference leader. Two games back means it would need to win two more and the leader lose two more to tie.",
  odds:
    "Odds come from sportsbooks. \"LAL -11.5\" means the Lakers are favored and expected to win by about 11.5 points (the spread). \"O/U 238.5\" (over/under) is the expected combined score of both teams.",
  model:
    "\"Prediction: LAL 68% · by ~5\" is the DeepSports prediction made before tip-off: the Lakers have a 68% chance to win, by about 5 points. It's built from past box scores and schedule data, for context only: it doesn't beat the betting market.",
} as const;
