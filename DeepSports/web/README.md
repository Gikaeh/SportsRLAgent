# DeepSports web

> **Frozen since 2026-11-10.** This stays the LAN build served on `:8787` (and next to the glasses
> plugin). New UI work happens in `../../BetDesk/web`, a copy of this app hosted on Cloudflare.
> Fixes only here.

Mobile-first scoreboard PWA for the DeepSports read API (`docs/API.md`, including the v2
additions: college basketball and model predictions). Vite + React + TypeScript, no UI framework,
one plain stylesheet, hash routing.

## Commands

```bash
cd web
npm install                # deps were installed with --before=2026-10-20
npm run dev                # dev server; proxies /api -> http://localhost:8787 (deepsports serve)
npm run dev:mock           # same, but serves fixtures from src/mocks/ (no backend needed)
npm run build              # typecheck + production build -> web/dist (served by Python at /)
npm run build:mock         # mock-data build -> web/dist-mock (for demos/screenshots)
npm run preview            # serve web/dist locally
npm run typecheck
```

The dev server listens on all interfaces, so a phone on the same Wi-Fi can open
`http://<mac-lan-ip>:5173`.

### Mock mode switches (`npm run dev:mock`)
Add a query string before the `#`:
- `?mock=busy`: `/api/standings`, `/api/teams/*` and `/api/predictions/record` return
  `503 {"error":"warehouse_busy"}`, and every card's `prediction` is `null` (as the server does)
  (e.g. `http://localhost:5173/?mock=busy#/model`)
- `?mock=record0`: the model record has 0 graded games ("Grading starts after tonight's games")
- `?mock=v1`: a pre-v2 server (ignores `league=`, no `league`/`prediction` fields, no record endpoint)
- `?mock=error`: every endpoint returns a 500
- `?mock=noplays`: a pre-v3 server: game detail has no `plays`/`possession` fields, so no court, feed or ball marker
- `?mock=flaky`: every 4th game-detail poll returns a 404, as the server does when an ESPN fetch fails; the screen keeps its data under the stale banner

Today's NBA mock slate has an in-progress game (a new play about every 2.5 s, refresh every 5 s; it plays out to a final after several minutes, reload to restart), a final, a final in OT,
upcoming games with odds and predictions (one without), and a postponed game; finals carry a graded
prediction. The college slate (`#/?league=ncaab`) has Nevada's neutral-site game vs Saint Mary's, a
live game in the 2nd half, a final in OT, and upcoming games; college cards have `prediction: null`.
Yesterday has finals, tomorrow has upcoming games, Nevada plays again in 3 days, and any other date
is empty ("No games today").

## Screens (hash routes)
| Route | Screen |
|---|---|
| `#/`, `#/?date=YYYY-MM-DD`, `#/?league=ncaab` | Today: "NBA · College" switch (remembered in localStorage; a `league=` link sets it), date switcher, followed teams first, then "Around the league/country"; your teams' next game when they don't play today; model line on pre-game cards; auto-refresh every `refresh_seconds` while visible; pull to refresh |
| `#/game/{id}?league=nba\|ncaab` | Box score: score header and linescore (quarters, or halves for college), Prediction panel (win-probability bar, predicted margin/total, graded ✓/✗ once final; hidden when `prediction` is null), team comparison bars, player tables; auto-refresh while not final. Live games also show a bouncing ball by the team with possession, a "+N" float and score pop on new scoring plays, a court diagram of the last shot, and "Updated Xs ago". Live and final games show a play-by-play feed (All/Scoring, latest 30 with "Show more", substitutions hidden); it's hidden before tip-off. Animations fire only for plays new since the previous poll, never on first load or after a hidden tab or failed poll. College games have no team-page links (team pages are NBA-only). Missing `league` = nba |
| `#/standings` | East/West tables, followed teams highlighted, playoff/play-in cut lines, column legend |
| `#/team/{abbr}` | Record, standing details, last 10 results, next 5 games |
| `#/model` | Model record (`/api/predictions/record?league=nba&days=30`): winner accuracy and average margin/total miss vs the betting market's favorite, recent graded games; friendly 0-games, 503 and not-deployed states |

The tab bar has three tabs: Today, Standings (NBA-only), Model.

## Structure
```
web/
  index.html              PWA meta, manifest link
  public/                 manifest.webmanifest, sw.js (app shell only, never /api), icons
  vite.config.ts          /api proxy, outDir dist
  src/
    main.tsx              mount + service worker registration (production only)
    App.tsx               route switch + bottom tab bar
    router.ts             hash router, in-app back stack
    styles.css            design tokens (light/dark via prefers-color-scheme) and all styles
    format.ts             date/number formatting, game-state helpers
    league.ts             remembered league choice (localStorage, try/catch), period labels (quarters/halves)
    api/types.ts          types mirroring docs/API.md
    api/client.ts         fetch wrapper, ApiError, warehouse_busy detection, mock switch
    hooks/useApi.ts       fetch + polling that pauses when the page is hidden
    components/           GameCard (+ College badge), Prediction (card line + Game panel), TeamLogo, Help, States, Layout, PullToRefresh
    components/live/      Game screen's live parts: useLiveFx (diffs polls into one-shot effects), LiveHeader (floats, ball), LiveCourt, PlayFeed, ScrollKeeper, LiveAge
    screens/              Today, Game, Standings, Team, ModelRecord
    mocks/                fixtures + mock router (bundled only when VITE_MOCK=1)
```

## Notes
- All requests use relative `/api/...` URLs.
- The service worker caches only the app shell (index, hashed `/assets/*`, icons). API responses
  and cross-origin logos always go to the network.
- If a logo fails to load, a text badge with the team abbreviation is shown instead.
- A card without `league` is treated as NBA. In College mode, cards whose league isn't `ncaab` are
  dropped, so a pre-v2 server never shows NBA games labeled as college (the screen says college
  scores aren't available yet instead).
- Pre-game box scores are shown as "starts at tip-off" even if the server sends team rows with all-null stats.
