"""Build the Stat Search query tables from the captured league data.

Reads through scripts.generate's own loaders rather than raw/*.json directly.
load_raw() supplies apostrophe normalization, draft position backfill and
overall pick numbering; load_league() below adds the four passes generate's
main() applies on top of it, in the same order. Stat Search and the generated
pages therefore see identical data by construction -- which is only true while
load_league() stays in step with main(), so change the two together.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# E402: the sys.path line above has to run before this import resolves.
from scripts.generate import (  # noqa: E402
    CONTENT,
    apply_bible_positions,
    apply_derived_champions,
    apply_derived_owners,
    apply_player_aliases,
    build_award_book,
    build_game_log,
    build_owner_map,
    build_player_index,
    build_player_log,
    champ_year,
    dash_normalize,
    load_bible,
    load_raw,
    slug,
    standings_teams,
    team_owners_by_year,
)

ROOT = Path(__file__).resolve().parent.parent

# The DuckDB type of every column, declared rather than inferred. DuckDB would
# happily guess from the first row it is handed, and the guess is wrong wherever
# a column is empty in the rows it sampled -- an all-blank `round` reads as
# VARCHAR either way, but an all-zero `seed` sampled from an unplayed season
# would type the whole column off ten pre-season rows. Declaring it also keeps
# schema.json's advertised types stable across a re-capture, which is what the
# browser's operator menus are built from.
#
# `round` is the one name that means two things: the bracket label ("Final") in
# the game tables and the draft round number in the draft table. Hence a type
# map per table rather than one shared map.

# One row per team per game, so the 615 captured games become 1,230 rows.
MATCHUP_SCHEMA = (
    ("year", "INTEGER"),
    ("week", "INTEGER"),
    ("phase", "VARCHAR"),
    ("round", "VARCHAR"),
    ("owner", "VARCHAR"),
    ("team", "VARCHAR"),
    ("score", "DOUBLE"),
    ("opp_owner", "VARCHAR"),
    ("opp_team", "VARCHAR"),
    ("opp_score", "DOUBLE"),
    ("margin", "DOUBLE"),
    ("won", "BOOLEAN"),
    ("tied", "BOOLEAN"),
)

# One row per roster slot per week, bench and IR included, so the whole roster
# is queryable and not just the starting lineup.
#
# `swung` is the one derived column in the query tables. It carries the measure
# four of the seven awards are defined by -- see docs/awards.md -- which is
# otherwise unanswerable here: a reader can already ask for a week's top score,
# but not for the wins that score decided. It is a BOOLEAN per row rather than a
# per-season count so it stays at this table's grain; `sum(swung)` in the UI is
# the count, and grouping it by owner, position or year costs nothing extra.
PLAYER_WEEK_SCHEMA = (
    ("year", "INTEGER"),
    ("week", "INTEGER"),
    ("phase", "VARCHAR"),
    ("round", "VARCHAR"),
    ("owner", "VARCHAR"),
    ("team", "VARCHAR"),
    ("player", "VARCHAR"),
    ("player_slug", "VARCHAR"),
    ("position", "VARCHAR"),
    ("slot", "VARCHAR"),
    ("started", "BOOLEAN"),
    ("points", "DOUBLE"),
    ("swung", "BOOLEAN"),
)

# One row per team per season, so the 88 captured team-seasons become 88 rows.
# The four title columns are booleans rather than a single "result" string: a
# team can be both runner-up and regular-season top seed in one year, and twice
# has been.
TEAM_SEASON_SCHEMA = (
    ("year", "INTEGER"),
    ("owner", "VARCHAR"),
    ("team", "VARCHAR"),
    ("wins", "INTEGER"),
    ("losses", "INTEGER"),
    ("pf", "DOUBLE"),
    ("pa", "DOUBLE"),
    ("rank", "INTEGER"),
    ("seed", "INTEGER"),
    ("champion", "BOOLEAN"),
    ("runner_up", "BOOLEAN"),
    ("top_seed", "BOOLEAN"),
    ("toilet", "BOOLEAN"),
)

# One row per draft pick, so the 1,320 captured picks become 1,320 rows.
DRAFT_SCHEMA = (
    ("year", "INTEGER"),
    ("round", "INTEGER"),
    ("pick", "INTEGER"),
    ("overall", "INTEGER"),
    ("player", "VARCHAR"),
    ("player_slug", "VARCHAR"),
    ("position", "VARCHAR"),
    ("owner", "VARCHAR"),
    ("team", "VARCHAR"),
)

# One row per award won, per holder. A tie is two rows, not one row naming two
# people, because a query that groups by player has to be able to count a shared
# award once for each of them.
#
# `wins_swung` is NULL rather than 0 on a Finals MVP: that award is decided by
# the title game's top score, so the player has no swung-wins figure at all, and
# a zero would sort them below every other winner as though they had one.
AWARD_SCHEMA = (
    ("year", "INTEGER"),
    ("award", "VARCHAR"),
    ("slot", "VARCHAR"),
    ("player", "VARCHAR"),
    ("player_slug", "VARCHAR"),
    ("position", "VARCHAR"),
    ("owner", "VARCHAR"),
    ("team", "VARCHAR"),
    ("wins_swung", "INTEGER"),
    ("points", "DOUBLE"),
)

# One row per inductee per class. `season_unit` is the year for the defenses and
# kickers the Hall admits on a single season rather than a career, and NULL for
# everyone admitted on the whole body of work -- the same split the page prints.
HALL_OF_FAME_SCHEMA = (
    ("class_year", "INTEGER"),
    ("charter", "BOOLEAN"),
    ("player", "VARCHAR"),
    ("player_slug", "VARCHAR"),
    ("season_unit", "INTEGER"),
    ("position", "VARCHAR"),
    ("qualified", "INTEGER"),
    ("score", "INTEGER"),
    ("awards", "INTEGER"),
    ("championships", "INTEGER"),
    ("points", "DOUBLE"),
    ("starts", "INTEGER"),
    ("teams", "INTEGER"),
)

# The column names alone, in emit order. Derived from the schemas above rather
# than typed out a second time, so a column can never be declared with a type
# and omitted from the name list or the reverse.
MATCHUP_COLUMNS = tuple(name for name, _ in MATCHUP_SCHEMA)
PLAYER_WEEK_COLUMNS = tuple(name for name, _ in PLAYER_WEEK_SCHEMA)
TEAM_SEASON_COLUMNS = tuple(name for name, _ in TEAM_SEASON_SCHEMA)
DRAFT_COLUMNS = tuple(name for name, _ in DRAFT_SCHEMA)
AWARD_COLUMNS = tuple(name for name, _ in AWARD_SCHEMA)
HALL_OF_FAME_COLUMNS = tuple(name for name, _ in HALL_OF_FAME_SCHEMA)

# Parquet file stem -> its column schema. The browser fetches these six names.
TABLE_SCHEMAS = {
    "matchups": MATCHUP_SCHEMA,
    "player_weeks": PLAYER_WEEK_SCHEMA,
    "team_seasons": TEAM_SEASON_SCHEMA,
    "draft": DRAFT_SCHEMA,
    "awards": AWARD_SCHEMA,
    "hall_of_fame": HALL_OF_FAME_SCHEMA,
}
TABLES = tuple(TABLE_SCHEMAS)

# Every column carrying an owner. Named here rather than sniffed by suffix so
# the emitter's owner check below covers `opp_owner` too: a blank on the
# opponent side of a matchup row breaks a head-to-head query just as completely.
#
# `hall_of_fame` carries no owner at all: the Hall inducts players, and a career
# spanning six rosters has no single manager to name.
OWNER_COLUMNS = ("owner", "opp_owner")

# The columns the UI offers as a dropdown instead of a free-text box, so
# schema.json ships their distinct values. Low cardinality is the whole test:
# 16 owners, 9 years, 3 phases, 6 positions, 9 roster slots, 5 awards. `team` is
# not here on purpose -- 60-odd names, and it is a text search in the UI.
#
# `slot` is shared: the roster table's bench and flex labels and the Team of the
# Season slots come from the same vocabulary, which is why the enum list is per
# column name rather than per (table, column).
ENUM_COLUMNS = ("owner", "position", "slot", "phase", "year", "award")


def load_league() -> tuple[dict, dict]:
    """Return (seasons, bible) normalized exactly as generate.main() has them.

    `load_raw` is only half of the pipeline. main() runs four more passes before
    anything indexes a player, and each one changes a value this module emits,
    so the builder runs the same four in the same order (generate.py:4729-4735):

    `apply_derived_champions` overlays the scraper's per-season champions block
    onto the bible. team_season_rows' four title flags are read from there, and
    the bible's own block is placeholders, so skipping this flags no champion in
    any season.

    `apply_derived_owners` fills the bible's team-name -> manager map from the
    data. The owner join here goes through `owner_aliases` rather than that map,
    so it changes no value today; it is run anyway because a builder whose load
    path has silently diverged from main()'s is the failure this function
    exists to prevent.

    `apply_player_aliases` folds the platforms' two spellings of one player onto
    one name. Without it 11 of the 2026 Sleeper picks keep the short spelling
    and their `player_slug` points at a page that was never written --
    "aaron-jones" against the "aaron-jones-sr" the wiki actually holds -- which
    defeats the only reason the column exists. The weekly rosters escape it
    solely because 2026 has no captured games yet.

    `apply_bible_positions` fills the draft positions no captured roster could,
    from the bible's hand-sourced block: 6 more of the 1,320 picks, taking
    position coverage from 98.11% to 98.56%, matching the wiki's draft board.

    Both passes that take a bible mutate it in place and return it; the seasons
    passes only mutate. Loading here rather than taking a caller's dicts keeps
    that mutation inside this function.
    """
    seasons = load_raw()
    bible = load_bible()
    bible = apply_derived_champions(bible, seasons)
    bible = apply_derived_owners(bible, seasons)
    apply_player_aliases(seasons, bible)
    apply_bible_positions(seasons, bible)
    return seasons, bible


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


def winning_margins(matchups: list[dict]) -> dict:
    """{(year, week, team): margin} for games a team won outright.

    Built from the finished matchup rows rather than from build_game_log again,
    so `won`, `tied` and `margin` reach the swung-win test as the matchups table
    reports them. A row that disagrees with the matchups table is then not
    reachable: the two are the same numbers by construction.

    Ties are excluded rather than given a zero margin. Nothing was won, so
    nothing can have swung it, and a zero margin would otherwise mark every
    starter in a tie as decisive.
    """
    return {
        (row["year"], row["week"], row["team"]): row["margin"]
        for row in matchups
        if row["won"] and not row["tied"]
    }


def player_week_rows(seasons: dict, owners: dict, margins: dict) -> list[dict]:
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

    `swung` applies generate.build_decisive_wins' rule one row at a time: the
    player started, their team won that game outright, and they outscored the
    margin of victory, so taking them out of the lineup flips the result. Stated
    here rather than imported because that function returns a per-season roll-up
    keyed by (year, player) -- the opposite grain to this table -- while the rule
    it rolls up is a per-row test. `margins` is the shared input that keeps the
    two readings of a win from drifting apart.
    """
    rows = []
    for entry in build_player_log(seasons):
        year = entry["year"]
        team = entry["team"]
        player = entry["player"]
        margin = margins.get((year, entry["week"], team))
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
                "swung": bool(
                    entry["started"] and margin is not None and entry["points"] > margin
                ),
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

    That overlay is `load_league`'s job, not this function's, and `bible` must
    arrive already carrying it. It used to run here, which read as a projection
    while quietly rewriting the caller's dict -- and through a module-scoped
    test fixture that made the champion flags depend on which test ran first.

    Added here: `owner`, joined on (year, team) so a career reads as one
    manager's across a rename, and the four title columns as booleans, so a
    query can filter on them without string-matching a team name.

    A season the league has not played still has a full team list -- Sleeper
    publishes the 2026 rosters months before kickoff -- so those ten rows are
    kept with rank 0, seed 0 and no titles. Rank 0 is the scraper's "no finish
    known", and dropping the rows would hide a captured season entirely.
    """
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

    A pick `annotate_overall_picks` could not number -- a forfeited or
    auto-skipped slot, which reaches it with no round or no within-round number
    -- is dropped rather than sorted. Sorting it would place it at 0, ahead of
    the whole draft, and shift every `pick` in its round by one. The capture
    holds no such pick today, so the drop is currently a no-op; the per-season
    pick counts in the tests are what makes it visible if one ever appears.
    """
    rows = []
    for year in sorted(seasons):
        picks = (seasons[year].get("draft") or {}).get("draft_results") or []
        numbered = [pick for pick in picks if int(pick.get("overall") or 0) > 0]
        within_round: dict[int, int] = {}
        for pick in sorted(numbered, key=lambda p: int(p["overall"])):
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


def award_book(seasons: dict, bible: dict) -> dict:
    """generate's own award assembly, fed the inputs main() feeds it.

    Every argument is one call to a generate function, and the assembly itself
    is generate's, so the awards these tables carry are the objects the Awards
    and Hall of Fame pages render rather than a second reading of the same rule.
    """
    player_log = build_player_log(seasons)
    game_log = build_game_log(seasons, bible)
    player_index = build_player_index(seasons, player_log, build_owner_map(bible, seasons))
    return build_award_book(
        seasons, bible, player_log, game_log, player_index, min(seasons),
    )


def _award_home(record: dict, owners: dict, year: int) -> tuple[str, str]:
    """(owner, team) for an award record, by the roster it was won on.

    A decisive-wins record carries `teams` as {team: swung wins there}, because a
    player traded mid-season swings wins for two managers. The award goes to the
    roster it was mostly won on rather than to both, so one award is one row per
    holder and a count by owner still totals the awards handed out.
    """
    teams = record.get("teams")
    if isinstance(teams, dict) and teams:
        team = max(sorted(teams), key=lambda name: teams[name])
    else:
        team = record.get("team") or ""
    return owners.get((year, team), ""), team


def award_rows(seasons: dict, owners: dict, book: dict) -> list[dict]:
    """One row per award per holder, over every computed award.

    Read out of generate.build_award_book rather than recomputed, so Stat Search
    cannot hand out an award the Awards page does not: the five season awards
    here are the same objects those pages render.

    Ties become one row each. The pages print "A, B - 7 wins swung" in a single
    cell, which reads correctly as prose and would be unusable as data -- nothing
    could count Bob's MVPs without splitting that string back apart.
    """
    rows = []

    def add(year, award, record, slot=""):
        player = record.get("player") or ""
        if not player:
            return
        owner, team = _award_home(record, owners, year)
        positions = record.get("positions")
        if isinstance(positions, dict):
            position = max(sorted(positions), key=lambda name: positions[name])
        else:
            position = record.get("position") or ""
        rows.append(
            {
                "year": year,
                "award": award,
                "slot": slot,
                "player": player,
                "player_slug": slug(player),
                "position": position,
                "owner": owner,
                "team": team,
                # NULL for any award whose record carries no swung-wins count.
                # The record shape decides this, not the caller: a Finals MVP is
                # a player_log row, which has no `wins` key at all.
                "wins_swung": record.get("wins"),
                "points": float(record.get("points", 0.0)),
            }
        )

    for year in sorted(seasons):
        for record in book["season_mvps"].get(year) or []:
            add(year, "Most Valuable Player", record)
        for record in book["finals_mvps"].get(year) or []:
            # A player_log row rather than a decisive record, so it carries no
            # `wins` key and `wins_swung` comes out NULL. See add().
            add(year, "Finals MVP", record)
        for record in book["newcomers"].get(year) or []:
            add(year, "Newcomer of the Year", record)
        for record in book["undrafted"].get(year) or []:
            add(year, "Undrafted Player of the Year", record)
        for entry in book["all_league_teams"].get(year) or []:
            for record in entry["holders"]:
                add(year, "Team of the Season", record, slot=entry["slot"])
    return rows


def hall_of_fame_rows(book: dict) -> list[dict]:
    """One row per inductee per class, in induction order.

    `hall_classes` is the page's own list, so this table cannot induct anyone the
    Hall of Fame page does not, or leave anyone out that it names. The candidates
    the class caps left waiting are deliberately absent for the same reason: the
    page does not print them either.
    """
    rows = []
    for entry in book["hall_classes"]:
        for member in entry["members"]:
            years = member.get("years") or []
            # The Hall admits defenses and kickers on one season rather than a
            # career; `display` carries the year for those and the bare name for
            # everyone else, which is what tells the two apart.
            season_unit = years[0] if member["display"] != member["player"] else None
            positions = member.get("positions") or []
            rows.append(
                {
                    "class_year": entry["year"],
                    "charter": bool(entry.get("charter")),
                    "player": member["player"],
                    "player_slug": slug(member["player"]),
                    "season_unit": season_unit,
                    "position": positions[0] if positions else "",
                    "qualified": member["qualified"],
                    "score": int(member["score"]),
                    "awards": int(member["awards"]),
                    "championships": len(member.get("championships") or []),
                    "points": float(member["points"]),
                    "starts": int(member["starts"]),
                    "teams": int(member["teams"]),
                }
            )
    return rows


def build_tables(seasons: dict, bible: dict) -> dict:
    """{table name: rows} for all four tables, off one shared owner index.

    One `owner_index` call, not four: the point of the join key is that every
    table resolves a manager the same way, and four independent calls is four
    chances for one of them to be built from a different argument.

    The matchup rows are built first and handed to the player-week rows, for the
    same reason: `swung` is decided by a margin the matchups table also reports,
    and reading it from the built rows is what makes the two agree by
    construction rather than by coincidence.
    """
    owners = owner_index(seasons, bible)
    matchups = matchup_rows(seasons, bible, owners)
    book = award_book(seasons, bible)
    return {
        "matchups": matchups,
        "player_weeks": player_week_rows(seasons, owners, winning_margins(matchups)),
        "team_seasons": team_season_rows(seasons, bible, owners),
        "draft": draft_rows(seasons, owners),
        "awards": award_rows(seasons, owners, book),
        "hall_of_fame": hall_of_fame_rows(book),
    }


def _sql_literal(path) -> str:
    """A filesystem path, ready to sit inside a single-quoted SQL string.

    Both statements below name a file rather than bind one, because DuckDB's
    read_json and COPY take the path as a literal. The paths are not fixed: the
    content directory is the caller's, and generate.CONTENT honours a
    $WIKI_CONTENT_DIR env var, so a checkout under a directory with an
    apostrophe in it -- a name, most often -- would end the literal early and
    fail as a parser error pointing at the middle of the path.
    """
    return Path(path).as_posix().replace("'", "''")


def _load_table(con, name: str, rows: list[dict]) -> None:
    """Create `name` with its declared types and load `rows`, owners checked.

    The owner check is here, in the emitter, rather than only in the tests. Every
    table is joined on a person, and a blank owner is not a queryable value: it
    silently drops that row out of every "by owner" grouping the UI can build,
    and it does so without an error anywhere. Failing the build is the only
    outcome that cannot ship. A blank reaches this point when the standings
    block names a team the matchup or draft data does not, so the fix is in the
    capture, never here.

    The empty-table check is the same argument one level up: all four tables are
    non-empty in the capture, so an empty one means the load path broke, and a
    zero-row Parquet file would leave the UI querying nothing at all.

    The rows go in through a temporary newline-delimited JSON file rather than
    an INSERT, because DuckDB's Python parameter binding converts one value at a
    time: the 19,881-row roster table takes 23 seconds that way and 0.07 through
    read_json. JSON rather than CSV because CSV cannot tell an empty string from
    a NULL, and two of these columns are legitimately blank -- `round` on every
    non-bracket game, `position` on an unrostered draftee -- which CSV would turn
    into nulls the UI would then have to special-case. `columns` is passed
    explicitly so nothing is inferred from the file: the declared type is the
    type, and a value the declaration cannot hold fails the build rather than
    widening the column under it.
    """
    columns = TABLE_SCHEMAS[name]
    names = [column for column, _ in columns]
    if not rows:
        raise ValueError(f"{name} has no rows; the capture never produces this")
    # Every row of a table is built from one dict literal, so the first row
    # settles the key set for all of them. An extra key would otherwise be
    # dropped from the Parquet file in silence.
    if set(rows[0]) != set(names):
        raise ValueError(f"{name} rows carry {sorted(rows[0])}, declared {names}")
    for column in OWNER_COLUMNS:
        if column not in names:
            continue
        blank = [row for row in rows if not str(row[column] or "").strip()]
        if blank:
            raise ValueError(
                f"{name}: {len(blank)} rows with a blank {column}, "
                f"first {blank[0]}"
            )
    declared = ", ".join(f"'{column}': '{sql_type}'" for column, sql_type in columns)
    with tempfile.TemporaryDirectory() as work:
        staged = Path(work) / f"{name}.jsonl"
        with staged.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps({column: row[column] for column in names}))
                handle.write("\n")
        con.execute(
            f'CREATE TABLE "{name}" AS SELECT * FROM read_json('
            f"'{_sql_literal(staged)}', columns = {{{declared}}}, "
            f"format = 'newline_delimited')"
        )


def _schema(con) -> dict:
    """The dict written to schema.json: per-table columns and row counts.

    Read back out of DuckDB with DESCRIBE rather than restated from
    TABLE_SCHEMAS, so what the file advertises is the table the COPY actually
    wrote: a column the load dropped or reordered is reported as it is, not as
    this module declared it.

    `enums` is flat, one entry per column name rather than per (table, column),
    because the UI's dropdowns are: a `position` filter offers the same list
    whether the query is over rosters or over draft picks. Blanks are dropped --
    a blank is "not captured", and an empty dropdown row is unclickable noise.
    """
    tables = {}
    for name in TABLES:
        described = con.execute(f'DESCRIBE "{name}"').fetchall()
        row_count = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        tables[name] = {
            "columns": [
                {"name": column, "type": sql_type}
                for column, sql_type, *_ in described
            ],
            "row_count": int(row_count),
        }
    enums = {}
    for column in ENUM_COLUMNS:
        values = set()
        for name in TABLES:
            if column not in dict(TABLE_SCHEMAS[name]):
                continue
            found = con.execute(
                f'SELECT DISTINCT "{column}" FROM "{name}" '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchall()
            values.update(row[0] for row in found if str(row[0]).strip())
        # Sorted, so re-running the build rewrites the same bytes and a diff of
        # schema.json shows what the capture changed and nothing else.
        enums[column] = sorted(values)
    return {"tables": tables, "enums": enums}


def build_all(content_dir) -> dict:
    """Write the four Parquet tables and schema.json under <content>/query/.

    Parquet rather than a shipped DuckDB database file: the browser engine reads
    Parquet over HTTP range requests, so a query that touches one column of one
    table fetches roughly that column. ZSTD because the columns are mostly low
    cardinality strings repeated thousands of times -- the four tables together
    come to 137 KB against a 1 MB budget, and the roster table is 97 KB of it.

    schema.json is what the UI is built from. It carries every column with its
    type, so the operator menus can offer numeric comparisons only on numeric
    columns, and the distinct values of the five low-cardinality columns, so the
    owner / year / phase / position / slot pickers are populated without the
    page first downloading a table to find out what is in it.

    Returns the schema dict so a caller that wants to render the query page from
    the same data does not have to read the file back. Returns None, having said
    so, when raw/ holds no capture at all: that is a checkout that never ran
    scripts/extract.py, which generate.main() answers the same way, and the
    emitter's "matchups has no rows" points at the wrong thing entirely.
    """
    seasons, bible = load_league()
    if not seasons:
        print("No raw JSON found in raw/. Run scripts/extract.py first.")
        return None
    tables = build_tables(seasons, bible)
    con = duckdb.connect()
    try:
        # Two passes, load then copy, rather than one interleaved loop. Every
        # check _load_table makes is a reason to write no files at all, and the
        # browser reads this directory as a set: schema.json names the tables
        # and their row counts, and query.js builds its whole UI from it before
        # fetching a single Parquet file. A loop that copied `matchups` and then
        # rejected a blank owner in `draft` left the old schema.json describing
        # three files that had already been replaced, and nothing downstream can
        # detect that -- the queries simply return the wrong numbers.
        for name, rows in tables.items():
            _load_table(con, name, rows)
        # Everything above can raise; from here on the writes are the only work
        # left. mkdir waits until now for the same reason: a failed build should
        # leave no query/ directory rather than an empty one that reads as built.
        out = Path(content_dir) / "query"
        out.mkdir(parents=True, exist_ok=True)
        staged = []
        for name, rows in tables.items():
            tmp = out / f"{name}.parquet.tmp"
            target = out / f"{name}.parquet"
            con.execute(
                f'COPY "{name}" TO \'{_sql_literal(tmp)}\' '
                f"(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            print(f"  wrote {target.as_posix()} ({len(rows)} rows)")
            staged.append((tmp, target))
        schema = _schema(con)
    finally:
        con.close()
    # sort_keys and the trailing newline are what make a rebuild byte-identical
    # when the capture has not changed, so the file is diffable in a review.
    tmp_schema = out / "schema.json.tmp"
    tmp_schema.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    for tmp, target in staged:
        tmp.replace(target)
    tmp_schema.replace(out / "schema.json")
    print(f"  wrote {(out / 'schema.json').as_posix()}")
    return schema


# The Stat Search page itself. Static: every number on it is fetched by
# query.js from the Parquet files beside it, so nothing here is interpolated
# from the capture and a rebuild rewrites the same bytes.
#
# `data-query-base` is resolved by the browser against the page's own URL.
# use_directory_urls is on, so this page is served at /query/ and the tables sit
# in the same directory -- "../query/" and "./" name the same place from there,
# and the explicit form is the one that survives the page being moved.
#
# The fallback markup lives inside the mount rather than beside it, so query.js
# replaces it when it boots instead of leaving a "this needs JavaScript" notice
# stacked above a working UI. Its two links are source-relative .md paths:
# Zensical rewrites href in raw HTML the same way it does in Markdown, so they
# are checked like any other link on the site.
#
# No per-page importmap here on purpose: Zensical strips
# <script type="importmap"> from Markdown, so the map for DuckDB-WASM's bare
# "apache-arrow" import lives once in zensical/overrides/main.html instead.
QUERY_PAGE = """---
title: Stat Search
icon: lucide/search
description: Query the league's matchups, rosters, team seasons and draft picks in the browser.
hide:
  - toc
---

# Stat Search

Ad hoc queries over six tables. Four are the capture itself: one row per team per
game, one per roster slot per week, one per team per season and one per draft
pick. Two are computed the same way the rest of the wiki computes them: every
[award](../awards.md) handed out, and every [Hall of Fame](../hall-of-fame.md)
inductee. The tables are downloaded and queried in the browser, so a query is
answered on the reader's own machine and nothing is sent anywhere.

!!! tip "Start from a preset"

    Pick a preset chip, then adjust filters. Click a column header to sort.
    Use Copy link to share the exact query.

The roster table carries one derived column, `swung`: the player started, their
team won that game outright, and they outscored the margin of victory, so taking
them out of the lineup flips the result. It is the measure four of the seven
awards rank by, and `sum(swung)` over any grouping reproduces their numbers.

<div id="phfl-query" data-query-base="../query/">
  <p>Stat Search runs in the browser and needs JavaScript enabled. The
  league's standing marks are on <a href="../records/index.md">Records</a>,
  and the postseason ones on <a href="../playoffs.md">Playoffs</a>.</p>
</div>

<script type="module" src="../javascripts/query.js"></script>
"""


def write_page(content_dir) -> Path:
    """Write <content>/query/index.md, the page the four tables are read by.

    Emitted here rather than in generate.py because the page is meaningless
    without the Parquet files: the two are one build step, and a run that wrote
    one and not the other would put either an empty UI or four unreachable
    tables on the site.

    Routed through generate's dash_normalize like every other generated page,
    so the house no-en/em-dash rule holds by construction rather than by the
    author of this string having remembered it.

    Returns the path written, so a caller does not rebuild it to check.
    """
    out = Path(content_dir) / "query"
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.md"
    page.write_text(dash_normalize(QUERY_PAGE))
    print(f"  wrote {page.as_posix()}")
    return page


def main():
    """Build the tables, then the page that reads them, under CONTENT.

    CONTENT is generate.py's, so WIKI_CONTENT_DIR redirects this builder and the
    page generator to the same tree with one variable -- which is how
    zensical/build.mjs points both at zensical/.stage.
    """
    if build_all(CONTENT) is None:
        return
    write_page(CONTENT)


if __name__ == "__main__":
    main()
