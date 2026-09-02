import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (  # noqa: E402
    build_owner_aggregates,
    build_owner_map,
    canonical_owner,
    team_image_src,
)


SEASONS = {
    2024: {
        "standings": {
            "teams": [
                {"name": "Old Name", "owner": "lokesh", "wins": 9, "losses": 5, "rank": 1,
                 "points_for": 1500, "points_against": 1400},
                {"name": "Other Team", "owner": "Pat", "wins": 5, "losses": 9, "rank": 2,
                 "points_for": 1300, "points_against": 1450},
            ]
        }
    },
    2025: {
        "standings": {
            "teams": [
                {"name": "New Name", "owner": "Lokesh", "wins": 3, "losses": 11, "rank": 8,
                 "points_for": 1200, "points_against": 1500},
                {"name": "Other Team", "owner": "Pat", "wins": 11, "losses": 3, "rank": 1,
                 "points_for": 1600, "points_against": 1350},
            ]
        }
    },
}


def test_owner_map_folds_casing_and_prefers_latest_season():
    owner_map = build_owner_map({}, SEASONS)
    # "lokesh" (2024) and "Lokesh" (2025) are one person; the later season wins.
    assert canonical_owner("lokesh", owner_map) == "Lokesh"
    assert canonical_owner("LOKESH", owner_map) == "Lokesh"


def test_owner_aliases_beat_the_data():
    bible = {"owner_aliases": {"Lokesh R": ["lokesh", "Lokesh"]}}
    owner_map = build_owner_map(bible, SEASONS)
    assert canonical_owner("Lokesh", owner_map) == "Lokesh R"
    assert canonical_owner("lokesh", owner_map) == "Lokesh R"


def test_owner_aggregates_span_every_franchise():
    owner_map = build_owner_map({}, SEASONS)
    aggregates = build_owner_aggregates(SEASONS, {}, owner_map)
    lokesh = aggregates["Lokesh"]
    assert lokesh["wins"] == 12 and lokesh["losses"] == 16
    assert lokesh["seasons_count"] == 2
    # Two differently named teams, one owner, one career record.
    assert sorted(f["name"] for f in lokesh["teams"].values()) == ["New Name", "Old Name"]
    assert lokesh["playoff_appears"] == 1
    assert lokesh["titles"] == []


def test_owner_aggregates_attribute_championships_by_year():
    owner_map = build_owner_map({}, SEASONS)
    bible = {"champions": {2025: {"champion": "Other Team"}}}
    aggregates = build_owner_aggregates(SEASONS, bible, owner_map)
    assert aggregates["Pat"]["titles"] == [2025]
    assert aggregates["Lokesh"]["titles"] == []


def test_team_image_src_forms():
    images = {
        "Bare": "bare.png",
        "Pathed": "assets/teams/pathed.png",
        "Rooted": "/assets/teams/rooted.png",
        "Remote": "https://example.com/logo.png",
        "Blank": "",
    }
    assert team_image_src("Bare", images) == "../assets/teams/bare.png"
    assert team_image_src("Pathed", images) == "../assets/teams/pathed.png"
    assert team_image_src("Rooted", images) == "../assets/teams/rooted.png"
    assert team_image_src("Remote", images) == "https://example.com/logo.png"
    assert team_image_src("Blank", images) == ""
    assert team_image_src("Missing", images) == ""


def load_transform():
    """zensical/transform.py is a script, not a package module."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "zensical" / "transform.py"
    spec = importlib.util.spec_from_file_location("phf_transform", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEAM_PAGE = """# 🏈 Roger That

- **Image:** ![Roger That](../assets/teams/roger-that.png)
- **Owner:** [Pranav](../owners/pranav.md)
- **Joined:** _TBD_
- **Status:** Active

## Franchise Summary

- **Championships:** 1
- **All-Time Record:** 46-60 (43.4%)
- **All-Time Points For / Against:** 13094.50 / 13278.08
"""


def test_infobox_lifts_image_and_link_out_of_the_lead():
    transform = load_transform()
    out = transform.inject_infobox(TEAM_PAGE, transform.TEAM_INFOBOX_FIELDS)
    # The image heads the box, keeping the source-relative path the engine rewrites.
    assert '<div class="infobox-image"><img src="../assets/teams/roger-that.png"' in out
    # Markdown links inside a raw-HTML value would ship as literal text.
    assert '<a href="../owners/pranav.md">Pranav</a>' in out
    # Lead lines are the box's data source, so they are not repeated below it.
    assert "- **Image:**" not in out
    assert "- **Owner:**" not in out


def test_owner_infobox_uses_its_own_fields():
    transform = load_transform()
    page = """# 🧑 Naren

- **Franchises:** 8
- **Seasons:** 2018-present
- **Status:** Active

## Career Summary

- **Championships:** 0
- **All-Time Record:** 64-43 (59.8%)
- **All-Time Points For / Against:** 13898.38 / 12907.72
"""
    out = transform.inject_infobox(page, transform.OWNER_INFOBOX_FIELDS)
    assert '<div class="label">Franchises</div><div class="value">8</div>' in out
    assert '<div class="label">Seasons</div>' in out
    assert "Owner</div>" not in out
    assert "- **Franchises:**" not in out


# --------------------------------------------------------------------------- #
# matchup-derived records
# --------------------------------------------------------------------------- #
# One season: three regular weeks, then a two-game playoff week where one game
# is in the bracket and the other is consolation play.
MATCHUP_SEASON = {
    2025: {
        "standings": {
            "teams": [
                {"name": "A", "owner": "Ann", "wins": 3, "losses": 0, "rank": 1,
                 "points_for": 300, "points_against": 200},
                {"name": "B", "owner": "Bo", "wins": 0, "losses": 3, "rank": 4,
                 "points_for": 200, "points_against": 300},
            ]
        },
        "playoffs": {"weeks": {"4": []}},
        "bracket": {"games": [{"week": 4, "round": "Final", "teams": [
            {"name": "A", "score": 150.0, "is_winner": True},
            {"name": "B", "score": 100.0, "is_winner": False},
        ]}]},
        "matchups": {
            "1": [{"teams": [{"name": "A", "score": 110.0, "is_winner": True},
                             {"name": "B", "score": 90.0, "is_winner": False}]}],
            "2": [{"teams": [{"name": "A", "score": 80.0, "is_winner": True},
                             {"name": "B", "score": 79.5, "is_winner": False}]}],
            "3": [{"teams": [{"name": "A", "score": 200.0, "is_winner": True},
                             {"name": "B", "score": 60.0, "is_winner": False}]}],
            "4": [
                {"teams": [{"name": "A", "score": 150.0, "is_winner": True},
                           {"name": "B", "score": 100.0, "is_winner": False}]},
                {"teams": [{"name": "C", "score": 70.0, "is_winner": True},
                           {"name": "D", "score": 65.0, "is_winner": False}]},
            ],
        },
    }
}


def test_phases_split_bracket_from_consolation():
    from scripts.generate import PHASE_CONSOLATION, PHASE_PLAYOFF, PHASE_REGULAR, build_game_log

    log = build_game_log(MATCHUP_SEASON, {})
    phases = {}
    for row in log:
        phases[row["phase"]] = phases.get(row["phase"], 0) + 1
    # Two rows per game: 3 regular games, 1 bracket game, 1 consolation game.
    assert phases == {PHASE_REGULAR: 6, PHASE_PLAYOFF: 2, PHASE_CONSOLATION: 2}


def test_record_books_stay_separate_per_phase():
    from scripts.generate import (
        FINALS_ROUND,
        PHASE_PLAYOFF,
        PHASE_REGULAR,
        build_matchup_stats,
    )

    books = build_matchup_stats(MATCHUP_SEASON, {})["books"]
    # The 200-point regular week is a regular-season record and nothing more.
    assert books[PHASE_REGULAR]["highest_score"][0]["score"] == 200.0
    assert books[PHASE_REGULAR]["nailbiter"][0]["margin"] == 0.5
    assert books[PHASE_REGULAR]["blowout"][0]["margin"] == 140.0
    # The playoff book sees only the bracket game.
    assert books[PHASE_PLAYOFF]["highest_score"][0]["score"] == 150.0
    assert books[PHASE_PLAYOFF]["lowest_score"][0]["score"] == 100.0
    # The consolation game (70-65) is in no book at all.
    assert books[PHASE_PLAYOFF]["lowest_score"][0]["score"] != 65.0
    # This season's only bracket game is the Final, so both books agree.
    assert books[FINALS_ROUND]["highest_score"][0]["score"] == 150.0


def test_matchup_stats_head_to_head():
    from scripts.generate import build_matchup_stats

    stats = build_matchup_stats(MATCHUP_SEASON, {})
    team_a = stats["teams"]["A"]
    # A rivalry counts every meeting, bracket games included: 3 regular wins
    # plus the Final. The playoff split is kept alongside, not instead.
    head_to_head = team_a["head_to_head"]["B"]
    assert head_to_head["wins"] == 4 and head_to_head["losses"] == 0
    assert head_to_head["playoff_wins"] == 1 and head_to_head["playoff_losses"] == 0
    # The record books stay phase-scoped; only the rivalry spans them.
    assert len(team_a["regular"]) == 3
    assert team_a["streak"] == (3, 2025, 2025)
    assert team_a["playoff_wins"] == 1 and team_a["playoff_losses"] == 0
    # Consolation play is in neither ledger.
    assert stats["teams"]["C"]["playoff_wins"] == 0
    assert stats["playoff_teams"] == {(2025, "A"), (2025, "B")}


def test_season_records_pick_both_extremes():
    from scripts.generate import build_season_records

    records = build_season_records(MATCHUP_SEASON, {})
    assert records["most_pf"][0]["team"] == "A"
    assert records["fewest_pf"][0]["team"] == "B"
    assert records["best_record"][0]["team"] == "A"
    assert records["worst_record"][0]["team"] == "B"


def test_playoff_membership_comes_from_the_bracket():
    from scripts.generate import build_matchup_stats, made_playoffs

    playoff_teams = build_matchup_stats(MATCHUP_SEASON, {})["playoff_teams"]
    # Rank 4 would pass the old seed cutoff either way; rank 9 would not, and
    # the bracket is what decides.
    assert made_playoffs(2025, "B", 9, playoff_teams) is True
    assert made_playoffs(2025, "C", 1, playoff_teams) is False
    # No bracket captured: fall back to the seed cutoff.
    assert made_playoffs(2025, "C", 1, None) is True


def test_owner_playoff_career_counts_finals():
    from scripts.generate import build_matchup_stats, build_owner_game_stats, build_owner_map

    owner_map = build_owner_map({}, MATCHUP_SEASON)
    stats = build_owner_game_stats(
        MATCHUP_SEASON, owner_map, build_matchup_stats(MATCHUP_SEASON, {})
    )
    ann = stats["Ann"]
    assert ann["playoff_wins"] == 1 and ann["playoff_losses"] == 0
    assert ann["playoff_years"] == {2025} and ann["finals_years"] == {2025}
    assert ann["playoff_wpct"] == 1.0
    assert ann["playoff_avg"] == 150.0
    # Bo reached the Final and lost it: an appearance, not a title.
    assert stats["Bo"]["finals_years"] == {2025}
    assert stats["Bo"]["playoff_wins"] == 0


def test_totals_span_every_phase():
    from scripts.generate import build_matchup_stats, build_owner_game_stats, build_owner_map

    owner_map = build_owner_map({}, MATCHUP_SEASON)
    stats = build_owner_game_stats(
        MATCHUP_SEASON, owner_map, build_matchup_stats(MATCHUP_SEASON, {})
    )
    ann = stats["Ann"]
    # 3 regular + 1 bracket game: totals count both, the split books do not.
    assert ann["total_games"] == 4
    assert ann["total_wins"] == 4 and ann["total_losses"] == 0
    assert ann["total_points"] == 540.0  # 110 + 80 + 200 + 150
    assert ann["total_avg"] == 135.0
    assert len(ann["regular"]) == 3


def test_rate_minimums_admit_one_full_unit_of_play():
    from scripts.generate import MIN_GAMES_FOR_AVERAGE, MIN_PLAYOFF_GAMES_FOR_RATE

    # A single season is 11-14 games in the captured data, and a full bracket
    # run is 3. Raising either above one complete unit silently drops managers
    # who played exactly one -- and hid the league's best playoff average.
    assert MIN_GAMES_FOR_AVERAGE <= 11
    assert MIN_PLAYOFF_GAMES_FOR_RATE <= 3


def test_outright_book_sees_every_phase():
    from scripts.generate import (
        BOOK_TOTAL,
        PHASE_PLAYOFF,
        PHASE_REGULAR,
        build_matchup_stats,
    )

    books = build_matchup_stats(MATCHUP_SEASON, {})["books"]
    # Here a regular-season game holds both outright marks, so the two books
    # agree -- the case the totals book exists to notice is when they stop.
    assert books[PHASE_REGULAR]["lowest_score"][0]["score"] == 60.0
    assert books[BOOK_TOTAL]["lowest_score"][0]["score"] == 60.0
    assert books[BOOK_TOTAL]["highest_score"][0]["score"] == 200.0
    # Only the totals book can name a game no phase book contains: the 70-65
    # consolation win is the outright fewest points in a win, while the
    # regular-season book sees 80.0 and the playoff book 150.0.
    assert books[BOOK_TOTAL]["fewest_points_in_win"][0]["score"] == 70.0
    assert books[PHASE_REGULAR]["fewest_points_in_win"][0]["score"] == 80.0
    assert books[PHASE_PLAYOFF]["fewest_points_in_win"][0]["score"] == 150.0


# A season with a drawn game and a two-way share of the closest-game record.
TIED_SEASON = {
    2025: {
        "standings": {
            "teams": [
                {"name": "A", "owner": "Ann", "wins": 1, "losses": 1, "rank": 1,
                 "points_for": 250, "points_against": 250},
                {"name": "B", "owner": "Bo", "wins": 1, "losses": 1, "rank": 2,
                 "points_for": 250, "points_against": 250},
            ]
        },
        "matchups": {
            # Drawn game: Yahoo reports neither side as the winner.
            "1": [{"teams": [{"name": "A", "score": 143.2, "is_winner": False},
                             {"name": "B", "score": 143.2, "is_winner": False}]}],
            # Two different games decided by the same 0.02 margin.
            "2": [{"teams": [{"name": "A", "score": 100.02, "is_winner": True},
                             {"name": "B", "score": 100.0, "is_winner": False}]}],
            "3": [{"teams": [{"name": "B", "score": 90.02, "is_winner": True},
                             {"name": "A", "score": 90.0, "is_winner": False}]}],
        },
    }
}


def test_a_drawn_game_is_a_tie_not_a_loss():
    from scripts.generate import PHASE_REGULAR, build_matchup_stats, record_str

    stats = build_matchup_stats(TIED_SEASON, {})
    drawn = [row for row in stats["log"] if row["year"] == 2025 and row["week"] == 1]
    assert len(drawn) == 2
    assert all(row["tied"] and not row["won"] for row in drawn)

    head_to_head = stats["teams"]["A"]["head_to_head"]["B"]
    assert (head_to_head["wins"], head_to_head["losses"], head_to_head["ties"]) == (1, 1, 1)
    assert record_str(1, 1, 1) == "1-1-1"
    assert record_str(1, 1, 0) == "1-1"

    # The tie is listed on its own: it has no winner, so it ranks in neither
    # margin record.
    book = stats["books"][PHASE_REGULAR]
    assert len(book["ties"]) == 1  # one game, not one row per side
    assert book["ties"][0]["score"] == 143.2
    assert all(row["margin"] > 0 for row in book["nailbiter"])


def test_a_shared_record_lists_every_holder():
    from scripts.generate import PHASE_REGULAR, build_matchup_stats, single_game_rows

    book = build_matchup_stats(TIED_SEASON, {})["books"][PHASE_REGULAR]
    # Two separate games are both decided by 0.02, so both hold the record.
    assert len(book["nailbiter"]) == 2
    assert {row["team"] for row in book["nailbiter"]} == {"A", "B"}

    rendered = [row for row in single_game_rows(book) if "Closest Game" in row]
    assert len(rendered) == 2
    assert all("(tied)" in row for row in rendered)


def test_tie_counts_as_half_a_win_in_totals():
    from scripts.generate import build_matchup_stats, build_owner_game_stats, build_owner_map

    owner_map = build_owner_map({}, TIED_SEASON)
    stats = build_owner_game_stats(
        TIED_SEASON, owner_map, build_matchup_stats(TIED_SEASON, {})
    )["Ann"]
    assert stats["total_games"] == 3
    assert (stats["total_wins"], stats["total_losses"], stats["total_ties"]) == (1, 1, 1)
    # NFL convention: (1 + 0.5) / 3.
    assert stats["total_wpct"] == 0.5


def test_owner_rivalries_follow_the_person_across_renames():
    from scripts.generate import build_matchup_stats, build_owner_game_stats, build_owner_map

    owner_map = build_owner_map({}, MATCHUP_SEASON)
    stats = build_owner_game_stats(
        MATCHUP_SEASON, owner_map, build_matchup_stats(MATCHUP_SEASON, {})
    )
    versus_bo = stats["Ann"]["head_to_head"]["Bo"]
    # Three regular meetings plus the Final: a rivalry counts the bracket games,
    # which is where the phase-split record books deliberately do not look.
    assert versus_bo["wins"] == 4 and versus_bo["losses"] == 0
    assert versus_bo["playoff_wins"] == 1
    # The mirror image is the same rivalry from the other side.
    versus_ann = stats["Bo"]["head_to_head"]["Ann"]
    assert versus_ann["losses"] == 4 and versus_ann["playoff_losses"] == 1
    assert versus_ann["pf"] == versus_bo["pa"]
    # Nobody is their own rival.
    assert "Ann" not in stats["Ann"]["head_to_head"]


def test_margin_boards_list_one_row_per_game():
    from scripts.generate import build_matchup_stats, games_by_margin

    log = build_matchup_stats(TIED_SEASON, {})["log"]
    # The drawn game is margin 0.00 and belongs in the close list, as one row
    # rather than one per side.
    close = games_by_margin(log, 1.0, above=False)
    assert len(close) == 3  # the tie plus the two 0.02 games
    assert close[0]["tied"] and close[0]["margin"] == 0.0
    assert [row["margin"] for row in close] == [0.0, 0.02, 0.02]

    # Nothing in this fixture is a blowout, and an empty board is empty rather
    # than wrong.
    assert games_by_margin(log, 80.0, above=True) == []


def test_margin_boards_sort_outward_from_the_threshold():
    from scripts.generate import build_matchup_stats, games_by_margin

    log = build_matchup_stats(MATCHUP_SEASON, {})["log"]
    wide = games_by_margin(log, 20.0, above=True)
    # Widest first for blowouts.
    assert [row["margin"] for row in wide] == sorted(
        (row["margin"] for row in wide), reverse=True
    )
    assert wide[0]["margin"] == 140.0
    # Closest first for nailbiters, and a losing side never appears (negative
    # margins are excluded).
    close = games_by_margin(log, 10.0, above=False)
    assert all(row["margin"] >= 0 for row in close)
    assert close[0]["margin"] == 0.5
