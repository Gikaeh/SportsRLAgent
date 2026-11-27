# DeepSports for Even Realities G2

A glasses plugin that tracks the owner's open bets, the same two lists as the web app's Bets
screen: **Bets** (every game with an open bet: live score and how each bet stands) and
**Parlays** (each ticket and its legs). It is a small TypeScript web page that runs inside the
Even Realities phone app and draws text on the G2's 576×288 green display. Labels and odds only,
never stakes. (Until v0.2.0 it showed followed teams' scores; that was replaced on 2026-11-27.)

```
Bets 2-1 · 2 live · 12:27 PM                 1/5
● ME 53-47 LEM  2nd 11:13
  Under 139 · 100 · pace 139
● FRES 65-50 USA  2nd 6:53
  Over 144.5 · 115 · pace 139
UMBC @ GW  1:00 PM
  Under 152.5
Tap: parlays · Swipe: more
```
```
Parlays · 12:28 PM                           3/5
LOST +21.2M · 2-1 · 16/19 left
W UVA/XAV U156.5  154
L STMN/LIB O146.5  143
● ME/LEM U139  101, 2nd 11:11
○ UMBC/GW U152.5  1:00 PM
Tap: bets · Swipe: more
```

## Using it on the glasses

| Gesture | What happens |
|---|---|
| Tap | Switches between Bets and Parlays (back to page 1). |
| Swipe down / up | Next/previous page. |
| Double-tap | Asks the system to close the app (the glasses show a confirm dialog). |

- **Bets** (`GET /api/bets`): live games first, then upcoming, then finals not graded yet in the
  log, in the server's order. Each game line is followed by one line per bet:
  - totals: points so far and `pace N` (projected final total at the current scoring rate, from
    5 minutes in, not in OT), or `WON 154` / `LOST 143`. A live over already past the line shows
    WON and a live under past it LOST, since those can't change;
  - spreads: `covering by 2` / `short by 3` / `on the number`; moneylines: `up 3` / `down 3`;
  - first-half bets (`1H`) use the first-half points and are decided once the half ends.
  The header shows today's tally of decided bets on screen (`2-1`) and how many games are live.
  A game drops off once its bet is graded in the log.
- **Parlays** (`GET /api/parlays`): alive tickets first, then settled or dead ones (placed today).
  The first line is the ticket: result (`ALIVE`, `LOST`, `WON`), price, legs won-lost and legs
  left. Then 7 legs a page: `W`/`L`/`P` decided, `●` live, `○` not started.
- `●` marks a live game. The header shows when the data was last updated. **"stale 3m"** means
  the last update failed: you're looking at data from 3 minutes ago, and it retries every 30 s.
- Refreshes every 30 s while a game is live and every 5 min otherwise (the server decides,
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

In the Even app open **Even Hub → Scan QR** and scan the code. The bets list opens on the
glasses. The Mac's LAN IP is currently `172.16.0.61`. If it changes, run
`npx evenhub qr --url http://<new-ip>:8787/glasses/` (find the IP in System Settings → Wi-Fi → Details).

To work on the plugin with hot reload instead, run `npm run dev` (Vite on port 5173, which
proxies `/api` to the server on 8787) and scan `npx evenhub qr --url http://172.16.0.61:5173/glasses/`.

## Packaged build for Even Hub (private upload)

```bash
cd glasses && npm run pack:lan   # -> glasses/deepsports-glasses.ehpk (currently v0.3.0: bets + parlays)
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
| `default` | 3 live games (incl. an NBA spread + total), 2 upcoming, 2 finals; a dead 9-leg parlay and an alive 2-leg one |
| `busy` | 10 games: paging, a game with two bets |
| `empty` | No open bets, no parlays |
| `flaky` | First load works, then every fetch fails ("stale Xm") |
| `down` | The server is unreachable from the start |

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
- The packaged build (`npm run pack:lan`) has the Mac's address built in; see "Packaged build" above.

## Code layout

| File | Role |
|---|---|
| `src/even.ts` | The only file that calls the Even Hub SDK (pinned 0.0.16, pre-1.0): two text containers, `textContainerUpgrade` updates, input → `tap/up/down/double/...` |
| `src/display.ts` | The small `Display` interface the app talks to |
| `src/preview.ts` | Mirrors the glasses text on the phone page, plus the `?preview` browser stand-in |
| `src/app.ts` | Polling, caching the last good data (localStorage), input, and redrawing only changed text |
| `src/view.ts` | Pure view state: gestures → state, state → header/body text |
| `src/format.ts`, `src/width.ts` | Pure formatting: bet status (totals, spreads, ML, 1H, pace), game/bet/leg lines, pages, header, pixel-width fitting (≤ 34 chars / ~560 px) |
| `src/api.ts` | `/api/bets` + `/api/parlays` clients, poll interval |
| `src/mock/fixtures.ts` | Mock API for `dev:mock` and the tests |
| `test/format.test.ts` | `npm test`: Node's built-in test runner; checks text widths and glyphs against `@evenrealities/pretext` (the firmware font metrics) |

Data source: the plugin polls `GET /api/bets` and `GET /api/parlays` together (docs/API.md). If one
fails, the other still updates and the header shows `stale Xm` (age of the older data). Bet status
is worked out on the glasses from the card's score and the bet label; parlay leg status comes from
the server.

Versions are pinned exactly and were installed with `npm install --before=2026-10-21`.
Requires Node ≥ 22.6 for `npm test`.
