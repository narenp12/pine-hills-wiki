import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.generate import (
    HALL_ANNUAL_CLASS_SIZE,
    HALL_CHARTER_CLASS_SIZE,
    HALL_AWARDS_REQUIRED,
    HALL_CHARTER_YEAR,
    HALL_SCORE_SEASON_UNIT,
    HALL_SCORE_TO_INDUCT,
    HALL_WEIGHT_BIG_AWARD,
    HALL_WEIGHT_CREDENTIAL,
    gen_hall_of_fame,
    hall_of_fame_class,
    hall_of_fame_classes,
)

# Two seasons after the Hall opened, so the charter class has annual classes
# behind it to absorb whatever its cap could not take.
LAST_YEAR = HALL_CHARTER_YEAR + 2


def one_class(members):
    """Every member in a single charter class, for the page-rendering tests."""
    classes, waiting = hall_of_fame_classes(members, LAST_YEAR)
    assert not waiting
    return classes


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


def test_an_mvp_weighs_double_a_lesser_award():
    """Two Team of the Season years and an MVP is 1 + 1 + 2, which is the bar.
    The same three credentials without the MVP would not be."""
    index = {"Decorated": player(), "Ordinary": player()}
    awards = {"Decorated": {"all_league": [2020, 2021], "mvp": [2021]}}
    members = hall_of_fame_class(index, awards, {}, {})
    assert [m["display"] for m in members] == ["Decorated"]
    assert members[0]["score"] == HALL_SCORE_TO_INDUCT


def test_a_case_one_point_short_does_not_get_in():
    index = {"Three": player()}
    awards = {"Three": {"all_league": [2020], "mvp": [2021]}}
    assert inducted(index, awards) == []


def test_a_ring_and_a_record_finish_a_thin_award_case():
    """Mahomes' case: one Finals MVP, but he started a winning Final and holds
    a league mark. 2 + 1 + 1."""
    index = {"Mahomes": player()}
    awards = {"Mahomes": {"finals": [2022]}}
    records = {"Mahomes": [mark("Most Weeks Rostered - 131 weeks")]}
    rings = {"Mahomes": [{"year": 2022, "team": "Team 0", "started": True}]}
    members = hall_of_fame_class(index, awards, records, {}, rings)
    assert [m["display"] for m in members] == ["Mahomes"]
    assert members[0]["score"] == HALL_SCORE_TO_INDUCT


def test_records_alone_never_qualify_however_many():
    """The award guard: a record is one week, and a pile of them is still not a
    career with the player's own name on it."""
    index = {"One Week Wonder": player()}
    records = {"One Week Wonder": [mark(f"Highest K Week - {n}.00", 2020) for n in
                                   range(HALL_SCORE_TO_INDUCT + 2)]}
    assert inducted(index, {}, records) == []
    assert HALL_AWARDS_REQUIRED == 1


def test_biggest_bust_is_not_a_credential():
    """The league hands out Biggest Bust and player pages print it. Counting it
    toward induction would let a bad pick argue for a career."""
    index = {"Busted": player()}
    awards = {"Busted": {"bust": [2021, 2022, 2023], "mvp": [2020]}}
    records = {"Busted": [mark("Highest RB Week - 55.40", 2020),
                          mark("Most Weeks Rostered - 131 weeks")]}
    members = hall_of_fame_class(index, awards, records, {})
    # In on the MVP and the two records; three busts add nothing either way.
    assert [m["player"] for m in members] == ["Busted"]
    assert members[0]["score"] == HALL_WEIGHT_BIG_AWARD + 2 * HALL_WEIGHT_CREDENTIAL
    assert members[0]["awards"] == 1
    assert not any("Bust" in line for line in members[0]["credentials"])


def test_a_drafted_and_cut_player_has_no_career_to_honour():
    index = {"Never Rostered": player(years=())}
    awards = {"Never Rostered": {"best_pick": [2020], "mvp": [2021], "finals": [2022]}}
    assert inducted(index, awards) == []


def test_class_is_ordered_by_the_score_not_the_alphabet():
    index = {
        "Five": player(points=100.0),
        "Four": player(points=900.0),
        "AlsoFour": player(points=800.0),
    }
    awards = {
        "Five": {"all_league": [2018, 2019, 2020, 2021, 2022]},
        "Four": {"all_league": [2018, 2019, 2020, 2021]},
        "AlsoFour": {"mvp": [2020], "all_league": [2021]},
    }
    records = {"AlsoFour": [mark("Highest Week - 57.90 (WR)", 2020)]}
    # Score first; the tie between the two fours goes to the deeper award list,
    # and only then to points.
    assert inducted(index, awards, records) == ["Five", "Four", "AlsoFour"]


def test_the_page_prints_the_case_beside_the_name():
    index = {"Hill": player(years=(2018, 2025), points=1969.7, starts=104, teams=8)}
    awards = {"Hill": {"all_league": [2020, 2022, 2023]}}
    records = {"Hill": [mark("Highest Week - 57.90 (WR)", 2020)]}
    # Three selections and a record: 1 + 1 + 1 + 1.
    highs = {"Hill": {"WR": [2018, 2020, 2021]}}
    page = gen_hall_of_fame(one_class(hall_of_fame_class(index, awards, records, highs)))
    assert "### Hill (WR)" in page
    assert "Team of the Season 2020, 2022, 2023" in page
    assert "Highest Week - 57.90 (WR)" in page
    assert "WR 2018, 2020, 2021" in page
    # The rule the page states is the rule the code applied.
    assert f"A career is scored. {HALL_SCORE_TO_INDUCT} gets in." in page
    assert f"**{HALL_WEIGHT_BIG_AWARD} points** - MVP, Finals MVP." in page
    assert f"at least {HALL_AWARDS_REQUIRED} individual award" in page


def test_a_defense_is_inducted_as_the_season_that_earned_it():
    """The 2019 Patriots: an MVP, an award and the DEF record, all in one year.
    The unit is named for the season, not for the eight years that share the
    name."""
    index = {"Patriots": player(years=(2019, 2020, 2021), position="DEF")}
    awards = {"Patriots": {"mvp": [2019], "undrafted": [2019]}}
    records = {"Patriots": [mark("Highest DEF Week - 37.00", 2019)]}
    highs = {"Patriots": {"DEF": [2019, 2020, 2021]}}
    members = hall_of_fame_class(index, awards, records, highs)
    assert [m["display"] for m in members] == ["2019 Patriots"]
    assert members[0]["years"] == [2019]
    # Only the inducted season's credentials, not the franchise's whole ledger.
    assert members[0]["season_highs"] == "DEF 2019"


def test_a_defense_cannot_pool_credentials_across_years():
    """The Cowboys' case, and why it fails: the award came in 2022 and the two
    records were set by a different unit in 2023. Together they would clear the
    bar; one season at a time neither does."""
    index = {"Cowboys": player(years=(2022, 2023), position="DEF")}
    awards = {"Cowboys": {"all_league": [2022]}}
    records = {"Cowboys": [mark("Highest DEF Week - 37.00", 2023),
                           mark("Highest DEF Week - 38.00", 2023)]}
    assert inducted(index, awards, records) == []


def test_a_season_unit_reaches_the_bar_one_point_lower():
    """A defense collects in one season what a career has eight seasons for, so
    it is inducted on HALL_SCORE_SEASON_UNIT. The same case on a player, who
    gets the whole career to build it, falls short."""
    awards = {"2019": {"all_league": [2019], "undrafted": [2019]}}
    records = {"2019": [mark("Highest DEF Week - 37.00", 2019)]}
    defense = {"2019": player(years=(2019,), position="DEF")}
    members = hall_of_fame_class(defense, awards, records, {})
    assert [m["display"] for m in members] == ["2019 2019"]
    assert members[0]["score"] == HALL_SCORE_SEASON_UNIT

    receiver = {"2019": player(years=(2019,), position="WR")}
    assert hall_of_fame_class(receiver, awards, records, {}) == []


def test_a_player_is_still_judged_across_a_whole_career():
    """Credentials from different seasons pool into one case, which is the
    difference the position makes."""
    index = {"Player": player(years=(2022, 2023))}
    awards = {"Player": {"all_league": [2022], "mvp": [2023]}}
    records = {"Player": [mark("Highest WR Week - 57.90", 2023)]}
    assert inducted(index, awards, records) == ["Player"]


def test_a_defense_season_can_stand_on_awards_alone():
    index = {"Bears": player(years=(2018, 2024), position="DEF")}
    awards = {"Bears": {"all_league": [2018], "mvp": [2018], "undrafted": [2018]}}
    assert inducted(index, awards) == ["2018 Bears"]


def test_the_page_names_a_defense_by_its_season_fixture_guard():
    """The defense fixtures above must clear the bar for the right reason."""
    index = {"Bears": player(years=(2018,), position="DEF")}
    awards = {"Bears": {"all_league": [2018], "mvp": [2018], "undrafted": [2018]}}
    members = hall_of_fame_class(index, awards, {}, {})
    assert members[0]["score"] == HALL_WEIGHT_BIG_AWARD + 2 * HALL_WEIGHT_CREDENTIAL


def test_the_page_names_a_defense_by_its_season():
    index = {"Patriots": player(years=(2019,), position="DEF")}
    awards = {"Patriots": {"mvp": [2019], "undrafted": [2019]}}
    records = {"Patriots": [mark("Highest DEF Week - 37.00", 2019)]}
    page = gen_hall_of_fame(one_class(hall_of_fame_class(index, awards, records, {})))
    assert "### 2019 Patriots (DEF)" in page
    # The link still points at the defense's own page, under the season label.
    assert "[[Patriots|2019 Patriots]]" in page
    assert "inducted as a single season" in page


def test_an_empty_hall_says_so_rather_than_printing_a_headless_table():
    page = gen_hall_of_fame([])
    assert "_No player has yet met the standard._" in page
    assert "_The league has not played long enough to open the Hall._" in page
    assert "| Player | Pos |" not in page


def test_an_ineligible_player_is_kept_out_and_named():
    """A league decision, not a calculation. The page says so rather than
    leaving a silent hole in a Hall that claims to compute its members."""
    index = {"Banned": player(), "Clean": player()}
    awards = {name: {"all_league": [2020, 2021], "mvp": [2021]}
              for name in ("Banned", "Clean")}
    members = hall_of_fame_class(index, awards, {}, {}, {}, {"Banned": ""})
    assert [m["player"] for m in members] == ["Clean"]

    page = gen_hall_of_fame(one_class(members), LAST_YEAR, {"Banned": "kicked a dog"})
    assert "Permanently ineligible by league decision" in page
    assert "[[Banned]] (kicked a dog)" in page


def test_the_ineligible_list_reads_a_bare_list_too():
    from scripts.generate import hall_ineligible

    assert hall_ineligible({"hall_of_fame": {"ineligible": ["A", "B"]}}) == {
        "A": "", "B": "",
    }
    assert hall_ineligible({}) == {}


def test_a_class_that_inducted_nobody_still_prints_a_table():
    page = gen_hall_of_fame([{"year": 2023, "charter": False, "members": []}])
    assert "### Class of 2023" in page
    assert "| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |" in page


def ring(year, team="Team 0", started=True):
    return {"year": year, "team": team, "started": started}


def test_rings_alone_are_never_a_case():
    """Nine starters win a Final together. Four rings and no individual award
    is a fact about four rosters, so the guard keeps it out."""
    index = {"Ringed": player(years=(2019, 2021, 2024, 2025))}
    rings = {"Ringed": [ring(y) for y in (2019, 2021, 2024, 2025)]}
    assert hall_of_fame_class(index, {}, {}, {}, rings) == []


def test_rings_finish_a_case_that_has_an_award_in_it():
    """Butker's case: three titles he was started in, plus one award."""
    index = {"Ringed": player(years=(2019, 2021, 2024))}
    awards = {"Ringed": {"all_league": [2021]}}
    members = hall_of_fame_class(
        index, awards, {}, {}, {"Ringed": [ring(2019), ring(2021), ring(2024)]}
    )
    assert [m["display"] for m in members] == ["Ringed"]
    assert members[0]["score"] == HALL_SCORE_TO_INDUCT
    # Titles lead the case, ahead of any individual award.
    assert members[0]["credentials"][0] == "Champion 2019, 2021, 2024"


def test_a_bench_ring_is_not_a_credential():
    """Four titles from the bench is a fact about those rosters, not a case for
    a career: the player page prints them, the Hall does not count them."""
    index = {"Backup": player(years=(2021, 2023, 2024, 2025))}
    rings = {"Backup": [ring(year, started=False) for year in (2021, 2023, 2024)]}
    assert inducted(index, {}, {}, {}) == []
    assert hall_of_fame_class(index, {}, {}, {}, rings) == []


def test_a_finals_record_scores_like_any_other_credential():
    index = {"Roleplayer": player()}
    awards = {"Roleplayer": {"mvp": [2021]}}
    records = {"Roleplayer": [mark("Finals Highest Week - 40.00 (WR)", 2021)]}
    members = hall_of_fame_class(
        index, awards, records, {}, {"Roleplayer": [ring(2021)]}
    )
    assert [m["display"] for m in members] == ["Roleplayer"]
    assert members[0]["score"] == HALL_SCORE_TO_INDUCT


def test_a_defense_only_counts_the_ring_it_won_that_season():
    index = {"Patriots": player(years=(2019, 2020, 2021), position="DEF")}
    awards = {"Patriots": {"mvp": [2019], "undrafted": [2019]}}
    rings = {"Patriots": [ring(2019), ring(2021)]}
    members = hall_of_fame_class(index, awards, {}, {}, rings)
    # In as the 2019 unit: an MVP, an award and that season's title. The 2021
    # ring belongs to a different unit that happens to share the name.
    assert [m["display"] for m in members] == ["2019 Patriots"]
    assert members[0]["score"] == HALL_SCORE_TO_INDUCT
    assert members[0]["championships"] == [ring(2019)]


def test_the_page_prints_the_rings():
    index = {"Ringed": player(years=(2019, 2021, 2024))}
    awards = {"Ringed": {"all_league": [2021]}}
    page = gen_hall_of_fame(
        one_class(
            hall_of_fame_class(
                index, awards, {}, {}, {"Ringed": [ring(2019), ring(2021), ring(2024)]}
            )
        )
    )
    assert "**Championships:** 3 - 2019 [[Team 0]]" in page
    assert "| 1969.70 |" not in page
    assert "**The Case:** Champion 2019, 2021, 2024" in page


def qualified_in(year, name="Player"):
    """A candidate whose case was complete in `year`: an MVP and two more
    credentials, all in that season."""
    index = {name: player(years=(year,))}
    awards = {name: {"mvp": [year], "all_league": [year]}}
    rings = {name: [ring(year)]}
    return hall_of_fame_class(index, awards, {}, {}, rings)[0]


def test_a_case_is_dated_to_the_season_it_became_complete():
    """The credential that reaches the bar is what makes a Hall of Famer, so
    that is the season the résumé is dated to - not the first, not the last."""
    index = {"Slow Build": player(years=(2019, 2021, 2024))}
    awards = {"Slow Build": {"all_league": [2019, 2021], "mvp": [2024]}}
    members = hall_of_fame_class(index, awards, {}, {})
    assert members[0]["qualified"] == 2024


def test_the_charter_class_opens_the_hall_and_is_capped():
    members = [qualified_in(2019, f"Player {i}") for i in range(20)]
    classes, waiting = hall_of_fame_classes(members, LAST_YEAR)
    charter = classes[0]
    assert charter["year"] == HALL_CHARTER_YEAR
    assert charter["charter"] is True
    assert len(charter["members"]) == HALL_CHARTER_CLASS_SIZE
    # The three the charter class could not fit are not left out of the Hall;
    # the next class takes them.
    assert [m["player"] for m in classes[1]["members"]] == [
        f"Player {i}" for i in (17, 18, 19)
    ]
    assert not waiting


def test_a_later_class_is_capped_lower_than_the_charter_class():
    members = [qualified_in(2019, f"Player {i}") for i in range(60)]
    classes, waiting = hall_of_fame_classes(members, LAST_YEAR)
    assert [len(entry["members"]) for entry in classes] == [
        HALL_CHARTER_CLASS_SIZE, HALL_ANNUAL_CLASS_SIZE, HALL_ANNUAL_CLASS_SIZE,
    ]
    # Three capped classes cannot clear sixty, and the rest stay on the ballot
    # rather than being quietly waved in.
    assert len(waiting) == 60 - (HALL_CHARTER_CLASS_SIZE + 2 * HALL_ANNUAL_CLASS_SIZE)
    assert all("class_year" not in m for m in waiting)


def test_a_season_the_league_has_not_played_announces_no_class():
    """raw/2026.json exists before a ball is thrown. An empty table under a
    Class of 2026 heading would announce an induction that never happened."""
    classes, _ = hall_of_fame_classes([qualified_in(2019)], LAST_YEAR)
    assert [entry["year"] for entry in classes] == [HALL_CHARTER_YEAR]


def test_nobody_is_inducted_before_their_case_was_complete():
    early = qualified_in(HALL_CHARTER_YEAR - 1, "Early")
    late = qualified_in(HALL_CHARTER_YEAR + 1, "Late")
    classes, waiting = hall_of_fame_classes([early, late], LAST_YEAR)
    # The charter class could not take a case that was not yet complete.
    assert [m["player"] for m in classes[0]["members"]] == ["Early"]
    assert late["class_year"] == HALL_CHARTER_YEAR + 1
    assert not waiting


def test_a_league_too_young_to_open_the_hall_inducts_nobody():
    members = [qualified_in(2019)]
    classes, waiting = hall_of_fame_classes(members, HALL_CHARTER_YEAR - 1)
    assert classes == []
    assert waiting == members


def test_the_page_names_the_class_a_member_went_in_with():
    page = gen_hall_of_fame(one_class([qualified_in(2019, "Ringed")]), LAST_YEAR)
    assert f"### The Charter Class ({HALL_CHARTER_YEAR})" in page
    assert f"- **Inducted:** The Charter Class ({HALL_CHARTER_YEAR})" in page
    # A season not yet played will mint new candidates, so no waiting list is
    # printed - only when the next class is chosen.
    assert "On the Ballot" not in page
    assert f"chosen after the {HALL_CHARTER_YEAR + 1} season" in page


def test_a_final_mark_counts_once_not_twice():
    """The Final is a playoff game, so the same week is in both postseason
    books. Counting it twice would inflate the case that got a player in."""
    from scripts.generate import FINALS_ROUND, hall_record_marks

    log = [
        {"year": 2024, "week": 16, "phase": "playoff", "round": FINALS_ROUND,
         "team": "Team A", "player": "Finalist", "position": "WR", "slot": "WR",
         "points": 40.0, "started": True},
    ]
    held = [m["text"] for m in hall_record_marks(log)["Finalist"]]
    # The Finals label wins; the playoff twin of the same mark is dropped.
    assert "Finals Highest Week - 40.00 (WR)" in held
    assert not any(text.startswith("Playoff ") for text in held)
    # Weeks rostered is a career mark and spans every phase, so it stays.
    assert "Most Weeks Rostered - 1 weeks" in held
