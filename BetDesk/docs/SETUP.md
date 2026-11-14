# BetDesk setup (owner, one time)

About 20 minutes, all on Cloudflare's free plans, plus a domain already on Cloudflare. Run commands
from `BetDesk/` unless a step says otherwise. Each step says where a value goes; none of them go
into the repo or a chat. Steps marked *verify* depend on Cloudflare's current dashboard layout: if a
menu has moved, look for the same setting by name.

How it fits together: phone → Access login → BetDesk Worker (`*.workers.dev`) → Cloudflare Tunnel
hostname on your domain (Access, service token only) → `cloudflared` on the Mac → DeepSports API on
`localhost:8787`.

## 1. Cloudflare account and deploy
```bash
npm install --before=2026-10-28     # once
npx wrangler login                  # browser OAuth
npm run deploy                      # builds web/ and deploys; prints https://betdesk.<subdomain>.workers.dev
```
The site now answers `403 forbidden` on `/api/*`: the Worker refuses data until Access is set up
(it fails closed).

## 2. Login for people: Access on the Worker
Menu names as of 2026-11 (Cloudflare docs): Zero Trust's "Access" is now **Access controls**, "Networks"
is **Networking**, a tunnel's "Public hostname" is a **Published application** route.
1. Dashboard → Workers & Pages → `betdesk` → **Access** tab → **Protect this Worker behind Access** →
   **All traffic** → Authentication policy **Cloudflare account** (only you are a member; never
   "Email domain", that admits a whole domain) → session 1 month → **Apply Access**. If it asks for
   Zero Trust first: pick a **team name** (team domain `https://<team>.cloudflareaccess.com`) and the
   **Free** plan. The Free plan still asks for payment details but doesn't charge.
2. The team name is shown later under Zero Trust → **Settings**.
3. The **AUD tag**: Zero Trust → Access controls → **Applications** → the betdesk app → **Edit** →
   **Additional settings** → **Application Audience (AUD) Tag** (step 5).
4. Login method: **One-time PIN** (on by default). People are let in only if they pass the policy *and*
   are in the `ALLOWED_EMAILS` secret (the Worker checks it itself).

## 3. The tunnel on the Mac
`cloudflared` is already installed (`brew install cloudflared` otherwise). DeepSports' API must be
running (`com.deepsports.serve`; `curl -s localhost:8787/api/health`). A published route needs a
domain (zone) on your Cloudflare account.
1. Zero Trust → **Networking** → **Tunnels** → **Create a tunnel** → name `deepsports-mac` → **Create
   Tunnel**. Pick macOS; the page shows an install command with a long token. Run it on the Mac in
   Terminal (the token is a secret: don't save it anywhere else), then **Continue**:
   ```bash
   sudo cloudflared service install <token>    # a launchd daemon; starts at boot, reconnects by itself
   ```
   The tunnel turns **Healthy** in the dashboard.
2. Same tunnel → **Routes** tab → **Add route** → **Published application**: subdomain of your choice
   (e.g. `ds-api`), your **Domain**, **Service URL** `http://localhost:8787` → **Add route**. Nothing
   else on the Mac is reachable through it.

## 4. Lock the tunnel hostname: Access, service token only
1. Zero Trust → Access controls → **Service credentials** → **Service Tokens** → **Create Service
   Token**: name `betdesk-worker`, duration non-expiring (or a year with a reminder) → **Generate
   token**. Keep the page open: the Client Secret is shown only once.
2. Zero Trust → Access controls → **Applications** → add a **Self-hosted** application, domain = the
   hostname from 3.2. One policy only: *Worker*, action **Service Auth**, Include → **Service Token**
   → `betdesk-worker`. No email policy: people never call this hostname directly. (Any other action
   makes Access show a login page, and the Worker's calls fail.)
3. Optional second lock, on the Mac side: the tunnel route's Access setting (**Protect with Access**,
   *verify*) → pick that application. `cloudflared` then rejects any request without a valid Access
   token itself.
4. Check from any machine: `curl -s -o /dev/null -w '%{http_code}\n' https://<hostname>/api/health`
   must print `302` or `403`, never `200`.

## 5. Worker secrets
```bash
cd worker
npx wrangler secret put ACCESS_TEAM_DOMAIN     # https://<team>.cloudflareaccess.com
npx wrangler secret put ACCESS_AUD             # the betdesk app's AUD tag (step 2.4)
npx wrangler secret put ALLOWED_EMAILS         # your email; REQUIRED (comma-separated once Gikaeh is added)
npx wrangler secret put ORIGIN_URL             # https://<hostname from 3.2>
npx wrangler secret put ORIGIN_CLIENT_ID       # betdesk-worker service token (step 4.1)
npx wrangler secret put ORIGIN_CLIENT_SECRET
cd ..
```

## 6. Phones
Open the workers.dev URL, sign in (email → 6-digit code), then Share → **Add to Home Screen**. The
installed app keeps its own login, so sign in once more inside it. Sessions last a month.

## Adding Gikaeh later
In the betdesk Access application, add a policy: **Allow**, Include → **Emails** → their address. Add it to `ALLOWED_EMAILS` too
(`npx wrangler secret put ALLOWED_EMAILS` with both, comma-separated). Nothing else changes.

## When something's wrong
| Symptom | Check |
|---|---|
| Banner "The owner's Mac isn't reachable" (`mac_offline`) | Tunnel status in Zero Trust → Networking → Tunnels; on the Mac `sudo launchctl list \| grep cloudflared` and `curl -s localhost:8787/api/health` |
| Banner "setup issue: origin_auth" | The tunnel app's *Service Auth* policy, or `ORIGIN_CLIENT_ID`/`ORIGIN_CLIENT_SECRET` |
| Banner "setup issue: not_configured" | `ORIGIN_URL` secret missing |
| Every `/api` call is `403` after login | `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` or `ALLOWED_EMAILS` secret |
| "Stats refreshing" | A DeepSports writer job is running (normal, a few minutes) |

Removing the tunnel: `sudo cloudflared service uninstall`, then delete it in the dashboard.
