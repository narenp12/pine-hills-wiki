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

# standings_teams is unused here but reserved for the remaining query table
# (the team-season rows); load_bible and load_raw are for build_all() and
# main(). F401 is suppressed for those, E402 because the sys.path line above
# has to run before this import resolves.
from scripts.generate import (  # noqa: E402, F401
    build_game_log,
    build_player_log,
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

# One row per roster slot per week, bench and IR included, so the whole roster
# is queryable and not just the starting lineup.
PLAYER_WEEK_COLUMNS = (
    "year",
    "week",
    "phase",
    "round",
    "owner",
    "team",
    "player",
    "player_slug",
    "position",
    "slot",
    "started",
    "points",
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


def player_week_rows(seasons: dict, owners: dict) -> list[dict]:
    """One row per player per week per roster, owner-joined, for Stat Search.

    A projection over build_player_log rather than a second walk of the weekly
    rosters, for the same reason matchup_rows projects over build_game_log: the
    fields that take judgement are already decided there and must not be
    decided twice. `phase` and `round` come from season_phases, which unions
    the bracket's own weeks into the playoff weeks and keeps the round label,
    so a title-game row is distinguishable from any other postseason row.
    `started` is build_player_log's read of BENCH_SLOTS, so a slot added to the
    bench set changes the query tables and the generated pages together.

    Added here: `owner`, joined on (year, team) so a query can group by person
    across a team rename, and `player_slug`, the same slug the player pages are
    written to, so a result row can link to players/<slug>/ without the browser
    re-implementing slugification.

    Every slot is kept, bench and IR included; `started` is the filter. Dropping
    the bench would make "most points left on the bench" unanswerable.
    """
    rows = []
    for entry in build_player_log(seasons):
        year = entry["year"]
        team = entry["team"]
        player = entry["player"]
        rows.append(
            {
                "year": year,
                "week": entry["week"],
                "phase": entry["phase"],
                "round": entry["round"],
                "owner": owners.get((year, team), ""),
                "team": team,
                "player": player,
                "player_slug": slug(player),
                "position": entry["position"],
                "slot": entry["slot"],
                "started": entry["started"],
                "points": entry["points"],
            }
        )
    return rows
