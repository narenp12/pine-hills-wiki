"""The Stat Search query tables, checked against the real capture.

Like tests/test_mvp_curse.py these run on raw/ rather than a fixture, because
the claims are about the committed data as much as the code: the row count, the
owner join and the phase tagging are all properties of what was captured.
"""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import (
    DRAFT_COLUMNS as DECLARED_DRAFT_COLUMNS,
    MATCHUP_COLUMNS as DECLARED_MATCHUP_COLUMNS,
    PLAYER_WEEK_COLUMNS as DECLARED_PLAYER_WEEK_COLUMNS,
    TEAM_SEASON_COLUMNS as DECLARED_TEAM_SEASON_COLUMNS,
    draft_rows,
    matchup_rows,
    owner_index,
    player_week_rows,
    team_season_rows,
)
from scripts.generate import (
    BENCH_SLOTS,
    load_bible,
    load_raw,
    season_has_games,
    season_phases,
    slug,
)

# The Parquet schema and the browser's column dropdowns are both derived from
# these dicts, so a renamed or added key silently propagates to the front end.
# Assert the exact set rather than reading keys one at a time.
MATCHUP_COLUMNS = {
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
}

# 615 captured games, two mirrored rows each. This rises when 2026 games are
# captured: raw/2026.json is already committed, but its matchups block is empty
# because the season has not been played. Raise it deliberately when that lands
# rather than relaxing the assertion.
EXPECTED_MATCHUP_ROWS = 1230

PLAYER_WEEK_COLUMNS = {
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
}

# Every roster slot, bench included, of every captured week. This rises when
# 2026 games are captured: raw/2026.json is already committed, but its weekly
# rosters are empty because the season has not been played. Raise it
# deliberately when that lands rather than relaxing the assertion.
EXPECTED_PLAYER_WEEK_ROWS = 19881

# Roster sizes grew as the league added weeks and bench spots, so a per-season
# split catches a season dropped or double-counted that the total would hide.
EXPECTED_PLAYER_WEEKS_BY_YEAR = {
    2018: 1252,
    2019: 1895,
    2020: 2415,
    2021: 2676,
    2022: 2659,
    2023: 2655,
    2024: 3159,
    2025: 3170,
}

TEAM_SEASON_COLUMNS = {
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
}

# One row per team per captured season. This rises when the league next expands
# or a season is added; 2026 already contributes its ten teams, because Sleeper
# publishes the roster of teams months before kickoff.
EXPECTED_TEAM_SEASON_ROWS = 88

# The league grew from six teams to twelve and back to ten, so a per-season
# split catches a season dropped or double-counted that the total would hide.
EXPECTED_TEAM_SEASONS_BY_YEAR = {
    2018: 6,
    2019: 8,
    2020: 10,
    2021: 10,
    2022: 10,
    2023: 10,
    2024: 12,
    2025: 12,
    2026: 10,
}

# Read off raw/<year>.json's derived `champions` block, which is authoritative
# over the bible. The bible's own champions block is all placeholders, so a
# builder that skipped apply_derived_champions would flag no champion at all.
EXPECTED_CHAMPIONS = {
    2018: "Curry's legit team",
    2019: "Curry's legit team",
    2020: "Roger That",
    2021: "varun's victorious team",
    2022: "Jeremy's Neat Team",
    2023: "Super Squirrels",
    2024: "Stroud Boys",
    2025: "Jeremy's Neat Team",
}

# The people who have ever run a team, after the bible's owner_aliases fold the
# platform spellings together. Joining without that fold reports 26.
EXPECTED_OWNER_COUNT = 16

DRAFT_COLUMNS = {
    "year",
    "round",
    "pick",
    "overall",
    "player",
    "player_slug",
    "position",
    "owner",
    "team",
}

# Fifteen rounds every season, so the pick count tracks the team count. This
# rises when the league next expands or a season is added; 2026's 150 picks are
# already here, because its draft ran before this table was built.
EXPECTED_DRAFT_ROWS = 1320

EXPECTED_DRAFT_PICKS_BY_YEAR = {
    2018: 90,
    2019: 120,
    2020: 150,
    2021: 150,
    2022: 150,
    2023: 150,
    2024: 180,
    2025: 180,
    2026: 150,
}

# Yahoo's draft-results table never carried a position column, so 1,170 of the
# 1,320 picks arrive blank and are filled from that season's rosters. A player
# drafted and then cut before week one reaches no roster, so a handful stay
# blank rather than being guessed at.
MIN_DRAFT_POSITION_COVERAGE = 0.95

PHASES = {"regular", "playoff", "consolation"}

# Fantasy games can end level and Yahoo drops those from the standings W-L
# entirely, so a tie must not read as a loss. This is the only one on record.
TIE_YEAR, TIE_WEEK = 2018, 8


@pytest.fixture(scope="module")
def league():
    seasons = load_raw()
    bible = load_bible()
    return seasons, bible


@pytest.fixture(scope="module")
def rows(league):
    seasons, bible = league
    return matchup_rows(seasons, bible, owner_index(seasons, bible))


@pytest.fixture(scope="module")
def player_rows(league):
    seasons, bible = league
    return player_week_rows(seasons, owner_index(seasons, bible))


@pytest.fixture(scope="module")
def team_rows(league):
    seasons, bible = league
    return team_season_rows(seasons, bible, owner_index(seasons, bible))


@pytest.fixture(scope="module")
def picks(league):
    seasons, bible = league
    return draft_rows(seasons, owner_index(seasons, bible))


@pytest.fixture(scope="module")
def completed_years(league):
    """The seasons that have actually been played, newest capture included.

    raw/2026.json is committed with a full team list and a full draft but no
    games, so every claim about a finish, a seed or a title has to be scoped to
    the seasons that produced one.
    """
    seasons, _ = league
    played = {year for year, data in seasons.items() if season_has_games(data)}
    assert played, "no completed seasons; every scoped check would be vacuous"
    assert seasons.keys() - played, "no unplayed season; the scoping is untested"
    return played


def test_the_owner_join_canonicalizes_every_spelling(league, team_rows):
    """One manager is one owner value, whatever the platform called him.

    Yahoo reported the manager of "Curry's legit team" as "lokesh" and Sleeper
    reports the same person as "CurryMan123"; the bible's `owner_aliases` block
    folds both onto "Lokesh". Joining through `owners` instead — a team-name
    map, not an alias map — leaves the raw spellings in place, and the tables
    then carry 26 owners where the league has 16. Nothing else here would
    notice: the owner column is non-empty either way.
    """
    seasons, bible = league
    joined = {row["owner"] for row in team_rows}
    aliases = bible.get("owner_aliases") or {}
    assert aliases, "no owner aliases in the bible; the check would be vacuous"
    for canonical, variants in aliases.items():
        for variant in variants:
            assert variant not in joined, f"{variant} was not folded onto {canonical}"
    assert len(joined) == EXPECTED_OWNER_COUNT, sorted(joined)
    # The Sleeper season has to land on the same people as the Yahoo ones, or
    # the 2026 rows join a second copy of every returning manager.
    latest = {row["owner"] for row in team_rows if row["year"] == max(seasons)}
    assert latest <= joined - {""}
    assert len(latest & {row["owner"] for row in team_rows if row["year"] < 2026}) >= 9


def test_every_table_joins_the_same_owner_vocabulary(rows, player_rows, team_rows, picks):
    """All four tables share one join key, so their owner columns must agree."""
    team_owners = {row["owner"] for row in team_rows}
    for table in (rows, player_rows, picks):
        assert {row["owner"] for row in table} <= team_owners
    assert {row["opp_owner"] for row in rows} <= team_owners


def test_declared_columns_match_the_builders(rows, player_rows, team_rows, picks):
    """The module's column tuples are the Parquet schema, so pin them here.

    Each test below restates the key set independently; without this the module
    constant could drift from what the builder emits with every test still
    green, and the browser would offer a column the data does not have.
    """
    assert set(DECLARED_MATCHUP_COLUMNS) == MATCHUP_COLUMNS
    assert set(DECLARED_PLAYER_WEEK_COLUMNS) == PLAYER_WEEK_COLUMNS
    assert set(DECLARED_TEAM_SEASON_COLUMNS) == TEAM_SEASON_COLUMNS
    assert set(DECLARED_DRAFT_COLUMNS) == DRAFT_COLUMNS
    # A tuple with a repeated entry would satisfy the set comparison above while
    # emitting a duplicate Parquet column.
    for declared in (
        DECLARED_MATCHUP_COLUMNS,
        DECLARED_PLAYER_WEEK_COLUMNS,
        DECLARED_TEAM_SEASON_COLUMNS,
        DECLARED_DRAFT_COLUMNS,
    ):
        assert len(set(declared)) == len(declared), declared


def test_matchup_rows_have_the_declared_columns(rows):
    for row in rows:
        assert set(row) == MATCHUP_COLUMNS


def test_matchup_rows_cover_every_captured_game(rows):
    assert len(rows) == EXPECTED_MATCHUP_ROWS


def test_every_matchup_row_joins_an_owner_on_both_sides(rows):
    for row in rows:
        assert row["owner"], f"blank owner in {row}"
        assert row["opp_owner"], f"blank opp_owner in {row}"


def test_matchup_margin_is_the_score_difference(rows):
    for row in rows:
        assert abs(row["margin"] - (row["score"] - row["opp_score"])) < 1e-9


def test_matchup_phase_is_always_one_of_the_three(rows):
    for row in rows:
        assert row["phase"] in PHASES, row


def test_every_bracket_game_is_tagged_playoff(league, rows):
    """The invariant that catches a phase bug the row count cannot see.

    A bracket game whose week is missing from playoffs.weeks would be labelled
    regular or consolation, leaving the total unchanged and every other
    assertion here satisfied.
    """
    seasons, _ = league
    tagged = {
        (row["year"], row["week"], frozenset((row["team"], row["opp_team"])))
        for row in rows
        if row["phase"] == "playoff"
    }
    bracket = set()
    for year, season_data in seasons.items():
        _, bracket_games = season_phases(season_data)
        for week, names in bracket_games:
            bracket.add((year, week, names))
    assert bracket, "no bracket games found; the check would be vacuous"
    assert bracket - tagged == set(), "bracket games not tagged playoff"
    assert tagged - bracket == set(), "playoff rows with no bracket game"


def test_the_2018_tie_is_tied_on_both_sides(rows):
    tied = [
        row
        for row in rows
        if row["year"] == TIE_YEAR and row["week"] == TIE_WEEK and row["tied"]
    ]
    assert len(tied) == 2, f"expected one tied game, got {len(tied)} rows"
    for row in tied:
        assert row["margin"] == 0, row
        assert row["score"] == row["opp_score"], row


def test_a_tie_is_the_only_game_without_a_winner(rows):
    """Every game has a winner unless it was tied, so `not won` is a real loss."""
    for row in rows:
        if row["margin"] > 0:
            assert row["won"], row
        if row["margin"] < 0:
            assert not row["won"], row
        assert row["tied"] == (row["margin"] == 0), row


def test_matchup_rows_are_mirrored(rows):
    by_game = {}
    for row in rows:
        key = (row["year"], row["week"], frozenset((row["team"], row["opp_team"])))
        by_game.setdefault(key, []).append(row)
    for key, pair in by_game.items():
        assert len(pair) == 2, f"{key} produced {len(pair)} rows"
        a, b = pair
        # Mirror both directions: a one-sided check passes even if one row's
        # opponent fields were filled from the wrong side of the game.
        assert a["score"] == b["opp_score"], key
        assert b["score"] == a["opp_score"], key
        assert a["team"] == b["opp_team"], key
        assert b["team"] == a["opp_team"], key
        assert a["owner"] == b["opp_owner"], key
        assert b["owner"] == a["opp_owner"], key
        assert a["margin"] == -b["margin"], key
        # One game has one phase, round and tied flag, whichever side reads it.
        assert a["phase"] == b["phase"], key
        assert a["round"] == b["round"], key
        assert a["tied"] == b["tied"], key
        # Exactly one winner, unless the game was tied.
        assert (a["won"] and b["won"]) is False, key
        assert (a["won"] or b["won"]) is not a["tied"], key


def test_player_week_rows_have_the_declared_columns(player_rows):
    for row in player_rows:
        assert set(row) == PLAYER_WEEK_COLUMNS


def test_player_week_rows_cover_every_captured_roster_slot(player_rows):
    assert len(player_rows) == EXPECTED_PLAYER_WEEK_ROWS


def test_player_week_rows_split_by_season_as_captured(player_rows):
    counts = {}
    for row in player_rows:
        counts[row["year"]] = counts.get(row["year"], 0) + 1
    assert counts == EXPECTED_PLAYER_WEEKS_BY_YEAR


def test_2026_contributes_no_player_weeks(league, player_rows):
    """The empty season must be skipped, not crash and not invent rows.

    raw/2026.json is committed with an empty weeks block, so anything that
    assumes a roster exists per season would raise here.
    """
    seasons, _ = league
    assert 2026 in seasons, "2026 not captured; the check would be vacuous"
    assert [row for row in player_rows if row["year"] == 2026] == []


def test_every_player_week_row_joins_an_owner(player_rows):
    for row in player_rows:
        assert row["owner"], f"blank owner in {row}"


def test_player_slug_matches_the_player_page_slug(player_rows):
    """The slug is the link target for players/<slug>/, so it cannot drift."""
    for row in player_rows:
        assert row["player_slug"] == slug(row["player"]), row


def test_started_is_false_exactly_on_the_bench(player_rows):
    for row in player_rows:
        assert row["started"] == (row["slot"] not in BENCH_SLOTS), row


def test_both_started_and_benched_rows_exist(player_rows):
    """Guards the slot check above from passing on an all-one-value column."""
    started = {row["started"] for row in player_rows}
    assert started == {True, False}
    benched = {row["slot"] for row in player_rows if not row["started"]}
    assert benched == BENCH_SLOTS


def test_player_week_phase_is_genuinely_populated(player_rows):
    """Set equality, so this covers membership as well as coverage.

    The matchups table keeps a separate membership check because it has no
    equality counterpart; here the equality subsumes it.
    """
    assert {row["phase"] for row in player_rows} == PHASES


def test_every_bracket_roster_is_tagged_playoff(league, player_rows):
    """The invariant the row count cannot see, as for the matchups table.

    A bracket week missing from playoffs.weeks would leave its rosters labelled
    regular or consolation with the total unchanged.
    """
    seasons, _ = league
    tagged = {
        (row["year"], row["week"], row["team"])
        for row in player_rows
        if row["phase"] == "playoff"
    }
    bracket = set()
    for year, season_data in seasons.items():
        _, bracket_games = season_phases(season_data)
        for week, names in bracket_games:
            for name in names:
                bracket.add((year, week, name))
    assert bracket, "no bracket games found; the check would be vacuous"
    # A bracket team with no captured roster contributes no rows, so only the
    # one-way containment holds: every playoff row is a bracket roster.
    assert tagged - bracket == set(), "playoff rows with no bracket game"
    rostered = {(row["year"], row["week"], row["team"]) for row in player_rows}
    assert bracket & rostered <= tagged, "bracket rosters not tagged playoff"


def test_player_week_round_is_set_only_on_playoff_rows(player_rows):
    labelled = {row["round"] for row in player_rows if row["round"]}
    assert labelled, "no bracket round labels; the check would be vacuous"
    for row in player_rows:
        if row["round"]:
            assert row["phase"] == "playoff", row


def test_team_season_rows_have_the_declared_columns(team_rows):
    for row in team_rows:
        assert set(row) == TEAM_SEASON_COLUMNS


def test_team_season_rows_cover_every_captured_team(team_rows):
    assert len(team_rows) == EXPECTED_TEAM_SEASON_ROWS


def test_team_season_rows_split_by_season_as_captured(team_rows):
    counts = {}
    for row in team_rows:
        counts[row["year"]] = counts.get(row["year"], 0) + 1
    assert counts == EXPECTED_TEAM_SEASONS_BY_YEAR


def test_every_team_season_row_joins_an_owner(team_rows):
    for row in team_rows:
        assert row["owner"], f"blank owner in {row}"


def test_one_team_season_row_per_team_per_year(team_rows):
    keys = [(row["year"], row["team"]) for row in team_rows]
    assert len(set(keys)) == len(keys), "a team appears twice in one season"


def test_each_completed_season_has_exactly_one_champion(team_rows, completed_years):
    """Also the check that apply_derived_champions was applied at all.

    bible.yaml's champions block is placeholders — every field an empty string —
    so a builder reading the bible alone flags nobody and this drops to zero.
    """
    for year in sorted(completed_years):
        flagged = [row for row in team_rows if row["year"] == year and row["champion"]]
        assert len(flagged) == 1, f"{year} flagged {len(flagged)} champions"
        assert flagged[0]["team"] == EXPECTED_CHAMPIONS[year], flagged[0]


def test_each_completed_season_has_one_of_each_other_title(team_rows, completed_years):
    for field in ("runner_up", "top_seed", "toilet"):
        for year in sorted(completed_years):
            flagged = [
                row for row in team_rows if row["year"] == year and row[field]
            ]
            assert len(flagged) == 1, f"{year} flagged {len(flagged)} for {field}"


def test_the_champion_is_never_also_the_runner_up(team_rows):
    for row in team_rows:
        assert not (row["champion"] and row["runner_up"]), row


def test_the_top_seed_is_sometimes_not_the_champion(team_rows):
    """The season page's whole point: the 1 seed is champion only by winning.

    A builder that flagged top_seed off the standings rank instead of the
    derived block would make the two columns identical and this would fail.
    """
    top_seeds = {(row["year"], row["team"]) for row in team_rows if row["top_seed"]}
    champions = {(row["year"], row["team"]) for row in team_rows if row["champion"]}
    assert top_seeds, "no top seeds flagged; the check would be vacuous"
    assert top_seeds - champions, "every top seed won the title"


def test_team_season_flags_are_booleans(team_rows):
    """Parquet types these columns, so a stray name string would poison them."""
    for row in team_rows:
        for field in ("champion", "runner_up", "top_seed", "toilet"):
            assert row[field] is True or row[field] is False, row


def test_the_unplayed_season_carries_no_result(league, team_rows, completed_years):
    """2026 has a full team list and no games, so it must report no finish.

    Rank 0 is the scraper's "no finish known"; reporting it as a first-place
    finish would hand every 2026 team the best season in league history.
    """
    seasons, _ = league
    for year in sorted(seasons.keys() - completed_years):
        unplayed = [row for row in team_rows if row["year"] == year]
        assert unplayed, f"{year} contributed no rows"
        for row in unplayed:
            assert row["rank"] == 0, row
            assert row["seed"] == 0, row
            assert (row["wins"], row["losses"]) == (0, 0), row
            for field in ("champion", "runner_up", "top_seed", "toilet"):
                assert row[field] is False, row


def test_completed_seasons_report_a_finish_and_a_record(team_rows, completed_years):
    for row in team_rows:
        if row["year"] not in completed_years:
            continue
        assert row["rank"] > 0, row
        assert row["wins"] + row["losses"] > 0, row
        assert row["pf"] > 0, row
        assert row["pa"] > 0, row


def test_playoff_seeds_are_a_gapless_field_per_completed_season(
    team_rows, completed_years
):
    """Seed 0 means "did not qualify", so the flagged seeds must be 1..n."""
    for year in sorted(completed_years):
        seeds = sorted(
            row["seed"] for row in team_rows if row["year"] == year and row["seed"]
        )
        assert seeds == list(range(1, len(seeds) + 1)), f"{year} seeds {seeds}"
        assert seeds, f"{year} has no seeded teams"


def test_draft_rows_have_the_declared_columns(picks):
    for row in picks:
        assert set(row) == DRAFT_COLUMNS


def test_draft_rows_cover_every_captured_pick(picks):
    assert len(picks) == EXPECTED_DRAFT_ROWS


def test_draft_rows_split_by_season_as_captured(picks):
    counts = {}
    for row in picks:
        counts[row["year"]] = counts.get(row["year"], 0) + 1
    assert counts == EXPECTED_DRAFT_PICKS_BY_YEAR


def test_every_draft_row_joins_an_owner(picks):
    for row in picks:
        assert row["owner"], f"blank owner in {row}"


def test_every_draft_row_names_a_player(picks):
    for row in picks:
        assert row["player"], row


def test_draft_player_slug_matches_the_player_page_slug(picks):
    """The slug is the link target for players/<slug>/, so it cannot drift."""
    for row in picks:
        assert row["player_slug"] == slug(row["player"]), row


def test_draft_overall_is_a_gapless_sequence_per_season(picks):
    """The invariant that catches the platform's two pick-numbering schemes.

    Yahoo numbers picks within the round and Sleeper numbers them overall;
    annotate_overall_picks reconciles the two. Offsetting an already-overall
    number would push 2026's later rounds past 150 and leave gaps here.
    """
    by_year = {}
    for row in picks:
        by_year.setdefault(row["year"], []).append(row["overall"])
    for year, overalls in sorted(by_year.items()):
        assert sorted(overalls) == list(range(1, len(overalls) + 1)), year


def test_draft_pick_restarts_at_one_every_round(picks):
    by_round = {}
    for row in picks:
        by_round.setdefault((row["year"], row["round"]), []).append(row["pick"])
    assert by_round, "no draft rounds; the check would be vacuous"
    for key, numbers in sorted(by_round.items()):
        assert sorted(numbers) == list(range(1, len(numbers) + 1)), key


def test_draft_pick_and_overall_actually_differ(picks):
    """Guards the two checks above from passing on one column copied twice.

    `pick` equals `overall` through round one of every season and nowhere else,
    so a builder that emitted the raw Yahoo number as both would be caught here
    rather than by the round or season sequence checks.
    """
    for row in picks:
        if row["round"] == 1:
            assert row["pick"] == row["overall"], row
        else:
            assert row["pick"] != row["overall"], row


def test_draft_rounds_are_a_gapless_sequence_per_season(picks):
    by_year = {}
    for row in picks:
        by_year.setdefault(row["year"], set()).add(row["round"])
    for year, rounds in sorted(by_year.items()):
        assert sorted(rounds) == list(range(1, len(rounds) + 1)), year


def test_draft_positions_are_almost_all_filled(picks):
    """1,170 of 1,320 picks arrive blank, so this measures the backfill.

    Not 100%: a player drafted and cut before week one never reached a captured
    roster, and inventing his position would be fabrication.
    """
    filled = [row for row in picks if row["position"]]
    coverage = len(filled) / len(picks)
    assert coverage > MIN_DRAFT_POSITION_COVERAGE, f"only {coverage:.1%} filled"
    assert coverage < 1.0, "every position filled; the backfill note is stale"


def test_draft_teams_are_teams_that_played_that_season(picks, team_rows):
    """The join key is (year, team), so a draft-only team name would break it."""
    known = {(row["year"], row["team"]) for row in team_rows}
    for row in picks:
        assert (row["year"], row["team"]) in known, row
