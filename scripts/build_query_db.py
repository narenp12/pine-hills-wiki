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

# load_bible and load_raw are unused here but are the entry points build_all()
# and main() will call. F401 is suppressed for those, E402 because the sys.path
# line above has to run before this import resolves.
from scripts.generate import (  # noqa: E402, F401
    apply_derived_champions,
    build_game_log,
    build_owner_map,
    build_player_log,
    champ_year,
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

# One row per team per season, so the 88 captured team-seasons become 88 rows.
# The four title columns are booleans rather than a single "result" string: a
# team can be both runner-up and regular-season top seed in one year, and twice
# has been.
TEAM_SEASON_COLUMNS = (
    "year",
    "owner",
    "team",
    "wins",
    "losses",
    "pf",
    "pa",
    "rank",
    "seed",
    "champion",
    "runner_up",
    "top_seed",
    "toilet",
)

# One row per draft pick, so the 1,320 captured picks become 1,320 rows.
DRAFT_COLUMNS = (
    "year",
    "round",
    "pick",
    "overall",
    "player",
    "player_slug",
    "position",
    "owner",
    "team",
)


def owner_index(seasons: dict, bible: dict) -> dict:
    """{(year, team name): canonical owner}, the join key for every table.

    Wraps team_owners_by_year by pre-applying build_owner_map, so callers pass
    the bible they already hold rather than assembling the alias map first.

    build_owner_map, not get_owners: `owners` is a team-name -> manager map (one
    entry, a leftover of the hand-maintained era), while the alias map that
    folds a manager's spellings together is `owner_aliases`, and only
    build_owner_map reads it. Passing the wrong one leaves canonical_owner
    falling through to the raw platform name, so "lokesh" and "CurryMan123"
    stay separate from "Lokesh" -- 26 of the 88 team-seasons, and 26 distinct
    owners in the query tables where the wiki has 16. That defeats the point of
    the owner join, which exists so a career reads as one manager's across a
    rename and across the 2026 move to Sleeper.
    """
    return team_owners_by_year(seasons, build_owner_map(bible, seasons))


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


def team_season_rows(seasons: dict, bible: dict, owners: dict) -> list[dict]:
    """One row per team per season, owner-joined, for the Stat Search table.

    Unlike the matchup and player-week tables there is no upstream log to
    project over: `build_aggregates` rolls the same standings up ACROSS years
    into one row per franchise, which is the opposite of what a per-season table
    needs, and `gen_season` renders these numbers straight to Markdown table
    rows rather than returning data. So this walks the standings itself -- but
    through `standings_teams`, which already unwraps the two shapes the capture
    uses, and through `champ_year`, so it reads the titles the season pages
    read.

    Inherited rather than re-derived: `apply_derived_champions` decides that the
    scraper's per-season `champions` block WINS over the hand-maintained bible,
    which matters here because the bible's block is placeholders -- reading it
    alone would flag no champion in any season. Deriving the flags from `rank`
    instead would be wrong twice over: 2020's standings carry two teams at rank
    7, and the regular-season top seed is champion only by winning the bracket.

    Added here: `owner`, joined on (year, team) so a career reads as one
    manager's across a rename, and the four title columns as booleans, so a
    query can filter on them without string-matching a team name.

    A season the league has not played still has a full team list -- Sleeper
    publishes the 2026 rosters months before kickoff -- so those ten rows are
    kept with rank 0, seed 0 and no titles. Rank 0 is the scraper's "no finish
    known", and dropping the rows would hide a captured season entirely.
    """
    bible = apply_derived_champions(bible, seasons)
    rows = []
    for year in sorted(seasons):
        titles = champ_year(bible, year)
        champion = str(titles.get("champion") or "").strip()
        runner_up = str(titles.get("runner_up") or "").strip()
        top_seed = str(titles.get("top_seed") or "").strip()
        toilet = str(titles.get("toilet_winner") or "").strip()
        for team in standings_teams(seasons[year]):
            name = str(team.get("name") or "").strip()
            rows.append(
                {
                    "year": year,
                    "owner": owners.get((year, name), ""),
                    "team": name,
                    "wins": int(team.get("wins", 0) or 0),
                    "losses": int(team.get("losses", 0) or 0),
                    "pf": float(team.get("points_for", 0) or 0),
                    "pa": float(team.get("points_against", 0) or 0),
                    # 0 is "no finish known", not a finish ahead of first.
                    "rank": int(team.get("rank", 0) or 0),
                    # 0 is "did not reach the bracket". The standings position
                    # is not a fallback: 2018's champion was the 5 seed.
                    "seed": int(team.get("playoff_seed") or 0),
                    "champion": bool(name) and name == champion,
                    "runner_up": bool(name) and name == runner_up,
                    "top_seed": bool(name) and name == top_seed,
                    "toilet": bool(name) and name == toilet,
                }
            )
    return rows


def draft_rows(seasons: dict, owners: dict) -> list[dict]:
    """One row per draft pick, owner-joined, for the Stat Search table.

    There is no upstream draft log to project over either:
    `draft_picks_by_player` is keyed by player and drops the within-round
    number, and `draft_value_scored` keeps only the picks it could score against
    a finish. What this does reuse is the two normalizations `load_raw` already
    applied to the picks in place, and neither is repeated here:

    `annotate_overall_picks` writes the `overall` number. Yahoo (2018-2025)
    numbers picks WITHIN the round, so its round 2 pick 1 is the 13th pick of a
    twelve-team draft; Sleeper (2026-) already numbers them overall. Recomputing
    that offset here would push 2026's later rounds past the end of its draft.
    `backfill_draft_positions` fills `position` from that season's rosters,
    which is where 1,170 of the 1,320 picks get one -- Yahoo's draft table never
    carried the column. The handful still blank are players drafted and cut
    before week one, who reached no captured roster; they stay blank rather than
    being guessed at.

    Added here: `pick`, the within-round number, taken as the pick's position in
    its round ordered by `overall`. Deriving it from the normalized `overall`
    rather than reading the raw `pick` field is what makes the column mean the
    same thing on both platforms -- Sleeper's raw `pick` is the overall number.
    Also `owner`, joined on (year, team), and `player_slug`, the path the player
    pages are written to, so a result row can link to players/<slug>/.
    """
    rows = []
    for year in sorted(seasons):
        picks = (seasons[year].get("draft") or {}).get("draft_results") or []
        within_round: dict[int, int] = {}
        for pick in sorted(picks, key=lambda p: int(p.get("overall") or 0)):
            round_number = int(pick.get("round") or 0)
            within_round[round_number] = within_round.get(round_number, 0) + 1
            team = str(pick.get("team") or "").strip()
            player = str(pick.get("player") or "").strip()
            rows.append(
                {
                    "year": year,
                    "round": round_number,
                    "pick": within_round[round_number],
                    "overall": int(pick.get("overall") or 0),
                    "player": player,
                    "player_slug": slug(player),
                    "position": str(pick.get("position") or "").strip(),
                    "owner": owners.get((year, team), ""),
                    "team": team,
                }
            )
    return rows
