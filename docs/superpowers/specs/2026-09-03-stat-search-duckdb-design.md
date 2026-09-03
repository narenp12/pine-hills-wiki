# Stat Search: a dbplyr-style query tab over DuckDB-WASM

Date: 2026-09-03
Status: approved design, not yet implemented

## Summary

Add a `Stat Search` tab to the wiki where league members build queries by composing
verbs in a UI — never by typing SQL. The UI edits an abstract syntax tree, a pure
function compiles that tree to DuckDB SQL, and DuckDB-WASM executes it in the
browser against Parquet files generated from `raw/*.json` at build time.

The model is dbplyr: you compose `filter`, `group by`, `summarise`, `arrange`;
the layer compiles and runs; `show_query()` reveals the SQL it sent. Here the
equivalent is a collapsible **Show query** panel that prints the compiled SQL
read-only.

## Goals

- Answer questions the static Records page cannot anticipate.
- Support aggregation, window functions, and joins across datasets — the reason
  DuckDB is present at all.
- Require no SQL knowledge to use, while making the generated SQL visible to
  anyone curious.
- Produce shareable URLs, so any wiki page can link the query that proves its claim.
- Add no new build system, bundler, or JavaScript framework.

## Non-goals

- A typed SQL console. Users compose verbs; they do not write SQL.
- User accounts, saved queries server-side, or any backend service. The site is
  static on GitHub Pages.
- Charts or visualizations. Tables only in v1.
- Recomputing anything the Records or Playoffs pages already state. Stat Search
  is the ad-hoc complement to those curated pages, and a test asserts the two agree.

## Data model

Four tables, built from `raw/*.json`. Owner is the identity key across all of
them; team name is carried for display because team names change between seasons.

Row counts are measured from the committed `raw/` data as of 2026-09-03.

### `matchups` — 1,230 rows

One row per team per game (each game contributes two rows).

| column | type | source |
|---|---|---|
| `year` | INTEGER | `season` |
| `week` | INTEGER | `matchups` key |
| `phase` | VARCHAR | derived: see below |
| `owner` | VARCHAR | resolved from team name via `standings.teams` |
| `team` | VARCHAR | `matchups[week][i].teams[j].name` |
| `score` | DOUBLE | `.score` |
| `opp_owner` | VARCHAR | the other team's owner |
| `opp_team` | VARCHAR | the other team's name |
| `opp_score` | DOUBLE | the other team's score |
| `margin` | DOUBLE | `score - opp_score` |
| `won` | BOOLEAN | `.is_winner` |

`phase` derivation: a week absent from `playoffs.weeks` is `regular`. Within a
postseason week, a game whose two team names match a `bracket.games` entry for
that week is `playoff`; any other postseason game is `consolation`.

### `player_weeks` — 19,881 rows

One row per rostered player per week, bench and IR included. This is the largest
and most interesting table, and the one that motivates a real query engine.

| column | type | source |
|---|---|---|
| `year` | INTEGER | `season` |
| `week` | INTEGER | `weeks` key |
| `owner` | VARCHAR | resolved from team name |
| `team` | VARCHAR | `weeks[week].rosters` key |
| `player` | VARCHAR | `.name` |
| `player_slug` | VARCHAR | same slug function the player pages use |
| `position` | VARCHAR | `.position` — one of `QB RB WR TE K DEF` |
| `slot` | VARCHAR | `.slot` — one of `QB RB WR TE K DEF W/R/T BN IR` |
| `started` | BOOLEAN | `slot NOT IN ('BN','IR')` |
| `points` | DOUBLE | `.points` |

Per-season coverage: 2018 1,252 · 2019 1,895 · 2020 2,415 · 2021 2,676 ·
2022 2,659 · 2023 2,655 · 2024 3,159 · 2025 3,170 · 2026 0. The 2026 season has
no weekly rosters yet; queries must degrade to "no rows" rather than error.

### `team_seasons` — 88 rows

| column | type | source |
|---|---|---|
| `year` | INTEGER | `season` |
| `owner` | VARCHAR | `standings.teams[].owner` |
| `team` | VARCHAR | `.name` |
| `wins`, `losses` | INTEGER | `.wins`, `.losses` |
| `pf`, `pa` | DOUBLE | `.points_for`, `.points_against` |
| `rank` | INTEGER | `.rank` |
| `seed` | INTEGER | `.playoff_seed` |
| `champion`, `runner_up`, `top_seed`, `toilet` | BOOLEAN | `champions` block |

### `draft` — 1,320 rows

| column | type | source |
|---|---|---|
| `year` | INTEGER | `season` |
| `round` | INTEGER | `.round` |
| `pick` | INTEGER | normalized to pick-within-round — see below |
| `overall` | INTEGER | normalized to pick-within-draft — see below |
| `player` | VARCHAR | `.player` |
| `player_slug` | VARCHAR | slug function |
| `position` | VARCHAR | backfilled — see below |
| `owner` | VARCHAR | resolved from team name |
| `team` | VARCHAR | `.team` |

**Data-quality note — `pick` is not uniform across seasons.** For 2018 through
2025 (Yahoo-sourced), `pick` restarts at 1 each round: 2024 round 1 is picks
1-12 and round 2 is also picks 1-12. For 2026 (Sleeper-sourced, per commit
`aef5d2e` which deliberately preserves Sleeper's overall numbering), `pick` is
already the overall number: round 1 is 1-10 and round 2 is 11-20.

**This is already solved and must not be reimplemented.**
`annotate_overall_picks` (`scripts/generate.py:2273`) detects the convention per
season — a pick number exceeding the round size means the season is already
overall-numbered — and writes a normalized `overall` field onto each pick in
place. The builder reads `overall` and leaves `pick` as the within-round number.

**Data-quality note — missing positions.** `draft_results[].position` is empty
for every pick from 2018 through 2025 (1,170 of 1,320 rows); only 2026 carries
it. **Also already solved:** `backfill_draft_positions`
(`scripts/generate.py:2312`) fills positions from that season's weekly rosters,
and `apply_bible_positions` (`scripts/generate.py:2335`) covers players who were
drafted then cut before week one, from `raw/bible.yaml`. Picks that match neither
stay blank rather than being guessed.

Both normalizations run inside `load_raw()` (`scripts/generate.py:129`), so the
builder gets them free by calling that function instead of parsing `raw/*.json`
itself. The builder imports `load_raw`; it writes no draft normalization logic of
its own.

## Build pipeline

New `scripts/build_query_db.py`:

1. Call `scripts.generate.load_raw()` and `load_bible()` rather than reading
   `raw/` directly. This inherits apostrophe normalization, draft position
   backfill, and overall-pick numbering, and guarantees Stat Search sees exactly
   the data the generated pages see.
2. Build the four tables in an in-memory DuckDB database.
3. Run integrity assertions as SQL (see Testing).
4. `COPY ... TO '<stage>/query/<table>.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)`.
5. Emit `<stage>/query/schema.json`: per table, the column list with types,
   distinct values for low-cardinality columns (owners, positions, slots, phases,
   years), and row counts. The UI builds its dropdowns from this file, so adding a
   column never requires touching the JavaScript.
6. Emit `<stage>/query/index.md` — front matter plus the mount `div`.

Wired into `zensical/build.mjs` as a step between `generate.py` and
`transform.py`, taking `WIKI_CONTENT_DIR` the same way `generate.py` does.

Dependency: `duckdb` (PyPI, current 1.5.5) added to `[project.dependencies]`.
CI already runs `uv sync --locked --group dev`, so no workflow change is needed.

## Runtime architecture

- `@duckdb/duckdb-wasm` pinned to **1.32.0** — an exact stable version, not a
  range. The `latest` dist-tag currently points at `1.33.1-dev57.0`, a
  pre-release, so it must never be followed.
- The `eh` bundle, single-threaded. The threaded `coi` bundle requires
  cross-origin isolation response headers, which GitHub Pages cannot set.
- Engine loaded from jsDelivr; Parquet files served from the site's own origin.
- Boot is lazy: nothing loads until the Stat Search page is opened. The nav link
  gets a `mouseenter` prefetch hint.
- On boot, register each Parquet file and create a view per table, then run every
  query against those views.

Measured first-load cost, version 1.32.0, brotli from jsDelivr:

| asset | size |
|---|---|
| `duckdb-eh.wasm` | 6.76 MB |
| `duckdb-browser-eh.worker.js` | 0.18 MB |
| `duckdb-browser.mjs` | ~0.03 MB |
| Parquet data (all four tables, ZSTD) | well under 1 MB |

Roughly 7 MB on a cold first visit to this one page, browser-cached afterwards.
This is accepted deliberately: it buys a single execution path with no
hand-written query engine to maintain, and window functions and joins that the
data genuinely warrants at 19,881 player-week rows. The boot state is a
determinate progress bar driven by the `fetch` stream, not a spinner.

## The AST

Every piece of query state lives in one plain object. Presets are serialized
ASTs, URL state is a serialized AST, and undo is a stack of ASTs.

```js
{
  from: "player_weeks",
  join: null,                       // or { table, on: ["year", "owner"] }
  filter: [                         // AND-joined
    { field: "slot", op: "=",  value: "BN" },
    { field: "points", op: ">", value: 25 }
  ],
  groupBy: ["owner"],
  summarise: [
    { fn: "count",                as: "games" },
    { fn: "sum", field: "points", as: "wasted_points" }
  ],
  having: [],                       // same shape as filter, applied post-aggregate
  arrange: [{ field: "wasted_points", dir: "desc" }],
  limit: 200
}
```

Supported operators: `= != < <= > >= in not_in between contains is_null`.
Supported aggregates: `count count_distinct sum avg min max median stddev`.
Window functions in v1 are exposed as named derived columns the compiler knows
how to emit (`rank_in_season`, `streak_len`, `rolling_avg_3`), not as free-form
window syntax — the UI has no vocabulary for `OVER` clauses and users are not
writing SQL.

## The compiler

```
compileAst(ast, schema) -> { sql, params }
```

A pure function: no DOM, no DuckDB import, no network. Fully testable under
`node:test`.

Safety contract:

- Every `field`, `table`, and `fn` is validated against `schema.json`. Anything
  not present throws before a string is built.
- Identifiers are emitted quoted, drawn only from the validated schema.
- Every literal is passed as a DuckDB prepared-statement parameter. No user-supplied
  string is ever concatenated into SQL text.
- `limit` is clamped to a maximum of 5,000 rows.

The Show query panel prints the compiled SQL with parameters inlined for
readability, clearly marked as a display rendering rather than the executed text.

## UI

One file: `zensical/docs/javascripts/query.js`, vanilla JavaScript, committed
alongside the existing `tablesort.js`. It early-returns unless the mount element
is present, so every other page pays nothing.

Layout top to bottom:

1. **Dataset picker** — Matchups · Player Weeks · Seasons · Draft.
2. **Preset chips** — the page opens on these, so a first-time visitor has
   something to click rather than an empty builder.
3. **Verb rows** — `filter`, `group by`, `summarise`, `having`, `arrange`,
   `limit`. Add and remove rows; fields and operators come from `schema.json`.
4. **Results table** — click-to-sort, 200 rows rendered with a "show all" control,
   row count, and copy-as-CSV.
5. **Show query** — collapsible, read-only SQL.

Owner cells link to `owners/<slug>.md`; player cells link to
`players/<slug>.md`. Query results feed back into the wiki rather than
dead-ending.

The mount element contains static fallback text pointing at Records and Playoffs,
so a visitor without JavaScript sees a useful page rather than a blank one.

### Presets shipped in v1

Matchups: biggest blowouts · one-score games · most points in a loss · fewest
points in a win.
Player weeks: highest-scoring benched players · best single weeks by position ·
most points left on the bench by owner · most reliable starters.
Seasons: best regular season records · champions with the worst point totals ·
points for versus finish.
Draft: earliest picks by owner · draft position runs by round.

## URL state and cross-linking

The AST serializes into the query string. Any wiki page can then link the exact
query behind a claim — a Records footnote, a lore entry citing a bad start/sit.
Opening such a link restores the full verb stack in the UI, editable.

## Navigation

New `Stat Search` entry in `zensical.toml`, placed immediately after `Records`:
Records holds the curated answers, Stat Search is where you ask your own.

## Testing

Python, under `tests/`, matching the existing suite's style:

- Builder row counts per season match the source JSON.
- No NULL owners in any table; every `owner` resolves to an existing
  `owners/<slug>.md`.
- `margin == score - opp_score` for every matchups row.
- Each game contributes exactly two matchups rows, with mirrored scores.
- `phase` classification: postseason weeks are non-`regular`, and every
  `bracket.games` entry has a matching `playoff` row.
- Draft position backfill hit rate is reported and asserted non-zero.
- Draft numbering normalization: for every season, `pick` restarts at 1 in each
  round, and `overall` runs 1..n with no gaps or duplicates. Covers both the
  Yahoo per-round convention and the Sleeper overall convention.
- **Consistency:** SQL over the generated Parquet reproduces the Records page's
  marquee values — highest score, lowest score, biggest blowout, closest game.
  This is the guard against Stat Search and Records drifting apart.

JavaScript, under `node:test` (built into Node 22, which CI already installs;
no new dependency):

- Every shipped preset compiles without throwing.
- Malformed ASTs are rejected: unknown field, unknown table, unknown aggregate,
  unknown operator.
- Injection attempts through field names, table names, and aggregate names fail
  validation rather than reaching the SQL string.
- Literals appear in `params`, never in `sql`.
- `limit` above 5,000 is clamped.

## Risks

| risk | mitigation |
|---|---|
| 7 MB first load on mobile data | Lazy, single-page, cached after first visit; determinate progress bar; the tab is opt-in from the nav. |
| `duckdb-wasm` `latest` tag points at a pre-release | Pin the exact stable version, 1.32.0. Upgrades are deliberate. |
| jsDelivr outage takes the tab down | Page detects boot failure and falls back to the static message plus links to Records and Playoffs. Vendoring the wasm stays available as a later option. |
| Stat Search and Records disagree | Consistency test above, run in CI. |
| Draft position mostly missing | Already backfilled by `load_raw()`; unmatched picks stay blank and the UI labels the filter partial. |
| Two draft pick-numbering conventions in one dataset | Already normalized by `annotate_overall_picks`; builder consumes `overall` and adds a regression test. |
| Builder drifts from `generate.py` by re-parsing `raw/` | Builder calls `load_raw()`/`load_bible()`, never reads `raw/` itself. |
| Parquet files bloat the repo | Under 1 MB total, ZSTD-compressed, regenerated from `raw/` on every build like all other generated content. |

## Out of scope for v1

Typed SQL entry · saved accounts · charts · the threaded `coi` bundle · a vendored
wasm binary · derived tables that duplicate `scripts/generate.py` logic.
