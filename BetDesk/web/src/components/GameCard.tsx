import type { GameCard as Game, GameTeam } from "../api/types";
import { isDisrupted, isFinal, isLive } from "../format";
import { gameLeague } from "../league";
import { href } from "../router";
import { CardPrediction } from "./Prediction";
import { TeamLogo } from "./TeamLogo";

/** Small "College" tag so a college game is never mistaken for an NBA one. */
export function LeagueBadge({ game }: { game: Game }) {
  if (gameLeague(game) !== "ncaab") return null;
  return (
    <span className="league-badge" title="College basketball (NCAA)">
      <span aria-hidden="true">🎓</span> College
    </span>
  );
}

/** "Bet: TOR -2.5" chip for a game with an open bet (not shown once final). */
export function BetBadge({ game, always = false }: { game: Game; always?: boolean }) {
  if (!game.bets?.length || (isFinal(game) && !always)) return null;
  return (
    <span className="bet-badge" title="You have an open bet on this game">
      <span aria-hidden="true">💵</span> {game.bets.join(" · ")}
    </span>
  );
}

export function StatusPill({ game }: { game: Game }) {
  if (isLive(game)) {
    return (
      <span className="status status-live">
        <span className="live-dot" aria-hidden="true" />
        <span className="live-word">LIVE</span>
        <span>{game.status_text}</span>
      </span>
    );
  }
  if (isDisrupted(game)) return <span className="status status-warn">{game.status_text}</span>;
  if (isFinal(game)) return <span className="status status-final">{game.status_text}</span>;
  return <span className="status">{game.status_text}</span>;
}

function TeamRow({ team, game, won }: { team: GameTeam; game: Game; won: boolean | null }) {
  const showScore = game.state !== "pre" && team.score != null;
  return (
    <div className={`team-row${won === false ? " lost" : ""}`}>
      <TeamLogo logo={team.logo} abbr={team.abbr} size={32} />
      <span className="team-id">
        <span className="team-abbr">
          {team.abbr}
          {team.followed && (
            <span className="star" aria-label="followed team" title="You follow this team">
              ★
            </span>
          )}
        </span>
        <span className="team-sub">
          {team.short_name}
          {team.record && <span className="record"> · {team.record}</span>}
        </span>
      </span>
      {showScore && (
        <span className={`score${won ? " won" : ""}`}>
          {team.score}
        </span>
      )}
    </div>
  );
}

/** "BOS -11.5, O/U 225.5" -> "BOS -11.5 · O/U 225.5" */
export function formatOdds(odds: string): string {
  return odds.replace(", O/U", " · O/U");
}

export function describeGame(g: Game): string {
  const a = `${g.away.name}${g.away.score != null && g.state !== "pre" ? ` ${g.away.score}` : ""}`;
  const h = `${g.home.name}${g.home.score != null && g.state !== "pre" ? ` ${g.home.score}` : ""}`;
  const lg = gameLeague(g) === "ncaab" ? "College game: " : "";
  const bet = g.bets?.length ? ` Open bet: ${g.bets.join(", ")}.` : "";
  const pred = g.state === "pre" && g.prediction
    ? ` Model favors ${g.prediction.favorite_abbr}, ${Math.round(g.prediction.favorite_prob * 100)}%.`
    : "";
  return `${lg}${a} at ${h}. ${isLive(g) ? "Live, " : ""}${g.status_text}.${bet}${pred}`;
}

export function GameCardView({ game, showBets = false }: { game: Game; showBets?: boolean }) {
  const final = isFinal(game);
  const a = game.away.score;
  const h = game.home.score;
  const awayWon = final && a != null && h != null ? a > h : null;
  const homeWon = final && a != null && h != null ? h > a : null;
  const cls = ["card", "game-card", game.followed && "is-followed", isLive(game) && "is-live"]
    .filter(Boolean)
    .join(" ");
  return (
    <a className={cls} href={href.game(game.id, gameLeague(game))} aria-label={describeGame(game)}>
      <div className="card-top">
        <span className="card-top-left">
          <StatusPill game={game} />
          <LeagueBadge game={game} />
          <BetBadge game={game} always={showBets} />
        </span>
        {game.broadcasts.length > 0 && <span className="tv">{game.broadcasts.join(" · ")}</span>}
      </div>
      <TeamRow team={game.away} game={game} won={awayWon} />
      <TeamRow team={game.home} game={game} won={homeWon} />
      {game.state === "pre" && game.odds && <div className="odds">Odds: {formatOdds(game.odds)}</div>}
      <CardPrediction game={game} />
    </a>
  );
}
