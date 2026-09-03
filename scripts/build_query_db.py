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

# slug and standings_teams are unused here but reserved for the remaining query
# tables (the player and team-season rows); load_bible and load_raw are for
# build_all() and main(). F401 is suppressed for those, E402 because the
# sys.path line above has to run before this import resolves.
from scripts.generate import (  # noqa: E402, F401
    build_game_log,
    get_owners,
    load_bible,
    load_raw,
    slug,
    standings_teams,
    team_owners_by_year,
)

ROOT = Path(__file__).resolve().parent.parent

# One row per team per game, so the 615 captured games become 1,230 rows.
MATCHUP_COLUMNS = (
    "year",
    "week",
    "phase",
    "round",
    "owner",
    "team",
    "score",
    "opp_owner",
    "opp_team",
    "opp_score",
    "margin",
    "won",
    "tied",
)


def owner_index(seasons: dict, bible: dict) -> dict:
    """{(year, team name): canonical owner}, the join key for every table.

    Wraps team_owners_by_year by pre-applying get_owners(bible), so callers
    pass the bible they already hold rather than knowing that the alias map
    lives under its "owners" key.
    """
    return team_owners_by_year(seasons, get_owners(bible))


def matchup_rows(seasons: dict, bible: dict, owners: dict) -> list[dict]:
    """One row per team per game, owner-joined, for the Stat Search table.

    A projection over build_game_log rather than a second flattening of the
    matchups block: phase, round, won and tied are inherited from it, not
    re-derived. That matters for more than dedup — build_game_log unions the
    bracket's own weeks into the playoff weeks (so a season whose
    playoffs.weeks omits a bracket week still labels its championship game a
    playoff game), treats a bare score comparison as the fallback for games
    Yahoo left unflagged, and keeps ties as their own column rather than
    letting them read as losses.

    Each game contributes two rows, one from each side, which is why 615
    captured games become 1,230 rows. Head-to-head and streak queries then
    need no self-join.

    The renames drop build_game_log's own vocabulary for the query tables'
    one: `opponent` becomes `opp_team`, `opponent_score` becomes `opp_score`.
    Its `canonical`/`opponent_canonical` pair is dropped in favour of the
    owner join, which resolves through the standings block and so survives a
    team rename mid-season.
    """
    rows = []
    for game in build_game_log(seasons, bible):
        year = game["year"]
        team = game["team"]
        opp_team = game["opponent"]
        rows.append(
            {
                "year": year,
                "week": game["week"],
                "phase": game["phase"],
                "round": game["round"],
                "owner": owners.get((year, team), ""),
                "team": team,
                "score": game["score"],
                "opp_owner": owners.get((year, opp_team), ""),
                "opp_team": opp_team,
                "opp_score": game["opponent_score"],
                "margin": game["margin"],
                "won": game["won"],
                "tied": game["tied"],
            }
        )
    return rows
