# Player and roster data

**Date:** 2026-09-01
**Status:** approved, not implemented

## Problem

The wiki has no player-level data. Every season's `raw/<year>.json` carries
`weeks: {}`, so the "Team Rosters" table on each season page renders as a bare
header ([generate.py:1095](../../../scripts/generate.py)), the Post-Draft and
End-of-Season columns in each team's season log are empty, and four season
awards sit at `_TBD_`. Draft picks carry player names but `position: ""` for all
eight seasons.

The Rust model already defines `Roster` / `RosterPlayer` and a
`weeks[wk].rosters` container ([model.rs:45](../../../scraper/src/model.rs)),
and the HTML scraper has an experimental `extract_rosters`. None of it is fed:
the v2 harvest fetches only `standings` and `scoreboard;week=N`.

## Decisions

Four choices, made during design:

1. **Capture depth:** every week, with per-player weekly points — not just two
   snapshots per season. Cost over snapshot-only is payload size, not request
   count, and the award and record work below depends on the weekly numbers.
2. **Surface area:** enrich existing pages only. No `Players` index, no page per
   player. Capture makes both possible later; only generation would change.
3. **Season-page rendering:** one collapsed admonition per team, holding both
   snapshots with slot / player / position / points.
4. **Storage:** the existing `weeks[wk].rosters` slot in `raw/<year>.json`. No
   sidecar file, no lossy aggregation.

Storage cost of (1) + (4): roughly 12 teams x 16 players x 15 weeks = ~2,900
player-week rows per season, taking `raw/2025.json` from 68 KB to roughly
300 KB, ~2.4 MB across eight seasons, all committed. Accepted: it keeps one file
per season, one contract, and one loader, and it preserves the raw capture so a
future question does not require re-harvesting.

## Capture

`harvest_v2.py` gains one call per week, nested so roster and weekly points
arrive in the same response:

```
league/{league_key}/teams/roster;week=N/players/stats;type=week;week=N?format=json_f
```

Written to `dump/v2/{season}-{key}-rosters-wk{NN}.json`, gitignored and cached
by the existing `already_have()` resume check. 131 weeks across 2018-2025 at the
current 5s spacing is about 11 minutes.

**This nesting depth is unverified against `pub-api-ro`.** Implementation starts
with a one-week probe on a single season. If it is rejected, fall back to two
calls per week (`teams/roster;week=N`, then `.../players/stats`), which raises
the total to ~262 requests and changes nothing downstream.

## Model

`RosterPlayer` grows from `{name, position}` to four fields. Two are new
(`slot`, `points`); `position` already exists on the struct but is never
populated by any current path.

| Field | v2 source | Purpose |
|---|---|---|
| `name` | `name.full` | already present |
| `position` | `primary_position` | currently empty everywhere, including draft picks |
| `slot` | `selected_position` | starter vs bench — required for the bench record |
| `points` | `player_points.total` | the week's score |

The container is unchanged: `weeks[wk].rosters[team_key].players[]`.

## Parse and merge

- `parse_v2.rs` gains `parse_rosters()`, wired into `from_v2_dir` by the same
  directory-scan pattern used for scoreboards (discover the week range from what
  the harvest actually wrote, do not assume 1-17).
- `main.rs` adds `"weeks"` to the authoritative-key list in `build_from_v2`
  ([main.rs:122](../../../scraper/src/main.rs)). Without it the merge drops
  rosters on every rebuild, the same way it would drop draft picks.
- `model_contract.rs` grows the two new fields, since it locks the JSON shape
  that `generate.py` reads.
- Draft-pick positions are backfilled by joining pick names against roster
  players in the same season.

## Generation

### Season page — Team Rosters

Replaces the header-only table with one collapsed admonition per team:

```
??? note "Jeremy's Neat Team"
    **Post-draft — week 1**
    | Slot | Player | Pos | Pts |
    **End of season — week 17**
    | Slot | Player | Pos | Pts |
```

Snapshot weeks are the first and last captured week of that season, not
hard-coded 1 and 17 — 2018 ran weeks 3-16.

### Team page — season log

The `Post-Draft Roster` / `End-of-Season Roster` columns cannot hold sixteen
names per cell. Each becomes a wikilink to that year's season page. The columns
keep their purpose without breaking the table width.

### Records — player book

Player records are keyed to the **player**, a third key alongside the existing
person and franchise keys, and obey the same phase rule as every other book:
regular season and postseason never mix.

- Highest single week by a player, regular season
- Highest single week by a player, postseason (separate book)
- Highest season total by a player on one roster
- Highest-scoring benched player in a week
- Most weeks rostered, career

Existing conventions carry over: ties are listed and marked `(tied)`, never
arbitrated.

### Awards

Two of the four `_TBD_` awards need no roster data at all — **Highest** and
**Lowest Single-Week Score** are team scores already present in `matchups`.
They are stubbed because they were never wired. They get filled in this pass.

The other two are computed, with the formula printed next to the award so it
reads as a computation rather than a verdict:

- **Best Draft Pick** — the largest positive gap between a pick's draft slot and
  that player's end-of-season rank among players at the same position.
- **Biggest Bust** — the inverse, restricted to rounds 1-3.

## Non-goals

- No `Players` index page and no per-player pages.
- No re-scrape of the HTML path; `extract_rosters` stays experimental and unused.
- No change to how records key managers and franchises.

## Verification

- `cargo test` — contract test covers the two new fields.
- Probe one week before the full harvest; do not run 131 requests against an
  unverified endpoint shape.
- After the build, assert non-empty `weeks[*].rosters` for all eight seasons and
  that draft-pick positions are no longer uniformly empty.
- Existing guard stays: the merge must not drop draft picks.
- Render and read one season page and one team page before claiming done.
