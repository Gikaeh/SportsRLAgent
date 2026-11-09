import { useEffect, useMemo, useRef, useState } from "react";
import type { GameCard, Play } from "../../api/types";
import { gameLeague, periodName, periodShort } from "../../league";
import { TeamLogo } from "../TeamLogo";
import { LiveAge } from "./LiveAge";
import { ScrollKeeper } from "./ScrollKeeper";
import { playText } from "./useLiveFx";

const PAGE = 30; // rows shown at first, and added by each "Show more"
const TRIM_AT = 60; // a long-open live page drops back to PAGE rows when the reader is at the top

type Filter = "all" | "scoring";

const matches = (p: Play, f: Filter) => (f === "scoring" ? p.scoring : p.kind !== "substitution");

function PlayRow({ play, game, fresh }: { play: Play; game: GameCard; fresh: boolean }) {
  const league = gameLeague(game);
  const team = play.team_id === game.away.id ? game.away : play.team_id === game.home.id ? game.home : null;
  const cls = ["play", play.scoring && "play-scoring", play.kind === "period_end" && "play-end", fresh && "play-new"].filter(Boolean).join(" ");
  return (
    <li className={cls} data-play-id={play.id}>
      <span className="play-when">
        <span>{periodShort(play.period, league)}</span>
        <span>{play.clock ?? ""}</span>
      </span>
      <span className="play-team">
        {team && (
          <>
            <TeamLogo logo={team.logo} abbr={team.abbr} size={24} />
            <span className="play-abbr">{team.abbr}</span>
          </>
        )}
      </span>
      <span className="play-body">
        <span className="play-text">{playText(play)}</span>
        {play.scoring && (
          <span className="play-score">
            <span className="play-points">+{play.points}</span>
            {game.away.abbr} {play.away_score}, {game.home.abbr} {play.home_score}
          </span>
        )}
      </span>
    </li>
  );
}

/** Play-by-play, newest first. Stays mounted across polls so the filter and "Show more" survive. */
export function PlayFeed(props: { game: GameCard; plays: Play[]; freshIds: ReadonlySet<string>; updatedAt: number | null; stale: boolean }) {
  if (props.game.state === "pre" || props.plays.length === 0) return null;
  return <Feed {...props} />;
}

function Feed({ game, plays, freshIds, updatedAt, stale }: { game: GameCard; plays: Play[]; freshIds: ReadonlySet<string>; updatedAt: number | null; stale: boolean }) {
  const league = gameLeague(game);
  const live = game.state === "in";
  const [filter, setFilter] = useState<Filter>("all");
  const matching = useMemo(() => plays.filter((p) => matches(p, filter)), [plays, filter]);
  // Index of the oldest row shown. It stays put as plays arrive, so what the reader sees is never pushed out.
  const [floor, setFloor] = useState(() => Math.max(0, matching.length - PAGE));
  const from = Math.min(floor, Math.max(0, matching.length - PAGE));
  const rows = useMemo(() => matching.slice(from).reverse(), [matching, from]);
  const listRef = useRef<HTMLDivElement>(null);
  const expanded = useRef(false);

  useEffect(() => {
    if (!live || expanded.current || matching.length - floor <= TRIM_AT) return;
    const top = listRef.current?.getBoundingClientRect().top ?? -1;
    if (top > 0) setFloor(matching.length - PAGE);
  }, [live, matching.length, floor]);

  const choose = (f: Filter) => {
    setFilter(f);
    expanded.current = false;
    setFloor(Math.max(0, plays.filter((p) => matches(p, f)).length - PAGE));
  };

  return (
    <section className="card play-feed" aria-labelledby="plays-h">
      <div className="feed-head">
        <h2 id="plays-h" className="card-title">Play-by-play</h2>
        {live && (
          <span className="feed-live">
            {!stale && <span className="live-dot" aria-hidden="true" />}
            <span className="live-word">LIVE</span> <span className="live-age">updated <LiveAge at={updatedAt} /></span>
          </span>
        )}
      </div>
      <div className="segmented" role="group" aria-label="Which plays to show">
        <button type="button" aria-pressed={filter === "all"} onClick={() => choose("all")}>All</button>
        <button type="button" aria-pressed={filter === "scoring"} onClick={() => choose("scoring")}>Scoring</button>
      </div>
      <div ref={listRef}>
        <ScrollKeeper watch={rows[0]?.id ?? null}>
          {rows.length === 0 ? (
            <p className="fine">No points scored yet.</p>
          ) : (
            <ul className="play-list">
              {rows.map((p, i) => (
                <PeriodRow key={p.id} play={p} first={i === 0 || rows[i - 1].period !== p.period} game={game} league={league} fresh={freshIds.has(p.id)} />
              ))}
            </ul>
          )}
        </ScrollKeeper>
      </div>
      {from > 0 && (
        <button
          type="button"
          className="show-more"
          onClick={() => {
            expanded.current = true;
            setFloor(Math.max(0, from - PAGE));
          }}
        >
          Show more ({from} earlier)
        </button>
      )}
      <p className="fine">
        {live && "Plays can run about 20 seconds behind the game. "}
        {filter === "all" && "Player substitutions are left out to keep this readable."}
      </p>
    </section>
  );
}

function PeriodRow({ play, first, game, league, fresh }: { play: Play; first: boolean; game: GameCard; league: ReturnType<typeof gameLeague>; fresh: boolean }) {
  return (
    <>
      {first && <li className="play-period">{periodName(play.period, league)}</li>}
      <PlayRow play={play} game={game} fresh={fresh} />
    </>
  );
}
