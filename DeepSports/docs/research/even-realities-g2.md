# Even Realities G2: developer options for a live NBA scoreboard

Research date: 2026-11-03. Primary sources are the official Even Hub docs (hub.evenrealities.com/docs), the npm registry, and the `even-realities` GitHub org. Anything I could not confirm from a primary source is marked **UNCONFIRMED**.

---

## 1. Official developer path for the G2

**Platform: Even Hub "plugins".** These are web apps (HTML/CSS/TypeScript) that run in a WebView inside the Even Realities phone app: Chromium WebView on Android, WKWebView on iOS. The glasses are only a display and input surface over BLE 5.2, and no app logic runs on them. The SDK injects an `EvenAppBridge` into the WebView. Your code calls methods like `createStartUpPageContainer` / `textContainerUpgrade`, and input comes back through `onEvenHubEvent`.
- The overview says: "Today, one surface is live: plugins." It lists **dashboard widgets, dashboard layouts and AI skills as "coming"**, with no dates (page last updated 2026-08-29).
- The docs cover only the G2; I found no G1 support statement in Even Hub. G1 has its own older BLE demo repo (`even-realities/EvenDemoApp`).
- Press reports put the public Even Hub launch at **2026-04-03** (androidguys/ground.news). The official docs do not state a launch date.

**Packages (versions from the npm registry, checked 2026-11-03):**

| Package | Latest | Published | Notes |
|---|---|---|---|
| `@evenrealities/even_hub_sdk` | **0.0.16** | 2026-09-24 | 0.0.16 fixes `setTimeout`/`setInterval` callbacks running twice. 0.0.15 raises the minimum Even app to **2.2.10**. MIT. README is mostly in Chinese. |
| `@evenrealities/evenhub-cli` | **0.2.0** | 2026-10-20 | `init`, `qr`, `pack`, `upload`, `login`, testers, JSON output |
| `@evenrealities/evenhub-simulator` | **0.9.5** | 2026-09-01 | Desktop simulator with an automation HTTP API |

All three packages are still 0.x and changed often in 2026. Treat the platform as early-stage and still changing: limits, the manifest format and event semantics have all changed between releases. The docs do not use the word "beta" for the platform itself.

**Language:** TypeScript or JavaScript. The templates use Vite with Node 18+ (the SDK README says Node 20+).

**Accounts and approval:**
- You need an Even Realities app account. You sign in at hub.evenrealities.com/login with the same credentials, and that sign-in enables **Developer Mode** in the phone app. There is no toggle: after signing in, restart the app and the developer section appears in the Even Hub tab. The docs mention no fee, and paid apps are "TBD".
- **No review is needed for personal use.** There are three ways to run without review:
  1. **QR sideload (dev):** run `npm run dev`, then `evenhub qr --url http://<laptop-lan-ip>:5173`, then scan in Even app → Even Hub → Scan QR. The page loads on the glasses with hot reload.
  2. **Private build:** run `evenhub pack app.json dist -o app.ehpk`, then `evenhub upload`, then install from Even Hub → Me → Apps → Private builds. These builds are only for your own account, and **can only be launched from the phone app, not the glasses menu.** The docs say private builds "do not pass the 5-minute lock test".
  3. **Beta testing:** promotes a build to testers and makes it launchable from the glasses menu.
- The public store needs portal submission and QA review. Root-page exit must use `shutDownPageContainer(1)`, and a custom exit UI gets the app rejected.
- The architecture page also says: "If you'd rather stay outside the Even Hub distribution flow, build a Progressive Web App and point users at your hosted URL." **UNCONFIRMED:** the docs don't explain how a hosted URL gets the glasses bridge, other than through the QR loader.

**Other official resources:** `even-realities/evenhub-templates` (last push 2026-08-07), `even-realities/everything-evenhub` (Claude Code/Codex skills plugin, last push 2026-10-21), and `even-realities/EH-InNovel` (a novel-reader demo).

## 2. Display capabilities and limits (third-party plugins)

From the Display & UI System and Design Guidelines docs and the SDK 0.0.16 typings:

- **Canvas:** 576 × 288 px per eye, origin at top-left.
- **Color:** 4-bit greyscale shown as 16 levels of green. Black means off/transparent. There is no background fill; borders are the only decoration.
- **Layout model:** absolute-positioned containers with no DOM or CSS. Each page allows **up to 4 image containers plus 8 other containers** (text/list). Exactly one container must have `isEventCapture: 1`. Optional `zOrderIndex` (SDK 0.0.12+) is all-or-nothing per page.
- **Text containers:**
  - One firmware LVGL font. It is **not monospaced** and has no size, bold or alignment options; centering is done by padding with spaces.
  - `\n` breaks lines, and text wraps at the container width.
  - A full-screen container holds roughly 400–500 characters.
  - Character limits: 1,000 chars on create/rebuild and 2,000 on `textContainerUpgrade`.
  - Glyphs outside the font are silently dropped. Reliable glyphs include box-drawing characters, arrows, ●○ ■□ ★☆ and `━ ─`.
  - Five brightness levels via `textColor` 0–4 (SDK 0.0.14+).
  - Border width 0–5, radius 0–10, padding 0–32.
- **Lists:** up to 20 items of 64 chars each, with native scroll and highlight. Lists can't be updated in place; changing one means a page rebuild.
- **Images:** up to 288 × 144 px per container, 4-bit grey. Pixels are pushed with `updateImageRawData` and LZ4-compressed in transit. Only one image send can run at a time, and each send holds the image path for 100 ms. A full-screen image refresh takes about 800 ms.
- **Update method for a scoreboard:** use `textContainerUpgrade`, which the docs call "faster than a rebuild and flicker-free on hardware". It supports partial updates via `contentOffset`/`contentLength`. The docs give **no explicit rate limit for text updates (UNCONFIRMED)**. Community score and ticker apps poll about every 15 s, and the BLE link will be the real limit.
- **Input** (`OsEventTypeList`):
  - CLICK(0), SCROLL_TOP(1), SCROLL_BOTTOM(2) (swipe up/down), DOUBLE_CLICK(3), LONG_PRESS(9)/RELEASE(10) (SDK 0.0.14+, app 2.2.9+).
  - The same enum also has FOREGROUND_ENTER(4), FOREGROUND_EXIT(5), ABNORMAL_EXIT(6), SYSTEM_EXIT(7) and IMU_DATA_REPORT(8).
  - Input sources are the G2 temple touchpads (left and right) and the optional R1 ring. From SDK 0.0.15, events carry the source (`eventSource`).
  - Head motion is available as a raw IMU stream (`imuControl`). There is **no documented "head-up gesture" event**.
  - Gotcha from the templates README: a single tap arrives with *no* `eventType`, because the zero value is omitted on the wire.
- **Device info:** `getDeviceInfo()` / `onDeviceStatusChanged` report battery, wearing state and charging.
- **Contextual menu:** available from SDK 0.0.14 and Even app 2.2.9+.
- **Updates while idle or not foregrounded.** The sources disagree:
  - Background & Lifecycle doc: on iOS the WebView "keeps running when the app is backgrounded or the screen locks" and in-memory state survives. On Android the WebView may be suspended under memory pressure, and open WebSockets typically drop.
  - FAQ: "Can I make network calls while backgrounded? No. The WebView is suspended in the background."
  - Local Testing doc: backgrounding the Even app suspends the WebView in QR dev mode.
  - The official `everything-evenhub` background-state skill describes a "headless WebView" that "keeps pushing frames to the glasses" in the background, using `setBackgroundState`/`onBackgroundRestore`. **These APIs are not in the published SDK 0.0.16 typings**, so this may be unreleased.
  - SDK 0.0.10 notes "stronger WebView background keep-alive".
  - **Conclusion (UNCONFIRMED):** plan for updates to work reliably only while the plugin is the active app on the glasses and the Even app is alive. Background or locked-phone behavior has to be tested on the owner's own phone and OS.
  - I could not confirm from the docs whether the glasses display sleeps or times out while a plugin is open, or how a plugin interacts with the native head-up dashboard. Plugins can't show on the native dashboard today, because dashboard widgets are "coming".

## 3. How a plugin gets data

- The plugin itself makes requests with **`fetch()`, XHR or WebSockets** from the WebView. There is no special proxy through the phone app.
- Every request must pass **two independent checks**:
  1. **Even app whitelist:** the destination origin must appear in `app.json` → `permissions: [{ name: "network", desc, whitelist: ["https://api.example.com"] }]`. Use one full origin per entry. Bare hosts and wildcards are not supported, and changing the list means repack and re-upload. Blocked requests produce no traffic at all.
  2. **Standard CORS**, enforced by WKWebView or Chromium. The server must send `Access-Control-Allow-Origin` (`*` or the WebView origin). Requests with JSON bodies or custom headers trigger a preflight that needs a 2xx `OPTIONS` response with Allow-Methods/Allow-Headers. In the docs' words: "If curl succeeds but the WebView fails, the cause is almost always CORS."
- **HTTP vs HTTPS:** the docs say "use HTTPS in production; plain `http://` is only useful for local development against a LAN dev server". They do **not** specify:
  - whether a whitelist entry like `http://192.168.1.20:8000` (IP and port) is accepted;
  - what origin a packaged `.ehpk` page runs under, which matters because an https origin calling an http IP would be blocked as mixed content;
  - whether iOS ATS or local-network restrictions apply.
- **Evidence from a community app (unofficial):** `bigdra50/even-status-deck` polls `http://<LAN-IP>:8723/api/...` on a PC, yet its `app.json` whitelist lists only https weather APIs. Either the whitelist isn't enforced for LAN or dev loads, or it was only used in QR dev mode. **UNCONFIRMED.** That project also reports a known iOS issue where the WebView goes white after a few minutes in the foreground.
- **Implications for `http://<mac-lan-ip>:port`:**
  - In **QR dev mode** (page itself served over `http://` from the LAN), calling another `http://` LAN origin is same-scheme, so mixed content is not a concern. You still need CORS headers, unless you serve the plugin from the same origin as the API, which removes CORS entirely.
  - Same-origin is the strongest option: have the Python API also serve the built plugin's static files, then QR-load `http://<mac-ip>:<port>/glasses/`.
  - For a packaged private build, the safest assumption is an HTTPS endpoint. **Tailscale Serve** (`tailscale serve`) gives the Mac a real `https://<host>.<tailnet>.ts.net` certificate; whitelist that origin and add CORS.
  - The phone must be able to reach the Mac directly. That means no Wi-Fi client isolation and the macOS firewall allowing inbound connections on the port. The docs suggest Tailscale or a hotspot as workarounds.

## 4. Templates, examples and community options

**Official** (`even-realities` org, MIT):
- `evenhub-templates`: `minimal` (tap counter, double-tap exit), `text-heavy` (pagination, the 2,000-char `textContainerUpgrade` path, font measurement), `asr`, `image`. Install with `npx degit even-realities/evenhub-templates/minimal my-app`.
- `everything-evenhub`: 13 Claude Code/Codex skills (quickstart, glasses-ui, handle-input, font-measurement, background-state, simulator-automation, sdk/cli references). Directly usable from this Claude Code environment.
- `EH-InNovel`: reader demo.
- None of the official examples is a live-updating ticker or scoreboard.

**Unofficial community Even Hub plugins** (good references, all TypeScript/Vite plugins; listed in `pangoleen/awesome-even-realities-g2`):
- **`Minna-Cross/even-nba-pulse`:** a live NBA score and play-by-play plugin. It polls every 15 s through a CORS-enabling Cloudflare Worker, and its whitelist holds the Worker plus `https://site.api.espn.com`. This is the closest existing analog to our app.
- `opinsky/even_score`: live score tracker.
- `fabioglimb/even-market` and `ARNLTony/even-g2-crypto-ticker`: tickers.
- `bigdra50/even-status-deck`: HUD fed from a local PC HTTP server, the closest analog to our "Mac API" setup.
- Teleprompters: `PitchBeam`, `Even-LotH`.
- Helper libraries: `fabioglimb/even-toolkit` (text measurement), `@jappyjan/even-better-sdk` 0.0.11 (SDK wrapper, last published 2026-03-25), `fabioglimb/create-even-app`.

**Unofficial direct-BLE options** (bypass the Even app; reverse-engineered; can break with firmware updates; may conflict with the official app's connection):
- `i-soxi/even-g2-protocol`: protobuf definitions plus Python examples, including a teleprompter. Display rendering is still listed as an open research area.
- `Commute773/g2-kit`: aa 21 framing, CRC-16, pre-1.0.
- `Thepizzapie/OpenEvenSdk`: Python, Swift and Kotlin bridges.
- `gpsnmeajp/men-g2-ble-gateway`: a Python gateway that exposes the G2 over HTTP, WebSocket or MCP. This could let the Mac drive the glasses directly, but only within Bluetooth range.
- MentraOS: an open glasses OS that drives the G2 over BLE.
- These are interesting for an always-on push model, but they are much riskier than the official path.

## 5. Recommended architecture and simplest prototype

**Recommendation: an official Even Hub plugin (TypeScript) that polls the Mac's read API, plus a shared TS client module used by both the PWA and the plugin.**

```
Mac (Python API, LAN/Tailscale)
  GET /api/glance?teams=...   -> compact JSON: per followed team
                                  {status: live|final|scheduled, home, away, score,
                                   period, clock, start_time, next_game}
  + CORS headers (Access-Control-Allow-Origin: *), GET-only (no preflight)
  + optionally serves built plugin static files at /glasses/ (same-origin)
        |
        | fetch every ~10-15 s while any game is live; every few minutes otherwise
        v
Phone: Even app WebView running the plugin (TS, @evenrealities/even_hub_sdk 0.0.16)
  - shared `api-client.ts` + `formatGlance.ts` (also used by the PWA)
  - 1 full-width text container (isEventCapture) for game lines + 1 small header/footer
  - textContainerUpgrade on change only (diff the string) -> flicker-free
  - tap = next game / double-tap = exit (shutDownPageContainer(1)), swipe = page
  - cache last payload in localStorage; show "stale 2m" when the fetch fails
        | BLE
        v
G2 display (576x288, green text)
```

- **Server side:** shape the payload for glanceability. Pre-format short strings server-side, or in the shared TS formatter, to fit about 30–40 chars per line, since the font isn't monospaced; use the `text-heavy` template's font-measurement helper. Keep to GET with no custom headers so CORS stays a "simple request". If the API grows later, consider SSE or WebSocket, but polling is simpler and survives Android suspension better.
- **Simplest path to a first working prototype:**
  1. Install the Even app (≥ 2.2.10 for SDK 0.0.15+), create an account, and sign in at hub.evenrealities.com to unlock Developer Mode.
  2. Run `npx degit even-realities/evenhub-templates/minimal deepsports-g2`, then `npm i` and add `@evenrealities/evenhub-cli` and `@evenrealities/evenhub-simulator`.
  3. Add CORS to the Python API, bind it to `0.0.0.0`, and allow it through the macOS firewall.
  4. Replace the template's counter with `setInterval` → `fetch('http://<mac-ip>:<port>/api/glance')` → `textContainerUpgrade`. Iterate in `evenhub-simulator` first.
  5. Set Vite `server.host: true` and `hmr.host` to the Mac's LAN IP, run `npm run dev`, then `npx evenhub qr --url http://<mac-ip>:5173`, and scan from the Even app. It should be live on the glasses within minutes.
  6. Later: pack a private build with the whitelist pointing at a Tailscale Serve HTTPS origin (or test whether an `http://IP:port` entry works). Promote to Beta if you want to launch from the glasses menu.

**Risks and unknowns:**
1. **Background, lock and idle behavior (highest risk).** The official docs contradict each other (iOS "keeps running" vs FAQ "suspended, no network"). Private builds don't pass the 5-minute lock test, the headless-WebView background APIs aren't in the published SDK, and a community app reports iOS white-screens after a few minutes. Expect the app to work only while it is open on the glasses and the Even app is alive, and test this early on the owner's actual phone. There is also no dashboard widget surface yet, so scores can't appear on the native head-up dashboard.
2. **HTTP/LAN in packaged builds.** It is unconfirmed whether the whitelist accepts `http://IP:port` origins, and what origin and mixed-content rules a packaged `.ehpk` has. QR dev mode avoids this. For a durable install, plan on an HTTPS origin (Tailscale Serve) plus CORS. The Mac must also be awake and reachable.
3. **Immature, fast-moving platform.** SDK 0.0.x had 16 releases in 9 months and requires minimum Even app versions. Limits have changed (for example, startup containers went from 4 to 12), the README is mostly in Chinese, and some documented features ship ahead of the npm package. Pin versions, isolate SDK calls behind a small adapter, and re-check the changelog.

Minor items:
- No documented rate limit for text updates, so be conservative and update only on change.
- No font size control and a proportional font make column alignment imperfect.
- A single tap has no `eventType` field on the wire.
- Store submission (if ever wanted) needs a 1-bit store icon and QA review.
- Unofficial BLE routes risk breaking with firmware updates and may conflict with the official app.

---

## Sources

Official (Even Realities):
- Even Hub docs home: https://hub.evenrealities.com/docs
- Overview (surfaces live vs coming): https://hub.evenrealities.com/docs/get-started/overview
- Architecture (WebView, bridge, QR, PWA note): https://hub.evenrealities.com/docs/get-started/architecture
- Sign in / Developer Mode: https://hub.evenrealities.com/docs/get-started/quickstart/sign-in
- Templates: https://hub.evenrealities.com/docs/get-started/quickstart/templates
- Display & UI System: https://hub.evenrealities.com/docs/build/display
- Design Guidelines: https://hub.evenrealities.com/docs/build/design-guidelines
- Device APIs (input, IMU): https://hub.evenrealities.com/docs/build/device-apis
- Page Lifecycle: https://hub.evenrealities.com/docs/build/page-lifecycle
- Networking (whitelist + CORS): https://hub.evenrealities.com/docs/build/networking
- Background & Lifecycle: https://hub.evenrealities.com/docs/build/background-lifecycle
- Local Testing (QR sideload): https://hub.evenrealities.com/docs/test/local-testing
- Private Testing: https://hub.evenrealities.com/docs/test/private-testing
- Packaging & Deployment (app.json, permissions): https://hub.evenrealities.com/docs/ship/packaging
- Changelog: https://hub.evenrealities.com/docs/reference/changelog
- FAQ: https://hub.evenrealities.com/docs/reference/faq
- Glossary: https://hub.evenrealities.com/docs/reference/glossary
- Developer portal: https://evenhub.evenrealities.com
- npm SDK: https://www.npmjs.com/package/@evenrealities/even_hub_sdk (registry: https://registry.npmjs.org/@evenrealities/even_hub_sdk; README changelog and `dist/index.d.ts` of 0.0.16 inspected)
- npm CLI: https://www.npmjs.com/package/@evenrealities/evenhub-cli
- npm simulator: https://www.npmjs.com/package/@evenrealities/evenhub-simulator
- GitHub org: https://github.com/even-realities (evenhub-templates, everything-evenhub, EH-InNovel, EvenDemoApp)
- Templates: https://github.com/even-realities/evenhub-templates
- Skills plugin: https://github.com/even-realities/everything-evenhub (background-state skill)
- Blog: https://www.evenrealities.com/blogs/even-insider/the-unfinished-glasses

Press (secondary):
- https://androidguys.com/news/even-realities-even-hub-app-store-for-g2-smart-glasses-launches/
- https://ground.news/article/even-realities-unveils-even-hub-open-developer-ecosystem-for-g2-smart-glasses

Unofficial / community:
- Awesome list: https://github.com/pangoleen/awesome-even-realities-g2
- NBA Pulse: https://github.com/Minna-Cross/even-nba-pulse
- even_score: https://github.com/opinsky/even_score
- Status Deck (local PC server HUD): https://github.com/bigdra50/even-status-deck
- even-toolkit: https://github.com/fabioglimb/even-toolkit
- even-better-sdk: https://www.npmjs.com/package/@jappyjan/even-better-sdk
- codeview (QR with LAN URL example): https://github.com/opencolin/codeview
- even-g2-protocol (BLE RE): https://github.com/i-soxi/even-g2-protocol
- g2-kit: https://github.com/Commute773/g2-kit
- OpenEvenSdk: https://github.com/Thepizzapie/OpenEvenSdk
- men-g2-ble-gateway: https://github.com/gpsnmeajp/men-g2-ble-gateway
- MentraOS: https://github.com/Mentra-Community/MentraOS
