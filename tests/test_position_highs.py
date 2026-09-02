import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.generate import (
    FINALS_ROUND,
    PHASE_PLAYOFF,
    PHASE_REGULAR,
    POSITION_ORDER,
    player_book_rows,
    player_record_lines,
    player_season_high_line,
    player_season_highs,
    position_week_highs,
    position_week_rows,
)


def row(player, position, points, **over):
    entry = {
        "year": 2024,
        "week": 3,
        "phase": PHASE_REGULAR,
        "round": "",
        "team": "Team A",
        "player": player,
        "position": position,
        "slot": position,
        "points": points,
        "started": True,
    }
    entry.update(over)
    return entry


def winners(highs):
    return {position: [r["player"] for r in holders] for position, holders in highs}


def test_each_position_gets_its_own_high():
    """The point of the split: a kicker's best day cannot be seen through a
    league-wide record a receiver always holds."""
    log = [
        row("Big WR", "WR", 57.9),
        row("Small WR", "WR", 10.0),
        row("Big K", "K", 26.0),
        row("Small K", "K", 4.0),
    ]
    assert winners(position_week_highs(log)) == {"WR": ["Big WR"], "K": ["Big K"]}


def test_benched_scores_do_not_hold_the_mark():
    log = [
        row("Benched", "QB", 51.9, started=False, slot="BN"),
        row("Started", "QB", 30.0),
    ]
    assert winners(position_week_highs(log)) == {"QB": ["Started"]}


def test_phase_scoping_keeps_the_books_apart():
    log = [
        row("Regular", "RB", 30.0),
        row("Playoff", "RB", 60.0, phase=PHASE_PLAYOFF, week=15),
        row("Final", "RB", 70.0, phase=PHASE_PLAYOFF, week=17, round=FINALS_ROUND),
    ]
    assert winners(position_week_highs(log)) == {"RB": ["Regular"]}
    assert winners(position_week_highs(log, PHASE_PLAYOFF)) == {"RB": ["Final"]}
    assert winners(position_week_highs(log, FINALS_ROUND)) == {"RB": ["Final"]}


def test_year_filter_is_what_a_season_page_reads():
    log = [row("This Year", "TE", 20.0), row("Last Year", "TE", 45.0, year=2023)]
    assert winners(position_week_highs(log, year=2024)) == {"TE": ["This Year"]}


def test_ties_are_listed_not_arbitrated():
    """Two defenses really did both score 37. Picking one would hide the other,
    which is the rule the rest of the record book follows."""
    log = [
        row("Patriots", "DEF", 37.0, year=2019),
        row("Cowboys", "DEF", 37.0, year=2023),
        row("Bears", "DEF", 24.0),
    ]
    highs = position_week_highs(log)
    assert winners(highs) == {"DEF": ["Patriots", "Cowboys"]}
    rows = position_week_rows(highs, lambda r: str(r["year"]))
    assert "DEF (2-way tie)" in rows[0]
    # The second holder's label cell is blank, so the pair reads as one group.
    assert rows[1].startswith("|  | ")


def test_positions_come_out_in_reading_order():
    log = [row(p, p, 10.0) for p in reversed(POSITION_ORDER)] + [row("Odd", "P", 9.0)]
    assert [position for position, _ in position_week_highs(log)] == POSITION_ORDER + ["P"]


def test_empty_log_renders_a_tbd_row_rather_than_an_empty_table():
    assert position_week_highs([]) == []
    assert position_week_rows([], lambda r: "") == ["| _TBD_ | _TBD_ | _TBD_ | _TBD_ |"]


# Weeks rostered is a career mark that spans every phase and ties whenever two
# players sat on a roster equally often, which in a fixture this small is always.
# These tests are about the scoring marks, so they read past it.
def scoring_marks(lines, player):
    return [line for line in lines.get(player, []) if "Weeks Rostered" not in line]


def test_only_holders_get_record_lines():
    log = [row("Holder", "WR", 50.0), row("Nobody", "WR", 5.0)]
    lines = player_record_lines(log)
    assert scoring_marks(lines, "Nobody") == []
    assert "Highest Week - 50.00 (WR)" in scoring_marks(lines, "Holder")


def test_the_league_wide_holder_is_not_told_twice():
    """The best week in the league is always a receiver or a back, so his page
    would otherwise read "Highest Week" and "Highest WR Week" for one game."""
    log = [row("Best", "WR", 50.0), row("Kicker", "K", 26.0)]
    lines = player_record_lines(log)
    assert "Highest Week - 50.00 (WR)" in scoring_marks(lines, "Best")
    assert not any("WR Week" in line for line in lines["Best"])
    # The kicker's mark is invisible league-wide, which is the whole point.
    assert "Highest K Week - 26.00" in scoring_marks(lines, "Kicker")


def test_a_positional_high_survives_when_another_player_holds_the_league_mark():
    log = [row("Best", "WR", 50.0), row("Second", "WR", 40.0), row("RB Guy", "RB", 45.0)]
    lines = player_record_lines(log)
    assert scoring_marks(lines, "RB Guy") == ["Highest RB Week - 45.00"]
    assert scoring_marks(lines, "Second") == []


def test_both_sides_of_a_tie_are_credited():
    log = [
        row("Patriots", "DEF", 37.0, year=2019),
        row("Cowboys", "DEF", 37.0, year=2023),
        row("Big WR", "WR", 50.0),
    ]
    lines = player_record_lines(log)
    assert scoring_marks(lines, "Patriots") == ["Highest DEF Week - 37.00"]
    assert scoring_marks(lines, "Cowboys") == ["Highest DEF Week - 37.00"]


def test_record_lines_and_the_book_name_the_same_holder():
    """Both read `player_book_marks`, so a page cannot credit someone the record
    book does not."""
    log = [row("Best", "WR", 50.0), row("Benched", "QB", 60.0, started=False, slot="BN")]
    book = "\n".join(player_book_rows(log))
    for player in player_record_lines(log):
        assert player in book


def test_a_season_high_is_credited_even_when_a_bigger_year_exists():
    """The 2019 leader led 2019. An all-time table hides him behind whoever had
    the better week in some other season, which is why the seasons are read one
    at a time."""
    log = [
        row("Watson", "QB", 41.7, year=2019),
        row("Allen", "QB", 44.7, year=2025),
        row("Nobody", "QB", 10.0, year=2019),
    ]
    highs = player_season_highs(log)
    assert highs["Watson"] == {"QB": [2019]}
    assert highs["Allen"] == {"QB": [2025]}
    assert "Nobody" not in highs


def test_repeat_years_gather_under_one_position():
    log = [
        row("Hill", "WR", 43.5, year=2018),
        row("Hill", "WR", 57.9, year=2020),
        row("Hill", "WR", 47.6, year=2021),
    ]
    assert player_season_highs(log)["Hill"] == {"WR": [2018, 2020, 2021]}
    assert player_season_high_line({"WR": [2018, 2020, 2021]}) == "WR 2018, 2020, 2021"


def test_a_season_tie_credits_both_kickers():
    log = [
        row("Carlson", "K", 21.0, year=2021),
        row("Folk", "K", 21.0, year=2021, team="Team B"),
    ]
    highs = player_season_highs(log)
    assert highs["Carlson"] == {"K": [2021]} and highs["Folk"] == {"K": [2021]}


def test_the_line_reads_in_position_order():
    line = player_season_high_line({"TE": [2021], "QB": [2019, 2023]})
    assert line == "QB 2019, 2023 · TE 2021"
    assert player_season_high_line({}) == ""


def test_record_lines_respect_scope():
    """A 70-point Final is not a regular-season record, and the October week is
    not a Finals one. Weeks rostered is the documented exception: it counts time
    on a roster rather than a result, so it spans every phase."""
    log = [
        row("Regular", "RB", 30.0),
        row("Final", "RB", 70.0, phase=PHASE_PLAYOFF, week=17, round=FINALS_ROUND),
    ]
    regular = player_record_lines(log)
    assert scoring_marks(regular, "Final") == []
    assert "Highest Week - 30.00 (RB)" in scoring_marks(regular, "Regular")
    finals = player_record_lines(log, FINALS_ROUND)
    assert "Regular" not in finals
    assert scoring_marks(finals, "Final") == ["Highest Week - 70.00 (RB)"]
