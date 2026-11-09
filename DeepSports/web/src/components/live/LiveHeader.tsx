import type { GameCard, Possession } from "../../api/types";
import { Help } from "../Help";
import { LiveAge } from "./LiveAge";
import type { LiveFx } from "./useLiveFx";

const INFERRED_NOTE = "Worked out from the last play, so it can lag.";

function ballSide(game: GameCard, possession: Possession | null): "away" | "home" | null {
  if (game.state !== "in" || !possession) return null;
  return possession.team_id === game.away.id ? "away" : possession.team_id === game.home.id ? "home" : null;
}

/** Rising "+N" by the team that scored. Absolutely positioned, so it never moves the layout. */
export function ScoreFloats({ floats }: { floats: LiveFx["floats"] }) {
  return (
    <>
      {floats.away && <span key={floats.away.n} className="score-float away" aria-hidden="true">+{floats.away.points}</span>}
      {floats.home && <span key={floats.home.n} className="score-float home" aria-hidden="true">+{floats.home.points}</span>}
    </>
  );
}

/**
 * A bouncing ball by the team with possession; it slides across when possession changes.
 * Decorative and click-through: PossessionLine carries the words, and the team links stay tappable.
 */
export function PossessionMarker({ game, possession }: { game: GameCard; possession: Possession | null }) {
  const side = ballSide(game, possession);
  if (!side) return null;
  return (
    <span className={`poss-track ${side}`} aria-hidden="true">
      <span className="poss-ball">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <circle cx="12" cy="12" r="10.5" fill="var(--ball)" stroke="var(--ball-line)" strokeWidth="1.5" />
          <path d="M1.5 12h21M12 1.5v21M4.6 4.6c3.2 3 3.2 11.8 0 14.8M19.4 4.6c-3.2 3-3.2 11.8 0 14.8" fill="none" stroke="var(--ball-line)" strokeWidth="1.4" />
        </svg>
      </span>
    </span>
  );
}

/** The live line in the header. Always rendered while live, so the card's height doesn't jump. */
export function PossessionLine({ game, possession, updatedAt }: { game: GameCard; possession: Possession | null; updatedAt: number | null }) {
  const side = ballSide(game, possession);
  const team = side === "away" ? game.away : side === "home" ? game.home : null;
  return (
    <p className="hdr-live">
      {team && (
        <>
          <span>
            {team.short_name} have the ball
            {possession?.source === "inferred" && (
              <>
                <span className="sr-only"> ({INFERRED_NOTE})</span>{" "}
                <Help label="the ball marker">{INFERRED_NOTE} ESPN doesn't always say who has the ball, so we work it out.</Help>
              </>
            )}
          </span>
          <span aria-hidden="true"> · </span>
        </>
      )}
      <span>Updated <LiveAge at={updatedAt} /></span>
    </p>
  );
}
