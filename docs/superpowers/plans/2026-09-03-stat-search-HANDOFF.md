# Stat Search — handoff

Updated 2026-09-03, stopped for context limits after Task 6. Written for a fresh
model continuing the `superpowers-extended-cc:subagent-driven-development` loop.

## State

Branch **`feat/stat-search`**, branched from `main` at `e4b0659`. Working tree
clean, everything committed. Full suite **324 passed**.

Tasks 1-6 done and reviewed. **Tasks 7-10 remain.**

```
b3545ef chore: mark Stat Search Task 6 complete
67f3902 feat: build the Stat Search page into the site
fa424f3 fix: write the query tables only after all four validate
e847e05 test: hold Stat Search and the Records page to the same numbers
0984683 feat: emit the Stat Search Parquet tables and schema
5230866 feat: build the Stat Search team_seasons and draft tables
ee96d51 feat: build the Stat Search player_weeks table
edbf396 refactor: project matchup_rows over build_game_log
```

`d58f250` and `0cad9d1` (spec, plan) are also on `main`. Everything else is
branch-only.

What works today: `node zensical/build.mjs` emits four Parquet tables plus
`schema.json` and a Stat Search page into `zensical/site/query/`, and the tab is
in the nav. 137 KB of Parquet, 13.8% of the 1 MB budget.

## Documents

- Spec: `docs/superpowers/specs/2026-09-03-stat-search-duckdb-design.md` — **the
  schemas in here are authoritative over the task bodies in the plan**
- Plan: `docs/superpowers/plans/2026-09-03-stat-search.md` — ten tasks. Carries a
  correction banner; the Task 1-2 code in it is superseded, see below
- Tracker: `docs/superpowers/plans/2026-09-03-stat-search.md.tasks.json` — tasks
  0-5 `completed`, 6-9 `pending`

Native task tools (`TaskCreate`/`TaskGet`/`TaskUpdate`) were unavailable in this
session; the tracker was maintained by writing that JSON directly. Check whether
you have them before assuming.

## Resume here: Task 7

Task 7 was dispatched and killed before it wrote any file. Nothing partial.

**Task 7 — the AST compiler.** Two new files, `zensical/docs/javascripts/query-compile.js`
and `tests/js/query-compile.test.mjs`, plus adding `node --test tests/js/` to the
test step in `.github/workflows/deploy.yml`. Full task body in the plan; the
authoritative contract is the spec's "The AST" and "The compiler" sections.

The security contract is the point of that task: every field, table and aggregate
validated against `schema.json` before any SQL is built; identifiers quoted and
drawn only from the schema; every literal a prepared-statement parameter; limit
clamped to 5000. The module must import nothing at all — that is what lets
`node:test` load it and what makes the contract checkable.

Do NOT implement window functions there (`rank_in_season`, `streak_len`,
`rolling_avg_3`). The spec lists them for v1 but they need a verb vocabulary that
does not exist until Task 10.

Then Tasks 8 (DuckDB-WASM engine), 9 (presets + verb UI), 10 (aggregation verbs +
shareable links).

## The loop that has been running

Per task: implementer subagent → review subagent → fold any findings into the
next task's brief rather than a separate cycle → mark the tracker → commit.
Tasks 1-3 used separate spec and quality reviewers; from Task 4 the two were
combined into one reviewer, which worked as well and costs half as much.

Two habits that have repeatedly paid off and are worth keeping:

1. **Verify a subagent's headline claim yourself** before acting on it. Several
   review findings were wrong, and one agent correctly overturned a reviewer with
   evidence. Equally, several were right about bugs that had already passed a
   review.
2. **Require mutation-checking of every new assertion.** This run produced three
   tautological tests that looked green — two slug tests asserting
   `slug(x) == slug(x)`, and a vacuous `assert schema`. Ask each implementer to
   break the thing the test claims to catch and confirm the test fails.

## Traps — carry these forward

1. **Builders project over `generate.py`'s logs; they do not re-derive rows.**
   `build_game_log` (`generate.py:712`) and `build_player_log` (`:766`), both
   phase-tagged via `season_phases` (`:699`). Tasks 1 and 2 were originally
   written as hand-rolled loops and diverged on `won`, `tied`, `margin`, `round`,
   and — for player weeks — dropped `phase` entirely. Before writing any loop
   over `raw/`, search `generate.py` for an existing equivalent. For Task 3 no
   equivalent existed and loops were correct; the point is to look, not to assume
   either way.

2. **`load_league()` in `scripts/build_query_db.py` must stay in step with
   `generate.main()`'s normalization passes** (`generate.py:4729-4735`).
   `load_raw()` alone is not enough: `apply_player_aliases` and
   `apply_bible_positions` run in `main()`, and skipping the former gave 11 draft
   rows a dead `player_slug` (`aaron-jones` against a page at `aaron-jones-sr`).

3. **The owner map is `build_owner_map(bible, seasons)`, not
   `get_owners(bible)`.** `bible["owners"]` is a one-entry team-to-manager map.
   The wrong one shipped in Task 1 and survived two reviews, because every test
   asserted owners were non-empty, never that they were correct: 26 distinct
   owners for a 16-person league. Now pinned by a test.

4. **`zensical/transform.py` only copied `*.md` until Task 6.** `copy_assets`
   now byte-copies non-Markdown stage files, deliberately with no pruning
   counterpart — `zensical/docs` also holds hand-authored skin
   (`stylesheets`, `javascripts`, `assets/images`) that was never in the stage
   tree, so pruning would delete it.

5. **Row-count constants are year-coupled.** `raw/2026.json` is committed but
   unplayed: 150 draft picks, no games, no rosters. `EXPECTED_MATCHUP_ROWS`
   (1230), `EXPECTED_PLAYER_WEEK_ROWS` (19881) and friends rise deliberately when
   2026 is captured.

6. **Tasks 8-10 close on browser checks CI cannot run.** Serve over HTTP
   (`uv run python -m http.server 8000 --directory zensical/site`) — `file://`
   fails, module imports and Parquet fetches need an origin. Closing that gap
   properly means a Playwright suite, which is its own plan.

## Pinned decisions — do not re-open

- dbplyr-style verb builder. Users never type SQL; a "Show query" panel shows the
  compiled SQL read-only.
- Always DuckDB, one execution path, no JS fallback engine. ~7 MB first load on
  that tab, lazy and cached, accepted deliberately.
- `@duckdb/duckdb-wasm` pinned to exactly **1.32.0**, `eh` bundle. `latest` points
  at a `-dev` prerelease; never follow it. The threaded `coi` bundle is
  impossible — it needs cross-origin isolation headers GitHub Pages cannot set.
- All four datasets in v1. Presets plus an editable verb stack.

## Deferred, recorded not dropped

- Named window functions (`rank_in_season`, `streak_len`, `rolling_avg_3`) — need
  the verb vocabulary from Task 10. Add as Task 11.
- Copy-as-CSV in the results table — ~10 lines on `renderTable`, ride along with
  Task 11.

## Two things for the repo owner, outside this feature

1. **608 tracked files under `zensical/docs` are stale.** `scripts/generate.py`
   last changed in `e4b0659` ("a career record book for players") but the docs
   were last regenerated at `d32bb1b`, the commit before. Verified by rebuilding
   and diffing. Merging this branch triggers a deploy that publishes 608 files of
   never-reviewed rendered output. Regenerate and commit them as their own change
   first. **This predates Stat Search and is not caused by it.**

2. **`sahil` renders lowercase** while the other 15 owners are capitalized. The
   raw standings spell it that way in 2019-2020 and nowhere else, and
   `raw/bible.yaml` has no `Sahil:` entry. Adding `Sahil: [sahil]` to
   `owner_aliases` fixes it; no code change would. Affects the wiki generally,
   not just Stat Search.
