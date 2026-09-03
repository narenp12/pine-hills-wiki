# Stat Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Stat Search` tab where league members compose queries from UI verbs, which compile to DuckDB SQL and run in the browser against Parquet built from `raw/`.

**Architecture:** A Python builder calls `scripts.generate.load_raw()` and emits four Parquet tables plus a `schema.json`. In the browser, a pure compiler turns an AST into parameterized DuckDB SQL, and DuckDB-WASM executes it. The AST is the single source of truth for presets, URL state, and undo.

**Tech Stack:** Python 3.11 + `duckdb` 1.5.5, vanilla ES modules (no bundler), `@duckdb/duckdb-wasm` 1.32.0 (`eh` bundle), Zensical, pytest, `node:test`.

**User decisions (already made):**
- Play Index style builder, not a curated gallery, not a typed SQL console.
- All datasets in v1, not a phased subset.
- Presets plus an editable verb stack, not a bare builder and not a frozen control panel.
- DuckDB backend, with users never typing SQL — "like dbplyr but for duckdb".
- Always DuckDB: one execution path, engine loaded from jsDelivr, accepting ~7 MB on first visit to the tab.

**Spec:** `docs/superpowers/specs/2026-09-03-stat-search-duckdb-design.md`

**Note on task tracking:** The native task tools (`TaskList`/`TaskCreate`/`TaskUpdate`) are not available in this session, so no native tasks were created. The companion `2026-09-03-stat-search.md.tasks.json` carries the same task bodies for whichever session executes this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/build_query_db.py` | Create (new). Build four tables from `load_raw()`, emit Parquet + `schema.json` + `query/index.md`. |
| `tests/test_query_db.py` | Create (new). Row shape, integrity, and normalization regression tests. |
| `tests/test_query_records_consistency.py` | Create (new). SQL over Parquet reproduces the Records page's marquee values. |
| `zensical/docs/javascripts/query-compile.js` | Create (new). Pure `compileAst(ast, schema)`. No DOM, no DuckDB, no network. |
| `zensical/docs/javascripts/query-engine.js` | Create (new). DuckDB-WASM boot, Parquet registration, `runSql()`. |
| `zensical/docs/javascripts/query-presets.js` | Create (new). The shipped preset ASTs, as data. |
| `zensical/docs/javascripts/query.js` | Create (new). UI: verb rows, results table, URL state. Imports the three above. |
| `zensical/docs/stylesheets/zensical.css` | Modify. Stat Search styles appended. |
| `tests/js/query-compile.test.mjs` | Create (new). `node:test` suite for the compiler. |
| `zensical/build.mjs` | Modify. Insert the builder between `generate.py` and `transform.py`. |
| `zensical/zensical.toml` | Modify. Nav entry, `extra_javascript` unchanged (query.js is an ES module loaded by the page). |
| `pyproject.toml` | Modify. Add `duckdb` to `[project.dependencies]`. |
| `.github/workflows/deploy.yml` | Modify. Add a test step (currently the workflow only builds). |

Splitting the browser code four ways is deliberate: `query-compile.js` must stay importable by `node:test` with no DOM or network, which is only true if it imports nothing else.

---

### Task 1: Builder skeleton and the matchups table

**Goal:** `scripts/build_query_db.py` produces the 1,230-row matchups table with correct owners and phase classification.

**Files:**
- Create: `scripts/build_query_db.py`
- Create: `tests/test_query_db.py`
- Modify: `pyproject.toml`

**Acceptance Criteria:**
- [ ] `matchup_rows()` returns exactly 1,230 rows from the committed `raw/`
- [ ] Every row has a non-empty `owner` and `opp_owner`
- [ ] `margin == score - opp_score` on every row
- [ ] Each game yields exactly two rows with mirrored scores
- [ ] `phase` is one of `regular`, `playoff`, `consolation`

**Verify:** `uv run pytest tests/test_query_db.py -v` → all pass

**Steps:**

- [ ] **Step 1: Add the duckdb dependency**

In `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "pyyaml>=6.0",
    "duckdb>=1.5.5",
]
```

Then run:

```bash
uv sync
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_query_db.py`:

```python
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import matchup_rows, owner_index
from scripts.generate import load_bible, load_raw


def test_matchup_rows_shape():
    seasons = load_raw()
    rows = matchup_rows(seasons, owner_index(seasons, load_bible()))
    assert len(rows) == 1230
    for row in rows:
        assert row["owner"], f"blank owner in {row}"
        assert row["opp_owner"], f"blank opp_owner in {row}"
        assert abs(row["margin"] - (row["score"] - row["opp_score"])) < 1e-9
        assert row["phase"] in {"regular", "playoff", "consolation"}


def test_matchup_rows_are_mirrored():
    seasons = load_raw()
    rows = matchup_rows(seasons, owner_index(seasons, load_bible()))
    by_game = {}
    for row in rows:
        key = (row["year"], row["week"], frozenset((row["team"], row["opp_team"])))
        by_game.setdefault(key, []).append(row)
    for key, pair in by_game.items():
        assert len(pair) == 2, f"{key} produced {len(pair)} rows"
        a, b = pair
        assert a["score"] == b["opp_score"]
        assert a["margin"] == -b["margin"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.build_query_db'`

- [ ] **Step 4: Write the builder**

Create `scripts/build_query_db.py`:

```python
"""Build the Stat Search query tables from the captured league data.

Reads through scripts.generate.load_raw() rather than raw/*.json directly, so
this inherits apostrophe normalization, draft position backfill, and overall
pick numbering. Stat Search and the generated pages therefore see identical
data by construction.
"""

import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.generate import (  # noqa: E402
    canonical_owner,
    get_owners,
    load_bible,
    load_raw,
    slug,
    standings_teams,
    team_owners_by_year,
)

ROOT = Path(__file__).resolve().parent.parent


def owner_index(seasons: dict, bible: dict) -> dict:
    """{(year, team name): canonical owner}, the join key for every table."""
    return team_owners_by_year(seasons, get_owners(bible))


def _bracket_pairs(season_data: dict) -> set:
    """{(week, frozenset of the two team names)} for every real bracket game."""
    pairs = set()
    for game in (season_data.get("bracket") or {}).get("games") or []:
        week = int(game.get("week") or 0)
        names = frozenset(
            str(t.get("name") or "") for t in game.get("teams") or []
        )
        if week and len(names) == 2:
            pairs.add((week, names))
    return pairs


def _phase(season_data: str, week: int, names: frozenset, pairs: set) -> str:
    playoff_weeks = {
        int(w) for w in ((season_data.get("playoffs") or {}).get("weeks") or {})
    }
    if week not in playoff_weeks:
        return "regular"
    return "playoff" if (week, names) in pairs else "consolation"


def matchup_rows(seasons: dict, owners: dict) -> list[dict]:
    rows = []
    for year, season_data in sorted(seasons.items()):
        pairs = _bracket_pairs(season_data)
        for raw_week, games in (season_data.get("matchups") or {}).items():
            week = int(raw_week)
            for game in games or []:
                teams = game.get("teams") or []
                if len(teams) != 2:
                    continue
                names = frozenset(str(t.get("name") or "") for t in teams)
                phase = _phase(season_data, week, names, pairs)
                for index, team in enumerate(teams):
                    other = teams[1 - index]
                    name = str(team.get("name") or "")
                    opp_name = str(other.get("name") or "")
                    score = float(team.get("score") or 0.0)
                    opp_score = float(other.get("score") or 0.0)
                    rows.append(
                        {
                            "year": year,
                            "week": week,
                            "phase": phase,
                            "owner": owners.get((year, name), ""),
                            "team": name,
                            "score": score,
                            "opp_owner": owners.get((year, opp_name), ""),
                            "opp_team": opp_name,
                            "opp_score": opp_score,
                            "margin": score - opp_score,
                            "won": bool(team.get("is_winner")),
                        }
                    )
    return rows
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: PASS, 2 tests

If `test_matchup_rows_shape` fails on a blank owner, the team name in `matchups` does not match the name in `standings.teams` for that season — fix by resolving through the same normalization, not by defaulting the owner to a placeholder.

- [ ] **Step 6: Commit**

```bash
rtk git add pyproject.toml uv.lock scripts/build_query_db.py tests/test_query_db.py
rtk git commit -m "feat: build the Stat Search matchups table"
```

---

### Task 2: The player_weeks table

**Goal:** Emit 19,881 player-week rows with points, position, lineup slot, and a `started` flag.

**Files:**
- Modify: `scripts/build_query_db.py`
- Modify: `tests/test_query_db.py`

**Acceptance Criteria:**
- [ ] `player_week_rows()` returns exactly 19,881 rows
- [ ] `started` is False exactly when `slot` is `BN` or `IR`
- [ ] Every `player_slug` matches `scripts.generate.slug(player)`
- [ ] 2026 contributes zero rows without raising

**Verify:** `uv run pytest tests/test_query_db.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `tests/test_query_db.py`:

```python
from scripts.build_query_db import player_week_rows  # noqa: E402
from scripts.generate import slug  # noqa: E402

BENCH_SLOTS = {"BN", "IR"}


def test_player_week_rows_shape():
    seasons = load_raw()
    rows = player_week_rows(seasons, owner_index(seasons, load_bible()))
    assert len(rows) == 19881
    for row in rows:
        assert row["started"] == (row["slot"] not in BENCH_SLOTS)
        assert row["player_slug"] == slug(row["player"])
        assert isinstance(row["points"], float)


def test_player_weeks_cover_expected_seasons():
    seasons = load_raw()
    rows = player_week_rows(seasons, owner_index(seasons, load_bible()))
    by_year = {}
    for row in rows:
        by_year[row["year"]] = by_year.get(row["year"], 0) + 1
    assert by_year[2018] == 1252
    assert by_year[2025] == 3170
    assert by_year.get(2026, 0) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'player_week_rows'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/build_query_db.py`:

```python
BENCH_SLOTS = {"BN", "IR"}


def player_week_rows(seasons: dict, owners: dict) -> list[dict]:
    rows = []
    for year, season_data in sorted(seasons.items()):
        for raw_week, week_data in (season_data.get("weeks") or {}).items():
            week = int(raw_week)
            rosters = (week_data or {}).get("rosters") or {}
            for team_name, roster in rosters.items():
                name = str(team_name)
                for player in roster.get("players") or []:
                    player_name = str(player.get("name") or "")
                    if not player_name:
                        continue
                    slot = str(player.get("slot") or "")
                    rows.append(
                        {
                            "year": year,
                            "week": week,
                            "owner": owners.get((year, name), ""),
                            "team": name,
                            "player": player_name,
                            "player_slug": slug(player_name),
                            "position": str(player.get("position") or ""),
                            "slot": slot,
                            "started": slot not in BENCH_SLOTS,
                            "points": float(player.get("points") or 0.0),
                        }
                    )
    return rows
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/build_query_db.py tests/test_query_db.py
rtk git commit -m "feat: build the Stat Search player-weeks table"
```

---

### Task 3: The team_seasons and draft tables

**Goal:** Emit 88 team-season rows with championship flags and 1,320 draft rows using the already-normalized `overall` and backfilled `position`.

**Files:**
- Modify: `scripts/build_query_db.py`
- Modify: `tests/test_query_db.py`

**Acceptance Criteria:**
- [ ] `team_season_rows()` returns 88 rows; exactly one `champion` per completed season
- [ ] `draft_rows()` returns 1,320 rows
- [ ] `pick` restarts at 1 in every round, for every season
- [ ] `overall` is a gapless 1..n sequence per season
- [ ] Draft position coverage exceeds 95% of rows

**Verify:** `uv run pytest tests/test_query_db.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `tests/test_query_db.py`:

```python
from scripts.build_query_db import draft_rows, team_season_rows  # noqa: E402


def test_team_season_rows_shape():
    seasons = load_raw()
    bible = load_bible()
    rows = team_season_rows(seasons, bible, owner_index(seasons, bible))
    assert len(rows) == 88
    champs_by_year = {}
    for row in rows:
        if row["champion"]:
            champs_by_year[row["year"]] = champs_by_year.get(row["year"], 0) + 1
    for year, count in champs_by_year.items():
        assert count == 1, f"{year} has {count} champions"


def test_draft_numbering_is_normalized():
    seasons = load_raw()
    bible = load_bible()
    rows = draft_rows(seasons, owner_index(seasons, bible))
    assert len(rows) == 1320
    by_year = {}
    for row in rows:
        by_year.setdefault(row["year"], []).append(row)
    for year, picks in by_year.items():
        overalls = sorted(p["overall"] for p in picks)
        assert overalls == list(range(1, len(picks) + 1)), f"{year} overall gaps"
        by_round = {}
        for pick in picks:
            by_round.setdefault(pick["round"], []).append(pick["pick"])
        for round_number, numbers in by_round.items():
            assert min(numbers) == 1, f"{year} round {round_number} starts at {min(numbers)}"


def test_draft_positions_are_mostly_filled():
    seasons = load_raw()
    bible = load_bible()
    rows = draft_rows(seasons, owner_index(seasons, bible))
    filled = sum(1 for row in rows if row["position"])
    assert filled / len(rows) > 0.95
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'draft_rows'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/build_query_db.py`:

```python
from scripts.generate import apply_derived_champions, champ_year  # noqa: E402


def team_season_rows(seasons: dict, bible: dict, owners: dict) -> list[dict]:
    bible = apply_derived_champions(bible, seasons)
    rows = []
    for year, season_data in sorted(seasons.items()):
        champs = champ_year(bible, year)
        for team in standings_teams(season_data):
            name = str(team.get("name") or "")
            rows.append(
                {
                    "year": year,
                    "owner": owners.get((year, name), ""),
                    "team": name,
                    "wins": int(team.get("wins") or 0),
                    "losses": int(team.get("losses") or 0),
                    "pf": float(team.get("points_for") or 0.0),
                    "pa": float(team.get("points_against") or 0.0),
                    "rank": int(team.get("rank") or 0),
                    "seed": int(team.get("playoff_seed") or 0),
                    "champion": name == champs.get("champion"),
                    "runner_up": name == champs.get("runner_up"),
                    "top_seed": name == champs.get("top_seed"),
                    "toilet": name == champs.get("toilet_winner"),
                }
            )
    return rows


def draft_rows(seasons: dict, owners: dict) -> list[dict]:
    """Draft picks. `overall` and `position` are already normalized by
    load_raw() via annotate_overall_picks and backfill_draft_positions -- do
    not recompute either here."""
    rows = []
    for year, season_data in sorted(seasons.items()):
        picks = (season_data.get("draft") or {}).get("draft_results") or []
        round_sizes = {}
        for pick in picks:
            round_number = int(pick.get("round") or 0)
            round_sizes[round_number] = round_sizes.get(round_number, 0) + 1
        widest = max(round_sizes.values(), default=0)
        for pick in picks:
            player = str(pick.get("player") or "")
            team_name = str(pick.get("team") or "")
            round_number = int(pick.get("round") or 0)
            overall = int(pick.get("overall") or 0)
            # Sleeper seasons carry `pick` as the overall number; derive the
            # within-round number back out of `overall` so the column means one
            # thing in every season.
            within = overall - (round_number - 1) * widest if widest else 0
            rows.append(
                {
                    "year": year,
                    "round": round_number,
                    "pick": within,
                    "overall": overall,
                    "player": player,
                    "player_slug": slug(player),
                    "position": str(pick.get("position") or ""),
                    "owner": owners.get((year, team_name), ""),
                    "team": team_name,
                }
            )
    return rows
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: PASS, 7 tests

If `test_team_season_rows_shape` reports a season with zero champions, the `champions` block names a team spelling that `standings.teams` does not use — resolve through `normalize_apostrophes`, which `load_raw()` has already applied to both.

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/build_query_db.py tests/test_query_db.py
rtk git commit -m "feat: build the Stat Search season and draft tables"
```

---

### Task 4: Emit Parquet and schema.json

**Goal:** Write the four tables to ZSTD Parquet plus a `schema.json` the UI builds its dropdowns from.

**Files:**
- Modify: `scripts/build_query_db.py`
- Modify: `tests/test_query_db.py`

**Acceptance Criteria:**
- [ ] `main()` writes four `.parquet` files and one `schema.json` under `<content dir>/query/`
- [ ] `schema.json` lists every column with its type for all four tables
- [ ] `schema.json` carries distinct value lists for `owner`, `position`, `slot`, `phase`, `year`
- [ ] Total Parquet size is under 1 MB
- [ ] Re-running is idempotent

**Verify:** `uv run pytest tests/test_query_db.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `tests/test_query_db.py`:

```python
import json  # noqa: E402
import pathlib  # noqa: E402

from scripts.build_query_db import build_all  # noqa: E402

TABLES = ("matchups", "player_weeks", "team_seasons", "draft")
ENUM_COLUMNS = ("owner", "position", "slot", "phase", "year")


def test_build_all_emits_parquet_and_schema(tmp_path: pathlib.Path):
    build_all(tmp_path)
    out = tmp_path / "query"
    for table in TABLES:
        assert (out / f"{table}.parquet").exists()
    schema = json.loads((out / "schema.json").read_text())
    assert set(schema["tables"]) == set(TABLES)
    for table in TABLES:
        assert schema["tables"][table]["columns"], f"{table} has no columns"
        assert schema["tables"][table]["row_count"] > 0
    enums = schema["enums"]
    for column in ENUM_COLUMNS:
        assert enums.get(column), f"no distinct values captured for {column}"
    total = sum((out / f"{t}.parquet").stat().st_size for t in TABLES)
    assert total < 1_000_000, f"parquet total {total} bytes exceeds 1 MB"


def test_build_all_is_idempotent(tmp_path: pathlib.Path):
    build_all(tmp_path)
    first = (tmp_path / "query" / "schema.json").read_text()
    build_all(tmp_path)
    assert (tmp_path / "query" / "schema.json").read_text() == first
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_all'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/build_query_db.py`:

```python
import duckdb  # noqa: E402

TABLES = ("matchups", "player_weeks", "team_seasons", "draft")
ENUM_COLUMNS = ("owner", "position", "slot", "phase", "year")


def build_tables(seasons: dict, bible: dict) -> dict:
    owners = owner_index(seasons, bible)
    return {
        "matchups": matchup_rows(seasons, owners),
        "player_weeks": player_week_rows(seasons, owners),
        "team_seasons": team_season_rows(seasons, bible, owners),
        "draft": draft_rows(seasons, owners),
    }


def _register(con, name: str, rows: list[dict]) -> None:
    """Register rows as a DuckDB table. Column order comes from the first row,
    so every row dict must carry the same keys."""
    if not rows:
        raise ValueError(f"table {name} is empty")
    columns = list(rows[0].keys())
    tuples = [tuple(row[column] for column in columns) for row in rows]
    con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM (VALUES (NULL)) WHERE FALSE')
    con.execute(f'DROP TABLE "{name}"')
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(f'"{c}"' for c in columns)
    con.execute(
        f'CREATE TABLE "{name}" AS SELECT * FROM (SELECT {column_list} '
        f"FROM (VALUES ({placeholders})) AS t({column_list})) WHERE FALSE",
        tuples[0],
    )
    con.executemany(f'INSERT INTO "{name}" VALUES ({placeholders})', tuples)


def _schema(con) -> dict:
    tables = {}
    for name in TABLES:
        described = con.execute(f'DESCRIBE "{name}"').fetchall()
        row_count = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        tables[name] = {
            "columns": [{"name": r[0], "type": r[1]} for r in described],
            "row_count": row_count,
        }
    enums = {}
    for column in ENUM_COLUMNS:
        values = set()
        for name in TABLES:
            has_column = any(
                c["name"] == column for c in tables[name]["columns"]
            )
            if not has_column:
                continue
            found = con.execute(
                f'SELECT DISTINCT "{column}" FROM "{name}" '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchall()
            values.update(row[0] for row in found if row[0] != "")
        enums[column] = sorted(values, key=str)
    return {"tables": tables, "enums": enums}


def build_all(content_dir) -> dict:
    """Build every table and write Parquet + schema.json under <content>/query/."""
    out = Path(content_dir) / "query"
    out.mkdir(parents=True, exist_ok=True)
    seasons = load_raw()
    bible = load_bible()
    tables = build_tables(seasons, bible)
    con = duckdb.connect()
    for name, rows in tables.items():
        _register(con, name, rows)
        target = (out / f"{name}.parquet").as_posix()
        con.execute(
            f"COPY \"{name}\" TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        print(f"  wrote {target} ({len(rows)} rows)")
    schema = _schema(con)
    (out / "schema.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    con.close()
    return schema
```

Add `import json` to the top of the file alongside `import os`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_query_db.py -v`
Expected: PASS, 9 tests

If `_register` proves awkward, replace its body with `con.register(name, pyarrow_table)` only if `pyarrow` is already a transitive dependency — do not add a new direct dependency for it.

- [ ] **Step 5: Commit**

```bash
rtk git add scripts/build_query_db.py tests/test_query_db.py
rtk git commit -m "feat: emit Stat Search Parquet tables and schema"
```

---

### Task 5: Records consistency test

**Goal:** Prove SQL over the generated Parquet reproduces the Records page's marquee values, so the two cannot drift apart unnoticed.

**Files:**
- Create: `tests/test_query_records_consistency.py`

**Acceptance Criteria:**
- [ ] Highest regular-season score from SQL matches the Records page value
- [ ] Lowest regular-season score matches
- [ ] Biggest blowout margin matches
- [ ] Closest game margin matches
- [ ] The test reads expected values from the generated Records page, not from hardcoded numbers

**Verify:** `uv run pytest tests/test_query_records_consistency.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the test**

Create `tests/test_query_records_consistency.py`:

```python
"""Stat Search must agree with the Records page.

Both derive from the same raw data, so any disagreement means one of the two
code paths has a bug. Expected values are parsed out of the generated Records
markdown rather than hardcoded, so the test tracks the page instead of freezing
a snapshot of it.
"""

import os
import pathlib
import re
import sys

import duckdb
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import build_all
from scripts.generate import gen_records_index, build_aggregates, load_bible, load_raw

NUMBER = re.compile(r"\d+\.\d+")


def records_markdown() -> str:
    seasons = load_raw()
    bible = load_bible()
    return gen_records_index(seasons, build_aggregates(seasons), bible)


def value_after(markdown: str, label: str) -> float:
    for line in markdown.splitlines():
        if line.startswith(f"| {label}"):
            found = NUMBER.findall(line)
            if found:
                return float(found[0])
    pytest.fail(f"no numeric value found on the {label!r} row")


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    out = tmp_path_factory.mktemp("query")
    build_all(out)
    connection = duckdb.connect()
    parquet = (out / "query" / "matchups.parquet").as_posix()
    connection.execute(
        f"CREATE VIEW matchups AS SELECT * FROM read_parquet('{parquet}')"
    )
    yield connection
    connection.close()


def test_highest_score_matches_records(con):
    markdown = records_markdown()
    sql_value = con.execute(
        "SELECT max(score) FROM matchups WHERE phase = 'regular'"
    ).fetchone()[0]
    assert sql_value == pytest.approx(value_after(markdown, "Highest Score"))


def test_lowest_score_matches_records(con):
    markdown = records_markdown()
    sql_value = con.execute(
        "SELECT min(score) FROM matchups WHERE phase = 'regular'"
    ).fetchone()[0]
    assert sql_value == pytest.approx(value_after(markdown, "Lowest Score"))


def test_biggest_blowout_matches_records(con):
    markdown = records_markdown()
    sql_value = con.execute(
        "SELECT max(margin) FROM matchups WHERE phase = 'regular'"
    ).fetchone()[0]
    assert sql_value == pytest.approx(value_after(markdown, "Biggest Blowout"))


def test_closest_game_matches_records(con):
    markdown = records_markdown()
    sql_value = con.execute(
        "SELECT min(margin) FROM matchups WHERE phase = 'regular' AND margin > 0"
    ).fetchone()[0]
    assert sql_value == pytest.approx(value_after(markdown, "Closest Game"))
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_query_records_consistency.py -v`
Expected: PASS, 4 tests

A failure here is meaningful, not a test bug to paper over. The likely cause is `phase` classification: if a postseason week leaks into `regular`, the maxima will exceed the Records page. Compare `SELECT year, week, phase, count(*) FROM matchups GROUP BY 1,2,3` against `playoffs.weeks` for the offending season.

If `value_after` cannot find a row, the Records page label changed — update the label string, not the assertion.

- [ ] **Step 3: Commit**

```bash
rtk git add tests/test_query_records_consistency.py
rtk git commit -m "test: assert Stat Search agrees with the Records page"
```

---

### Task 6: Wire the builder into the build and add the nav entry

**Goal:** `node zensical/build.mjs` produces a Stat Search page with its data, reachable from the nav.

**Files:**
- Modify: `scripts/build_query_db.py`
- Modify: `zensical/build.mjs`
- Modify: `zensical/zensical.toml`
- Modify: `.github/workflows/deploy.yml`

**Acceptance Criteria:**
- [ ] `uv run python scripts/build_query_db.py` writes into `zensical/.stage/query/`
- [ ] `node zensical/build.mjs` completes and produces `zensical/site/query/index.html`
- [ ] The four Parquet files and `schema.json` land in `zensical/site/query/`
- [ ] `Stat Search` appears in the nav after `Records`
- [ ] CI runs the test suite before building

**Verify:** `node zensical/build.mjs && ls zensical/site/query/` → lists 4 parquet files, schema.json, index.html

**Steps:**

- [ ] **Step 1: Add the page emitter and CLI entry point**

Append to `scripts/build_query_db.py`:

```python
PAGE = """---
title: Stat Search
icon: lucide/search
description: Build your own queries across every season of the Pine Hills Fantasy League.
---

# Stat Search

Pick a dataset, stack up filters, and run it. Nothing here is precomputed - the
query runs in your browser against the same data every other page is built from.

<div id="phfl-query" data-query-base="../query/">
  <p>
    Stat Search needs JavaScript. Without it, the curated numbers live on the
    <a href="../records/">Records</a> and <a href="../playoffs/">Playoffs</a>
    pages.
  </p>
</div>

<script type="module" src="../javascripts/query.js"></script>
"""


def write_page(content_dir) -> Path:
    out = Path(content_dir) / "query"
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.md"
    page.write_text(PAGE)
    return page


def main() -> None:
    content_env = os.environ.get("WIKI_CONTENT_DIR")
    content_dir = Path(content_env) if content_env else ROOT / "zensical" / ".stage"
    schema = build_all(content_dir)
    page = write_page(content_dir)
    print(f"  wrote {page}")
    total = sum(t["row_count"] for t in schema["tables"].values())
    print(f"Done building Stat Search tables ({total} rows).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it standalone**

Run: `uv run python scripts/build_query_db.py`
Expected: five `wrote` lines, then `Done building Stat Search tables (22519 rows).`

- [ ] **Step 3: Wire it into build.mjs**

In `zensical/build.mjs`, inside the `if (rawHasData())` branch, the three existing lines become four. Replace:

```js
  console.log("[build] 2/3 transform.py -> zensical/docs");
  uvRun(["python", "zensical/transform.py"], { cwd: root });
```

with:

```js
  console.log("[build] 2/4 build_query_db.py ->", stage);
  uvRun(["python", "scripts/build_query_db.py"], {
    cwd: root,
    env: { ...process.env, WIKI_CONTENT_DIR: stage },
  });
  console.log("[build] 3/4 transform.py -> zensical/docs");
  uvRun(["python", "zensical/transform.py"], { cwd: root });
```

Update the two neighbouring labels for consistency: `1/3` becomes `1/4`, and the final `console.log("[build] zensical build --clean -> zensical/site")` line stays as is. Also update the pipeline comment at the top of the file to list four steps.

- [ ] **Step 4: Confirm transform.py copies the Parquet through**

Run: `node zensical/build.mjs && ls zensical/site/query/`
Expected: `draft.parquet  index.html  matchups.parquet  player_weeks.parquet  schema.json  team_seasons.parquet`

If the `.parquet` files are missing from `zensical/site/query/` but present in `zensical/docs/query/`, Zensical is not treating them as static assets — confirm they are not being filtered by extension, and if they are, rename the emitted files to `.parquet.bin` in `build_all` and update the fetch paths in Task 8 to match.

If the files are missing from `zensical/docs/query/` too, `zensical/transform.py` only copies Markdown; extend its copy step to pass non-Markdown files through unchanged.

- [ ] **Step 5: Add the nav entry**

In `zensical/zensical.toml`, in the `nav` array, insert after the `Records` line:

```toml
  { "Stat Search" = "query/index.md" },
```

- [ ] **Step 6: Add a test step to CI**

In `.github/workflows/deploy.yml`, insert between "Install build environment" and "Build Zensical site":

```yaml
      - name: Run tests
        run: uv run pytest -q
```

- [ ] **Step 7: Verify the full build**

Run: `node zensical/build.mjs && ls zensical/site/query/`
Expected: the six files above, and `Stat Search` present in the built nav.

- [ ] **Step 8: Commit**

```bash
rtk git add scripts/build_query_db.py zensical/build.mjs zensical/zensical.toml .github/workflows/deploy.yml zensical/docs/query
rtk git commit -m "feat: add the Stat Search page to the build and nav"
```

---

### Task 7: The AST compiler

**Goal:** A pure `compileAst(ast, schema)` that produces parameterized DuckDB SQL and rejects anything not in the schema.

**Files:**
- Create: `zensical/docs/javascripts/query-compile.js`
- Create: `tests/js/query-compile.test.mjs`

**Acceptance Criteria:**
- [ ] Compiles filter, group by, summarise, having, arrange, limit, and a two-table join
- [ ] Every literal appears in `params`, never in `sql`
- [ ] Unknown table, column, operator, or aggregate throws before any SQL is built
- [ ] `limit` above 5,000 is clamped to 5,000
- [ ] The module imports nothing — no DOM, no DuckDB, no network

**Verify:** `node --test tests/js/` → all pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `tests/js/query-compile.test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";
import { compileAst, MAX_LIMIT } from "../../zensical/docs/javascripts/query-compile.js";

const schema = {
  tables: {
    matchups: {
      columns: [
        { name: "year", type: "BIGINT" },
        { name: "owner", type: "VARCHAR" },
        { name: "score", type: "DOUBLE" },
        { name: "margin", type: "DOUBLE" },
        { name: "phase", type: "VARCHAR" },
      ],
      row_count: 1230,
    },
    team_seasons: {
      columns: [
        { name: "year", type: "BIGINT" },
        { name: "owner", type: "VARCHAR" },
        { name: "wins", type: "BIGINT" },
      ],
      row_count: 88,
    },
  },
  enums: {},
};

test("compiles a filtered projection with parameters", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "score", op: ">", value: 150 }],
      arrange: [{ field: "score", dir: "desc" }],
      limit: 10,
    },
    schema,
  );
  assert.match(sql, /FROM "matchups"/);
  assert.match(sql, /WHERE "score" > \?/);
  assert.match(sql, /ORDER BY "score" DESC/);
  assert.match(sql, /LIMIT 10/);
  assert.deepEqual(params, [150]);
});

test("compiles group by with aggregates and having", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "phase", op: "=", value: "regular" }],
      groupBy: ["owner"],
      summarise: [
        { fn: "count", as: "games" },
        { fn: "avg", field: "score", as: "avg_score" },
      ],
      having: [{ field: "games", op: ">", value: 50 }],
      arrange: [{ field: "avg_score", dir: "desc" }],
    },
    schema,
  );
  assert.match(sql, /count\(\*\) AS "games"/);
  assert.match(sql, /avg\("score"\) AS "avg_score"/);
  assert.match(sql, /GROUP BY "owner"/);
  assert.match(sql, /HAVING "games" > \?/);
  assert.deepEqual(params, ["regular", 50]);
});

test("compiles a join between two tables", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      limit: 5,
    },
    schema,
  );
  assert.match(sql, /JOIN "team_seasons"/);
  assert.match(sql, /"matchups"\."year" = "team_seasons"\."year"/);
  assert.match(sql, /"matchups"\."owner" = "team_seasons"\."owner"/);
});

test("never inlines a literal into the sql text", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "owner", op: "=", value: "'; DROP TABLE matchups; --" }],
    },
    schema,
  );
  assert.ok(!sql.includes("DROP TABLE"));
  assert.deepEqual(params, ["'; DROP TABLE matchups; --"]);
});

test("rejects an unknown table", () => {
  assert.throws(() => compileAst({ from: "secrets" }, schema), /unknown table/i);
});

test("rejects an unknown column", () => {
  assert.throws(
    () => compileAst({ from: "matchups", filter: [{ field: "ssn", op: "=", value: 1 }] }, schema),
    /unknown column/i,
  );
});

test("rejects an injected column name", () => {
  assert.throws(
    () =>
      compileAst(
        { from: "matchups", arrange: [{ field: 'score" FROM x; --', dir: "asc" }] },
        schema,
      ),
    /unknown column/i,
  );
});

test("rejects an unknown operator", () => {
  assert.throws(
    () => compileAst({ from: "matchups", filter: [{ field: "score", op: "~~", value: 1 }] }, schema),
    /unknown operator/i,
  );
});

test("rejects an unknown aggregate", () => {
  assert.throws(
    () =>
      compileAst(
        { from: "matchups", groupBy: ["owner"], summarise: [{ fn: "exec", as: "x" }] },
        schema,
      ),
    /unknown aggregate/i,
  );
});

test("clamps an oversized limit", () => {
  const { sql } = compileAst({ from: "matchups", limit: 999999 }, schema);
  assert.match(sql, new RegExp(`LIMIT ${MAX_LIMIT}`));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/js/`
Expected: FAIL — cannot find module `query-compile.js`

- [ ] **Step 3: Write the compiler**

Create `zensical/docs/javascripts/query-compile.js`:

```js
// Compile a Stat Search AST into parameterized DuckDB SQL.
//
// Pure: no DOM, no DuckDB, no network, no imports. That is what lets the
// node:test suite load it directly, and it is why every identifier must be
// validated against the schema rather than trusted from the AST.

export const MAX_LIMIT = 5000;

const OPERATORS = {
  "=": (col) => `${col} = ?`,
  "!=": (col) => `${col} != ?`,
  "<": (col) => `${col} < ?`,
  "<=": (col) => `${col} <= ?`,
  ">": (col) => `${col} > ?`,
  ">=": (col) => `${col} >= ?`,
  contains: (col) => `${col} ILIKE ?`,
  is_null: (col) => `${col} IS NULL`,
};

const AGGREGATES = {
  count: (col) => (col ? `count(${col})` : "count(*)"),
  count_distinct: (col) => `count(DISTINCT ${col})`,
  sum: (col) => `sum(${col})`,
  avg: (col) => `avg(${col})`,
  min: (col) => `min(${col})`,
  max: (col) => `max(${col})`,
  median: (col) => `median(${col})`,
  stddev: (col) => `stddev(${col})`,
};

const MULTI_VALUE = new Set(["in", "not_in"]);
const NO_VALUE = new Set(["is_null"]);

function quote(identifier) {
  // Identifiers only ever come from the schema, so this is belt and braces.
  return `"${String(identifier).replaceAll('"', '""')}"`;
}

function columnsOf(schema, table) {
  const entry = schema.tables[table];
  if (!entry) throw new Error(`unknown table: ${table}`);
  return entry.columns.map((c) => c.name);
}

function resolveColumn(schema, ast, field, extraNames = []) {
  const known = new Set(columnsOf(schema, ast.from));
  if (ast.join) for (const name of columnsOf(schema, ast.join.table)) known.add(name);
  for (const name of extraNames) known.add(name);
  if (!known.has(field)) throw new Error(`unknown column: ${field}`);
  return quote(field);
}

function compilePredicates(schema, ast, clauses, params, extraNames) {
  return clauses.map((clause) => {
    const build = OPERATORS[clause.op];
    if (!build && !MULTI_VALUE.has(clause.op) && clause.op !== "between") {
      throw new Error(`unknown operator: ${clause.op}`);
    }
    const column = resolveColumn(schema, ast, clause.field, extraNames);
    if (MULTI_VALUE.has(clause.op)) {
      const values = Array.isArray(clause.value) ? clause.value : [clause.value];
      if (values.length === 0) throw new Error(`empty value list for ${clause.field}`);
      params.push(...values);
      const holes = values.map(() => "?").join(", ");
      return clause.op === "in" ? `${column} IN (${holes})` : `${column} NOT IN (${holes})`;
    }
    if (clause.op === "between") {
      const [low, high] = clause.value;
      params.push(low, high);
      return `${column} BETWEEN ? AND ?`;
    }
    if (NO_VALUE.has(clause.op)) return build(column);
    params.push(clause.op === "contains" ? `%${clause.value}%` : clause.value);
    return build(column);
  });
}

export function compileAst(ast, schema) {
  if (!ast || typeof ast !== "object") throw new Error("ast must be an object");
  const params = [];
  const from = quote(ast.from);
  columnsOf(schema, ast.from); // throws on unknown table

  const summarise = ast.summarise ?? [];
  const groupBy = ast.groupBy ?? [];
  const aliases = summarise.map((s) => s.as);

  let select = "*";
  if (groupBy.length || summarise.length) {
    const grouped = groupBy.map((field) => resolveColumn(schema, ast, field));
    const aggregated = summarise.map((spec) => {
      const build = AGGREGATES[spec.fn];
      if (!build) throw new Error(`unknown aggregate: ${spec.fn}`);
      const inner = spec.field ? resolveColumn(schema, ast, spec.field) : null;
      if (!spec.as) throw new Error(`aggregate ${spec.fn} needs an alias`);
      return `${build(inner)} AS ${quote(spec.as)}`;
    });
    select = [...grouped, ...aggregated].join(", ");
  }

  const parts = [`SELECT ${select}`, `FROM ${from}`];

  if (ast.join) {
    const joinTable = quote(ast.join.table);
    columnsOf(schema, ast.join.table);
    const conditions = (ast.join.on ?? []).map((field) => {
      resolveColumn(schema, ast, field);
      return `${from}.${quote(field)} = ${joinTable}.${quote(field)}`;
    });
    if (!conditions.length) throw new Error("join needs at least one column");
    parts.push(`JOIN ${joinTable} ON ${conditions.join(" AND ")}`);
  }

  const where = compilePredicates(schema, ast, ast.filter ?? [], params, []);
  if (where.length) parts.push(`WHERE ${where.join(" AND ")}`);

  if (groupBy.length) {
    parts.push(`GROUP BY ${groupBy.map((f) => resolveColumn(schema, ast, f)).join(", ")}`);
  }

  const having = compilePredicates(schema, ast, ast.having ?? [], params, aliases);
  if (having.length) parts.push(`HAVING ${having.join(" AND ")}`);

  const arrange = (ast.arrange ?? []).map((spec) => {
    const column = resolveColumn(schema, ast, spec.field, aliases);
    return `${column} ${spec.dir === "asc" ? "ASC" : "DESC"}`;
  });
  if (arrange.length) parts.push(`ORDER BY ${arrange.join(", ")}`);

  const limit = Math.min(Number(ast.limit) || 200, MAX_LIMIT);
  parts.push(`LIMIT ${limit}`);

  return { sql: parts.join("\n"), params };
}

export function renderSql(sql, params) {
  // Display only: inlines parameters so the Show query panel reads naturally.
  // Never send this string to DuckDB.
  let index = 0;
  return sql.replaceAll("?", () => {
    const value = params[index++];
    return typeof value === "string" ? `'${value.replaceAll("'", "''")}'` : String(value);
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/js/`
Expected: PASS, 10 tests

- [ ] **Step 5: Add the JS suite to CI**

In `.github/workflows/deploy.yml`, change the test step to:

```yaml
      - name: Run tests
        run: |
          uv run pytest -q
          node --test tests/js/
```

- [ ] **Step 6: Commit**

```bash
rtk git add zensical/docs/javascripts/query-compile.js tests/js/query-compile.test.mjs .github/workflows/deploy.yml
rtk git commit -m "feat: compile Stat Search ASTs to parameterized DuckDB SQL"
```

---

### Task 8: DuckDB-WASM engine module

**Goal:** Boot DuckDB-WASM lazily, register the four Parquet files as views, and expose `runSql()`.

**Files:**
- Create: `zensical/docs/javascripts/query-engine.js`

**Acceptance Criteria:**
- [ ] Loads `@duckdb/duckdb-wasm` pinned to exactly `1.32.0`, `eh` bundle
- [ ] Reports download progress so the boot state is determinate, not a spinner
- [ ] Registers all four Parquet files as named views
- [ ] `runSql(sql, params)` returns `{columns, rows}`
- [ ] Boots at most once, even under concurrent calls
- [ ] A boot failure rejects with a message the UI can display

**Verify:** Open the built page, run a preset, and confirm rows render. Then check the browser network panel shows `duckdb-eh.wasm` fetched exactly once.

**Steps:**

- [ ] **Step 1: Write the engine module**

Create `zensical/docs/javascripts/query-engine.js`:

```js
// DuckDB-WASM boot and query execution for Stat Search.
//
// The version is pinned exactly. The `latest` dist-tag on @duckdb/duckdb-wasm
// currently points at a -dev prerelease, so a range here would ship a
// prerelease engine to readers.
//
// The `eh` bundle is deliberate: the threaded `coi` bundle needs
// cross-origin-isolation response headers, which GitHub Pages cannot set.

const VERSION = "1.32.0";
const CDN = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${VERSION}/dist`;

let bootPromise = null;

async function fetchWithProgress(url, onProgress) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} fetching ${url}`);
  const total = Number(response.headers.get("content-length")) || 0;
  if (!response.body || !total) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(loaded / total);
  }
  const merged = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged.buffer;
}

async function boot(base, onProgress) {
  const duckdb = await import(`${CDN}/duckdb-browser.mjs`);
  const wasm = await fetchWithProgress(`${CDN}/duckdb-eh.wasm`, onProgress);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${CDN}/duckdb-browser-eh.worker.js");`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(URL.createObjectURL(new Blob([wasm], { type: "application/wasm" })));
  URL.revokeObjectURL(workerUrl);

  const connection = await db.connect();
  const schema = await (await fetch(`${base}schema.json`)).json();
  for (const table of Object.keys(schema.tables)) {
    const url = new URL(`${base}${table}.parquet`, window.location.href).href;
    await connection.query(
      `CREATE VIEW "${table}" AS SELECT * FROM read_parquet('${url}')`,
    );
  }
  return { db, connection, schema };
}

export function startEngine(base, onProgress = () => {}) {
  if (!bootPromise) {
    bootPromise = boot(base, onProgress).catch((error) => {
      bootPromise = null; // let a later attempt retry rather than caching failure
      throw error;
    });
  }
  return bootPromise;
}

export async function runSql(base, sql, params) {
  const { connection } = await startEngine(base);
  const statement = await connection.prepare(sql);
  try {
    const table = await statement.query(...params);
    const columns = table.schema.fields.map((field) => field.name);
    const rows = table.toArray().map((row) => {
      const record = row.toJSON();
      // Arrow returns BigInt for 64-bit integers; JSON and sorting want Number.
      for (const key of Object.keys(record)) {
        if (typeof record[key] === "bigint") record[key] = Number(record[key]);
      }
      return record;
    });
    return { columns, rows };
  } finally {
    await statement.close();
  }
}
```

- [ ] **Step 2: Verify version and bundle names resolve**

Run:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.32.0/dist/duckdb-browser.mjs
```

Expected: `200`. Repeat for `duckdb-eh.wasm` and `duckdb-browser-eh.worker.js`; all three must return 200 before continuing.

- [ ] **Step 3: Commit**

```bash
rtk git add zensical/docs/javascripts/query-engine.js
rtk git commit -m "feat: boot DuckDB-WASM over the Stat Search parquet tables"
```

---

### Task 9: Presets and the verb UI

**Goal:** The page renders preset chips, an editable verb stack, a results table, and a Show query panel.

**Files:**
- Create: `zensical/docs/javascripts/query-presets.js`
- Create: `zensical/docs/javascripts/query.js`
- Modify: `zensical/docs/stylesheets/zensical.css`

**Acceptance Criteria:**
- [ ] All twelve presets run and return rows
- [ ] Filter, group by, summarise, arrange, and limit rows can each be added, edited, and removed
- [ ] Field and operator dropdowns are built from `schema.json`, not hardcoded
- [ ] Owner cells link to `owners/<slug>.md`; player cells link to `players/<slug>.md`
- [ ] Show query displays the compiled SQL
- [ ] A boot failure replaces the results area with a message linking Records and Playoffs

**Verify:** `node zensical/build.mjs`, open `zensical/site/query/index.html` in a browser, click each preset in turn, confirm all twelve return rows.

**Steps:**

- [ ] **Step 1: Write the presets**

Create `zensical/docs/javascripts/query-presets.js`:

```js
// Preset queries, as ASTs. Presets are data, not code: they load into the same
// verb stack the user edits, so every preset is a starting point rather than a
// fixed report.

export const PRESETS = [
  {
    id: "blowouts",
    label: "Biggest blowouts",
    ast: {
      from: "matchups",
      filter: [{ field: "phase", op: "=", value: "regular" }],
      arrange: [{ field: "margin", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "nailbiters",
    label: "One-score games",
    ast: {
      from: "matchups",
      filter: [
        { field: "phase", op: "=", value: "regular" },
        { field: "margin", op: "between", value: [0.01, 1] },
      ],
      arrange: [{ field: "margin", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "points-in-loss",
    label: "Most points in a loss",
    ast: {
      from: "matchups",
      filter: [{ field: "won", op: "=", value: false }],
      arrange: [{ field: "score", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "points-in-win",
    label: "Fewest points in a win",
    ast: {
      from: "matchups",
      filter: [{ field: "won", op: "=", value: true }],
      arrange: [{ field: "score", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "bench-heroes",
    label: "Highest-scoring benched players",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: false }],
      arrange: [{ field: "points", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "best-weeks",
    label: "Best single weeks",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: true }],
      arrange: [{ field: "points", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "bench-waste",
    label: "Points left on the bench, by owner",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: false }],
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "points", as: "bench_points" }],
      arrange: [{ field: "bench_points", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "position-scoring",
    label: "Scoring by position",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: true }],
      groupBy: ["position"],
      summarise: [
        { fn: "avg", field: "points", as: "avg_points" },
        { fn: "count", as: "starts" },
      ],
      arrange: [{ field: "avg_points", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "best-records",
    label: "Best regular-season records",
    ast: {
      from: "team_seasons",
      arrange: [{ field: "wins", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "weak-champions",
    label: "Champions with the fewest points",
    ast: {
      from: "team_seasons",
      filter: [{ field: "champion", op: "=", value: true }],
      arrange: [{ field: "pf", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "owner-careers",
    label: "Career totals by owner",
    ast: {
      from: "team_seasons",
      groupBy: ["owner"],
      summarise: [
        { fn: "sum", field: "wins", as: "wins" },
        { fn: "sum", field: "losses", as: "losses" },
        { fn: "count", as: "seasons" },
      ],
      arrange: [{ field: "wins", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "first-picks",
    label: "First-round picks",
    ast: {
      from: "draft",
      filter: [{ field: "round", op: "=", value: 1 }],
      arrange: [{ field: "year", dir: "desc" }],
      limit: 100,
    },
  },
];
```

- [ ] **Step 2: Write the UI**

Create `zensical/docs/javascripts/query.js`:

```js
// Stat Search UI. Owns the DOM and the AST; delegates SQL to query-compile.js
// and execution to query-engine.js.

import { compileAst, renderSql } from "./query-compile.js";
import { runSql, startEngine } from "./query-engine.js";
import { PRESETS } from "./query-presets.js";

const mount = document.getElementById("phfl-query");

const OPERATOR_LABELS = {
  "=": "is",
  "!=": "is not",
  ">": "more than",
  ">=": "at least",
  "<": "less than",
  "<=": "at most",
  between: "between",
  in: "any of",
  contains: "contains",
  is_null: "is blank",
};

const LINKED = {
  owner: (row, key) => `../owners/${slugify(row[key])}/`,
  opp_owner: (row) => `../owners/${slugify(row.opp_owner)}/`,
  player: (row) => `../players/${row.player_slug ?? slugify(row.player)}/`,
};

function slugify(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

class StatSearch {
  constructor(root, base) {
    this.root = root;
    this.base = base;
    this.ast = structuredClone(PRESETS[0].ast);
    this.schema = null;
  }

  async start() {
    this.renderShell();
    try {
      const { schema } = await startEngine(this.base, (fraction) => {
        this.progress.value = fraction;
        this.status.textContent = `Loading query engine ${Math.round(fraction * 100)}%`;
      });
      this.schema = schema;
      this.status.textContent = "";
      this.progress.hidden = true;
      this.readUrl();
      this.renderBuilder();
      await this.run();
    } catch (error) {
      this.fail(error);
    }
  }

  fail(error) {
    this.root.innerHTML = "";
    const box = element("div", "phfl-query__error");
    box.append(
      element("p", null, `Stat Search could not start: ${error.message}`),
      element("p", null, "The curated numbers are still available:"),
    );
    const list = element("ul");
    for (const [href, label] of [["../records/", "Records"], ["../playoffs/", "Playoffs"]]) {
      const item = element("li");
      const link = element("a", null, label);
      link.href = href;
      item.append(link);
      list.append(item);
    }
    box.append(list);
    this.root.append(box);
  }

  renderShell() {
    this.root.innerHTML = "";
    this.status = element("p", "phfl-query__status", "Loading query engine…");
    this.progress = document.createElement("progress");
    this.progress.max = 1;
    this.progress.value = 0;
    this.builder = element("div", "phfl-query__builder");
    this.results = element("div", "phfl-query__results");
    this.sqlPanel = document.createElement("details");
    this.sqlPanel.append(element("summary", null, "Show query"));
    this.sqlCode = document.createElement("pre");
    this.sqlPanel.append(this.sqlCode);
    this.root.append(this.status, this.progress, this.builder, this.results, this.sqlPanel);
  }

  columnsFor(table) {
    return this.schema.tables[table].columns.map((column) => column.name);
  }

  renderBuilder() {
    this.builder.innerHTML = "";

    const chips = element("div", "phfl-query__presets");
    for (const preset of PRESETS) {
      const button = element("button", "phfl-query__chip", preset.label);
      button.type = "button";
      button.addEventListener("click", () => {
        this.ast = structuredClone(preset.ast);
        this.renderBuilder();
        this.run();
      });
      chips.append(button);
    }
    this.builder.append(chips);

    const datasets = element("div", "phfl-query__datasets");
    for (const table of Object.keys(this.schema.tables)) {
      const button = element("button", "phfl-query__dataset", table.replace("_", " "));
      button.type = "button";
      button.disabled = table === this.ast.from;
      button.addEventListener("click", () => {
        this.ast = { from: table, filter: [], arrange: [], limit: 200 };
        this.renderBuilder();
        this.run();
      });
      datasets.append(button);
    }
    this.builder.append(datasets);

    this.builder.append(this.renderFilters());
    this.builder.append(this.renderSort());

    const run = element("button", "phfl-query__run", "Run query");
    run.type = "button";
    run.addEventListener("click", () => this.run());
    this.builder.append(run);
  }

  renderFilters() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Filters"));
    this.ast.filter ??= [];
    this.ast.filter.forEach((clause, index) => {
      const row = element("div", "phfl-query__verb");

      const field = document.createElement("select");
      for (const name of this.columnsFor(this.ast.from)) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === clause.field;
        field.append(option);
      }
      field.addEventListener("change", () => {
        clause.field = field.value;
      });

      const op = document.createElement("select");
      for (const [value, label] of Object.entries(OPERATOR_LABELS)) {
        const option = element("option", null, label);
        option.value = value;
        option.selected = value === clause.op;
        op.append(option);
      }
      op.addEventListener("change", () => {
        clause.op = op.value;
      });

      const value = document.createElement("input");
      value.value = Array.isArray(clause.value) ? clause.value.join(", ") : clause.value;
      value.addEventListener("change", () => {
        clause.value = parseValue(value.value, clause.op);
      });

      const remove = element("button", "phfl-query__remove", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => {
        this.ast.filter.splice(index, 1);
        this.renderBuilder();
      });

      row.append(field, op, value, remove);
      wrapper.append(row);
    });

    const add = element("button", "phfl-query__add", "Add filter");
    add.type = "button";
    add.addEventListener("click", () => {
      this.ast.filter.push({
        field: this.columnsFor(this.ast.from)[0],
        op: "=",
        value: "",
      });
      this.renderBuilder();
    });
    wrapper.append(add);
    return wrapper;
  }

  renderSort() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Sort"));
    const aliases = (this.ast.summarise ?? []).map((spec) => spec.as);
    const options = [...this.columnsFor(this.ast.from), ...aliases];
    const current = this.ast.arrange?.[0] ?? { field: options[0], dir: "desc" };

    const field = document.createElement("select");
    for (const name of options) {
      const option = element("option", null, name);
      option.value = name;
      option.selected = name === current.field;
      field.append(option);
    }

    const dir = document.createElement("select");
    for (const [value, label] of [["desc", "high to low"], ["asc", "low to high"]]) {
      const option = element("option", null, label);
      option.value = value;
      option.selected = value === current.dir;
      dir.append(option);
    }

    const apply = () => {
      this.ast.arrange = [{ field: field.value, dir: dir.value }];
    };
    field.addEventListener("change", apply);
    dir.addEventListener("change", apply);

    wrapper.append(field, dir);
    return wrapper;
  }

  async run() {
    let compiled;
    try {
      compiled = compileAst(this.ast, this.schema);
    } catch (error) {
      this.results.textContent = `That query is not valid: ${error.message}`;
      return;
    }
    this.sqlCode.textContent = renderSql(compiled.sql, compiled.params);
    this.writeUrl();
    this.results.textContent = "Running…";
    try {
      const { columns, rows } = await runSql(this.base, compiled.sql, compiled.params);
      this.renderTable(columns, rows);
    } catch (error) {
      this.results.textContent = `Query failed: ${error.message}`;
    }
  }

  renderTable(columns, rows) {
    this.results.innerHTML = "";
    this.results.append(element("p", "phfl-query__count", `${rows.length} rows`));
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const column of columns) head.append(element("th", null, column));
    table.append(head);
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const column of columns) {
        const cell = document.createElement("td");
        const linker = LINKED[column];
        if (linker && row[column]) {
          const link = element("a", null, String(row[column]));
          link.href = linker(row, column);
          cell.append(link);
        } else {
          cell.textContent = formatCell(row[column]);
        }
        tr.append(cell);
      }
      table.append(tr);
    }
    this.results.append(table);
  }

  writeUrl() {
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(this.ast))));
    const url = new URL(window.location.href);
    url.searchParams.set("q", encoded);
    window.history.replaceState(null, "", url);
  }

  readUrl() {
    const encoded = new URL(window.location.href).searchParams.get("q");
    if (!encoded) return;
    try {
      this.ast = JSON.parse(decodeURIComponent(escape(atob(encoded))));
    } catch {
      // A malformed link falls back to the default preset rather than erroring.
    }
  }
}

function parseValue(raw, op) {
  if (op === "between" || op === "in") {
    return raw.split(",").map((part) => coerce(part.trim()));
  }
  return coerce(raw.trim());
}

function coerce(raw) {
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (raw !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  return raw;
}

function formatCell(value) {
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value ?? "");
}

if (mount) {
  const base = mount.dataset.queryBase ?? "../query/";
  new StatSearch(mount, base).start();
}
```

- [ ] **Step 3: Add styles**

Append to `zensical/docs/stylesheets/zensical.css`:

```css
/* Stat Search */
.phfl-query__presets,
.phfl-query__datasets {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.8rem;
}

.phfl-query__chip,
.phfl-query__dataset,
.phfl-query__run,
.phfl-query__add,
.phfl-query__remove {
  border: 1px solid var(--md-default-fg-color--lighter);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  padding: 0.25rem 0.7rem;
}

.phfl-query__dataset:disabled {
  background: var(--md-accent-fg-color);
  color: var(--md-accent-bg-color);
  cursor: default;
}

.phfl-query__verb {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}

.phfl-query__results {
  overflow-x: auto;
}

.phfl-query__count {
  font-variant-numeric: tabular-nums;
  opacity: 0.7;
}

.phfl-query__error {
  border-left: 3px solid var(--md-accent-fg-color);
  padding-left: 0.8rem;
}
```

- [ ] **Step 4: Build and exercise every preset**

Run: `node zensical/build.mjs`

Then serve the built site and open the page — opening `zensical/site/query/index.html` from the filesystem will not work, because module imports and Parquet fetches need an HTTP origin:

```bash
uv run python -m http.server 8000 --directory zensical/site
```

Open `http://localhost:8000/query/`. Click each of the twelve presets in turn and confirm each returns rows. Then confirm in the network panel that `duckdb-eh.wasm` was fetched exactly once across all twelve.

- [ ] **Step 5: Commit**

```bash
rtk git add zensical/docs/javascripts/query-presets.js zensical/docs/javascripts/query.js zensical/docs/stylesheets/zensical.css
rtk git commit -m "feat: add the Stat Search verb builder and presets"
```

---

### Task 10: Aggregation verbs and shareable links

**Goal:** Group by and summarise are editable in the UI, and a shared URL restores the full verb stack.

**Files:**
- Modify: `zensical/docs/javascripts/query.js`
- Modify: `tests/js/query-compile.test.mjs`

**Acceptance Criteria:**
- [ ] Group-by columns can be added and removed
- [ ] Summarise rows choose an aggregate, a column, and an alias
- [ ] Sort offers summarise aliases alongside table columns
- [ ] Copying the URL and opening it in a new tab restores the same query and results
- [ ] A malformed `q` parameter falls back to the default preset without an error

**Verify:** Load a grouped preset, copy the URL, open it in a new private window, confirm identical results.

**Steps:**

- [ ] **Step 1: Add the aggregation verb renderer**

In `zensical/docs/javascripts/query.js`, add this method to `StatSearch`:

```js
  renderAggregation() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Group and summarise"));
    this.ast.groupBy ??= [];
    this.ast.summarise ??= [];

    const group = element("div", "phfl-query__verb");
    for (const name of this.columnsFor(this.ast.from)) {
      const label = element("label", "phfl-query__group");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = this.ast.groupBy.includes(name);
      box.addEventListener("change", () => {
        if (box.checked) this.ast.groupBy.push(name);
        else this.ast.groupBy = this.ast.groupBy.filter((n) => n !== name);
        this.renderBuilder();
      });
      label.append(box, document.createTextNode(` ${name}`));
      group.append(label);
    }
    wrapper.append(group);

    this.ast.summarise.forEach((spec, index) => {
      const row = element("div", "phfl-query__verb");

      const fn = document.createElement("select");
      for (const name of ["count", "count_distinct", "sum", "avg", "min", "max", "median", "stddev"]) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === spec.fn;
        fn.append(option);
      }
      fn.addEventListener("change", () => {
        spec.fn = fn.value;
        this.renderBuilder();
      });

      const field = document.createElement("select");
      const blank = element("option", null, "(all rows)");
      blank.value = "";
      field.append(blank);
      for (const name of this.columnsFor(this.ast.from)) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === spec.field;
        field.append(option);
      }
      field.addEventListener("change", () => {
        spec.field = field.value || undefined;
      });

      const alias = document.createElement("input");
      alias.value = spec.as ?? "";
      alias.addEventListener("change", () => {
        spec.as = alias.value.trim() || `${spec.fn}_${spec.field ?? "all"}`;
        this.renderBuilder();
      });

      const remove = element("button", "phfl-query__remove", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => {
        this.ast.summarise.splice(index, 1);
        this.renderBuilder();
      });

      row.append(fn, field, alias, remove);
      wrapper.append(row);
    });

    const add = element("button", "phfl-query__add", "Add summary");
    add.type = "button";
    add.addEventListener("click", () => {
      this.ast.summarise.push({ fn: "count", as: "rows" });
      this.renderBuilder();
    });
    wrapper.append(add);
    return wrapper;
  }
```

- [ ] **Step 2: Call it from renderBuilder**

In `renderBuilder`, replace:

```js
    this.builder.append(this.renderFilters());
    this.builder.append(this.renderSort());
```

with:

```js
    this.builder.append(this.renderFilters());
    this.builder.append(this.renderAggregation());
    this.builder.append(this.renderSort());
```

- [ ] **Step 3: Add a compiler test for alias sorting**

Append to `tests/js/query-compile.test.mjs`:

```js
test("sorting by a summarise alias is allowed", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "score", as: "total" }],
      arrange: [{ field: "total", dir: "desc" }],
    },
    schema,
  );
  assert.match(sql, /ORDER BY "total" DESC/);
});

test("sorting by an unknown alias still throws", () => {
  assert.throws(
    () =>
      compileAst(
        {
          from: "matchups",
          groupBy: ["owner"],
          summarise: [{ fn: "sum", field: "score", as: "total" }],
          arrange: [{ field: "nonsense", dir: "desc" }],
        },
        schema,
      ),
    /unknown column/i,
  );
});
```

- [ ] **Step 4: Run the tests**

Run: `node --test tests/js/`
Expected: PASS, 12 tests

- [ ] **Step 5: Verify link sharing by hand**

Run: `node zensical/build.mjs && uv run python -m http.server 8000 --directory zensical/site`

Open `http://localhost:8000/query/`, click "Points left on the bench, by owner", copy the URL from the address bar, open it in a private window, and confirm the verb stack and the result rows are identical.

Then open `http://localhost:8000/query/?q=not-valid-base64` and confirm the page loads the default preset rather than showing an error.

- [ ] **Step 6: Commit**

```bash
rtk git add zensical/docs/javascripts/query.js tests/js/query-compile.test.mjs
rtk git commit -m "feat: add Stat Search aggregation verbs and shareable links"
```

---

## Self-Review Notes

**Spec coverage.** Every spec section maps to a task: data model (1-3), build pipeline (4, 6), runtime architecture (8), AST (7, 10), compiler and safety contract (7), UI (9, 10), presets (9), URL state (10), nav (6), testing (1-5, 7, 10), no-JS fallback (6, 9).

**Two spec items deliberately deferred, with reasons:**

1. **Named window functions** (`rank_in_season`, `streak_len`, `rolling_avg_3`). The spec lists these as v1. They are not in any task above, because every one of them needs a UI vocabulary — which column to partition by, which to order by — that does not exist until the verb stack is real. Building them blind would mean guessing that vocabulary. Add them as Task 11 once Task 10 is merged and the shape of the verb rows is settled.

2. **Copy-as-CSV.** Listed in the spec's UI section, dropped from Task 9 to keep that task to one concern. It is a ten-line addition to `renderTable` and should ride along with Task 11.

Neither is load-bearing for the tab to work. Both should be picked up before calling the feature done.

**Type consistency.** `compileAst(ast, schema)` and `renderSql(sql, params)` keep the same signatures in Tasks 7, 9 and 10. `startEngine(base, onProgress)` and `runSql(base, sql, params)` are used in Task 9 exactly as defined in Task 8. `owner_index(seasons, bible)` takes the same arguments across Tasks 1, 2, 3 and 4. `build_all(content_dir)` returns the schema dict in both Task 4 and Task 6.

**Verification honesty.** Tasks 8, 9 and 10 close on browser checks that cannot run in CI. That is a real gap: the compiler is unit-tested, the builder is unit-tested, but the wiring between them is only ever checked by a person opening the page. If that proves too fragile, the fix is a Playwright smoke test, which would be its own plan.
