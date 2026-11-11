import { ApiError, api, type PredictionRecordResponse } from "../api/client";
import type { GradedPrediction, RecordStats } from "../api/types";
import { Help } from "../components/Help";
import { PageHeader, UpdatedAt } from "../components/Layout";
import { MODEL_NOTE, ResultMark, byText, modelLabel, pctText } from "../components/Prediction";
import { Empty, ErrorState, Skeleton, StaleBanner } from "../components/States";
import { shortDate } from "../format";
import { useApi } from "../hooks/useApi";
import { href } from "../router";

const DAYS = 30;

const HELP = {
  winner:
    "How often the team the model gave the better chance actually won. Picking the favorite every time gets roughly 2 of every 3 NBA games right, so that's the bar to beat.",
  market:
    "The betting market's favorite is the team the sportsbooks expected to win (the one giving points in the spread). It's a strong benchmark: markets pool a lot of information.",
  margin:
    "Average margin miss: how far the predicted winning margin was from the real one, on average. A 10-point miss is typical even for good forecasts, since games swing a lot.",
  total:
    "Average total miss: how far the predicted combined score was from the real one, on average.",
};

export function ModelRecord() {
  const q = useApi<PredictionRecordResponse>(api.predictionRecord("nba", DAYS), { refreshSeconds: () => 600 });
  const d = q.data;
  const notLive = q.error instanceof ApiError && q.error.status === 404;
  return (
    <>
      <PageHeader title="Model record" subtitle={`NBA predictions · last ${d?.window_days ?? DAYS} days`} />
      <main className="content">
        {d && q.error != null && <StaleBanner error={q.error} onRetry={q.refresh} />}
        {q.loading && !d ? (
          <Skeleton rows={3} height={120} />
        ) : !d && notLive ? (
          <Empty title="The model record isn't available yet">
            <p>The DeepSports server needs its predictions update. Scores still work.</p>
          </Empty>
        ) : !d ? (
          <ErrorState error={q.error} onRetry={q.refresh} />
        ) : (
          <>
            <section className="card" aria-labelledby="about-h">
              <h2 id="about-h" className="card-title">How good is the model?</h2>
              <p className="body-text">
                Before each NBA game, the model predicts who wins and by how much. After the game, it gets graded
                against the final score. Here's how it has done, next to the betting market's favorite.
              </p>
              <p className="fine">
                {MODEL_NOTE}
                {modelLabel(d.model_version) && <> Model: {modelLabel(d.model_version)}.</>} College games get
                predictions too (see each game), but this record covers NBA games only for now.
              </p>
            </section>
            {d.games === 0 ? (
              <Empty title="Grading starts after tonight's games">
                <p>Each prediction is checked once its game is final. Come back tomorrow to see the first results.</p>
              </Empty>
            ) : (
              <>
                <Comparison model={d} market={d.market} />
                <Recent rows={d.recent} />
              </>
            )}
            <UpdatedAt at={q.updatedAt} refreshing={q.refreshing} />
          </>
        )}
      </main>
    </>
  );
}

const pts = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(1)} pts`);
const acc = (v: number | null | undefined) => (v == null ? "–" : pctText(v));

function Comparison({ model, market }: { model: RecordStats; market: RecordStats | null }) {
  const rows: { key: string; label: string; help: string; m: string; k: string; better: "m" | "k" | null }[] = [
    {
      key: "win",
      label: "Picked winner",
      help: HELP.winner,
      m: acc(model.winner_accuracy),
      k: acc(market?.winner_accuracy),
      better: cmp(model.winner_accuracy, market?.winner_accuracy, true),
    },
    {
      key: "margin",
      label: "Margin miss",
      help: HELP.margin,
      m: pts(model.margin_mae),
      k: pts(market?.margin_mae),
      better: cmp(model.margin_mae, market?.margin_mae, false),
    },
    {
      key: "total",
      label: "Total miss",
      help: HELP.total,
      m: pts(model.total_mae),
      k: pts(market?.total_mae),
      better: cmp(model.total_mae, market?.total_mae, false),
    },
  ];
  return (
    <section className="card" aria-labelledby="cmp-rec-h">
      <h2 id="cmp-rec-h" className="card-title">Model vs. betting market</h2>
      <div className="scroll-x">
        <table className="record-table">
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">Measure</span></th>
              <th scope="col">Model</th>
              <th scope="col">
                Market <Help label="the market favorite">{HELP.market}</Help>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope="row">
                  {r.label} <Help label={r.label.toLowerCase()}>{r.help}</Help>
                </th>
                <td className={r.better === "m" ? "better" : undefined}>{r.m}</td>
                <td className={r.better === "k" ? "better" : undefined}>{r.k}</td>
              </tr>
            ))}
            <tr className="record-n">
              <th scope="row">Games graded</th>
              <td>{model.games}</td>
              <td>{market ? market.games : "–"}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="fine">
        Bold = the better of the two. Higher is better for picking winners. Misses are the average gap, in points, between the prediction and the final score: lower is better.
        {!market && " Market odds weren't available for these games."}
      </p>
    </section>
  );
}

function cmp(a: number | null | undefined, b: number | null | undefined, higherIsBetter: boolean): "m" | "k" | null {
  if (a == null || b == null || a === b) return null;
  return (a > b) === higherIsBetter ? "m" : "k";
}

/** "SAC by 4" from a home-margin number and a "AWAY @ HOME" matchup. */
function marginSide(matchup: string, homeMargin: number): string {
  const [away, home] = matchup.split(" @ ");
  const m = Math.round(homeMargin);
  if (m === 0) return "even";
  return `${m > 0 ? (home ?? "home") : (away ?? "away")} by ${Math.abs(m)}`;
}

function Recent({ rows }: { rows: GradedPrediction[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="card card-flush" aria-labelledby="recent-h">
      <h2 id="recent-h" className="card-title pad">Recent graded games</h2>
      <ul className="graded-list">
        {rows.map((r) => (
          <li key={r.game_id}>
            <a className="graded-row" href={href.game(r.game_id, "nba")}>
              <ResultMark correct={r.winner_correct} />
              <span className="graded-main">
                <span className="graded-matchup">{r.matchup}</span>
                <span className="graded-sub">Prediction: {r.favorite_abbr} {pctText(r.favorite_prob)} · {byText(r.pred_home_margin)}</span>
                <span className="graded-sub">Final: {marginSide(r.matchup, r.actual_home_margin)}</span>
              </span>
              <span className="graded-date">{shortDate(r.date)}</span>
            </a>
          </li>
        ))}
      </ul>
      <p className="fine pad">✓ = the model's favorite won. ✗ = it lost.</p>
    </section>
  );
}
