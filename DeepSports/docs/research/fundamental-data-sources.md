# Fundamental data sources: what to add beyond box scores (research, 2026-11-03)

**Question from the owner:** "Data is key; should we look into fundamental sources such as
sentiment on news, on top of the technical data?"

**Short answer:** Yes to *fundamental information*, no to *sentiment* as a general feature,
at least for now. The NBA betting market already prices most public news by the close. The
information that actually moves NBA results is **player availability** (who plays and how
much), then **schedule fatigue** (rest, back-to-backs, travel). Both are mostly structured,
free, and cheap to collect. "Sentiment" (the tone of news or social posts) has weak evidence of
adding anything beyond the closing line, and the social sources that are fast enough to matter
are now paid or gated. If we use language models on text at all, it should be to **extract
facts** ("Player X ruled out", "Player Y on a minutes limit") with timestamps. Scoring tone is
not worth it.

Status markers: **[confirmed]** = checked on a primary page or paper record on 2026-11-03;
**[secondary]** = from reputable secondary coverage; **[unconfirmed]** = plausible but not verified.

---

## 1. What moves NBA outcomes beyond box scores and schedules

### Benchmark reality check
Our target is to beat or match the **closing line**. The best evidence on NBA availability
news is Dare, Dennis and Paul (2015): **opening** lines have significant errors in games with
an absent player, but **the closing line offers no profitable strategy**. By the close, the
bias is gone, because books absorb the news or bettors move the line [confirmed, abstract].
This is the central fact for the rest of this report. Public information helps us **build a
model that matches the close**. Beating the close requires being **earlier** than the market,
not just better informed in general.

| Factor | How predictive | How fast the market prices it | Free and legitimate source | Notes |
|---|---|---|---|---|
| **Injuries / availability** (incl. load management, late scratches) | **Highest.** A top player can be worth several points on the spread (industry rule of thumb: up to 4–6 pts for a top-5 player [secondary, Action Network]). Our own box-score data can estimate player impact (minutes × on/off or a simple plus-minus model). | Within minutes for stars; lines move on official listings and beat-writer posts. Fully priced by close (Dare et al. 2015). | **Official NBA injury report** (league PDFs, [confirmed], see §2). ESPN `summary` `injuries` block (already in our raw zone). | Biggest value is **point-in-time history**: knowing who was listed Out/Questionable *before* tip. That makes our backtests honest and lets the model reproduce the close. |
| **Confirmed starting lineups** | High when they reveal a surprise (star rests, rookie starts). Mostly redundant with the injury report otherwise. | Announced ~30 min before tip (common practice [unconfirmed]); the market reacts within minutes. | Post-game: ESPN box score `starter` flag (already have). Pregame: no free official feed found. Team social accounts post them. Aggregators (RotoWire etc.) have terms that likely bar scraping [unconfirmed]. | Use post-game starters for **features about past games** (lineup continuity), not for pregame prediction. |
| **Rest, back-to-backs, travel** | Real and measurable. Ashman, Bowman and Lambrinos (2010, *J. Sports Econ.*, 19 seasons): home teams on the 2nd night of a back-to-back vs a rested visitor **underperformed against the spread**, worse after eastward travel [confirmed, abstract]. ESPN "Schedule Alert" analysis said markets don't adjust enough [secondary]. | Partly priced. The 2010 edge may have shrunk since (the market learns, and the league cut back-to-backs). Must re-test on recent seasons. | **Free, already in hand:** our schedule + venue table. Travel distance and time zones come from arena coordinates (a one-time static table of 30 arenas). | Cheapest high-value add. Pure feature engineering, no new source. |
| **Roster changes / trades** | Moderate; short-lived (team ratings lag for ~10–20 games after a big trade). | News is instant; *rating* adjustments by models and bettors are slower. | ESPN transactions / team roster endpoints (same unofficial API family [unconfirmed endpoint shape]). Player-level box scores already reveal who plays for whom. | Handle by computing **team strength from the players who are actually available**, not from the team's season record. This handles injuries too. |
| **Coaching changes** | Small and rare (a few per season). | Instant news. | ESPN news; Wikipedia. | Too rare to model; a manual flag is enough. |
| **Referee assignments** | Plausible effect on **totals** (crew foul rate → free throws, pace). Academic work shows crew composition affects foul counts [secondary, Price/Wolfers line of research; height-bias study]. No rigorous evidence of an edge vs the closing total [secondary: only vendor and newsletter backtests]. | The NBA publishes assignments at 9 a.m. ET on game day [unconfirmed timing]; sharp totals bettors use them. | official.nba.com referee assignments page [unconfirmed terms]. Post-game: ESPN summary lists officials (`gameInfo.officials` [unconfirmed field]). | Worth a cheap backtest for **totals only**, using officials from the already-cached summaries. |
| **Motivation (tanking, seeding, rest at end of season)** | Real in late season. Soebbing and Humphreys (2010): **spreads move 1–4 points** for games involving likely tanking teams, so the market *believes* in tanking. Choi (Penn) found the public and the odds **overestimate** tanking [secondary]. | Priced (maybe over-priced). | Derived: standings, games back, elimination flags, lottery position, all computable from our own results. | Medium value, low cost; a late-season feature. Note: the 2025-26 lottery and anti-tanking rule changes may change this [unconfirmed]. |

**Takeaway:** availability and fatigue are where the signal is. Both are **structured data**,
not text, and their main value is letting our model **reproduce the closing line from
first principles**. Once it can do that, any residual edge can be measured honestly.

---

## 2. News and social sentiment

### What the evidence says
- **Soccer, in-play (best study):** Brown, Rambaccussing, Reade and Rossi (2018, *Economic
  Inquiry*): 13.8M tweets vs Betfair prices across 372 EPL matches. Tweet tone held information
  not in prices, **mainly right after goals and red cards** (in-play, seconds-scale). Crucially,
  **tweets were not informative before goals**, so social media did not break news faster than
  the market [confirmed, paper record + press release]. That is an in-play result; we predict
  pregame.
- **NFL, pregame:** Sinha, Dyer, Gimpel and Smith (2013, CMU, arXiv 1310.6998): Twitter
  features (mainly the **rate of change in tweet volume**, not sentiment) hit ~55% against the
  spread on a small 2010–2012 sample, vs a 52.4–53% break-even. Twitter **did not help** for
  winners or totals [confirmed, arXiv + CMU release]. Small sample, old market, never traded.
- **NFL:** Schumaker et al., "Prediction from regional angst" (*Decision Support Systems*):
  sentiment-based strategies showed profits in a backtest [secondary]. Small sample, no
  replication found.
- **NBA:** The only direct work found is a master's thesis (NCU Taiwan) where sentiment raised
  winner accuracy from ~67.6% to ~69.4%, **without betting odds as a baseline** [secondary].
  That is not evidence of value over the line. No rigorous NBA study of sentiment vs closing
  lines was found.
- **Market efficiency on news:** Dare et al. (2015) above: player-absence news is fully priced
  by the close.

**Verdict:** No credible evidence that pregame news or social *sentiment* beats the NBA closing
line. The plausible mechanism is **speed**: an availability fact reaches us before the line
moves. That is an information-latency game against professional bettors and book traders who
watch the same feeds in real time. For a polite, rate-limited personal pipeline, it is a game we
would mostly lose.

### Sources: availability, terms, cost

| Source | Access & cost | Terms / legitimacy | Speed | Verdict |
|---|---|---|---|---|
| **Official NBA injury report** (`official.nba.com/nba-injury-report-2025-26-season/`, PDFs at `ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf`) | Free, no key. Page lists reports at **15-minute intervals** through the day; "updated on a continual basis" [confirmed]. Team deadlines: 5 p.m. local the day before (1 p.m. game day for the 2nd game of a back-to-back), and a game-day update between 11 a.m. and 1 p.m. local [confirmed]. Rules were tightened in Dec 2025 because of betting integrity [secondary, AP]. | NBA.com terms say no portion "may be duplicated, redistributed or manipulated" [confirmed]. Personal, non-redistributed research use looks reasonable, but read the full ToS before building [unconfirmed]. Fetch politely (a few PDFs per day, not every 15 min for every day). | Official and authoritative; usually *slightly behind* beat-writer posts. | **Add it.** Parse PDFs (pure parser + saved fixtures). Historical PDFs back to ~2021 appear to be at predictable URLs, which would give point-in-time history [unconfirmed coverage]. |
| **ESPN `summary` injuries** | Already in our raw zone, free. | Same unofficial-API status as today. | — | **Parse it now**, but check *when* the snapshot was taken. Summaries cached **after** the game may show post-game injury status, not pregame (leakage risk) [unconfirmed; needs checking against a fixture]. |
| **ESPN news API** (`site.api.espn.com/apis/site/v2/sports/basketball/nba/news`, also `?team=`) | Free, unauthenticated; ~10 items, no pagination or date filter [secondary]. | Unofficial, same posture as our other ESPN use. | Minutes to hours. | Low priority. Useful only as a fact-extraction input. |
| **RSS** (team sites, beat writers, ESPN/CBS/Yahoo feeds) | Free. | RSS is published to be consumed; respect the site's ToS and robots.txt, and keep only headlines and links, not full text. | Minutes. Beat writers are fast on X, slower on their sites. | Optional later, for fact extraction. |
| **Reddit API** | Free tier was 100 QPM per OAuth client, non-commercial [secondary, 2023 announcement]. **Since 11 Nov 2025, new OAuth tokens need manual approval** (Responsible Builder Policy); self-service is closed, and some applicants report rejections [secondary]. Commercial use is priced by negotiation (reports of ~$0.24 per 1k calls) [secondary]. | Must apply and be approved; the official help page returned 403 to our fetch, so terms were not re-read [unconfirmed]. | r/nba posts injury news within minutes, but they are reposts of reporters. | **Skip.** Gated, slow to get access, and only a derivative of reporters' posts. |
| **X (Twitter) API** | **No free tier.** Pay-per-use: **$0.005 per post read**, $0.010 per user read, capped at 3M post reads/month [confirmed, docs.x.com]. The legacy $200/mo Basic tier is closed to new sign-ups [secondary]. | Legitimate if paid. | **Fastest** source for injury and lineup news (reporters post there first). | Cheap at small scale: following ~50 accounts at a few hundred posts a day is ~$1–3/month. This is the **only** source that could plausibly beat the line, and the edge is still doubtful. Revisit only after items 1–4 below. |
| **Bluesky (AT Protocol)** | Free public AppView API (`public.api.bsky.app`, unauthenticated, cached) and Jetstream/firehose; "generous" rate limits [secondary; the official rate-limit page did not load for us]. | Open protocol; legitimate. | Fast, but few NBA insiders post there; coverage is the problem. | **Skip for now**; recheck if insiders move there. |
| **GDELT** (DOC 2.0 API) | Free, no key; article lists cover roughly the last 3 months, timelines back to 2017 [secondary, GDELT blog]. | Datasets free for any use with citation and link [confirmed, gdeltproject.org]. | 15-minute updates, but coverage of mainstream news is broad and shallow. | **Skip.** Too coarse for player-level facts. Fine for a research curiosity. |
| **NewsAPI.org** | Free Developer plan: 100 requests/day, **24-hour article delay**, development use only; production (including internal) needs Business at **$449/mo** [confirmed, pricing page]. | Free tier forbids our use case in production. | 24 h late on free. | **Skip.** |

### Scoring text: method and cost
Use an LLM for **structured extraction**, not tone. Example output:
`{player, team, status: out|doubtful|questionable|probable|available, reason, minutes_limit, source_url, published_at}`.
Classical sentiment models (VADER, FinBERT) measure tone, which is the wrong target. An injury
note like "expected to play through soreness" has negative tone but is good news.

Cost at our scale is **not a constraint** (Anthropic API list prices, cached 2026-10-06):

| Model | $/1M input | $/1M output | Assumed daily load | ≈ cost/day | ≈ cost/season (~170 days) |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | 0.10 | 0.50 | 15 games × 20 items × 600 tokens in, 80 out ≈ 180k in / 24k out | ~$0.03 | ~$5 |
| Claude Sonnet 5.5 | 2.00 | 10.00 | same | ~$0.60 | ~$100 |

The Batch API halves this for non-urgent backfills. Backfilling one season of historical news
costs similar amounts. **The real constraints are access, timestamps, and evaluation, not money:**
every extracted fact needs a trustworthy `published_at` so the backtest uses only what was known
before tip-off.

---

## 3. Recommendation (prioritized)

| # | Add | Effort | Expected value | Why |
|---|---|---|---|---|
| 1 | **Rest/fatigue features** from data we already have: days of rest, back-to-back flags (incl. 3-in-4), road-trip length, travel distance and time zones crossed (static arena-coordinate table). | **S** | Medium-high | Evidence-backed (Ashman et al. 2010), free, no new source, no leakage risk. Re-test the edge on 2016–2026 before trusting it. |
| 2 | **Player availability → team strength.** Build a player impact rating from our box scores, then compute "strength of the players who actually played" (historical) and "who is expected to play" (pregame). | **M** | **High** | The biggest driver of margin and totals. Lets the model reproduce the close and explains most line moves. |
| 3 | **Official NBA injury report ingestion** (PDF parser, polite schedule: e.g. the 1 p.m. ET and ~1 h-before-first-tip reports, plus a one-time historical backfill if the archive exists). Also parse ESPN `summary` injuries after verifying snapshot timing. | **M** | **High** | The pregame input for item 2 and the point-in-time record that makes backtests honest. Check NBA.com ToS first. |
| 4 | **Late-season motivation features** (games back, elimination, lottery position, clinched seed) derived from our own standings. | **S** | Low-medium | Cheap; the market already prices it (maybe over-prices it). Season-phase specific. |
| 5 | **Referee crew → totals backtest** using officials from cached summaries. | **S–M** | Low-medium (unproven) | Cheap to test because the data is already cached; keep it only if it beats the closing total out-of-sample. |
| 6 | **LLM fact extraction from news** (ESPN news + a few RSS feeds) into `player_status_events` with timestamps. | **M** | Low-medium | Only after 2–3 exist. Fills gaps between official reports (minutes limits, "will play"). |
| 7 | **X API watchlist of NBA insiders** + extraction, aimed at *reacting before the line moves*. | **M–L** (plus ~$1–5/mo) | Speculative | The only route to "earlier than the market". Requires live line snapshots to prove any edge. |

**Skip for now:** general news or social **sentiment** scores, Reddit (gated), NewsAPI
(free tier forbids production, $449/mo otherwise), GDELT (too coarse), Bluesky (insiders aren't
there), coaching-change modelling (too rare).

**What would make "sentiment" worthwhile:** (a) the model already reproduces the closing line
using availability + fatigue; (b) we store **timestamped line snapshots** (open → close), so we
can measure whether a news item arrived *before* the line moved; (c) the text pipeline extracts
**availability facts**, not tone, from a source that is faster than the official report (in
practice, reporters on X). If (a)–(c) hold and an out-of-sample test shows the extracted facts
predict *closing-line movement* or beat the close, it earns its place. Otherwise the money and
effort are better spent on items 1–3.

Process notes for whoever builds these (per CLAUDE.md): new sources and tables need
`store.py` + `DATA_MODEL.md` + tests together, saved real fixtures for the PDF/news parsers, a
`DATA_SOURCES.md` entry with terms notes, a diagram update, and a `DECISIONS.md` entry.

---

## Sources
Papers and research
- Dare, Dennis, Paul (2015), "Player absence and betting lines in the NBA", *Finance Research Letters* 13:130–136 — https://ideas.repec.org/a/eee/finlet/v13y2015icp130-136.html
- Ashman, Bowman, Lambrinos (2010), "The Role of Fatigue in NBA Wagering Markets", *J. Sports Economics* 11(6) — https://ideas.repec.org/a/sae/jospec/v11y2010i6p602-613.html
- Brown, Rambaccussing, Reade, Rossi (2018), "Forecasting with social media: Evidence from tweets on soccer matches", *Economic Inquiry* 56(3) — https://econpapers.repec.org/RePEc:bla:ecinqu:v:56:y:2018:i:3:p:1748-1763 ; https://ueaeprints.uea.ac.uk/id/eprint/64244/ ; https://www.uea.ac.uk/about/-/tweets-can-help-predict-the-outcome-of-football-matches
- Sinha, Dyer, Gimpel, Smith (2013), "Predicting the NFL using Twitter" — https://arxiv.org/abs/1310.6998 ; https://www.cmu.edu/news/stories/archives/2013/september/sept12_twitternflgames.html
- Schumaker et al., "Prediction from regional angst" (NFL Twitter sentiment) — https://robschumaker.com/publications/DAFC%20-%20Using%20Financial%20Analysis%20Techniques%20on%20Twitter%20Sentiment%20to%20Improve%20NFL%20Predictions.pdf
- Chung, "NBA Game Prediction based on Team-centric Data, Player Salary, and Social Media Sentiment" (thesis) — https://ir.lib.ncu.edu.tw/handle/987654321/85929
- Soebbing & Humphreys (2010), tanking and NBA betting markets — https://sites.ualberta.ca/~econwps/2010/wp2010-13.pdf ; https://ideas.repec.org/p/ris/albaec/2010_013.html
- Choi, "Trust the Process: Tanking in the NBA" — https://repository.upenn.edu/handle/20.500.14332/49228
- "Learning, Price Formation and the Early Season Bias in the NBA" (totals bias) — https://dc.etsu.edu/etsu-works/17780
- Referee impact metric (2026, arXiv) — https://arxiv.org/abs/2605.17845
- ESPN Schedule Alert analysis — https://africa.espn.com/nba/story/_/id/25117649/nba-schedule-alert-games-your-team-lose-2018-19

Official pages and terms
- NBA injury report 2025-26 (cadence, deadlines, terms notice) — https://official.nba.com/nba-injury-report-2025-26-season/
- Example injury report PDF — https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-02-18_10_15AM.pdf
- AP coverage of the Dec 2025 injury-reporting changes — https://abcnews.go.com/Sports/wireStory/nba-tweaks-injury-reporting-rules-prop-betting-128577446
- X API pricing — https://docs.x.com/x-api/getting-started/pricing
- NewsAPI pricing — https://newsapi.org/pricing
- GDELT terms (about page) — https://www.gdeltproject.org/about.html ; DOC 2.0 API — https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ ; https://blog.gdeltproject.org/doc-2-0-updates-1-5-year-searching-and-updated-mobile-interface/
- Bluesky Jetstream — https://docs.bsky.app/blog/jetstream
- Reddit Responsible Builder Policy announcement (mirror of r/redditdev, Nov 2025) — https://r.datuan.dev/r/redditdev/comments/1oug31u/introducing_the_responsible_builder_policy_new/noh6fun ; Reddit Data API wiki (403 to our fetch) — https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki

Secondary / industry (treat as indicative)
- Action Network, injuries and line movement — https://www.actionnetwork.com/education/how-injuries-affect-betting-lines-a-guide-to-market-movement
- Reddit API pricing overviews — https://www.techloy.com/reddit-api-pricing-in-2026-complete-guide-for-developers-and-businesses/ ; https://octolens.com/blog/reddit-api-pricing
- X API pay-per-use coverage — https://gigazine.net/gsc_news/en/20260209-x-api-pay-per-use
- ESPN hidden API guide (news endpoint) — https://zuplo.com/blog/2024/10/01/espn-hidden-api-guide
- BettingPros referee report — https://www.bettingpros.com/nba/referee-report/
- Anthropic model pricing: claude-api skill model table (cached 2026-10-06); live page https://platform.claude.com/docs/en/about-claude/pricing
