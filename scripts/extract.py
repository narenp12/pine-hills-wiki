"""
Yahoo Fantasy Football → Pine Hills Wiki extraction toolkit.

Layers (per the llm-wiki pattern):
  raw/        Immutable JSON pulled from Yahoo (one file per season). Never hand-edit.
  content/    Generated Markdown wiki pages (regenerated; safe to commit).

Usage:
  1. Copy .env.example -> .env and fill in Yahoo credentials + league id.
  2. python scripts/extract.py        # pulls all seasons -> raw/<year>.json
  3. python scripts/generate.py       # builds content/ markdown from raw/

Requires: yfpy  (pip install yfpy)
"""

import os
import sys
import json
import datetime as dt
from pathlib import Path

# ---- paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
CONTENT = ROOT / "content"
ENV_FILE = ROOT / ".env"

# ---- league config (edit these) -----------------------------------------
LEAGUE_ID = os.getenv("YAHOO_LEAGUE_ID", "447010")
GAME_CODE = "nfl"
# Yahoo "game id" per season. NFL game ids are stable per year; the query
# helper can resolve them, but providing the CURRENT season's game_id lets
# yfpy bootstrap. Use get_game_key_by_season(year) to map any year.
CURRENT_GAME_ID = int(os.getenv("YAHOO_GAME_ID", "449"))
# Seasons your league has played. Expand as needed.
SEASONS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]


def get_query():
    """Instantiate a YFPY query object using env-file credentials."""
    from yfpy.query import YahooFantasySportsQuery

    if not ENV_FILE.exists():
        sys.exit("Missing .env — copy .env.example to .env and fill in credentials.")

    q = YahooFantasySportsQuery(
        league_id=LEAGUE_ID,
        game_code=GAME_CODE,
        game_id=CURRENT_GAME_ID,
        env_file_location=ENV_FILE,
    )
    return q


def game_key_for_season(q, season):
    """Resolve the Yahoo game_key (e.g. '449' or 'nfl/2023') for a season."""
    try:
        return q.get_game_key_by_season(season)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not resolve game key for {season}: {e}")
        return None


def extract_season(q, season):
    """Pull one season's data and save to raw/<season>.json."""
    print(f"Extracting {season}...")
    gk = game_key_for_season(q, season)
    if not gk:
        return None

    data = {"season": season, "game_key": str(gk), "extracted": dt.date.today().isoformat()}

    def safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            print(f"    ! {fn.__name__} failed: {e}")
            return None

    data["settings"] = _serialize(safe(q.get_league_settings, gk))
    data["standings"] = _serialize(safe(q.get_league_standings, gk))
    data["teams"] = _serialize(safe(q.get_league_teams, gk))
    data["draft"] = _serialize(safe(q.get_league_draft_results, gk))
    data["transactions"] = _serialize(safe(q.get_league_transactions, gk))
    data["weeks"] = {}
    # Determine number of weeks from settings or just try 1..18
    for week in range(1, 19):
        wk = {}
        wk["matchups"] = _serialize(safe(q.get_league_matchups_by_week, gk, week))
        wk["scoreboard"] = _serialize(safe(q.get_league_scoreboard_by_week, gk, week))
        # roster for week 1 (post-draft) and last week (end-of-season) handled separately
        if week == 1 or week == 18:
            wk["rosters"] = {}
            teams = data["teams"] or []
            team_keys = [t.get("team_key") for t in _team_list(teams)] if teams else []
            for tk in team_keys:
                wk["rosters"][tk] = _serialize(safe(q.get_team_roster_by_week, tk, week))
        # stop early if no data
        if not wk["matchups"] and not wk["scoreboard"]:
            if week > 14:
                break
        data["weeks"][str(week)] = wk

    # ---- Playoffs: pull matchups for the typical playoff window (weeks 14-17) ----
    # Each matchup carries teams, scores, and the winner — enough to draw a real bracket.
    data["playoffs"] = {"weeks": {}}
    for week in range(14, 18):
        m = _serialize(safe(q.get_league_matchups_by_week, gk, week))
        if m:
            # normalize to a list of matchups, each with two teams + scores + winner
            matchups = _extract_matchups(m)
            if matchups:
                data["playoffs"]["weeks"][str(week)] = matchups

    return data


def _extract_matchups(m):
    """Normalize a yfpy matchups response (any shape) into a list of:
    {'teams': [{'name', 'score', 'is_winner'}, ...]}.
    Returns [] if nothing parseable."""
    out = []
    # navigate common nesting
    if isinstance(m, dict):
        for key in ("matchups", "matchup", "games", "game"):
            if key in m and isinstance(m[key], (list, dict)):
                m = m[key]
                break
    if isinstance(m, dict):
        # maybe a single matchup
        m = [m]
    if not isinstance(m, list):
        return out
    for mu in m:
        if not isinstance(mu, dict):
            continue
        teams = mu.get("teams", mu.get("team", []))
        if isinstance(teams, dict):
            teams = [teams]
        if not isinstance(teams, list):
            continue
        row = {"teams": []}
        for t in teams:
            if not isinstance(t, dict):
                continue
            name = t.get("name", t.get("team_name", t.get("team_key", "Unknown")))
            # score may be nested under 'team_points' or 'points'
            score = None
            if "team_points" in t:
                tp = t["team_points"]
                score = tp.get("total") if isinstance(tp, dict) else tp
            score = t.get("points", t.get("score", score))
            row["teams"].append(
                {
                    "name": name,
                    "score": score,
                    "is_winner": bool(t.get("is_winner", t.get("winner", False))),
                }
            )
        if row["teams"]:
            out.append(row)
    return out


def _team_list(teams):
    """Normalize yfpy teams response to a list of dicts."""
    if not teams:
        return []
    # yfpy returns various shapes; best-effort extraction
    if isinstance(teams, dict):
        for key in ("teams", "team"):
            if key in teams:
                teams = teams[key]
                break
    if isinstance(teams, dict):
        teams = [teams]
    return teams


def _serialize(obj):
    """Best-effort JSON serialization of yfpy model objects."""
    if obj is None:
        return None
    try:
        return json.loads(json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o))))
    except TypeError:
        return str(obj)


def main_extract():
    RAW.mkdir(exist_ok=True)
    q = get_query()
    for season in SEASONS:
        data = extract_season(q, season)
        if data:
            out = RAW / f"{season}.json"
            out.write_text(json.dumps(data, indent=2, default=str))
            print(f"  saved {out.name} ({out.stat().st_size} bytes)")
    print("Done extracting.")


if __name__ == "__main__":
    main_extract()
