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
1. Dashboard → Workers & Pages → `betdesk` → Settings → Domains & Routes → `workers.dev` →
   **Enable Cloudflare Access** (*verify*). This creates an Access application for the site. The
   first time, Cloudflare asks you to pick a Zero Trust **team name** (team domain
   `https://<team>.cloudflareaccess.com`) and the Free plan. It may ask for a card even though the
   plan is free.
2. Zero Trust → Access → Applications → the `betdesk` app → **Policies**: *Allow owners*, action
   **Allow**, Include → **Emails** → your email. (Add Gikaeh's later.)
3. The app's settings: **session duration 1 month**. Login method: **One-time PIN** (on by default).
4. Note the app's **Application Audience (AUD) tag** and your team domain (step 5).

## 3. The tunnel on the Mac
`cloudflared` is already installed (`brew install cloudflared` otherwise). DeepSports' API must be
running (`com.deepsports.serve`; `curl -s localhost:8787/api/health`).
1. Zero Trust → Networks → **Tunnels** → Create a tunnel → **Cloudflared** → name `deepsports-mac`.
   Pick macOS; the page shows an install command with a long token. Run it on the Mac in Terminal
   (the token is a secret: don't save it anywhere else):
   ```bash
   sudo cloudflared service install <token>    # a launchd daemon; starts at boot, reconnects by itself
   ```
   The tunnel turns **Healthy** in the dashboard.
2. Same tunnel → **Public hostname** → Add: subdomain of your choice (e.g. `ds-api`), your domain,
   service **HTTP** → `localhost:8787`. Nothing else on the Mac is reachable through it.

## 4. Lock the tunnel hostname: Access, service token only
1. Zero Trust → Access → Service credentials → **Service Tokens** → Create `betdesk-worker`
   (non-expiring, or a year with a reminder). Keep the page open: the secret is shown only once.
2. Zero Trust → Access → Applications → Add → **Self-hosted** → domain = the hostname from 3.2.
   One policy only: *Worker*, action **Service Auth**, Include → **Service Token** → `betdesk-worker`.
   No email policy: people never call this hostname directly.
3. Optional second lock, on the Mac side: tunnel → public hostname → Additional settings → Access →
   **Protect with Access** → pick that application (*verify*). `cloudflared` then rejects any
   request without a valid Access token itself.
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
Add their email to the *Allow owners* policy and to `ALLOWED_EMAILS`
(`npx wrangler secret put ALLOWED_EMAILS` with both, comma-separated). Nothing else changes.

## When something's wrong
| Symptom | Check |
|---|---|
| Banner "The owner's Mac isn't reachable" (`mac_offline`) | Tunnel status in Zero Trust → Tunnels; on the Mac `sudo launchctl list \| grep cloudflared` and `curl -s localhost:8787/api/health` |
| Banner "setup issue: origin_auth" | The tunnel app's *Service Auth* policy, or `ORIGIN_CLIENT_ID`/`ORIGIN_CLIENT_SECRET` |
| Banner "setup issue: not_configured" | `ORIGIN_URL` secret missing |
| Every `/api` call is `403` after login | `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` or `ALLOWED_EMAILS` secret |
| "Stats refreshing" | A DeepSports writer job is running (normal, a few minutes) |

Removing the tunnel: `sudo cloudflared service uninstall`, then delete it in the dashboard.
