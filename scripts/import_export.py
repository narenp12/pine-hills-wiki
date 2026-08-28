#!/usr/bin/env python3
"""
import_export.py — adapter from a third-party Yahoo export (Fantasy Helper,
fantasyhelper.net) to the canonical raw/<year>.json that scripts/generate.py
consumes.

Fantasy Helper is FREE and requires no Yahoo developer API key: you log in with
your Yahoo account (read-only), pick a league, and download the datasets
(Teams, Matchups, Transactions, Rosters) as CSV or JSON. Drop those files in a
folder and run this adapter. It maps them into one raw/<year>.json per season.

Design principles
-----------------
* Stdlib only (no third-party deps) so it runs anywhere `python3` runs.
* Format-tolerant: column names are mapped through a small dictionary that you
  can override with --map (a YAML/JSON file). Unknown columns are ignored but
  reported by --inspect.
* Non-destructive: it never edits your exports; it only writes raw/<year>.json.

Usage
-----
  python scripts/import_export.py exports/                 # convert whole folder
  python scripts/import_export.py exports/ --season 2024   # force a season
  python scripts/import_export.py exports/ --inspect       # show detected files/columns
  python scripts/import_export.py exports/ --map mymap.yaml # custom column map

Canonical raw/<year>.json shape (must match scripts/generate.py):
  {
    "season": 2024,
    "standings": {"standings": {"teams": [{"team_key","name","owner",
                   "wins","losses","points_for","points_against","rank"}]}},
    "teams":     {"teams": [<same + team_key>]},
    "draft":     {"draft_results": [{"pick","round","team","player","position"}]},
    "playoffs":  {"weeks": {"15": [{"teams":[{"name","score","is_winner"}]}]}},
    "weeks":     {"1": {"rosters": {team_key: {"players":[{"name","position"}]}}},
                  "18": {...}}
  }
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"

# ---------------------------------------------------------------------------
# Default column maps. Fantasy Helper's exact headers aren't known without a
# login, so these are best-guess Yahoo/Fantasy Helper conventions. Override any
# of them with --map. Left-hand = our canonical field; right-hand = list of
# candidate source column names (case-insensitive, matched in order).
# ---------------------------------------------------------------------------
DEFAULT_MAP = {
    "teams": {
        "team_key": ["team_key", "teamkey", "team id", "teamid", "id"],
        "name": ["name", "team name", "team", "team_name"],
        "owner": ["owner", "manager", "manager name", "owner name", "user"],
        "wins": ["wins", "w", "win"],
        "losses": ["losses", "l", "loss"],
        "points_for": ["points_for", "pf", "points for", "pointsfor", "fpts"],
        "points_against": ["points_against", "pa", "points against", "pointsagainst"],
        "rank": ["rank", "finish", "place", "standing"],
    },
    "draft": {
        "pick": ["pick", "overall_pick", "overall pick", "overall"],
        "round": ["round", "rd"],
        "team": ["team", "team name", "name", "owner"],
        "player": ["player", "player name", "full_name", "full name"],
        "position": ["position", "pos", "display_position", "display position"],
    },
    "matchups": {
        "week": ["week", "wk"],
        "team": ["team", "team name", "name", "team_a"],
        "opponent": ["opponent", "team_b", "vs"],
        "score": ["score", "points", "points_for", "pf"],
        "opponent_score": ["opponent_score", "opponent points", "opp_points"],
        "is_winner": ["is_winner", "win", "won", "w"],
    },
    "rosters": {
        "team": ["team", "team name", "name", "owner"],
        "week": ["week", "wk", "snapshot"],
        "player": ["player", "player name", "full_name", "full name"],
        "position": ["position", "pos", "display_position", "display position"],
    },
}

# How to recognise which dataset a file is, by filename keyword.
DATASET_HINTS = {
    "teams": ["team", "standings", "owner"],
    "draft": ["draft", "pick"],
    "matchups": ["matchup", "score"],
    "rosters": ["roster", "lineup"],
}


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------
def load_table(path: Path):
    """Return (rows, fieldnames) where rows is a list of dicts."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        # Accept a bare list, or {"data": [...]}, or {"rows": [...]}
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("data") or data.get("rows") or data.get("teams") or []
        else:
            rows = []
        if rows and isinstance(rows[0], dict):
            fieldnames = list(rows[0].keys())
        else:
            fieldnames = []
        return rows, fieldnames
    # CSV
    reader = csv.DictReader(text.splitlines())
    rows = [dict(r) for r in reader]
    return rows, (reader.fieldnames or [])


def detect_dataset(path: Path, col_map) -> str:
    name = path.stem.lower()
    for ds, hints in DATASET_HINTS.items():
        if any(h in name for h in hints):
            return ds
    # fall back to looking at columns
    _, cols = load_table(path)
    cl = {c.lower() for c in cols}
    if {"pick", "round"} & cl:
        return "draft"
    if {"points_for", "wins"} & cl or {"pf", "wins"} & cl:
        return "teams"
    if {"opponent", "week"} & cl or {"team_a", "team_b"} & cl:
        return "matchups"
    if {"lineup", "roster"} & cl or ("player" in cl and "week" in cl):
        return "rosters"
    return "unknown"


def pick_field(row: dict, candidates):
    """Return the first matching value from row for one of `candidates` (ci).
    Matching is tolerant of underscore/space differences (e.g. 'points_for' vs
    'points for') so we don't depend on Fantasy Helper's exact header style."""
    def norm(s):
        return str(s).strip().lower().replace(" ", "_").replace("-", "_")

    normed = {norm(k): v for k, v in row.items()}
    for c in candidates:
        key = norm(c)
        if key in normed:
            v = normed[key]
            if v not in (None, ""):
                return v
    return None


def norm_team_key(val, fallback):
    return str(val).strip() if val not in (None, "") else str(fallback).strip()


# ---------------------------------------------------------------------------
# Mapping functions (each returns a canonical sub-structure)
# ---------------------------------------------------------------------------
def map_teams(rows, col_map):
    teams = []
    for i, r in enumerate(rows, 1):
        tk = norm_team_key(pick_field(r, col_map["team_key"]) or f"team{i}", f"team{i}")
        teams.append({
            "team_key": tk,
            "name": pick_field(r, col_map["name"]) or f"Team {i}",
            "owner": pick_field(r, col_map["owner"]) or "Unknown",
            "wins": _to_int(pick_field(r, col_map["wins"])),
            "losses": _to_int(pick_field(r, col_map["losses"])),
            "points_for": _to_num(pick_field(r, col_map["points_for"])),
            "points_against": _to_num(pick_field(r, col_map["points_against"])),
            "rank": _to_int(pick_field(r, col_map["rank"]) or i),
        })
    return teams


def map_draft(rows, col_map, team_name_to_key):
    picks = []
    for r in rows:
        tname = pick_field(r, col_map["team"]) or "?"
        picks.append({
            "pick": _to_int(pick_field(r, col_map["pick"])),
            "round": _to_int(pick_field(r, col_map["round"])),
            "team": tname,
            "player": pick_field(r, col_map["player"]) or "?",
            "position": pick_field(r, col_map["position"]) or "—",
        })
    return picks


def map_matchups_to_playoffs(rows, col_map):
    """Group matchups by week into playoffs.weeks structure."""
    weeks: dict[str, list] = {}
    for r in rows:
        wk = pick_field(r, col_map["week"])
        if wk is None:
            continue
        wk = str(wk)
        tname = pick_field(r, col_map["team"]) or "?"
        opp = pick_field(r, col_map["opponent"])
        score = _to_num(pick_field(r, col_map["score"]))
        opp_score = _to_num(pick_field(r, col_map["opponent_score"]))
        is_win = _truthy(pick_field(r, col_map["is_winner"]))
        mus = weeks.setdefault(wk, [])
        # try to pair team + opponent into one matchup
        if opp is not None:
            mus.append({
                "teams": [
                    {"name": tname, "score": score, "is_winner": is_win},
                    {"name": opp, "score": opp_score, "is_winner": (not is_win)},
                ]
            })
        else:
            mus.append({"teams": [{"name": tname, "score": score, "is_winner": is_win}]})
    return weeks


def map_rosters(rows, col_map, team_name_to_key):
    """Group roster rows by week -> team_key -> players list."""
    weeks: dict[str, dict] = {}
    for r in rows:
        wk = pick_field(r, col_map["week"]) or pick_field(r, ["snapshot"]) or "1"
        wk = str(wk)
        tname = pick_field(r, col_map["team"]) or "?"
        tk = team_name_to_key.get(tname, tname)
        player = pick_field(r, col_map["player"]) or "?"
        pos = pick_field(r, col_map["position"]) or "—"
        weeks.setdefault(wk, {}).setdefault(tk, {"players": []})
        weeks[wk][tk]["players"].append({"name": player, "position": pos})
    return weeks


def _to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _to_num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _truthy(v):
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "win", "won", "w", "t")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def inspect(folder: Path, col_map):
    print(f"Inspecting {folder}:\n")
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() not in (".csv", ".json"):
            continue
        rows, cols = load_table(p)
        ds = detect_dataset(p, col_map)
        print(f"  {p.name}")
        print(f"    detected dataset : {ds}")
        print(f"    rows             : {len(rows)}")
        print(f"    columns          : {cols}")
        print()


def build(folder: Path, col_map, season_override=None):
    files_by_ds: dict[str, list[Path]] = {k: [] for k in DATASET_HINTS}
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() not in (".csv", ".json"):
            continue
        ds = detect_dataset(p, col_map)
        if ds == "unknown":
            print(f"  ! skipped (unknown dataset): {p.name}")
            continue
        files_by_ds.setdefault(ds, []).append(p)

    season = season_override
    if season is None:
        # infer from a filename like 2024_teams.csv or teams_2024.json
        for p in folder.glob("*"):
            for tok in p.stem.split("_"):
                if tok.isdigit() and 2000 <= int(tok) <= 2100:
                    season = int(tok)
                    break
            if season:
                break
    if season is None:
        season = 2024  # last-resort default
        print(f"  ! no season found in filenames; defaulting to {season}")

    out: dict[str, "Any"] = {"season": int(season)}
    team_name_to_key: dict[str, str] = {}

    # Teams / standings
    if files_by_ds.get("teams"):
        rows, _ = load_table(files_by_ds["teams"][0])
        teams = map_teams(rows, col_map["teams"])
        for t in teams:
            team_name_to_key[t["name"]] = t["team_key"]
        out["teams"] = {"teams": teams}
        out["standings"] = {"standings": {"teams": teams}}
        print(f"  teams: {len(teams)}")
    else:
        print("  ! no teams file found")

    # Draft
    if files_by_ds.get("draft"):
        rows, _ = load_table(files_by_ds["draft"][0])
        picks = map_draft(rows, col_map["draft"], team_name_to_key)
        out["draft"] = {"draft_results": picks}
        print(f"  draft picks: {len(picks)}")
    else:
        out["draft"] = {"draft_results": []}

    # Matchups -> playoffs (weeks >= playoff week, default 14)
    if files_by_ds.get("matchups"):
        rows, _ = load_table(files_by_ds["matchups"][0])
        po_weeks = map_matchups_to_playoffs(rows, col_map["matchups"])
        # treat weeks >= 14 as playoffs; keep all weeks under playoffs for now
        playoff_weeks = {wk: mus for wk, mus in po_weeks.items() if int(wk) >= 14}
        out["playoffs"] = {"weeks": playoff_weeks or po_weeks}
        # also keep all matchups as 'weeks' for potential roster/score use
        out["weeks"] = {wk: {} for wk in po_weeks}
        print(f"  matchup weeks: {sorted(po_weeks, key=int)}")
    else:
        out["playoffs"] = {"weeks": {}}
        out["weeks"] = {}

    # Rosters -> weeks[week]["rosters"][team_key]
    if files_by_ds.get("rosters"):
        rows, _ = load_table(files_by_ds["rosters"][0])
        wk_rosters = map_rosters(rows, col_map["rosters"], team_name_to_key)
        # merge into weeks
        for wk, teams in wk_rosters.items():
            out.setdefault("weeks", {}).setdefault(wk, {})["rosters"] = teams
        print(f"  roster weeks: {sorted(wk_rosters, key=int)}")
    else:
        print("  ! no rosters file found (post-draft / end-of-season rosters will be empty)")

    RAW.mkdir(exist_ok=True)
    dest = RAW / f"{season}.json"
    dest.write_text(json.dumps(out, indent=2))
    print(f"\n  wrote {dest.relative_to(ROOT)}")
    return dest


def load_map_file(path: Path):
    txt = path.read_text()
    data = json.loads(txt) if path.suffix.lower() == ".json" else _mini_yaml(txt)
    # deep-merge over defaults
    import copy
    merged = copy.deepcopy(DEFAULT_MAP)
    for ds, fields in data.items():
        merged.setdefault(ds, {}).update(fields)
    return merged


def _mini_yaml(txt: str) -> dict:
    """Tiny YAML reader sufficient for `dataset:\n  field: [a, b]` maps."""
    import ast
    result: dict = {}
    cur_ds = None
    for line in txt.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line:
            cur_ds = line.split(":", 1)[0].strip()
            result[cur_ds] = {}
        elif cur_ds and ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            try:
                parsed = ast.literal_eval(val)
            except Exception:
                parsed = [v.strip() for v in val.strip("[]").split(",") if v.strip()]
            result[cur_ds][key] = parsed
    return result


def main():
    ap = argparse.ArgumentParser(description="Adapt Fantasy Helper exports -> raw/<year>.json")
    ap.add_argument("folder", nargs="?", default="exports", help="folder with CSV/JSON exports")
    ap.add_argument("--season", type=int, help="force season year")
    ap.add_argument("--inspect", action="store_true", help="print detected files/columns only")
    ap.add_argument("--map", help="YAML/JSON column-map override file")
    args = ap.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)

    col_map = load_map_file(Path(args.map)) if args.map else DEFAULT_MAP

    if args.inspect:
        inspect(folder, col_map)
        return

    build(folder, col_map, args.season)


if __name__ == "__main__":
    main()
