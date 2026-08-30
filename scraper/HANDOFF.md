# Handoff — Pine Hills FF scraper (updated 2026-08-29)

## Where we are
The private JSON API approach is **dead** (proven): the SPA envelope is pre-draft
zeros, and the v2 REST API is blocked in-session. We pivoted to a **rendered-page
capture** pipeline that WORKS end-to-end and produces real scored data for the wiki.

## Confirmed facts (evidence-backed, 2026-08-29)
- **JSON API is unusable.** The SPA `service.leagues."447010".teams.<id>` envelope
  (old `dump/2016-standings.api.11.json`) is **pre-draft zeros** (wins=0, pf=0,
  rank="") for every team. The v2 REST API (`fantasysports.yahoo.com/ws/fantasy/v2/...`)
  returns "Failed to fetch" / HTML error shells in-session (CORS / gated).
- **Rendered pages are the source.** Driving a logged-in Edge tab and reading the
  rendered `innerText` yields real scored data:
  - **Standings** (in-app "Standings" nav → `/{year}/f1/{league}?lhst=stand`) renders a
    table: `Rank | Team | W-L-T | PF | PA | Streak | Waiver | Moves` for all 12 teams.
    This is the COMPLETE record (rank, wins, losses, points_for, points_against).
  - **Draft Results** (`/draftresults`): `Round N / <pick>. <Player> → <Team>` for
    every pick (134–135 picks/season).
  - **Matchups** (`/matchup`, singular): header shows the viewed team's W-L-T + rank +
    manager (e.g. `Save Me / Naren / 7-7-0 | 4th`). Only the *viewed* (your) team —
    all-team W-L comes from the standings table above.
- **Direct-URL navigation 404s for matchups/scoreboard.** `/f1/{league}/matchups` and
  `/scoreboard` return "document not found" via `Page.navigate`. They ONLY render when
  reached by **clicking the in-app nav link** (SPA route). `capture_season.py` does this.
- **Seasons are 2018+**, each with a DISTINCT league id (from the Yahoo History tab).
  Current 2026 season = `447010`. No 2016/2017 exist for this league. League IDs:
  `2018=1578201 2019=369572 2020=698987 2021=760144 2022=703496 2023=21996
   2024=489811 2025=484479` (see `selectors.toml` `[league].season_ids`).

## What works (the live pipeline)
1. `scraper/run-edge.sh` — launch Edge on `127.0.0.1:9222` (profile `~/.phf-edge`,
   uBlock Origin Lite). Log in once; session persists.
2. `scraper/scripts/capture_season.py <edge> <year> <league> [outdir]` — CDP capture
   that clicks the in-app nav (Standings / Draft Results / Matchups) and saves
   `<year>-<league>-<view>.innerText.txt`. Ban-safe: no login, sequential, human waits.
3. `scraper/src/parse_rendered.rs` — pure-offline parser: standings table (rank/W-L/PF/PA),
   draft picks, matchups W-L header. Tested in `tests/rendered_parse.rs` (TDD, GREEN).
4. `scraper/src/extract.rs::from_dump_dir` + `phf-scraper --from-dump <dir>` — assembles
   `Season` from the innerText dumps and writes `raw/<year>.json` (canonical contract).
5. `scripts/generate.py` — consumes `raw/<year>.json` → `content/teams/*.md` wiki pages.
   **Verified live:** 2024 + 2025 team pages generated with real W-L/PF/PA.

## Reproduce (2024 + 2025 already captured)
```
cd scraper
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2025 484479
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2024 489811
cargo run -- --from-dump dump --seasons 2024,2025 --out raw
cp raw/2024.json raw/2025.json ../raw/
cd .. && python3 scripts/generate.py
```

## Known gaps / next
- **Rosters** not yet captured (the `/rosters` page is a week-dropdown; lower priority).
- **Owner/manager** for non-viewed teams comes only from the matchups header (the user's
  team). Other teams' owners are blank unless scraped per-team.
- **2018–2023** not yet captured — same `capture_season.py` flow with their league IDs.
- Browser capture is still Python (`capture_season.py`); `src/scrape.rs` keeps the
  chromiumoxide fetch path for the HTML-based `extract_*` functions (unused by the
  dump pipeline but kept for the live `--connect` path once matchups/rosters routing is
  solved). Prefer the `--from-dump` offline path for now.

## Environment
- Edge on `127.0.0.1:9222`, logged in, `.phf-edge` profile.
- `uv` for Python; `cargo` (edition 2024) for the Rust scraper.
- Repo `narenp12/pine-hills-wiki`, branch `main`.
