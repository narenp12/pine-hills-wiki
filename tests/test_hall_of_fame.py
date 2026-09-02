import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.generate import (
    HALL_MAJORS_ALONE,
    HALL_MAJORS_WITH_RECORD,
    gen_hall_of_fame,
    hall_of_fame_class,
)


def player(years=(2020, 2021), points=500.0, starts=20, teams=1, position="WR"):
    return {
        "years": set(years),
        "points": points,
        "starts": starts,
        "teams": {f"Team {i}": 10 for i in range(teams)},
        "positions": {position: 20},
        "stints": {
            (year, "Team 0"): {
                "year": year, "team": "Team 0",
                "points": points / max(len(years), 1),
                "starts": starts // max(len(years), 1),
            }
            for year in years
        },
    }


def mark(text, year=None):
    return {"text": text, "year": year}


def inducted(index, awards, records=None, highs=None):
    members = hall_of_fame_class(index, awards, records or {}, highs or {})
    return [m["display"] for m in members]


def test_three_majors_gets_in_on_awards_alone():
    index = {"Decorated": player(), "Ordinary": player()}
    awards = {"Decorated": {"all_league": [2020, 2021], "mvp": [2021]}}
    assert inducted(index, awards) == ["Decorated"]


def test_two_majors_is_not_enough_without_a_record():
    index = {"Two": player()}
    awards = {"Two": {"all_league": [2020], "mvp": [2021]}}
    assert inducted(index, awards) == []


def test_a_record_plus_one_award_gets_in():
    """Mahomes' case: one Finals MVP, but he holds a league mark."""
    index = {"Mahomes": player()}
    awards = {"Mahomes": {"finals": [2022]}}
    records = {"Mahomes": [mark("Most Weeks Rostered - 131 weeks")]}
    assert inducted(index, awards, records) == ["Mahomes"]


def test_a_record_with_no_award_is_not_enough():
    index = {"One Week Wonder": player()}
    records = {"One Week Wonder": [mark("Highest K Week - 26.00", 2020)]}
    assert inducted(index, {}, records) == []


def test_biggest_bust_is_not_a_credential():
    """The league hands out Biggest Bust and player pages print it. Counting it
    toward induction would let a bad pick argue for a career."""
    index = {"Busted": player()}
    awards = {"Busted": {"bust": [2021, 2022, 2023], "mvp": [2020]}}
    records = {"Busted": [mark("Highest RB Week - 55.40", 2020)]}
    members = hall_of_fame_class(index, awards, records, {})
    # In on the MVP and the record, and the bust years appear nowhere.
    assert [m["player"] for m in members] == ["Busted"]
    assert members[0]["majors"] == 1
    assert not any("Bust" in line for line in members[0]["credentials"])


def test_a_drafted_and_cut_player_has_no_career_to_honour():
    index = {"Never Rostered": player(years=())}
    awards = {"Never Rostered": {"best_pick": [2020], "mvp": [2021], "finals": [2022]}}
    assert inducted(index, awards) == []


def test_class_is_ordered_by_the_case_not_the_alphabet():
    index = {
        "Four": player(points=100.0),
        "Three": player(points=900.0),
        "Recordholder": player(points=800.0),
    }
    awards = {
        "Four": {"all_league": [2018, 2019, 2020, 2021]},
        "Three": {"all_league": [2018, 2019, 2020]},
        "Recordholder": {"mvp": [2020]},
    }
    records = {"Recordholder": [mark("Highest Week - 57.90 (WR)", 2020)]}
    assert inducted(index, awards, records) == ["Four", "Three", "Recordholder"]


def test_the_page_prints_the_case_beside_the_name():
    index = {"Hill": player(years=(2018, 2025), points=1969.7, starts=104, teams=8)}
    awards = {"Hill": {"all_league": [2020, 2022, 2023]}}
    records = {"Hill": [mark("Highest Week - 57.90 (WR)", 2020)]}
    highs = {"Hill": {"WR": [2018, 2020, 2021]}}
    page = gen_hall_of_fame(hall_of_fame_class(index, awards, records, highs))
    assert "### Hill (WR)" in page
    assert "Team of the Season 2020, 2022, 2023" in page
    assert "Highest Week - 57.90 (WR)" in page
    assert "WR 2018, 2020, 2021" in page
    # The rule the page states is the rule the code applied.
    assert f"**{HALL_MAJORS_ALONE} or more major awards.**" in page
    assert f"at least {HALL_MAJORS_WITH_RECORD} major award" in page


def test_a_defense_is_inducted_as_the_season_that_earned_it():
    """The 2019 Patriots: two awards and the DEF record, all in one year. The
    unit is named for the season, not for the eight years that share the name."""
    index = {"Patriots": player(years=(2019, 2020, 2021), position="DEF")}
    awards = {"Patriots": {"all_league": [2019], "undrafted": [2019]}}
    records = {"Patriots": [mark("Highest DEF Week - 37.00", 2019)]}
    highs = {"Patriots": {"DEF": [2019, 2020, 2021]}}
    members = hall_of_fame_class(index, awards, records, highs)
    assert [m["display"] for m in members] == ["2019 Patriots"]
    assert members[0]["years"] == [2019]
    # Only the inducted season's credentials, not the franchise's whole ledger.
    assert members[0]["season_highs"] == "DEF 2019"


def test_a_defense_cannot_pool_credentials_across_years():
    """The Cowboys' case, and why it fails: the award came in 2022 and the
    record was set by a different unit in 2023."""
    index = {"Cowboys": player(years=(2022, 2023), position="DEF")}
    awards = {"Cowboys": {"all_league": [2022]}}
    records = {"Cowboys": [mark("Highest DEF Week - 37.00", 2023)]}
    assert inducted(index, awards, records) == []


def test_a_player_is_still_judged_across_a_whole_career():
    """The same two credentials in different years do get a player in, which is
    the difference the position makes."""
    index = {"Player": player(years=(2022, 2023))}
    awards = {"Player": {"all_league": [2022]}}
    records = {"Player": [mark("Highest WR Week - 57.90", 2023)]}
    assert inducted(index, awards, records) == ["Player"]


def test_a_defense_season_can_stand_on_awards_alone():
    index = {"Bears": player(years=(2018, 2024), position="DEF")}
    awards = {"Bears": {"all_league": [2018], "mvp": [2018], "undrafted": [2018]}}
    assert inducted(index, awards) == ["2018 Bears"]


def test_the_page_names_a_defense_by_its_season():
    index = {"Patriots": player(years=(2019,), position="DEF")}
    awards = {"Patriots": {"all_league": [2019], "undrafted": [2019]}}
    records = {"Patriots": [mark("Highest DEF Week - 37.00", 2019)]}
    page = gen_hall_of_fame(hall_of_fame_class(index, awards, records, {}))
    assert "### 2019 Patriots (DEF)" in page
    # The link still points at the defense's own page, under the season label.
    assert "[[Patriots|2019 Patriots]]" in page
    assert "judged one season at a time" in page


def test_an_empty_hall_says_so_rather_than_printing_a_headless_table():
    page = gen_hall_of_fame([])
    assert "_No player has yet met the standard._" in page
    assert "| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |" in page
