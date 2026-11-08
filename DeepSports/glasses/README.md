# DeepSports for Even Realities G2

A glasses plugin that shows your followed teams' games at a glance, NBA and college
(Nevada): live scores first, then today's finals and upcoming tip-offs. It is a small TypeScript web page that runs inside
the Even Realities phone app and draws text on the G2's 576×288 green display.

```
Scores · 7:42 PM                 Page 1/2
● LAL 98-95 SAC  Q4 2:31
● NCAA UNLV 68-70 NEV  OT 1:05
NCAA SMC @ NEV  1:30 PM
NY 104-112 BOS  Final

Tap: details · Swipe: more
```

## Using it on the glasses

| Gesture | What happens |
|---|---|
| Tap | Opens the next game: score by quarter (by half for college), time left, who's ahead, the model's pick, TV channel. After the last game, a tap goes back to the list. |
| Swipe down / up | In the list: next/previous page (5 games per page). In a game: next/previous game. Swiping up from the first game goes back to the list. |
| Double-tap | Asks the system to close the app (the glasses show a confirm dialog). |

- `●` marks a game that's being played right now.
- `NCAA` marks a college game (plain text, since emoji aren't in the glasses font). College games
  have two halves, shown as H1/H2 (then OT).
- `Model: BOS 81% · by ~6` in a game's detail is the DeepSports prediction made before tip-off:
  Boston has an 81% chance to win, by about 6 points. Once the game is final it says whether the
  pick was `right` or `wrong`. It's for context and doesn't beat the betting market. College games
  have no predictions yet, so the line is simply absent.
- The header shows when the scores were last updated. **"stale 3m"** means the last update
  failed: you're looking at scores from 3 minutes ago, and the app keeps retrying every 30 s.
- With no followed games today it says **"No followed games today"** and shows the next one,
  from either league (the server's `next_followed_game`).
- Scores refresh every 30 s while a game is live and every 5 min otherwise (the server decides,
  never faster than every 15 s).

## One-time setup (owner)

1. Install the **Even Realities** app, version **2.2.10 or newer** (the SDK needs it), and pair the G2.
2. Sign in at **https://hub.evenrealities.com** with the same account you use in the Even app.
   That turns on **Developer Mode**. There's no toggle: fully close and reopen the Even app
   afterwards, and a developer section appears in the **Even Hub** tab.
3. On the Mac, let the DeepSports server accept connections from your phone: the server listens
   on port 8787, and macOS may ask you to allow incoming connections the first time. The phone
   and the Mac need to be on the same Wi-Fi.

## Run it on the real glasses (dev)

The Python server serves the built plugin at `/glasses/`, on the same address as the API, so
the plugin needs no CORS or whitelist setup.

```bash
cd glasses
npm ci              # first time only
npm run build       # writes glasses/dist, which the server serves at /glasses/
# start (or restart) the DeepSports server: it mounts glasses/dist only if it exists at startup
npm run qr          # QR code for http://172.16.0.61:8787/glasses/
```

In the Even app open **Even Hub → Scan QR** and scan the code. The scoreboard opens on the
glasses. The Mac's LAN IP is currently `172.16.0.61`. If it changes, run
`npx evenhub qr --url http://<new-ip>:8787/glasses/` (find the IP in System Settings → Wi-Fi → Details).

To work on the plugin with hot reload instead, run `npm run dev` (Vite on port 5173, which
proxies `/api` to the server on 8787) and scan `npx evenhub qr --url http://172.16.0.61:5173/glasses/`.

## Packaged build for Even Hub (private upload)

```bash
cd glasses && npm run pack:lan   # -> glasses/deepsports-glasses.ehpk (currently v0.2.0: college + predictions)
```
This builds into `dist-pack/` with relative asset paths and `VITE_API_BASE=http://172.16.0.61:8787`
baked in (the server sends `Access-Control-Allow-Origin: *`), then packs with `app.json` (network
whitelist `http://172.16.0.61:8787`, min Even app 2.2.10). Upload the `.ehpk` on the Even Hub portal
or with `npx evenhub upload deepsports-glasses.ehpk -m "<changelog>"`, then install it from Even Hub → Me →
Apps → Private builds.

Verified working through Even Hub on the owner's G2 (2026-11-03), including the plain-http IP origin.
It depends on the Mac keeping `172.16.0.61`, which is reachable remotely through the owner's existing
network setup. If the IP changes, update `pack:lan` and `app.json` and repack.

## Simulator and mock data (no glasses, no server)

```bash
npm run dev:mock    # Vite on :5173 with built-in fake games (src/mock/fixtures.ts)
npm run simulate    # opens the official Even Hub simulator on http://localhost:5173/glasses/
```

Add `?scenario=...` to the URL to see each state. For example:
`node node_modules/@evenrealities/evenhub-simulator/bin/index.js "http://localhost:5173/glasses/?scenario=empty"`

| Scenario | Shows |
|---|---|
| `default` | One live game, one final, one upcoming |
| `busy` | 7 games: paging, overtime, a postponed game |
| `empty` | No followed games today; next is Nevada tomorrow (NBA's is in 2 days) |
| `flaky` | First load works, then every fetch fails ("stale Xm") |
| `down` | The server is unreachable from the start |
| `v1` | A pre-v2 server: no `league` field, ignores `league=` (college requests return NBA games, which are dropped) |

`default` and `busy` also include Nevada's game vs Saint Mary's and, in `busy`, a live college game in OT.

`npm run simulate:auto` also starts the simulator's automation API on port 9898. You can use it
to take screenshots (`curl -o shot.png localhost:9898/api/screenshot/glasses`), send gestures
(`curl -X POST -d '{"action":"click"}' localhost:9898/api/input`), and read the console
(`/api/console`). Note that macOS throttles timers in the simulator's window while it's in the
background, so auto-refresh can look stuck there. Any input wakes it up.

Without the simulator, open `http://localhost:5173/glasses/?preview` in a browser. The page
shows the glasses text and has Tap/Swipe/Double-tap buttons (or use Enter, arrow keys, Esc).

## Known limitations

- **It probably only updates while the plugin is open on the glasses and the Even app is
  running.** Even's docs disagree about background behavior, and locking the phone or
  backgrounding the Even app most likely pauses the plugin. It catches up as soon as it's back.
  This needs testing on your own phone.
- Plugins can't appear on the G2's built-in head-up dashboard yet (Even lists widgets as "coming").
- QR-loaded dev plugins launch from the phone app, not from the glasses menu.
- The firmware font is proportional, so the quarter-by-quarter columns line up only approximately.
- The packaged build (`npm run pack:lan`) has the Mac's address built in; see "Packaged build" above.

## Code layout

| File | Role |
|---|---|
| `src/even.ts` | The only file that calls the Even Hub SDK (pinned 0.0.16, pre-1.0): two text containers, `textContainerUpgrade` updates, input → `tap/up/down/double/...` |
| `src/display.ts` | The small `Display` interface the app talks to |
| `src/preview.ts` | Mirrors the glasses text on the phone page, plus the `?preview` browser stand-in |
| `src/app.ts` | Polling, caching the last good data (localStorage), input, and redrawing only changed text |
| `src/view.ts` | Pure view state: gestures → state, state → header/body text |
| `src/format.ts`, `src/width.ts` | Pure formatting: game lines, detail view, header, pixel-width fitting (≤ 34 chars / ~560 px) |
| `src/api.ts` | `/api/scoreboard?league=` client for both leagues (in parallel; one failing keeps the other), next-game lookahead fallback, poll interval |
| `src/mock/fixtures.ts` | Mock API for `dev:mock` and the tests |
| `test/format.test.ts` | `npm test`: Node's built-in test runner; checks text widths and glyphs against `@evenrealities/pretext` (the firmware font metrics) |

Data source: the plugin polls `GET /api/scoreboard?league=nba` and `?league=ncaab` instead of
`/api/glance`. Glance lines are plain strings, so there's no way to put live games first, open a
detail view (quarters, TV, prediction), or find the next game from them. The next game comes from
each scoreboard's `next_followed_game` (earliest of the two); on a server without that field the
plugin falls back to scanning the next 7 days of both leagues. If one league's fetch fails, the
other still updates and the header shows `stale Xm` (age of the oldest data).

Versions are pinned exactly and were installed with `npm install --before=2026-10-21`.
Requires Node ≥ 22.6 for `npm test`.
