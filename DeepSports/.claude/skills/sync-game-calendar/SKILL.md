---
name: sync-game-calendar
description: Refresh NBA + college basketball data and sync upcoming games for followed teams to the user's Google Calendar (create, update, or remove events). Use when the user asks to sync or update game notifications or the game calendar, or on a scheduled run.
---

# Sync upcoming games to Google Calendar

Goal: every upcoming game for the followed teams has exactly one Google Calendar event with
correct time, matchup, TV, and the latest line, so the user is notified before tip-off.

## Prefetched mode (scheduled runs)
If invoked as `/sync-game-calendar prefetched <dir>`, the scheduled script has already refreshed the
data and exported the games. **Don't run any `deepsports` command** (the headless sandbox can't open
the warehouse on the external drive and the command hangs). Skip steps 1 and 2 and use:
- `<dir>/upcoming.json`: the output of step 2
- `<dir>/upcoming-30d-<league>.json`: the step 3.3 lookup (`--all --days 30`) per league; if a
  file is missing, leave unmatched events of that league alone instead of deleting them.
Read `config/calendar.toml` as usual.

## 1. Refresh data
```bash
uv run deepsports update
uv run deepsports update --league ncaab
```
If this exits non-zero, note the errors but continue: the upcoming list may still be usable.
If it fails with a DuckDB lock error, another job is running; wait for it and retry once.

## 2. Get the games to sync
```bash
uv run deepsports upcoming --league all --json
```
This applies `config/calendar.toml`: top-level `teams` is the NBA follow list, `[ncaab] teams` is college
(currently `NEV`, the Nevada Wolf Pack), plus `days_ahead`. Read that file too for
`calendar_id` and `reminder_minutes`.
- If a league's follow list is empty, skip that league; never bulk-create every game unless the
  user explicitly asked for that.
- Each game includes `league` (`nba` | `ncaab`).
- Each game includes `calendar_key`, `title`, `start_local`, `end_local`, `venue`,
  `venue_city`, `broadcasts`, `odds_details`, `over_under`, `home_name`, `away_name`.
- Each game includes `prediction`: null, or `{p_home_win, pred_home_margin, pred_total,
  favorite_abbr, favorite_prob, model_version, ...}` made before tip-off: NBA v1.1, and college
  `ncaab-v1` (only once both teams have played ≥5 games, so early-season college games are often null).
  Example lines: `Prediction: LAL 68% to win, by ~5 (model v1.1)`, `Prediction: NEV 74% to win, by ~8 (college model v1)`
  (write `college model v1` for `ncaab-v1`). The model does not beat the
  betting market, so the line is context, not betting advice.

## 3. Reconcile with the calendar
Load the Google Calendar tools with ToolSearch (`google calendar`) if they aren't loaded.
The `calendar_key` (`deepsports:<league>:<espn_game_id>`, e.g. `deepsports:nba:401909924`,
`deepsports:ncaab:401...`) is the identity of an event. Always
put it on its own line in the event description, and find existing events by searching for it.

Tool details (verified 2026-11-03):
- Find existing: `list_events` with `fullText: "deepsports"`, `startTime`/`endTime` as local
  times **without** an offset (e.g. `2026-11-03T00:00:00`), `pageSize: 100`. The calendar is
  in America/Los_Angeles, the same as `DEEPSPORTS_TZ`.
- Create: `create_event` with `startTime`/`endTime` = `start_local`/`end_local` with the offset removed
  (first 19 chars), `availability: AVAILABILITY_FREE` (games shouldn't block the schedule), and
  `overrideReminders: [{method: popup, minutes: reminder_minutes}]`.
- Update/delete with the event `id` from `list_events`.

1. List or search the calendar's events in the sync window (now through `days_ahead`) and
   collect the ones whose description contains `deepsports:` and group them by league from the key.
2. For each upcoming game:
   - **Missing:** create the event.
   - **Exists, but time/title/TV/line/description format differ:** update it (e.g. add the app link to older events).
   - **Exists and matches:** leave it alone.
3. An event in the window whose key is no longer in the upcoming list (postponed,
   rescheduled out of the window, or team unfollowed): check
   `uv run deepsports upcoming --league <that league> --all --days 30 --json`. If the game is still on but
   rescheduled, update the time; otherwise delete the event.
4. Never touch events that lack a `deepsports:` key.

Event format:
- Title: `title` (e.g. `🏀 LAL @ SAC`; college titles come from the CLI too, `vs` at neutral sites)
- Start/end: `start_local` / `end_local` (these include the UTC offset)
- Location: `venue, venue_city`
- Reminder: popup `reminder_minutes` before start
- Description:
  ```
  {away_name} at {home_name}
  TV: {broadcasts or "local / League Pass"}
  Line: {odds_details}, O/U {over_under}   (omit if no odds yet)
  Prediction: {favorite_abbr} {favorite_prob as %} to win, by ~{|pred_home_margin| rounded} (model {model_version})   (omit if `prediction` is null)
  Live score & box score: http://172.16.0.61:8787/#/game/{game_id}?league={league}   (league = nba or ncaab)

  {calendar_key}
  ```

## 4. Report
End with one short summary: created / updated / deleted / unchanged counts and the next
game. The global Stop hook sends that summary to Discord, so keep it readable on a phone.
