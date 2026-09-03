# Stat Search — handoff

Stopped 2026-09-03 for context limits, mid-Task-1 review.

## Where things stand

Branch: **`feat/stat-search`** (branched from `main` at `e4b0659`). Working tree clean, all work committed.

```
13a3464  test: assert the matchups row schema explicitly
76738f1  feat: build the Stat Search matchups table
0cad9d1  docs: plan the Stat Search implementation
d58f250  docs: spec the Stat Search query tab
```

`d58f250` and `0cad9d1` are on `main`. The two code commits are only on this branch.

Full suite: **236 passed** as of `13a3464`, verified directly.

| Task | State |
|---|---|
| 1 — matchups table | code done, spec review ✅, **quality review NOT done** |
| 2-10 | not started |

## Pick up here

**First: finish Task 1's code-quality review.** It was dispatched and then killed for limits before returning any verdict. Nothing was approved and nothing was reported — do not treat it as passed. Re-run it over `76738f1` and `13a3464` together, covering `scripts/build_query_db.py` and `tests/test_query_db.py`.

The prompt to reuse asks specifically about: whether the file structure will hold four table builders plus a Parquet emitter plus a CLI without becoming unwieldy; edge cases in `_phase`/`_bracket_pairs` that the tests miss; whether all three tests calling `load_raw()` independently matters; and duplication against helpers already in `scripts/generate.py`.

Then continue the plan from Task 2 with the loop: implementer → spec review → quality review → mark complete in `.tasks.json` → next.

## Documents

- Spec: `docs/superpowers/specs/2026-09-03-stat-search-duckdb-design.md`
- Plan: `docs/superpowers/plans/2026-09-03-stat-search.md` — ten tasks, full code in every step
- Task state: `docs/superpowers/plans/2026-09-03-stat-search.md.tasks.json` — **all ten still say `pending`**; Task 1 (id 0) is code-complete but was never flipped, because the native task tools were unavailable in that session and the quality gate never closed

## Decisions already made — do not re-open

- dbplyr-style verb builder over DuckDB. Users never type SQL; a "Show query" panel displays the compiled SQL read-only.
- Always DuckDB, one execution path. No JS fallback engine. ~7 MB first load on the tab, lazy and cached, accepted deliberately.
- `@duckdb/duckdb-wasm` pinned to exactly **1.32.0**, `eh` bundle. The `latest` dist-tag points at a `-dev` prerelease; never follow it. The threaded `coi` bundle is impossible here — it needs cross-origin isolation headers GitHub Pages cannot set.
- All four datasets in v1: matchups, player_weeks, team_seasons, draft.
- Presets plus an editable verb stack.

## Traps worth carrying forward

1. **The builder must read through `scripts.generate.load_raw()`, never `raw/*.json` directly.** `load_raw()` already applies apostrophe normalization, draft position backfill (`backfill_draft_positions`, `scripts/generate.py:2312`) and overall-pick numbering (`annotate_overall_picks`, `scripts/generate.py:2273`). Two "bugs" were flagged during design that turned out to be already solved there — the spec was corrected in `0cad9d1`.

2. **`raw/2026.json` is committed but unplayed.** Zero matchups, zero player-weeks, 150 draft picks. The hardcoded `1230` in `test_matchup_rows_shape` is year-coupled and will need a deliberate bump once 2026 games land. Same for `19881` in Task 2.

3. **Five imports in `scripts/build_query_db.py` are intentionally unused** (`canonical_owner`, `slug`, `standings_teams`, `load_bible`, `load_raw`), reserved for Tasks 2-6. A spec reviewer already flagged them once; the waiver and its reasoning are in the file's import comment. Do not prune them.

4. **Tasks 8-10 close on browser checks CI cannot run.** The compiler and builder are unit-tested; the wiring between them is only verified by a person opening the page over HTTP (`file://` will not work — module imports and Parquet fetches need an origin). Closing that gap means a Playwright suite, which is its own plan.

## Deferred from v1, recorded not dropped

- Named window functions (`rank_in_season`, `streak_len`, `rolling_avg_3`). In the spec for v1, but absent from all ten tasks: they need a verb vocabulary that does not exist until the stack is real. Add as Task 11.
- Copy-as-CSV in the results table. Ten lines on `renderTable`; ride along with Task 11.
