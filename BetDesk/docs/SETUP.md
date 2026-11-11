# BetDesk setup (owner, one time)

About 20 minutes, all on the free plans. Run commands from `BetDesk/`. Each step says where a value
goes; none of them go into the repo. Steps marked *verify* depend on Cloudflare's current dashboard
layout: if a menu has moved, look for the same setting by name.

## 1. Cloudflare account and deploy
```bash
npm install --before=2026-10-27     # once
npx wrangler login                  # browser OAuth; creates a free account if needed
npx wrangler d1 create betdesk      # prints a database_id
```
Paste the `database_id` into `worker/wrangler.jsonc` (it isn't a secret; commit it). Then:
```bash
npm run migrate:remote -w worker
npm run deploy                      # builds web/ and deploys; prints https://betdesk.<subdomain>.workers.dev
```
The site now answers `403 forbidden` on `/api/*`: the Worker refuses data until Access is set up
(it fails closed).

## 2. Login: Cloudflare Access
1. Dashboard → Workers & Pages → `betdesk` → Settings → Domains & Routes → `workers.dev` →
   **Enable Cloudflare Access** (*verify*). This creates an Access application for the site. The
   first time, Cloudflare asks you to pick a Zero Trust **team name** (your team domain becomes
   `https://<team>.cloudflareaccess.com`) and the Free plan. It may ask for a card even though
   the plan is free.
2. Zero Trust → Access → Service credentials → **Service Tokens** → Create `betdesk-pusher`
   (duration: non-expiring, or a year with a reminder). Keep the page open for section 4: the
   secret is shown only once.
3. Zero Trust → Access → Applications → the `betdesk` app → **Policies**:
   - *Allow owners*: action **Allow**, Include → **Emails** → your email. (Add Gikaeh's later.)
   - *Pusher*: action **Service Auth**, Include → **Service Token** → `betdesk-pusher` (step 2).
4. The app's settings: **session duration 1 month**. Login methods: **One-time PIN** is on by
   default and needs no setup. Google login is optional (it needs a Google OAuth client; see
   Cloudflare's "Google" identity provider docs).
5. Note the app's **Application Audience (AUD) tag** (app overview) and your team domain.

## 3. Worker secrets
```bash
cd worker
npx wrangler secret put ACCESS_TEAM_DOMAIN   # https://<team>.cloudflareaccess.com
npx wrangler secret put ACCESS_AUD           # the AUD tag
npx wrangler secret put ALLOWED_EMAILS       # your email; REQUIRED (comma-separated once Gikaeh is added)
# Ingest token: generated once, stored in the Worker and in the Mac's Keychain, never printed.
T=$(openssl rand -hex 32); printf %s "$T" | npx wrangler secret put INGEST_TOKEN
security add-generic-password -U -s betdesk -a ingest-token -T /usr/bin/security -w "$T"; unset T
# (the token is visible to your own processes for an instant while `security` runs; acceptable on this Mac)
cd ..
```

## 4. The Mac's pusher
```bash
# The service token from step 2.3 (each command prompts for the value):
security add-generic-password -U -s betdesk -a access-client-id -T /usr/bin/security -w
security add-generic-password -U -s betdesk -a access-client-secret -T /usr/bin/security -w
mkdir -p ~/.config/betdesk
echo 'BETDESK_URL=https://betdesk.<subdomain>.workers.dev' > ~/.config/betdesk/env
tools/pusher.sh --full          # expect "push: ok, full=true ..."
tools/launchd/install.sh        # every minute from now on; log: ~/Library/Logs/BetDesk/pusher.log
```
`tools/launchd/install.sh uninstall` stops it.

## 5. Phones
Open the workers.dev URL, sign in (email → 6-digit code), then Share → **Add to Home Screen**. The
installed app keeps its own login, so sign in once more inside it. Sessions last a month.

## Adding Gikaeh later
Add their email to the *Allow owners* policy and to `ALLOWED_EMAILS`
(`npx wrangler secret put ALLOWED_EMAILS` with both, comma-separated). Nothing else changes.

## When something's wrong
| Symptom | Check |
|---|---|
| App says "Data is N min old" | `tail ~/Library/Logs/BetDesk/pusher.log`; is the Mac awake and `curl -s localhost:8787/api/health` ok? |
| Log: `redirected to login` | The Access *Service Auth* policy or the Keychain client id/secret |
| Log: `HTTP 401` | Keychain `ingest-token` ≠ Worker `INGEST_TOKEN`: redo step 3's last two lines |
| Every `/api` call is `403` after login | `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` or `ALLOWED_EMAILS` secret |
