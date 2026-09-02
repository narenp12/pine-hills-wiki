# Handoff — Pine Hills FF scraper (updated 2026-08-29)

## Where we are
**The Yahoo v2 API works and is now the primary source.** (Updated 2026-09-01 —
this reverses the previous conclusion, see below.) The rendered-page capture
pipeline is retained, but only draft picks still come from it.

## RETRACTED: "the JSON API is dead" (2026-09-01)
The previous version of this document claimed the JSON API was dead "(proven)".
That was wrong, and both supporting tests were faulty:

1. **The envelope capture read a season that does not exist.** It used
   `/f1/447010/2016/standings`, but `447010` is the *current* season's league and
   this league has no 2016. Pre-draft zeros were the correct response for that
   page — not evidence about historical seasons.
2. **The v2 test used the wrong host.** v2 is served from a dedicated read-only
   host, `pub-api-ro.fantasysports.yahoo.com`, with `format=json_f`. Requesting it
   from the page's own origin 404s, which is what produced the "HTML error shells"
   reading. Fetching from the page's JS context with `credentials: 'include'`
   returns 200 JSON.

Confirmed working (140 payloads harvested across 2018-2025, 0 failures):
- `users;use_login=1/games;game_codes=nfl/leagues` — every league key
- `league/<key>/standings` — rank, W-L-T, PF, PA, playoff seed, **every** owner
- `league/<key>/scoreboard;week=N` — scores, `winner_team_key`, `is_playoffs`
- `league/<key>/teams/roster;week=N` — all teams' rosters in ONE request

## Confirmed facts (evidence-backed, 2026-08-29)
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

## ALL SEASONS CAPTURED (2026-08-29, this session)
All 8 seasons (2018–2025) are captured and built into the wiki. 78 team-seasons,
1170 draft picks, all verified internally consistent (`picks == teams * 15` for
every season, zero unresolved team names, zero all-zero records).

| Season | League ID | Teams | Picks |
|--------|-----------|-------|-------|
| 2018 | 1578201 | 6 | 90 |
| 2019 | 369572 | 8 | 120 |
| 2020 | 698987 | 10 | 150 |
| 2021 | 760144 | 10 | 150 |
| 2022 | 703496 | 10 | 150 |
| 2023 | 21996 | 10 | 150 |
| 2024 | 489811 | 12 | 180 |
| 2025 | 484479 | 12 | 180 |

Team count grew over time (6 → 8 → 10 → 12); that is real, not missing data.

### Five real data bugs found and fixed (TDD, each with a regression test)
1. **Rank dedupe dropped a whole team.** The standings table renders twice, and
   dedupe keyed on `rank`. Yahoo's 2020 table has TWO teams at rank 7
   (`Sharman’s Scorpions` + `Aryan's Amazing Team`), so a real team vanished
   (10 → 9). Now dedupes on team NAME. `team_key` was also `<league>-<rank>`,
   which collided for the same reason — now `<league>-<name>`.
2. **Draft picks ≥ 10 were dropped.** `strip_prefix(char::is_ascii_digit)` strips
   only ONE digit, so `"10.\tPlayer\tTeam"` left `"0."` and failed the `.` check.
   A 12-team league lost 45 of 180 picks. Now consumes all leading digits.
3. **Draft team names were truncated.** The draft page clips labels
   (`"Sharman’s ..."`, `"Jeremy's Nea..."`), so picks were attributed to names
   matching no team. `parse_draft_with_teams` resolves them by prefix against the
   standings names — including the 2022 case where the clip lands mid-codepoint
   and renders `U+FFFD` (`"Hill We Go\u{fffd}..."`).
4. **The "49ers" defense pick was silently dropped.** An `is_alphabetic()` guard
   on the player's first char rejected it (2024 round 8). Now only requires a
   non-empty player + team.
5. **Wiki standings tables were EMPTY.** `from_dump_dir` filled `teams.teams` but
   left `standings.teams` empty — and `generate.py` renders the Final Standings
   table from `standings.teams`. Every season page shipped an empty table despite
   the JSON holding full records. Now populated and sorted by rank. `generate.py`
   also showed the row POSITION as the rank; it now prints Yahoo's real rank
   (so 2020's two rank-7 teams both read 7).

### Test / repo hygiene fixed
- Tests read fixtures from gitignored `dump/`, so `cargo test` FAILED on a clean
  clone. Real captures are now committed under `scraper/tests/fixtures/` (44K).
- `.prettierignore` didn't exclude `scraper/target`, so `npm run check` scanned
  Rust build artifacts and reported 799 files (now 6, all pre-existing docs).
- `model_contract.rs` only checked a hand-built sample, which is why bug 5 slipped
  through; it now also exercises the real `from_dump_dir` path against a fixture.

## Verified state
- `cargo test`: 11/11 pass. `npm run test`: 163/163 pass. `npx quartz build`: clean.
- Rendered HTML confirmed: each season page has one standings row per team with
  real PF/PA, each draft page has `picks + 1` table rows.

## The v2 pipeline (current, 2026-09-01)
```
cd scraper
./run-edge.sh                                    # log in once, keep the window open
uv run --with websocket-client python3 scripts/harvest_v2.py http://127.0.0.1:9222 dump/v2
cargo run -- --from-v2 dump/v2 --seasons 2018-2025 --out ../raw
cd .. && python3 scripts/generate.py
```
`harvest_v2.py` is resumable — any file already on disk that parses is skipped, so
a re-run only fetches what is missing. It issues two calls per week (scoreboard +
roster); a cold run over all eight seasons is ~262 requests and roughly 25
minutes at the 5s spacing. Roster payloads are ~1.8 MB each, so `dump/v2` grows
to a few hundred MB — it is gitignored.

`--from-v2` MERGES: it replaces standings / matchups / champions / weeks and
preserves everything else in `raw/<year>.json`, notably the draft picks, which
the v2 harvest does not fetch.

**`raw/*.json` is committed** (~3.5 MB across eight seasons) and is what the
generator reads. Keep it that way: `--from-v2` MERGES onto the file already on
disk, so rebuilding where `raw/` is empty merges onto `{}` and destroys every
draft pick, which the v2 harvest cannot re-fetch. The `picks_before ==
picks_after` guard does not catch that, because 0 equals 0.

Note that the working copy's root `.gitignore` lists both `raw/` and itself, and
is untracked — it never reaches a clone, so the ignore rule is local to whoever
created it. If you reinstate it locally, remember that already-tracked files stay
tracked; the risk is only ever a fresh checkout that skips copying `raw/` in.

## Gaps CLOSED by the v2 pipeline
- **Every team's owner** — was blank for all but your own team, now populated from
  `managers[].nickname` for all 78 team-seasons.
- **Weekly matchup scores** — all 131 weeks, in `matchups`, with `is_playoffs`.
- **Champion / runner-up / top seed / toilet winner** — derived from Yahoo's final
  playoff-adjusted rank; 7 of 8 seasons previously rendered `_TBD_`.
- **Real playoff seeds** — the generator was printing the standings row position
  as the seed, which is wrong (2025's champion entered as the 5 seed).
- **Weekly rosters with player points** — every team's lineup for all 131 weeks,
  bench and IR rows included, in `weeks[wk].rosters` as
  `{name, position, slot, points}`. One nested call per week
  (`teams/roster;week=N/players/stats;type=week;week=N`) covers all 12 teams;
  the shape is confirmed and recorded in `scripts/probe_rosters.py`. This fills
  the season-page roster blocks, backfills the draft-pick positions that were
  blank for all eight seasons, and supplies both the player record book and the
  computed draft-value awards.
- **The real playoff bracket.** Was a fixed 4-team seed skeleton that never
  happened; now derived per season from the captured weekly matchups, with real
  scores, who beat whom, and first-round byes. All 8 seasons verified to parse
  through `@mermaid-js/mermaid-cli`.

### How the bracket is derived
Yahoo gives no reliable flag for "this game is on the path to the title":
`is_consolation` is 0 even for games that plainly are consolation (2018 week 16
has two games, both `is_playoffs=1, is_consolation=0`), and both brackets run in
the same weeks with the same matchup count. So `derive_bracket` starts from the
one game it can identify with certainty — the last playoff week's game containing
the champion — and walks BACKWARDS, keeping in each earlier week only the games
involving teams already known to be in the bracket. Byes need no special case: a
team with one simply appears for the first time in a later round.

## Known gaps (NOT faked)
- **`PLAYOFF_SEEDS = 4` is still hardcoded** in `generate.py` and is wrong for
  this league (2025 ran an 8-team playoff). It no longer affects the bracket,
  which uses real data, but it still drives the "top N qualify" copy on
  `playoffs.md` and the `made_playoffs` flag on team pages.
- `content/seasons/2016-season.md` is pre-existing placeholder scaffolding
  (committed in `fbfaf2f`) for a season this league never had — it contains
  "Example FC" dummy data and should be deleted or rewritten.
- Browser capture is still Python (`capture_season.py`); `src/scrape.rs` keeps the
  chromiumoxide fetch path for the HTML-based `extract_*` functions (unused by the
  dump pipeline but kept for the live `--connect` path once matchups/rosters routing is
  solved). Prefer the `--from-dump` offline path for now.

## Reproduce the whole history
```
cd scraper
# one season at a time, sequential (anti-ban); ~35s each
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2018 1578201
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2019 369572
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2020 698987
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2021 760144
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2022 703496
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2023 21996
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2024 489811
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2025 484479
cargo run -- --from-dump dump --seasons 2018-2025 --out raw
cp raw/20*.json ../raw/
cd .. && python3 scripts/generate.py && npx quartz build
```

## Environment
- Edge on `127.0.0.1:9222`, logged in, `.phf-edge` profile.
- `uv` for Python; `cargo` (edition 2024) for the Rust scraper.
- Repo `narenp12/pine-hills-wiki`, branch `main`.
