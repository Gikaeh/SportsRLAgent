import { TabBar } from "./components/Layout";
import { MirrorStatus } from "./components/MirrorStatus";
import { Empty } from "./components/States";
import { useEffect } from "react";
import { setLeague, useLeague } from "./league";
import { Bets } from "./screens/Bets";
import { Game } from "./screens/Game";
import { ModelRecord } from "./screens/ModelRecord";
import { Standings } from "./screens/Standings";
import { Team } from "./screens/Team";
import { Today } from "./screens/Today";
import { useRoute } from "./router";

export function App() {
  const route = useRoute();
  const league = useLeague();
  // A deep link like #/?league=ncaab switches (and remembers) the league.
  const linked = route.name === "today" ? route.league : null;
  useEffect(() => {
    if (linked) setLeague(linked);
  }, [linked]);
  const tab =
    route.name === "today" || route.name === "game"
      ? "today"
      : route.name === "bets"
        ? "bets"
        : route.name === "standings" || route.name === "team"
        ? "standings"
        : route.name === "model"
          ? "model"
          : null;
  return (
    <div className="app">
      {import.meta.env.VITE_MOCK === "1" && <div className="mock-flag">Mock data</div>}
      {import.meta.env.VITE_MOCK !== "1" && <MirrorStatus />}
      {route.name === "today" && <Today key={route.date ?? "today"} date={route.date} league={linked ?? league} />}
      {route.name === "game" && <Game key={`${route.league}:${route.id}`} id={route.id} league={route.league} />}
      {route.name === "bets" && <Bets />}
      {route.name === "standings" && <Standings />}
      {route.name === "model" && <ModelRecord />}
      {route.name === "team" && <Team key={route.abbr} abbr={route.abbr} />}
      {route.name === "notfound" && (
        <main className="content">
          <Empty title="Page not found">
            <a className="btn" href="#/">Go to Today</a>
          </Empty>
        </main>
      )}
      <TabBar active={tab} />
    </div>
  );
}
