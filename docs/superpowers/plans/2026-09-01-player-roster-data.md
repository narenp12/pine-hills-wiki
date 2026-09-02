# Player and Roster Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture every week's Yahoo rosters with per-player points for 2018-2025, land them in `raw/<year>.json`, and use them to fill the empty roster tables, the empty draft positions, a new player record book, and the four `_TBD_` season awards.

**Architecture:** Three layers, in order. `harvest_v2.py` gains one nested roster+stats API call per week, cached in the gitignored `dump/v2/`. `parse_v2.rs` gains `parse_rosters()`, feeding the `weeks[wk].rosters` container the model already defines, keyed by team **name** (the key `model_contract.rs` already asserts). `generate.py` reads that container for season-page roster blocks, team-page links, draft-position backfill, a player-keyed record book, and computed awards.

**Tech Stack:** Rust (serde_json, anyhow) for parse/merge; Python 3.11 + pytest for generation; Yahoo Fantasy v2 read-only API (`pub-api-ro`) over CDP from a logged-in Edge session.

**User decisions (already made):**
- Capture every week with per-player weekly points, not two snapshots per season.
- Enrich existing pages only — no `Players` index, no page per player.
- Season pages render one collapsed admonition per team.
- Store in the existing `weeks[wk].rosters` slot in `raw/<year>.json`; no sidecar, no lossy aggregation.
- Best Draft Pick and Biggest Bust are computed, with the formula printed beside the award.

**Spec:** [`docs/superpowers/specs/2026-09-01-player-roster-data-design.md`](../specs/2026-09-01-player-roster-data-design.md)

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scraper/scripts/probe_rosters.py` | One-shot endpoint probe; not part of the pipeline | Create |
| `scraper/scripts/harvest_v2.py` | Fetch + cache raw v2 payloads | Modify |
| `scraper/src/model.rs` | Canonical JSON shape | Modify (`RosterPlayer`) |
| `scraper/src/parse_v2.rs` | Pure offline v2 parser | Modify (`parse_rosters`, `from_v2_dir`) |
| `scraper/src/main.rs` | Merge fresh v2 output into `raw/<year>.json` | Modify (authoritative key list) |
| `scraper/tests/v2_parse.rs` | Parser tests against committed fixtures | Modify |
| `scraper/tests/model_contract.rs` | Locks the JSON shape generate.py reads | Modify |
| `scraper/tests/fixtures/2024-449.l.489811-rosters-wk01.json` | Trimmed roster fixture | Create |
| `scripts/generate.py` | Markdown generation | Modify (5 areas) |
| `tests/test_player_roster.py` | Tests for every new generator function | Create |
| `README.md`, `scraper/HANDOFF.md` | Pipeline docs | Modify |

---

## Task 1: Probe the roster endpoint

**Goal:** Confirm the nested roster+stats endpoint answers with players and weekly points before committing to a 131-request harvest.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `scraper/scripts/probe_rosters.py`

**Acceptance Criteria:**
- [ ] Probe prints HTTP 200 for at least one of the two candidate paths
- [ ] Printed sample shows a player with a non-empty `name.full`, a `selected_position`, and a numeric `player_points.total`
- [ ] Winning path and observed JSON pointer path are written into the script's docstring as a comment for Task 3 to parse against
- [ ] Full payload saved to `scraper/dump/v2/` (gitignored)

**Verify:** `cd scraper && uv run --with websocket-client python3 scripts/probe_rosters.py http://127.0.0.1:9222` → prints `OK <path>` and a sample player line

**Steps:**

- [ ] **Step 1: Start the logged-in browser**

The probe drives an existing Edge session; it never logs in.

```bash
cd scraper && ./run-edge.sh
```

Leave the window open and logged in to Yahoo Fantasy.

- [ ] **Step 2: Write the probe script**

`scraper/scripts/probe_rosters.py`:

```python
#!/usr/bin/env python3
"""One-shot probe: does the nested roster+stats endpoint answer?

Reuses harvest_v2's CDP plumbing so the request comes from the fantasy page's
own JS context (session cookies + Origin match what Yahoo expects). Read-only
GET, two requests maximum, then it exits.

Usage:
  uv run --with websocket-client python3 scripts/probe_rosters.py <edge>

RESULT (fill in after running — Task 3 parses against this):
  winning path: <path>
  players at:   <json pointer>
"""
import json
import os
import sys
import time
import urllib.request

from websocket import create_connection

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_v2 import API_BASE, ORIGIN_PAGE, fetch, send

# 2024 Pine Hills. Its standings payload is already cached in dump/v2, so the
# key is known-good rather than guessed.
LEAGUE_KEY = "449.l.489811"
WEEK = 1

CANDIDATES = [
    # Preferred: roster and weekly points in ONE response.
    f"league/{LEAGUE_KEY}/teams/roster;week={WEEK}/players/stats;type=week;week={WEEK}",
    # Fallback: roster only. If this is the one that answers, the harvest needs
    # a second call per week for points.
    f"league/{LEAGUE_KEY}/teams/roster;week={WEEK}",
]


def sample_player(doc):
    """Walk to the first player object and return (pointer, player) or (None, None)."""
    teams = doc.get("fantasy_content", {}).get("league", {}).get("teams")
    if not isinstance(teams, list) or not teams:
        return None, None
    team = teams[0].get("team", teams[0])
    players = (team.get("roster") or {}).get("players")
    if not isinstance(players, list) or not players:
        return None, None
    player = players[0].get("player", players[0])
    return "/fantasy_content/league/teams/0/team/roster/players/0/player", player


def main():
    base = sys.argv[1]
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dump", "v2")
    os.makedirs(outdir, exist_ok=True)

    ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=10))
    conn = create_connection(ver["webSocketDebuggerUrl"], timeout=120)
    tid = send(conn, "Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send(conn, "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    send(conn, "Page.enable", {}, sid)
    send(conn, "Runtime.enable", {}, sid)
    send(conn, "Page.navigate", {"url": ORIGIN_PAGE}, sid)
    time.sleep(9)

    for path in CANDIDATES:
        url = f"{API_BASE}/{path}?format=json_f"
        res = fetch(conn, sid, url)
        status, body = res.get("status"), res.get("body", "")
        print(f"{status} {len(body):>8}b  {path}")
        if status != 200:
            time.sleep(5)
            continue
        doc = json.loads(body)
        pointer, player = sample_player(doc)
        if not player:
            print("   200 but no players found — dumping top-level keys:")
            print("  ", list(doc.get("fantasy_content", {}).keys()))
            time.sleep(5)
            continue
        out = os.path.join(outdir, f"probe-rosters-wk{WEEK:02d}.json")
        with open(out, "w") as f:
            f.write(body)
        print(f"OK {path}")
        print(f"   players at: {pointer}")
        print("   name       :", (player.get("name") or {}).get("full"))
        print("   position   :", player.get("primary_position"))
        print("   slot       :", (player.get("selected_position") or {}).get("position"))
        print("   points     :", (player.get("player_points") or {}).get("total"))
        print(f"   saved -> {out}")
        break
    else:
        print("FAIL: neither candidate returned usable roster data")
        sys.exit(1)

    send(conn, "Target.closeTarget", {"targetId": tid})
    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the probe**

Run: `cd scraper && uv run --with websocket-client python3 scripts/probe_rosters.py http://127.0.0.1:9222`

Expected: a line `OK league/449.l.489811/teams/roster;week=1/players/stats;type=week;week=1`, followed by a sample player with all four fields non-empty.

If the first candidate returns non-200 and the second succeeds, the nested form is rejected: record that in the docstring, and Task 5 must issue two calls per week instead of one.

If `selected_position` or `player_points.total` come back empty on the winning path, stop and report — the record book and awards in Tasks 10 and 11 depend on both.

- [ ] **Step 4: Record the result and commit**

Fill in the `RESULT` block in the docstring with the winning path and the pointer the probe printed.

```bash
git add scraper/scripts/probe_rosters.py
git commit -m "feat(scraper): probe script for the v2 roster endpoint"
```

---

## Task 2: Extend RosterPlayer with slot and points

**Goal:** The canonical model carries lineup slot and weekly points, and the contract test locks them.

**Files:**
- Modify: `scraper/src/model.rs:45-49`
- Modify: `scraper/tests/model_contract.rs:55-64` and `:108-116`

**Acceptance Criteria:**
- [ ] `RosterPlayer` serializes `name`, `position`, `slot`, `points`
- [ ] Contract test asserts all four in `weeks.1.rosters.<team>.players[0]`
- [ ] `cargo test` passes

**Verify:** `cd scraper && cargo test` → all tests pass, including `emitted_json_matches_generator_contract`

**Steps:**

- [ ] **Step 1: Write the failing assertions**

In `scraper/tests/model_contract.rs`, extend the sample roster player:

```rust
    let mut ros = BTreeMap::new();
    ros.insert(
        "Example FC".to_string(),
        Roster {
            players: vec![RosterPlayer {
                name: "Christian McCaffrey".into(),
                position: "RB".into(),
                slot: "RB".into(),
                points: 24.7,
            }],
        },
    );
```

and extend the roster assertions:

```rust
    // weeks.<n>.rosters keyed by team -> {players:[{name,position,slot,points}]}
    let r1 = &v["weeks"]["1"]["rosters"]["Example FC"]["players"];
    assert!(
        r1.is_array(),
        "weeks.1.rosters.Example FC.players must be a list"
    );
    assert_eq!(r1[0]["name"], "Christian McCaffrey");
    assert_eq!(r1[0]["position"], "RB");
    // slot is what separates a starter from a bench row; generate.py's player
    // record book cannot be computed without it.
    assert_eq!(r1[0]["slot"], "RB");
    assert_eq!(r1[0]["points"], 24.7);
    assert!(v["weeks"]["18"]["rosters"]["Example FC"]["players"].is_array());
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scraper && cargo test --test model_contract`
Expected: FAIL — `struct RosterPlayer has no field named slot`

- [ ] **Step 3: Add the fields**

In `scraper/src/model.rs`, replace the `RosterPlayer` struct:

```rust
#[derive(Debug, Serialize, Default, Clone)]
pub struct RosterPlayer {
    pub name: String,
    pub position: String,
    /// Lineup slot Yahoo had the player in that week ("QB", "W/R/T", "BN", "IR").
    /// Bench rows are what make start/sit questions answerable at all.
    pub slot: String,
    pub points: f64,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scraper && cargo test`
Expected: PASS, all tests

- [ ] **Step 5: Commit**

```bash
git add scraper/src/model.rs scraper/tests/model_contract.rs
git commit -m "feat(scraper): carry lineup slot and weekly points on RosterPlayer"
```

---

## Task 3: Parse roster payloads

**Goal:** `parse_rosters()` turns one week's roster payload into `(week, BTreeMap<team_name, Roster>)`, tested against a committed fixture.

**Files:**
- Create: `scraper/tests/fixtures/2024-449.l.489811-rosters-wk01.json`
- Modify: `scraper/src/parse_v2.rs`
- Modify: `scraper/tests/v2_parse.rs`

**Acceptance Criteria:**
- [ ] Fixture holds two teams with three players each, trimmed from the probe payload
- [ ] `parse_rosters` returns the week number and one entry per team, keyed by team **name**
- [ ] A bench player parses with `slot == "BN"`
- [ ] `cargo test` passes

**Verify:** `cd scraper && cargo test --test v2_parse` → `parses_rosters_with_slots_and_points` passes

**Steps:**

- [ ] **Step 1: Build the trimmed fixture**

From the probe payload saved in Task 1, keep two teams and three players each (one starter, one flex, one bench). Full-week payloads are hundreds of KB; a fixture that size does not belong in git.

```bash
cd scraper && python3 - <<'PY'
import json
doc = json.load(open("dump/v2/probe-rosters-wk01.json"))
league = doc["fantasy_content"]["league"]
teams = league["teams"][:2]
for entry in teams:
    t = entry.get("team", entry)
    players = t["roster"]["players"]
    starters = [p for p in players if (p.get("player", p).get("selected_position") or {}).get("position") not in ("BN", "IR")]
    bench = [p for p in players if (p.get("player", p).get("selected_position") or {}).get("position") == "BN"]
    t["roster"]["players"] = starters[:2] + bench[:1]
league["teams"] = teams
json.dump(doc, open("tests/fixtures/2024-449.l.489811-rosters-wk01.json", "w"), indent=1)
print("teams:", len(teams))
PY
```

Expected: `teams: 2`

- [ ] **Step 2: Write the failing test**

Append to `scraper/tests/v2_parse.rs`:

```rust
#[test]
fn parses_rosters_with_slots_and_points() {
    let text = fixture("2024-449.l.489811-rosters-wk01.json");
    let (week, rosters) = phf_scraper::parse_v2::parse_rosters(&text).expect("parse rosters");

    assert_eq!(week, 1);
    assert_eq!(rosters.len(), 2, "one entry per team in the fixture");

    // Keyed by team NAME, which is the key model_contract.rs asserts and the key
    // generate.py joins on.
    let (name, roster) = rosters.iter().next().expect("at least one team");
    assert!(!name.is_empty(), "team key must be the team name, not empty");
    assert_eq!(roster.players.len(), 3);

    let p = &roster.players[0];
    assert!(!p.name.is_empty(), "player name populated");
    assert!(!p.position.is_empty(), "primary position populated");
    assert!(!p.slot.is_empty(), "selected position populated");

    // The bench row is the whole reason slot exists.
    assert!(
        roster.players.iter().any(|p| p.slot == "BN"),
        "fixture must include a benched player"
    );
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd scraper && cargo test --test v2_parse parses_rosters`
Expected: FAIL — `cannot find function parse_rosters in module parse_v2`

- [ ] **Step 4: Implement the parser**

Add to `scraper/src/parse_v2.rs`. Update the import line to bring in the roster types:

```rust
use crate::model::{Champions, MatchTeam, Matchup, Roster, RosterPlayer, Season, Team};
```

then append:

```rust
/// Parse a `league/<key>/teams/roster;week=N/players/stats` payload.
///
/// Returns `(week, team_name -> Roster)`. Keyed by NAME rather than Yahoo's
/// `team_key` because that is what `model_contract.rs` locks and what
/// generate.py joins against — the generator never sees Yahoo's keys.
///
/// The week is read from the request echo rather than assumed, so a mislabeled
/// file cannot silently land a week's rosters under the wrong number.
pub fn parse_rosters(json: &str) -> Result<(i64, std::collections::BTreeMap<String, Roster>)> {
    let doc: Value = serde_json::from_str(json).context("roster payload is not valid JSON")?;
    let league = doc
        .pointer("/fantasy_content/league")
        .context("no fantasy_content.league in roster payload")?;
    let teams = league
        .pointer("/teams")
        .and_then(Value::as_array)
        .context("no league.teams array in roster payload")?;

    let mut week = 0_i64;
    let mut out = std::collections::BTreeMap::new();

    for entry in teams {
        let t = unwrap_entry(entry, "team");
        let name = as_str(&t["name"]);
        if name.is_empty() {
            continue;
        }
        let roster = &t["roster"];
        // Every team echoes the same week; take the first non-zero one.
        if week == 0 {
            week = as_i64(&roster["week"]);
        }
        let players = roster
            .pointer("/players")
            .and_then(Value::as_array)
            .map(Vec::as_slice)
            .unwrap_or(&[]);

        let mut parsed = Vec::with_capacity(players.len());
        for pentry in players {
            let p = unwrap_entry(pentry, "player");
            parsed.push(RosterPlayer {
                name: as_str(&p["name"]["full"]),
                position: as_str(&p["primary_position"]),
                slot: as_str(&p["selected_position"]["position"]),
                points: as_f64(&p["player_points"]["total"]),
            });
        }
        out.insert(name, Roster { players: parsed });
    }

    anyhow::ensure!(!out.is_empty(), "roster payload contained no teams");
    Ok((week, out))
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd scraper && cargo test --test v2_parse parses_rosters`
Expected: PASS

If the week assertion fails because `roster.week` is absent in the payload, read it from the filename in Task 4 instead and relax this test to `assert!(week == 1 || week == 0)` — but check the payload first; a present field is better than a parsed filename.

- [ ] **Step 6: Commit**

```bash
git add scraper/src/parse_v2.rs scraper/tests/v2_parse.rs scraper/tests/fixtures/2024-449.l.489811-rosters-wk01.json
git commit -m "feat(scraper): parse v2 roster payloads into slot/points rows"
```

---

## Task 4: Assemble rosters into the season and keep them through the merge

**Goal:** `from_v2_dir` fills `season.weeks[wk].rosters`, and `build_from_v2` stops discarding it on rebuild.

**Files:**
- Modify: `scraper/src/parse_v2.rs` (`from_v2_dir`)
- Modify: `scraper/src/main.rs:122-130`
- Modify: `scraper/tests/v2_parse.rs`

**Acceptance Criteria:**
- [ ] `from_v2_dir` discovers roster files by the same directory scan used for scoreboards
- [ ] `"weeks"` is in the authoritative-key list in `build_from_v2`
- [ ] A regression test asserts the merge preserves rosters, mirroring the existing draft-pick guard
- [ ] `cargo test` passes

**Verify:** `cd scraper && cargo test` → all tests pass

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `scraper/tests/v2_parse.rs`:

```rust
/// REGRESSION: `build_from_v2` overwrites only the keys it lists as authoritative.
/// Rosters live under `weeks`, so omitting that key from the list means every
/// rebuild silently drops them — the same failure mode the draft-pick guard exists
/// to catch.
#[test]
fn weeks_is_authoritative_in_the_merge() {
    let src = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src/main.rs"),
    )
    .expect("read main.rs");
    let list_start = src
        .find("// Exactly the keys the v2 path is authoritative for.")
        .expect("authoritative key list comment");
    let list = &src[list_start..list_start + 400];
    assert!(
        list.contains("\"weeks\""),
        "\"weeks\" must be in the authoritative key list or rosters are dropped on rebuild"
    );
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scraper && cargo test --test v2_parse weeks_is_authoritative`
Expected: FAIL — `"weeks" must be in the authoritative key list or rosters are dropped on rebuild`

- [ ] **Step 3: Add rosters to the assembly**

In `scraper/src/parse_v2.rs`, inside `from_v2_dir`, after the existing scoreboard loop that ends with `s.matchups.insert(week.to_string(), ws.matchups);`, add a second directory scan:

```rust
    // Rosters are a separate harvest file per week. Same discovery pattern as the
    // scoreboards: read what is on disk rather than assuming a week range, since
    // 2018 ran weeks 3-16 and later seasons 1-17.
    for entry in std::fs::read_dir(dir).with_context(|| format!("reading {}", dir.display()))? {
        let path = entry?.path();
        let Some(fname) = path.file_name().and_then(|f| f.to_str()) else {
            continue;
        };
        let prefix = format!("{season}-{league_key}-rosters-wk");
        if !fname.starts_with(&prefix) || !fname.ends_with(".json") {
            continue;
        }
        let text = std::fs::read_to_string(&path)
            .with_context(|| format!("reading {}", path.display()))?;
        let (week, rosters) =
            parse_rosters(&text).with_context(|| format!("parsing {}", path.display()))?;
        s.weeks.entry(week.to_string()).or_default().rosters = rosters;
    }
```

- [ ] **Step 4: Add `weeks` to the merge**

In `scraper/src/main.rs`, extend the authoritative key list:

```rust
        // Exactly the keys the v2 path is authoritative for.
        for k in [
            "season",
            "standings",
            "teams",
            "playoffs",
            "matchups",
            "champions",
            "bracket",
            // Rosters live here. Without it every rebuild drops them, the same way
            // omitting "draft" would drop the picks.
            "weeks",
        ] {
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scraper && cargo test`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add scraper/src/parse_v2.rs scraper/src/main.rs scraper/tests/v2_parse.rs
git commit -m "feat(scraper): assemble weekly rosters and keep them through the merge"
```

---

## Task 5: Harvest rosters for every week

**Goal:** `harvest_v2.py` fetches one roster payload per week per season, resumable and rate-limited exactly like the existing calls.

**Files:**
- Modify: `scraper/scripts/harvest_v2.py`

**Acceptance Criteria:**
- [ ] One roster request per week, alongside the existing scoreboard request
- [ ] Output named `{season}-{key}-rosters-wk{NN}.json`, matching the prefix Task 4 scans for
- [ ] Existing `already_have()` resume check applies unchanged
- [ ] The docstring's request-count description is updated

**Verify:** `cd scraper && uv run --with websocket-client python3 scripts/harvest_v2.py http://127.0.0.1:9222 dump/v2` → completes with `failed=0`

**Steps:**

- [ ] **Step 1: Update the fetch loop**

In `scraper/scripts/harvest_v2.py`, replace the per-season loop:

```python
    for s in seasons:
        print(f">> {s['season']} {s['key']} weeks {s['start']}-{s['end']}")
        get(conn, sid, f"league/{s['key']}/standings",
            os.path.join(outdir, f"{s['season']}-{s['key']}-standings.json"), stats)
        for wk in range(s["start"], s["end"] + 1):
            get(conn, sid, f"league/{s['key']}/scoreboard;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-scoreboard-wk{wk:02d}.json"), stats)
            # Rosters + that week's player points in one response. The nested form
            # is confirmed by scripts/probe_rosters.py.
            get(conn, sid,
                f"league/{s['key']}/teams/roster;week={wk}/players/stats;type=week;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-rosters-wk{wk:02d}.json"), stats)
```

If Task 1 found the nested form rejected, use two calls instead:

```python
            get(conn, sid, f"league/{s['key']}/teams/roster;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-rosters-wk{wk:02d}.json"), stats)
            get(conn, sid, f"league/{s['key']}/players/stats;type=week;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-playerstats-wk{wk:02d}.json"), stats)
```

and extend `parse_rosters` in Task 3 to join the two by player id before proceeding.

- [ ] **Step 2: Update the request-count line in the docstring**

Replace:

```
Fetches, per season: one `standings` call + one `scoreboard;week=N` call for each
week in the league's real start_week..end_week range (2018 starts at week 3).
```

with:

```
Fetches, per season: one `standings` call, plus a `scoreboard;week=N` and a
`teams/roster;week=N/players/stats` call for each week in the league's real
start_week..end_week range (2018 starts at week 3). Roster payloads are large;
expect dump/v2 to reach tens of MB. It is gitignored.
```

- [ ] **Step 3: Update the total count line**

Replace:

```python
    total = len(seasons) + sum(s["end"] - s["start"] + 1 for s in seasons)
```

with:

```python
    total = len(seasons) + 2 * sum(s["end"] - s["start"] + 1 for s in seasons)
```

- [ ] **Step 4: Commit**

```bash
git add scraper/scripts/harvest_v2.py
git commit -m "feat(scraper): harvest weekly rosters with player points"
```

---

## Task 6: Run the harvest and rebuild raw JSON

**Goal:** All eight seasons carry non-empty `weeks[*].rosters` in `raw/<year>.json`.

**Files:**
- Modify: `raw/2018.json` through `raw/2025.json` (generated)

**Acceptance Criteria:**
- [ ] Harvest completes with `failed=0`
- [ ] Every `raw/<year>.json` has at least ten weeks with non-empty rosters
- [ ] Draft-pick counts are unchanged (the existing merge guard passes)

**Verify:** the audit script in Step 3 → prints eight rows, none with `weeks_with_rosters=0`

**Steps:**

- [ ] **Step 1: Harvest**

```bash
cd scraper && uv run --with websocket-client python3 scripts/harvest_v2.py http://127.0.0.1:9222 dump/v2
```

Expected: `DONE. fetched=<n> skipped=<n> failed=0`. Roughly 22 minutes for a cold run at the 5s spacing. It is resumable — re-run to retry failures only.

- [ ] **Step 2: Rebuild**

```bash
cd scraper && cargo run -- --from-v2 dump/v2 --seasons 2018-2025 --out ../raw
```

Expected: no `merge dropped draft picks` error for any season.

- [ ] **Step 3: Audit what landed**

```bash
python3 - <<'PY'
import json, pathlib
for p in sorted(pathlib.Path("raw").glob("20*.json")):
    d = json.load(open(p))
    weeks = d.get("weeks") or {}
    with_ros = [w for w, v in weeks.items() if (v or {}).get("rosters")]
    players = sum(len(r.get("players") or [])
                  for w in with_ros
                  for r in weeks[w]["rosters"].values())
    picks = len((d.get("draft") or {}).get("draft_results") or [])
    print(f"{p.stem}  weeks_with_rosters={len(with_ros):>3}  player_rows={players:>5}  picks={picks:>3}")
PY
```

Expected: eight rows, each with `weeks_with_rosters` of at least 10 and `player_rows` in the low thousands. A zero anywhere means Task 4's filename prefix does not match what Task 5 wrote — compare `ls scraper/dump/v2 | head`.

- [ ] **Step 4: Commit the data**

```bash
git add raw/20*.json
git commit -m "data: weekly rosters with player points, 2018-2025"
```

---

## Task 7: Render team rosters on season pages

**Goal:** Each season page shows one collapsed admonition per team with both roster snapshots.

**Files:**
- Modify: `scripts/generate.py` (new helpers near `gen_season`, and the template at `:1095`)
- Create: `tests/test_player_roster.py`

**Acceptance Criteria:**
- [ ] `roster_snapshot_weeks` returns the first and last week that actually has rosters, not hard-coded 1 and 17
- [ ] Starters sort above bench, and rows carry slot, name, position, points
- [ ] A season with no roster data renders a single explanatory line, not a broken table
- [ ] `uv run pytest -q` passes

**Verify:** `uv run pytest tests/test_player_roster.py -v` → all tests pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

`tests/test_player_roster.py`:

```python
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import roster_snapshot_weeks, roster_table, team_roster_blocks


def season_with_rosters():
    def roster(pts):
        return {
            "players": [
                {"name": "Bench Guy", "position": "WR", "slot": "BN", "points": 30.0},
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": pts},
            ]
        }

    return {
        "standings": {"teams": [{"name": "Team A", "rank": 1}]},
        "weeks": {
            "3": {"rosters": {"Team A": roster(20.0)}},
            "9": {"rosters": {}},
            "16": {"rosters": {"Team A": roster(25.0)}},
        },
    }


def test_snapshot_weeks_skip_empty_weeks():
    # 2018 ran weeks 3-16, so 1 and 17 must never be assumed.
    assert roster_snapshot_weeks(season_with_rosters()) == (3, 16)


def test_snapshot_weeks_when_no_rosters():
    assert roster_snapshot_weeks({"weeks": {}}) == (None, None)


def test_roster_table_puts_starters_above_bench():
    rows = roster_table(season_with_rosters()["weeks"]["3"]["rosters"]["Team A"])
    body = [r for r in rows if r.startswith("| ") and "Slot" not in r]
    assert "Starter QB" in body[0]
    assert "Bench Guy" in body[1]


def test_roster_blocks_render_both_snapshots():
    out = team_roster_blocks(season_with_rosters(), [{"name": "Team A"}])
    assert '??? note "Team A"' in out
    assert "**Post-draft — week 3**" in out
    assert "**End of season — week 16**" in out
    # Admonition content must be indented or Zensical drops it out of the block.
    assert "    | Slot | Player | Pos | Pts |" in out


def test_roster_blocks_without_data():
    out = team_roster_blocks({"weeks": {}}, [{"name": "Team A"}])
    assert "_TBD" in out
    assert "???" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_player_roster.py -v`
Expected: FAIL — `ImportError: cannot import name 'roster_snapshot_weeks'`

- [ ] **Step 3: Implement the helpers**

In `scripts/generate.py`, above `def gen_season(`:

```python
# Yahoo's slot vocabulary, in the order a lineup card reads. Anything unknown
# sorts after the named slots but before the bench.
ROSTER_SLOT_ORDER = [
    "QB", "RB", "WR", "TE", "W/R", "W/T", "W/R/T", "Q/W/R/T", "K", "DEF", "D/ST",
]
BENCH_SLOTS = {"BN", "IR"}


def roster_snapshot_weeks(season_data: dict) -> tuple:
    """(first, last) week that actually has rosters, or (None, None).

    Discovered, never assumed: 2018 ran weeks 3-16 while later seasons ran 1-17,
    and a mid-season week can be empty if its harvest file was missing.
    """
    weeks = season_data.get("weeks") or {}
    have = sorted(
        int(w) for w, v in weeks.items() if (v or {}).get("rosters")
    )
    if not have:
        return (None, None)
    return (have[0], have[-1])


def roster_table(roster: dict) -> list[str]:
    """Markdown rows for one team's roster snapshot, starters first."""
    players = (roster or {}).get("players") or []

    def sort_key(player):
        slot = player.get("slot") or ""
        if slot in BENCH_SLOTS:
            rank = len(ROSTER_SLOT_ORDER) + 1
        elif slot in ROSTER_SLOT_ORDER:
            rank = ROSTER_SLOT_ORDER.index(slot)
        else:
            rank = len(ROSTER_SLOT_ORDER)
        # Within a slot, the bigger week wins the higher row.
        return (rank, -float(player.get("points") or 0.0), player.get("name") or "")

    rows = ["| Slot | Player | Pos | Pts |", "|------|--------|-----|-----|"]
    for player in sorted(players, key=sort_key):
        rows.append(
            f"| {player.get('slot') or '—'} "
            f"| {player.get('name') or TBD} "
            f"| {player.get('position') or '—'} "
            f"| {_fmt_score(player.get('points'))} |"
        )
    return rows


def team_roster_blocks(season_data: dict, teams: list[dict]) -> str:
    """One collapsed admonition per team, holding both roster snapshots."""
    first, last = roster_snapshot_weeks(season_data)
    if first is None:
        return "_TBD — no roster data captured for this season._"

    weeks = season_data.get("weeks") or {}
    out: list[str] = []
    for team in teams:
        name = team.get("name") or "?"
        snapshots = [
            ("Post-draft", first, ((weeks.get(str(first)) or {}).get("rosters") or {}).get(name)),
            ("End of season", last, ((weeks.get(str(last)) or {}).get("rosters") or {}).get(name)),
        ]
        if not any(roster for _, _, roster in snapshots):
            continue
        out.append(f'??? note "{name}"')
        for label, week, roster in snapshots:
            if not roster:
                continue
            out.append(f"    **{label} — week {week}**")
            out.append("")
            out.extend("    " + line for line in roster_table(roster))
            out.append("")
    return "\n".join(out) if out else "_TBD — no roster data captured for this season._"
```

- [ ] **Step 4: Wire it into the season template**

In `gen_season`, before the template string, add:

```python
    roster_blocks = team_roster_blocks(season_data, teams)
```

and in the template replace:

```
## Team Rosters

| Team | Post-Draft Roster | End-of-Season Roster |
|------|-------------------|----------------------|
```

with:

```
## Team Rosters

> Post-draft and end-of-season lineups as Yahoo recorded them. Bench and IR rows are included; points are that week's score.

{roster_blocks}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_player_roster.py -v`
Expected: PASS, five tests

- [ ] **Step 6: Commit**

```bash
git add scripts/generate.py tests/test_player_roster.py
git commit -m "feat(generate): render team roster snapshots on season pages"
```

---

## Task 8: Link roster columns on team pages

**Goal:** The two roster columns in each team's season log point at that year's season page instead of sitting empty.

**Files:**
- Modify: `scripts/generate.py:1291` region (`gen_team_page` season-log rows)
- Modify: `tests/test_player_roster.py`

**Acceptance Criteria:**
- [ ] Each row's roster cells are wikilinks to the season page when that season has roster data
- [ ] Seasons without roster data render `_TBD_`, not a dead link
- [ ] `uv run pytest -q` passes

**Verify:** `uv run pytest tests/test_player_roster.py -v` → `test_season_log_roster_cells` passes

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `tests/test_player_roster.py`:

```python
from scripts.generate import roster_cell


def test_season_log_roster_cells():
    with_data = {"weeks": {"3": {"rosters": {"Team A": {"players": []}}}}}
    assert "2018 Season" in roster_cell(2018, with_data)
    assert roster_cell(2018, {"weeks": {}}) == "_TBD_"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_player_roster.py::test_season_log_roster_cells -v`
Expected: FAIL — `ImportError: cannot import name 'roster_cell'`

- [ ] **Step 3: Implement**

In `scripts/generate.py`, next to the other roster helpers:

```python
def roster_cell(year: int, season_data: dict) -> str:
    """Season-log cell: a link to the year's roster blocks, or _TBD_.

    Sixteen names will not fit in a table cell and there are no player pages, so
    the column's job is navigation.
    """
    first, _ = roster_snapshot_weeks(season_data)
    if first is None:
        return TBD
    return wikilink(f"{year} Season")
```

- [ ] **Step 4: Use it in the season log**

The current cells are worse than empty — they link to `{year} {slug(name)} Post-Draft` and `{year} {slug(name)} End-of-Season`, pages the generator never writes, so every row carries two dead links.

`gen_team_page` has no access to the season dicts, so add a parameter. Change the signature:

```python
def gen_team_page(
    name: str,
    years_data: list,
    bible: dict,
    aggregates: dict,
    owner_map: dict,
    matchup_stats: dict,
    seasons: dict,
) -> str:
```

Replace the row construction:

```python
    rows = []
    for (year, wins, losses, rank, made_playoffs, _) in sorted(years_data, key=lambda x: x[0]):
        # Both cells point at the same place: the season page's roster blocks.
        # The previous links pointed at per-team roster pages that were never
        # generated, so every row shipped two dead links.
        roster_link = roster_cell(year, seasons.get(year) or {})
        rows.append(
            f"| {year} | {wins}–{losses} | {rank} | {'Yes' if made_playoffs else 'No'} | {roster_link} | {roster_link} | {TBD} |"
        )
```

Update the caller at `:2174`:

```python
        tp.write_text(dash_normalize(gen_team_page(name, ydata, bible, aggregates, owner_map, matchup_stats, seasons)))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add scripts/generate.py tests/test_player_roster.py
git commit -m "feat(generate): link team season-log roster columns to season pages"
```

---

## Task 9: Backfill draft-pick positions

**Goal:** Draft boards show a position for every pick whose player appears on any roster that season.

**Files:**
- Modify: `scripts/generate.py`
- Modify: `tests/test_player_roster.py`

**Acceptance Criteria:**
- [ ] A pick with `position: ""` gets the position from that season's roster data
- [ ] A pick whose player never appears on a roster keeps `""` — no guessing
- [ ] `uv run pytest -q` passes

**Verify:** `uv run pytest tests/test_player_roster.py::test_backfill_positions -v` → passes

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `tests/test_player_roster.py`:

```python
from scripts.generate import backfill_draft_positions


def test_backfill_positions():
    season = {
        "draft": {"draft_results": [
            {"pick": 1, "player": "Starter QB", "position": ""},
            {"pick": 2, "player": "Never Rostered", "position": ""},
        ]},
        "weeks": {"1": {"rosters": {"Team A": {"players": [
            {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 20.0},
        ]}}}},
    }
    backfill_draft_positions(season)
    picks = season["draft"]["draft_results"]
    assert picks[0]["position"] == "QB"
    # Never fabricate: an unmatched pick stays blank rather than getting a guess.
    assert picks[1]["position"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_player_roster.py::test_backfill_positions -v`
Expected: FAIL — `ImportError: cannot import name 'backfill_draft_positions'`

- [ ] **Step 3: Implement**

In `scripts/generate.py`:

```python
def backfill_draft_positions(season_data: dict) -> None:
    """Fill blank draft-pick positions from that season's roster data, in place.

    Yahoo's draft-results table never carried a position column, so all eight
    seasons shipped with `position: ""`. Rosters have it. Unmatched picks stay
    blank — an unrostered player's position is not in the captured data.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    if not picks:
        return
    positions = {}
    for week in (season_data.get("weeks") or {}).values():
        for roster in ((week or {}).get("rosters") or {}).values():
            for player in roster.get("players") or []:
                name, pos = player.get("name"), player.get("position")
                if name and pos:
                    positions.setdefault(name, pos)
    for pick in picks:
        if not pick.get("position"):
            pick["position"] = positions.get(pick.get("player"), "")
```

- [ ] **Step 4: Call it once per season at load**

In `load_raw()`, after each season's JSON is parsed, call `backfill_draft_positions(season_data)` so every consumer — draft pages and the award computation in Task 11 — sees positions.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add scripts/generate.py tests/test_player_roster.py
git commit -m "feat(generate): backfill draft-pick positions from roster data"
```

---

## Task 10: Player record book

**Goal:** Records carries a player-keyed book that honors the existing phase split and tie conventions.

**Files:**
- Modify: `scripts/generate.py` (new `build_player_log`, new section in `gen_records_index`)
- Modify: `tests/test_player_roster.py`

**Acceptance Criteria:**
- [ ] `build_player_log` produces one row per player per week per roster, phase-tagged
- [ ] A consolation-week row is tagged consolation, not playoff
- [ ] Records renders: regular-season single week, playoff single week, season total, highest-scoring benched player, most weeks rostered
- [ ] Ties are listed and marked `(tied)`, matching `top_holders`
- [ ] `uv run pytest -q` passes

**Verify:** `uv run pytest tests/test_player_roster.py -v` → all player-log tests pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_player_roster.py`:

```python
from scripts.generate import PHASE_PLAYOFF, PHASE_REGULAR, build_player_log


def two_week_season():
    return {2025: {
        "standings": {"teams": [{"name": "Team A", "rank": 1}, {"name": "Team B", "rank": 2}]},
        "matchups": {
            "1": [{"teams": [{"name": "Team A", "score": 100.0, "is_winner": True},
                             {"name": "Team B", "score": 90.0, "is_winner": False}]}],
            "2": [{"teams": [{"name": "Team A", "score": 110.0, "is_winner": True},
                             {"name": "Team B", "score": 95.0, "is_winner": False}]}],
        },
        "playoffs": {"weeks": {
            "2": [{"teams": [{"name": "Team A", "score": 110.0, "is_winner": True},
                             {"name": "Team B", "score": 95.0, "is_winner": False}]}],
        }},
        "bracket": {"games": []},
        "weeks": {
            "1": {"rosters": {"Team A": {"players": [
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 30.0},
                {"name": "Bench Guy", "position": "WR", "slot": "BN", "points": 40.0},
            ]}}},
            "2": {"rosters": {"Team A": {"players": [
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 35.0},
            ]}}},
        },
    }}


def test_player_log_rows_and_phases():
    log = build_player_log(two_week_season())
    assert len(log) == 3
    week1 = [r for r in log if r["week"] == 1]
    assert all(r["phase"] == PHASE_REGULAR for r in week1)
    assert {r["player"] for r in week1} == {"Starter QB", "Bench Guy"}


def test_player_log_marks_started():
    log = build_player_log(two_week_season())
    bench = [r for r in log if r["player"] == "Bench Guy"][0]
    assert bench["started"] is False
    starter = [r for r in log if r["player"] == "Starter QB"][0]
    assert starter["started"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_player_roster.py -k player_log -v`
Expected: FAIL — `ImportError: cannot import name 'build_player_log'`

- [ ] **Step 3: Implement the log**

In `scripts/generate.py`, after `build_game_log`:

```python
def build_player_log(seasons: dict) -> list:
    """One row per player per week per roster, phase-tagged.

    Phase comes from the same bracket read `build_game_log` uses, so a
    consolation week never contaminates the playoff book. A player row is tagged
    by the team whose roster it sat on that week.
    """
    log = []
    for year in sorted(seasons):
        season_data = seasons[year]
        playoff_start, bracket_games = season_phases(season_data)
        # (week, team) pairs that played a real bracket game.
        bracket_teams = {
            (week, name) for (week, names) in bracket_games for name in names
        }
        for week_key, week_data in sorted(
            (season_data.get("weeks") or {}).items(), key=lambda kv: int(kv[0])
        ):
            week = int(week_key)
            for team_name, roster in ((week_data or {}).get("rosters") or {}).items():
                if (week, team_name) in bracket_teams:
                    phase = PHASE_PLAYOFF
                elif playoff_start is not None and week >= playoff_start:
                    phase = PHASE_CONSOLATION
                else:
                    phase = PHASE_REGULAR
                for player in roster.get("players") or []:
                    slot = player.get("slot") or ""
                    log.append({
                        "year": year,
                        "week": week,
                        "phase": phase,
                        "team": team_name,
                        "player": player.get("name") or "",
                        "position": player.get("position") or "",
                        "slot": slot,
                        "points": float(player.get("points") or 0.0),
                        "started": slot not in BENCH_SLOTS,
                    })
    return log
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_player_roster.py -k player_log -v`
Expected: PASS

- [ ] **Step 5: Render the book**

In `scripts/generate.py`, add the section builder:

```python
def player_book_rows(player_log: list) -> list[str]:
    """The five player books as table rows, in the shape single_game_rows uses.

    Ties are listed and marked, never arbitrated — the same rule the team books
    follow. Bench marks read the whole log; every other book reads starters only,
    since a benched score is not a lineup result.
    """
    started = [row for row in player_log if row["started"]]

    def holders_rows(label, items, key, value, when) -> list[str]:
        holders = top_holders(items, key)
        if not holders:
            return [f"| {label} | {TBD} | {TBD} | {TBD} |"]
        shared = " (tied)" if len(holders) > 1 else ""
        return [
            f"| {label}{shared} | {row['player']} | {value(row)} | {when(row)} |"
            for row in holders
        ]

    def week_when(row) -> str:
        return f"{row['year']} Wk {row['week']}, {wikilink(row['team'])}"

    def points_value(row) -> str:
        return f"{row['points']:.2f} ({row['position'] or '—'})"

    season_totals = {}
    for row in started:
        key = (row["player"], row["team"], row["year"])
        season_totals[key] = season_totals.get(key, 0.0) + row["points"]
    totals = [
        {"player": k[0], "team": k[1], "year": k[2], "points": v}
        for k, v in season_totals.items()
    ]

    rostered = {}
    for row in player_log:
        rostered[row["player"]] = rostered.get(row["player"], 0) + 1
    weeks_rows = [{"player": k, "weeks": v} for k, v in rostered.items()]

    table = []
    table += holders_rows(
        "Highest Regular-Season Week",
        [r for r in started if r["phase"] == PHASE_REGULAR],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Highest Playoff Week",
        [r for r in started if r["phase"] == PHASE_PLAYOFF],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Highest Season Total", totals,
        lambda r: r["points"],
        lambda r: f"{r['points']:.2f}",
        lambda r: f"{r['year']}, {wikilink(r['team'])}",
    )
    table += holders_rows(
        "Highest-Scoring Benched Player",
        [r for r in player_log if not r["started"]],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Most Weeks Rostered", weeks_rows,
        lambda r: r["weeks"],
        lambda r: f"{r['weeks']} weeks",
        lambda r: "career",
    )
    return table
```

Then in `gen_records_index`, build the rows near the top of the function:

```python
    player_rows = player_book_rows(build_player_log(seasons))
```

and add this section to the template, after the existing All-Time Totals section and before `## Related`:

```
## Players

> Player records are keyed to the **player**, not the manager or the franchise. Regular season and postseason keep separate books, the same split the team records use. Bench marks count a player who scored while sitting.

| Record | Player | Mark | When |
|--------|--------|------|------|
{chr(10).join(player_rows)}
```

- [ ] **Step 6: Verify the section renders**

Run: `uv run python scripts/generate.py && grep -A5 "^## Players" zensical/.stage/records/index.md`
Expected: the lead paragraph followed by populated rows, no `_TBD_`

- [ ] **Step 7: Commit**

```bash
git add scripts/generate.py tests/test_player_roster.py
git commit -m "feat(generate): player record book on the Records page"
```

---

## Task 11: Fill the season awards

**Goal:** All four `_TBD_` awards on season pages carry real values, the computed two with their formula printed.

**Files:**
- Modify: `scripts/generate.py:1100-1108` (awards block) and new helpers
- Modify: `tests/test_player_roster.py`

**Acceptance Criteria:**
- [ ] Highest and Lowest Single-Week Score come from `matchups`, and needed no roster data
- [ ] Best Draft Pick and Biggest Bust are computed with the stated formula
- [ ] Bust is restricted to rounds 1-3
- [ ] A season with no roster data still renders the two score awards and `_TBD_` for the other two
- [ ] `uv run pytest -q` passes

**Verify:** `uv run pytest tests/test_player_roster.py -k award -v` → passes

**Steps:**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_player_roster.py`:

```python
from scripts.generate import draft_value_awards, weekly_score_awards


def test_weekly_score_awards():
    season = two_week_season()[2025]
    high, low = weekly_score_awards(season)
    assert "110" in high and "Team A" in high
    assert "90" in low and "Team B" in low


def test_weekly_score_awards_without_matchups():
    high, low = weekly_score_awards({"matchups": {}})
    assert high == "_TBD_" and low == "_TBD_"


def test_draft_value_awards():
    season = {
        "draft": {"draft_results": [
            {"pick": 1, "round": 1, "player": "Bust QB", "position": "QB", "team": "Team A"},
            {"pick": 2, "round": 1, "player": "Steal QB", "position": "QB", "team": "Team B"},
        ]},
        "weeks": {"1": {"rosters": {
            "Team A": {"players": [{"name": "Bust QB", "position": "QB", "slot": "QB", "points": 5.0}]},
            "Team B": {"players": [{"name": "Steal QB", "position": "QB", "slot": "QB", "points": 50.0}]},
        }}},
    }
    best, bust = draft_value_awards(season)
    assert "Steal QB" in best
    assert "Bust QB" in bust


def test_draft_value_awards_without_rosters():
    best, bust = draft_value_awards({"draft": {"draft_results": []}, "weeks": {}})
    assert best == "_TBD_" and bust == "_TBD_"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_player_roster.py -k award -v`
Expected: FAIL — `ImportError: cannot import name 'draft_value_awards'`

- [ ] **Step 3: Implement**

In `scripts/generate.py`:

```python
BUST_MAX_ROUND = 3


def weekly_score_awards(season_data: dict) -> tuple[str, str]:
    """Highest and lowest single-week team score. Needs no roster data."""
    scored = []
    for week_key, games in (season_data.get("matchups") or {}).items():
        for game in games:
            for side in game.get("teams") or []:
                if side.get("score") is None:
                    continue
                scored.append((float(side["score"]), side.get("name") or "?", int(week_key)))
    if not scored:
        return (TBD, TBD)
    high = max(scored)
    low = min(scored)
    return (
        f"{high[1]} — {_fmt_score(high[0])} (Wk {high[2]})",
        f"{low[1]} — {_fmt_score(low[0])} (Wk {low[2]})",
    )


def draft_value_awards(season_data: dict) -> tuple[str, str]:
    """Best Draft Pick and Biggest Bust, by draft-slot-versus-finish gap.

    For each position, picks are ranked by draft order and players are ranked by
    season points. The gap is (draft rank) - (finish rank): positive means the
    player finished better than where they were taken. Best pick is the largest
    gap; bust is the smallest, restricted to the first three rounds so a
    late-round miss cannot win an award nobody would give it.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    totals = {}
    for week in (season_data.get("weeks") or {}).values():
        for roster in ((week or {}).get("rosters") or {}).values():
            for player in roster.get("players") or []:
                name = player.get("name")
                if name:
                    totals[name] = totals.get(name, 0.0) + float(player.get("points") or 0.0)
    if not picks or not totals:
        return (TBD, TBD)

    scored = []
    by_position = {}
    for pick in picks:
        position = pick.get("position") or ""
        if position and pick.get("player") in totals:
            by_position.setdefault(position, []).append(pick)

    for position, position_picks in by_position.items():
        draft_order = sorted(position_picks, key=lambda p: int(p.get("pick") or 0))
        finish_order = sorted(
            position_picks, key=lambda p: totals.get(p.get("player"), 0.0), reverse=True
        )
        draft_rank = {p["player"]: i for i, p in enumerate(draft_order, 1)}
        finish_rank = {p["player"]: i for i, p in enumerate(finish_order, 1)}
        for pick in position_picks:
            name = pick["player"]
            scored.append({
                "player": name,
                "position": position,
                "team": pick.get("team") or "?",
                "round": int(pick.get("round") or 0),
                "pick": int(pick.get("pick") or 0),
                "gap": draft_rank[name] - finish_rank[name],
                "points": totals.get(name, 0.0),
            })
    if not scored:
        return (TBD, TBD)

    def line(row):
        return (
            f"{row['player']} ({row['position']}, {row['team']}) — "
            f"pick {row['pick']}, finished {row['gap']:+d} spots at the position, "
            f"{_fmt_score(row['points'])} pts"
        )

    best = max(scored, key=lambda r: (r["gap"], r["points"]))
    early = [r for r in scored if 0 < r["round"] <= BUST_MAX_ROUND]
    if not early:
        return (line(best), TBD)
    bust = min(early, key=lambda r: (r["gap"], -r["points"]))
    return (line(best), line(bust))
```

- [ ] **Step 4: Wire into the season template**

In `gen_season`, before the template:

```python
    high_week, low_week = weekly_score_awards(season_data)
    best_pick, biggest_bust = draft_value_awards(season_data)
```

and replace the awards block:

```
## Awards

- 🏆 **League Champion:** {champion}
- 💥 **Highest Single-Week Score:** {high_week}
- 📉 **Lowest Single-Week Score:** {low_week}
- 🔥 **Biggest Bust:** {biggest_bust}
- 🎯 **Best Draft Pick:** {best_pick}
- 🍗 **"Poultry Controversy" Nominee:** {TBD}

> Best Draft Pick and Biggest Bust are computed, not voted: for each position, the gap between where a player was drafted and where they finished on season points. Bust is restricted to rounds 1-3.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add scripts/generate.py tests/test_player_roster.py
git commit -m "feat(generate): fill the four TBD season awards"
```

---

## Task 12: Documentation and full-site verification

**Goal:** The pipeline docs describe the roster step, and the whole site builds clean with the new content.

**Files:**
- Modify: `scraper/HANDOFF.md` (pipeline block and gaps list)
- Modify: `README.md` (sections table and data description)

**Acceptance Criteria:**
- [ ] `HANDOFF.md`'s v2 pipeline block mentions the roster harvest and its runtime
- [ ] `HANDOFF.md`'s gaps list moves rosters from open to closed
- [ ] `README.md` describes the player record book and the two computed awards
- [ ] Full build succeeds and a spot-checked season page shows roster blocks

**Verify:** `node zensical/build.mjs` → completes clean; `grep -c '??? note' zensical/docs/seasons/2025-season.md` → at least 8

**Steps:**

- [ ] **Step 1: Update HANDOFF.md**

In the "The v2 pipeline (current, 2026-09-01)" block, after the `harvest_v2.py` line, note that the harvest now issues two calls per week (scoreboard + roster) and takes roughly 22 minutes cold. In "Gaps CLOSED by the v2 pipeline", add:

```markdown
- **Weekly rosters with player points** — every team's lineup for all 131 weeks,
  including bench and IR rows, in `weeks[wk].rosters`. This fills the season-page
  roster blocks, backfills the draft-pick positions that were blank for all eight
  seasons, and supplies the player record book and the two computed draft awards.
```

- [ ] **Step 2: Update README.md**

In the Sections table, note that Records now carries a player book. In the prose describing what is computed, add that player records are keyed to the player and split by phase like the team books, and that Best Draft Pick and Biggest Bust are computed from the draft-slot-versus-finish gap with the formula printed on the page.

- [ ] **Step 3: Full build**

```bash
node zensical/build.mjs
```

Expected: completes without error.

- [ ] **Step 4: Spot-check the output**

```bash
grep -c '??? note' zensical/docs/seasons/2025-season.md
grep -A8 '^## Awards' zensical/docs/seasons/2025-season.md
grep -A12 '^## Players' zensical/docs/records/index.md
```

Expected: at least 8 admonitions; awards with real values and no `_TBD_` except the Poultry Controversy line; a populated player book.

- [ ] **Step 5: Full test suite**

```bash
uv run pytest -q && cd scraper && cargo test
```

Expected: both green.

- [ ] **Step 6: Commit**

```bash
git add README.md scraper/HANDOFF.md zensical/docs
git commit -m "docs: describe the roster harvest and player records"
```

---

## Notes

**Task 1 blocks everything.** If the nested endpoint is rejected, Task 5's fallback doubles the request count and Task 3's parser needs a join step. Do not start Task 5 before Task 1 reports a winning path.

**Task 6 is a data run, not code.** It takes ~22 minutes and needs the logged-in Edge session from Task 1 still open.

**The never-fabricate rule holds throughout.** Unmatched draft picks keep a blank position, seasons without roster data render `_TBD_`, and every computed award prints its formula.
