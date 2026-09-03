"""The Stat Search query tables, checked against the real capture.

Like tests/test_mvp_curse.py these run on raw/ rather than a fixture, because
the claims are about the committed data as much as the code: the row count, the
owner join and the phase tagging are all properties of what was captured.
"""
import json
import os
import pathlib
import sys

import duckdb
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import (
    DRAFT_COLUMNS as DECLARED_DRAFT_COLUMNS,
    ENUM_COLUMNS,
    MATCHUP_COLUMNS as DECLARED_MATCHUP_COLUMNS,
    PLAYER_WEEK_COLUMNS as DECLARED_PLAYER_WEEK_COLUMNS,
    TABLE_SCHEMAS,
    TABLES,
    TEAM_SEASON_COLUMNS as DECLARED_TEAM_SEASON_COLUMNS,
    _load_table,
    build_all,
    build_tables,
    draft_rows,
    load_league,
    matchup_rows,
    owner_index,
    player_week_rows,
    team_season_rows,
)
from scripts.generate import (
    BENCH_SLOTS,
    apply_bible_positions,
    apply_derived_champions,
    apply_derived_owners,
    apply_player_aliases,
    build_owner_map,
    build_player_alias_map,
    build_player_index,
    build_player_log,
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

# All ten managers who own a 2026 team have run one before, so the Sleeper
# season adds nobody new. Pinned rather than given slack: a returning manager
# who failed to fold would drop this by one and nothing else here would notice.
# Move it deliberately when the league next takes on a new manager.
EXPECTED_RETURNING_OWNERS = 10

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

# The picks no roster and no bible entry could fill, pinned exactly. The floor
# above is the readable claim; this is the one with teeth. Dropping
# apply_bible_positions from the load path leaves 25 blank and still clears the
# floor at 98.11%, so a coverage ratio alone cannot see a skipped normalization.
# This moves when the bible's player_positions block next grows.
EXPECTED_DRAFT_PICKS_WITHOUT_POSITION = 19

PHASES = {"regular", "playoff", "consolation"}

# Fantasy games can end level and Yahoo drops those from the standings W-L
# entirely, so a tie must not read as a loss. This is the only one on record.
TIE_YEAR, TIE_WEEK = 2018, 8

# One players/<slug>.md per player ever rostered or drafted. This rises when
# 2026 is played and its rosters bring in players nobody has drafted.
EXPECTED_PLAYER_PAGES = 606

# The five Parquet columns the browser turns into dropdowns.
EXPECTED_ENUM_COLUMNS = {"owner", "position", "slot", "phase", "year"}

# The whole point of Parquet over a shipped database file: the tables have to
# stay small enough to fetch over a range request on a phone. The four together
# are an order of magnitude inside this today.
MAX_PARQUET_BYTES = 1_000_000


@pytest.fixture(scope="module")
def league():
    """The builder's own normalized load, not a bare load_raw().

    `load_league` is where the four passes generate.main() applies live, and
    two of them change values these tests assert on -- the player slugs and the
    champion flags. Loading raw here instead would test a data shape the
    emitter never sees.
    """
    return load_league()


@pytest.fixture(scope="module")
def owners(league):
    """The single owner index every table joins through.

    One index, built once and shared, because that is the claim being tested:
    four tables resolving a manager the same way. Four fixtures each calling
    `owner_index` again would still pass if the tables disagreed about which
    arguments to build it from.
    """
    seasons, bible = league
    return owner_index(seasons, bible)


@pytest.fixture(scope="module")
def wiki_player_pages():
    """The slugs of the players/<slug>.md pages generate.main() actually writes.

    Loaded and normalized here independently of the `league` fixture, in main()'s
    order, so this is a reference the builder is measured against rather than a
    restatement of what the builder did. Deriving it from the builder's own
    seasons would reproduce whatever normalization the builder skipped, and the
    comparison would hold by construction -- which is precisely how the two
    `player_slug == slug(player)` assertions this replaces came to prove nothing.
    """
    seasons = load_raw()
    bible = load_bible()
    bible = apply_derived_champions(bible, seasons)
    bible = apply_derived_owners(bible, seasons)
    apply_player_aliases(seasons, bible)
    apply_bible_positions(seasons, bible)
    index = build_player_index(
        seasons, build_player_log(seasons), build_owner_map(bible, seasons)
    )
    pages = {slug(name) for name in index}
    assert len(pages) == EXPECTED_PLAYER_PAGES, len(pages)
    return pages


@pytest.fixture(scope="module")
def rows(league, owners):
    seasons, bible = league
    return matchup_rows(seasons, bible, owners)


@pytest.fixture(scope="module")
def player_rows(league, owners):
    seasons, _ = league
    return player_week_rows(seasons, owners)


@pytest.fixture(scope="module")
def team_rows(league, owners):
    seasons, bible = league
    return team_season_rows(seasons, bible, owners)


@pytest.fixture(scope="module")
def picks(league, owners):
    seasons, _ = league
    return draft_rows(seasons, owners)


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    """build_all() run once into a temp dir, with its schema and output path.

    Module-scoped because it walks the whole capture and writes four Parquet
    files; the idempotency check below builds its own second copy rather than
    reusing this one, since that is the thing it is measuring.
    """
    out_root = tmp_path_factory.mktemp("query_db")
    schema = build_all(out_root)
    return schema, out_root / "query"


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
    earlier = {row["owner"] for row in team_rows if row["year"] < max(seasons)}
    assert len(latest & earlier) == EXPECTED_RETURNING_OWNERS


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


def test_player_slug_resolves_to_a_page_the_wiki_writes(
    player_rows, wiki_player_pages
):
    """The slug is the link target for players/<slug>/, so it must exist.

    Comparing it against `slug(row["player"])` would prove nothing: that is the
    expression the builder computes it with. The claim worth making is that the
    page is there, which is a claim about the NAME -- an unfolded spelling slugs
    perfectly well and links nowhere.
    """
    for row in player_rows:
        assert row["player_slug"] in wiki_player_pages, row


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


def test_draft_player_slug_resolves_to_a_page_the_wiki_writes(
    picks, wiki_player_pages
):
    """The draft table is where the unfolded names actually landed.

    Eleven 2026 Sleeper picks -- Aaron Jones, Kyle Pitts, Marvin Harrison and
    eight more -- reach the builder under the short spelling, and each one slugs
    to a path the wiki never wrote. The weekly rosters escape it only because
    2026 has no captured games yet, so this is the check that fails first.
    """
    for row in picks:
        assert row["player_slug"] in wiki_player_pages, row


def test_the_player_page_set_is_a_real_constraint(league, wiki_player_pages):
    """Guards the two checks above from holding for any spelling at all.

    They are only worth running while an unfolded name genuinely has no page.
    If every alias variant also got one -- because the fold stopped happening
    upstream, say -- both would pass on exactly the data they exist to reject.
    """
    _, bible = league
    aliases = build_player_alias_map(bible)
    assert aliases, "no player aliases; the slug checks would be vacuous"
    unwritten = {
        variant for variant in aliases if slug(variant) not in wiki_player_pages
    }
    assert unwritten, "every alias variant has a page of its own"


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
    blank = len(picks) - len(filled)
    assert blank == EXPECTED_DRAFT_PICKS_WITHOUT_POSITION, blank


def test_an_unnumbered_pick_is_dropped_rather_than_sorted_to_the_front():
    """A pick annotate_overall_picks could not number must not reorder a round.

    Synthetic, because the capture holds no such pick: a forfeited or
    auto-skipped slot reaches the builder with no `overall`, and reading that as
    0 sorts it ahead of the entire draft and shifts every `pick` in its round by
    one. Only round 2 shows the damage — the ghost would take pick 1 and push
    the real first pick of the round to 2.
    """
    season = {
        "draft": {
            "draft_results": [
                {"round": 1, "overall": 1, "player": "A", "team": "T"},
                {"round": 1, "overall": 2, "player": "B", "team": "T"},
                {"round": 2, "overall": 3, "player": "C", "team": "T"},
                {"round": 2, "player": "Forfeited", "team": "T"},
            ]
        }
    }
    rows = draft_rows({2099: season}, {(2099, "T"): "Someone"})
    assert [row["player"] for row in rows] == ["A", "B", "C"]
    assert [(row["round"], row["pick"]) for row in rows] == [(1, 1), (1, 2), (2, 1)]


def test_draft_teams_are_teams_that_played_that_season(picks, team_rows):
    """The join key is (year, team), so a draft-only team name would break it."""
    known = {(row["year"], row["team"]) for row in team_rows}
    for row in picks:
        assert (row["year"], row["team"]) in known, row


# --------------------------------------------------------------------------- #
# the emitter: Parquet + schema.json
# --------------------------------------------------------------------------- #
def test_build_all_writes_a_parquet_file_per_table(emitted):
    _, out = emitted
    for table in TABLES:
        assert (out / f"{table}.parquet").is_file(), table
    assert (out / "schema.json").is_file()


def test_build_all_returns_the_schema_it_wrote(emitted):
    """The query page is rendered from the return value, not from a re-read."""
    schema, out = emitted
    assert schema == json.loads((out / "schema.json").read_text())


def test_the_schema_describes_every_table(emitted):
    schema, _ = emitted
    assert set(schema["tables"]) == set(TABLES)


def test_the_schema_reports_the_declared_columns_and_types(emitted):
    """What the file advertises has to be what DuckDB actually typed.

    Read back with DESCRIBE, so a column DuckDB widened or reordered on insert
    shows up here rather than reaching the browser, which builds its operator
    menus from these types -- offering a numeric comparison on a column stored
    as text produces a query that returns nothing and reports no error.
    """
    schema, _ = emitted
    for table, declared in TABLE_SCHEMAS.items():
        reported = [
            (column["name"], column["type"])
            for column in schema["tables"][table]["columns"]
        ]
        assert reported == list(declared), table


def test_the_schema_types_describe_the_values_the_rows_carry(
    emitted, rows, player_rows, team_rows, picks
):
    """The declaration itself has to be right, not merely self-consistent.

    The check above compares what DuckDB reports against what this module
    declared, which both move together if the declaration is simply wrong. This
    one derives the type from the Python values the builders produced, so a
    `seed` declared VARCHAR — which DuckDB would cast to without complaint, and
    which would then sort 10 before 2 in the browser — fails here.
    """
    from_python = {bool: "BOOLEAN", int: "INTEGER", float: "DOUBLE", str: "VARCHAR"}
    built = {
        "matchups": rows,
        "player_weeks": player_rows,
        "team_seasons": team_rows,
        "draft": picks,
    }
    schema, _ = emitted
    for table, table_rows in built.items():
        reported = {c["name"]: c["type"] for c in schema["tables"][table]["columns"]}
        for column, sql_type in reported.items():
            # type(), not isinstance: bool subclasses int, so an isinstance
            # walk would type every flag column as INTEGER.
            seen = {type(row[column]) for row in table_rows}
            assert len(seen) == 1, f"{table}.{column} holds {seen}"
            assert from_python[seen.pop()] == sql_type, f"{table}.{column}"


def test_the_schema_row_counts_match_the_builders(emitted, rows, player_rows,
                                                  team_rows, picks):
    schema, _ = emitted
    counts = {table: schema["tables"][table]["row_count"] for table in TABLES}
    assert counts == {
        "matchups": len(rows),
        "player_weeks": len(player_rows),
        "team_seasons": len(team_rows),
        "draft": len(picks),
    }
    # The builders are pinned to the capture above; restate the totals here so a
    # schema that reported a count matching two equally wrong tables still fails.
    assert counts["matchups"] == EXPECTED_MATCHUP_ROWS
    assert counts["player_weeks"] == EXPECTED_PLAYER_WEEK_ROWS
    assert counts["team_seasons"] == EXPECTED_TEAM_SEASON_ROWS
    assert counts["draft"] == EXPECTED_DRAFT_ROWS


def test_the_schema_carries_a_dropdown_list_for_every_enum_column(emitted):
    schema, _ = emitted
    assert set(ENUM_COLUMNS) == EXPECTED_ENUM_COLUMNS
    for column in ENUM_COLUMNS:
        assert schema["enums"].get(column), f"no distinct values for {column}"


def test_the_enum_lists_are_the_values_the_tables_hold(emitted, league, team_rows):
    """A dropdown built from a stale or truncated list silently hides rows.

    The owner list is the one that matters most: it is 16 people, and a query
    UI that offers 15 of them makes one manager's career unreachable with no
    error anywhere.
    """
    schema, _ = emitted
    seasons, _bible = league
    enums = schema["enums"]
    assert set(enums["owner"]) == {row["owner"] for row in team_rows}
    assert len(enums["owner"]) == EXPECTED_OWNER_COUNT
    assert set(enums["phase"]) == PHASES
    assert set(enums["year"]) == set(seasons)
    assert set(enums["slot"]) >= BENCH_SLOTS
    # Blanks are dropped: an unclickable empty row in a dropdown is not a filter.
    for column in ENUM_COLUMNS:
        assert "" not in enums[column], column


def test_the_enum_lists_are_sorted(emitted):
    """Sorted is what makes a rebuild byte-identical and a diff readable."""
    schema, _ = emitted
    for column, values in schema["enums"].items():
        assert values == sorted(values), column


def test_the_parquet_tables_fit_the_transfer_budget(emitted):
    schema, out = emitted
    sizes = {t: (out / f"{t}.parquet").stat().st_size for t in TABLES}
    total = sum(sizes.values())
    assert total < MAX_PARQUET_BYTES, sizes
    for table, size in sizes.items():
        assert size > 0, table
    assert schema  # the sizes above are of the files this schema describes


def test_the_parquet_files_hold_the_rows_the_schema_claims(emitted):
    """Query the written files, not the in-memory tables that produced them.

    Everything above measures the dicts. This is the only check that the COPY
    actually landed the rows in a file a browser could read back.
    """
    schema, out = emitted
    con = duckdb.connect()
    try:
        for table in TABLES:
            path = (out / f"{table}.parquet").as_posix()
            count = con.execute(
                f"SELECT count(*) FROM read_parquet('{path}')"
            ).fetchone()[0]
            assert count == schema["tables"][table]["row_count"], table
    finally:
        con.close()


def test_no_owner_column_reaches_parquet_blank(emitted):
    """The spec's "no NULL owners in any table", checked on the shipped files.

    A blank owner drops its row out of every group-by the UI can build without
    raising anywhere, so it is enforced in the emitter; this is the end-to-end
    confirmation that the enforcement survives the COPY.
    """
    _, out = emitted
    con = duckdb.connect()
    try:
        for table, columns in TABLE_SCHEMAS.items():
            path = (out / f"{table}.parquet").as_posix()
            for column, _type in columns:
                if column not in ("owner", "opp_owner"):
                    continue
                bad = con.execute(
                    f"SELECT count(*) FROM read_parquet('{path}') "
                    f'WHERE "{column}" IS NULL OR trim("{column}") = \'\''
                ).fetchone()[0]
                assert bad == 0, f"{table}.{column} has {bad} blank rows"
    finally:
        con.close()


def test_the_emitter_refuses_a_blank_owner(team_rows):
    """The structural guard, exercised on a row the capture cannot produce.

    Without this the "no blank owners" rule lives only in the assertions above,
    which run against today's capture; a future one that lost a standings entry
    would ship a hole in the owner column instead of failing the build.
    """
    doctored = [dict(row) for row in team_rows]
    doctored[0]["owner"] = ""
    con = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="blank owner"):
            _load_table(con, "team_seasons", doctored)
    finally:
        con.close()


def test_the_emitter_refuses_a_blank_opponent_owner(rows):
    """The opponent side too: a head-to-head query joins on both."""
    doctored = [dict(row) for row in rows]
    doctored[0]["opp_owner"] = "   "
    con = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="blank opp_owner"):
            _load_table(con, "matchups", doctored)
    finally:
        con.close()


def test_the_emitter_refuses_an_empty_table():
    """All four tables are non-empty in the capture, so empty means broken."""
    con = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="no rows"):
            _load_table(con, "draft", [])
    finally:
        con.close()


def test_the_emitter_refuses_a_row_with_an_undeclared_column(picks):
    """An extra key would otherwise be dropped from the Parquet file silently."""
    doctored = [dict(row) for row in picks]
    for row in doctored:
        row["keeper"] = False
    con = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="declared"):
            _load_table(con, "draft", doctored)
    finally:
        con.close()


def test_build_tables_returns_one_entry_per_declared_table(league):
    seasons, bible = league
    tables = build_tables(seasons, bible)
    assert set(tables) == set(TABLES)
    for table, table_rows in tables.items():
        assert table_rows, table
        assert set(table_rows[0]) == {c for c, _ in TABLE_SCHEMAS[table]}, table


def test_rebuilding_rewrites_an_identical_schema(tmp_path: pathlib.Path):
    """Idempotent, so a rebuild in CI produces no diff to review."""
    build_all(tmp_path)
    first = (tmp_path / "query" / "schema.json").read_text()
    build_all(tmp_path)
    assert (tmp_path / "query" / "schema.json").read_text() == first
