"""The Stat Search query tables, checked against the real capture.

Like tests/test_mvp_curse.py these run on raw/ rather than a fixture, because
the claims are about the committed data as much as the code: the row count, the
owner join and the phase tagging are all properties of what was captured.
"""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import matchup_rows, owner_index, player_week_rows
from scripts.generate import (
    BENCH_SLOTS,
    load_bible,
    load_raw,
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


def test_player_week_phase_is_always_one_of_the_three(player_rows):
    for row in player_rows:
        assert row["phase"] in PHASES, row


def test_player_week_phase_is_genuinely_populated(player_rows):
    """A constant phase column would satisfy the membership check above."""
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
