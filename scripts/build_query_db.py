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

from scripts.generate import (  # noqa: E402, F401
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
        names = frozenset(str(t.get("name") or "") for t in game.get("teams") or [])
        if week and len(names) == 2:
            pairs.add((week, names))
    return pairs


def _phase(season_data: dict, week: int, names: frozenset, pairs: set) -> str:
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
