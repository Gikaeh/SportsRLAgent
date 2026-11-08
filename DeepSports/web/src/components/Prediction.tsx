import type { GameCard, Prediction } from "../api/types";
import { isFinal } from "../format";
import { gameLeague } from "../league";
import { setShowEarly, useShowEarly, visiblePrediction } from "../settings";
import { Help } from "./Help";

export const MODEL_NOTE =
  "The model is built from past box scores and schedule data. It's for context: it doesn't beat the betting market.";

export const PREDICTION_HELP =
  "Before tip-off, the DeepSports model estimates each team's chance to win, how many points the winner wins by (the margin), and the combined score (the total). A 68% chance means a team like this wins about 2 of every 3 such games, so upsets are normal.";

/** College only gets a prediction once both teams have some games behind them. */
export const COLLEGE_PREDICTION_NOTE =
  "College games get a prediction only once both teams have played at least 5 games, so early-season and some smaller-school games have none.";

/**
 * Readable model label from `model_version`: "ncaab-v1" -> "college v1", "v1.1" -> "NBA v1.1".
 * A suffix after the version ("v1.1-2026-11", "ncaab-v1-fall") is dropped. Anything else is shown as-is.
 */
export function modelLabel(version: string | null | undefined): string | null {
  if (!version) return null;
  const college = /^ncaab[-_ ]?(v\d+(?:\.\d+)*)/i.exec(version);
  if (college) return `college ${college[1].toLowerCase()}`;
  const nba = /^(?:nba[-_ ]?)?(v\d+(?:\.\d+)*)/i.exec(version);
  if (nba) return `NBA ${nba[1].toLowerCase()}`;
  return version;
}

export const EARLY_NOTE =
  "Early-season prediction: at least one team has played fewer than 5 games, so the model knows little about them yet. Expect bigger misses.";

/** Switch for early-season college predictions (shown on the College Today screen). */
export function EarlyToggle() {
  const on = useShowEarly();
  return (
    <label className="setting-toggle">
      <input type="checkbox" role="switch" checked={on} onChange={(e) => setShowEarly(e.target.checked)} />
      <span>Early-season predictions</span>
      <Help label="early-season predictions">{EARLY_NOTE} Off by default; the 5-game predictions always show.</Help>
    </label>
  );
}

export const pctText = (p: number) => `${Math.round(p * 100)}%`;

/** "by ~5", or "toss-up" when the predicted margin rounds to 0. */
export function byText(margin: number): string {
  const m = Math.round(Math.abs(margin));
  return m === 0 ? "toss-up" : `by ~${m}`;
}

/** Compact card line, e.g. "Prediction: LAL 68% · by ~5" ("Early prediction: ..." for early-season). */
export function predictionLine(p: Prediction): string {
  return `${p.early ? "Early prediction" : "Prediction"}: ${p.favorite_abbr} ${pctText(p.favorite_prob)} · ${byText(p.pred_home_margin)}`;
}

export function ResultMark({ correct }: { correct: boolean }) {
  return (
    <span className={`mark ${correct ? "mark-ok" : "mark-miss"}`} aria-label={correct ? "right" : "wrong"}>
      {correct ? "✓" : "✗"}
    </span>
  );
}

/** One small line on a game card: pre-game pick, or the pick graded once final. */
export function CardPrediction({ game }: { game: GameCard }) {
  const p = visiblePrediction(game, useShowEarly());
  if (!p) return null;
  if (game.state === "pre") return <div className="pred-line">{predictionLine(p)}</div>;
  if (isFinal(game) && p.result) {
    return (
      <div className="pred-line">
        {p.early ? "Early pick" : "Model picked"} {p.favorite_abbr} {pctText(p.favorite_prob)} <ResultMark correct={p.result.winner_correct} />
      </div>
    );
  }
  return null;
}

function sideText(home: string, away: string, homeMargin: number): string {
  if (Math.round(homeMargin) === 0) return "a tie";
  return `${homeMargin > 0 ? home : away} by ${Math.abs(Math.round(homeMargin))}`;
}

/** Game page panel: win-probability bar, predicted margin and total, and the grade once final. */
export function PredictionPanel({ game }: { game: GameCard }) {
  const early = useShowEarly();
  const p = visiblePrediction(game, early);
  if (!p) {
    if (!game.prediction?.early) return null;
    return (
      <section className="card prediction" aria-label="Prediction">
        <p className="fine">
          There's an early-season prediction for this game (a team has played fewer than 5 games).{" "}
          <button type="button" className="link-btn" onClick={() => setShowEarly(true)}>
            Show early-season predictions
          </button>
        </p>
      </section>
    );
  }
  const away = game.away.abbr;
  const home = game.home.abbr;
  const pHome = Math.min(1, Math.max(0, p.p_home_win));
  const pAway = 1 - pHome;
  const winner = p.pred_home_margin >= 0 ? home : away;
  const final = isFinal(game) && game.away.score != null && game.home.score != null;
  const actualMargin = final ? (game.home.score as number) - (game.away.score as number) : 0;
  const actualTotal = final ? (game.home.score as number) + (game.away.score as number) : 0;
  const college = gameLeague(game) === "ncaab";
  const label = modelLabel(p.model_version);

  return (
    <section className="card prediction" aria-labelledby="pred-h">
      <h2 id="pred-h" className="card-title">
        {p.early ? "Early prediction" : "Prediction"} <Help label="the prediction">{PREDICTION_HELP}</Help>
      </h2>
      {p.early && <p className="fine early-note">{EARLY_NOTE}</p>}
      <div className="pred-bar-labels" aria-hidden="true">
        <span className={pAway >= pHome ? "fav" : ""}>{away} {pctText(pAway)}</span>
        <span className={pHome > pAway ? "fav" : ""}>{home} {pctText(pHome)}</span>
      </div>
      <div
        className="pred-bar"
        role="img"
        aria-label={`Chance to win: ${game.away.name} ${pctText(pAway)}, ${game.home.name} ${pctText(pHome)}`}
      >
        <span className={`pred-fill away${pAway >= pHome ? " fav" : ""}`} style={{ width: `${pAway * 100}%` }} />
        <span className={`pred-fill home${pHome > pAway ? " fav" : ""}`} style={{ width: `${pHome * 100}%` }} />
      </div>
      <dl className="tiles pred-tiles">
        <div>
          <dt>Predicted winner</dt>
          <dd>
            {Math.round(Math.abs(p.pred_home_margin)) === 0 ? "Toss-up" : `${winner} ${byText(p.pred_home_margin)}`}
          </dd>
        </div>
        <div>
          <dt>Predicted total</dt>
          <dd>~{Math.round(p.pred_total)} pts</dd>
        </div>
      </dl>
      {final && p.result ? (
        <div className={`pred-result ${p.result.winner_correct ? "ok" : "miss"}`}>
          <p className="pred-result-head">
            <ResultMark correct={p.result.winner_correct} />{" "}
            {p.result.winner_correct ? "The model picked the winner." : "The model picked the wrong team."}
          </p>
          <p>
            Final: {sideText(home, away, actualMargin)}, {actualTotal} points in all. The margin was off by{" "}
            {fmtPts(p.result.margin_error)} and the total by {fmtPts(p.result.total_error)}.
          </p>
        </div>
      ) : game.state === "in" ? (
        <p className="fine">Made before tip-off; it doesn't change during the game.</p>
      ) : null}
      <p className="fine">
        {MODEL_NOTE}
        {label && <> Model: {label}.</>}
        {college && <> {COLLEGE_PREDICTION_NOTE}</>}
      </p>
    </section>
  );
}

export function fmtPts(v: number): string {
  const n = Math.abs(v);
  const r = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return `${r} ${r === "1" ? "point" : "points"}`;
}
