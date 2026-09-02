"""Display rules shared across pages: shared records, overflow lists, lore."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (
    TBD,
    gen_lore_page,
    lore_blocks,
    lore_entries,
    more_list,
    shared_label,
    shared_label_cells,
)


def test_one_holder_gets_a_plain_label():
    assert shared_label("Most Career Wins", 1) == "Most Career Wins"
    assert shared_label_cells("Most Career Wins", 1) == ["Most Career Wins"]


def test_shared_record_counts_its_holders():
    # "tied" is reserved for a game that ended level; a shared record says how
    # many share it.
    assert shared_label("Most Weeks Rostered", 6) == "Most Weeks Rostered (6-way tie)"


def test_continuation_rows_leave_the_label_cell_blank():
    cells = shared_label_cells("Highest Week", 3)
    assert cells[0] == "Highest Week (3-way tie)"
    assert cells[1:] == ["", ""]


def test_short_list_is_printed_whole():
    assert more_list(["A", "B"], 3) == "A, B"
    assert more_list([], 3) == TBD


def test_overflow_folds_into_a_disclosure_that_names_everyone():
    out = more_list(["A", "B", "C", "D", "E"], 2)
    assert out.startswith("A, B ")
    assert '<span class="more-show">+3 more</span>' in out
    # The toggle says what it will do next in both states.
    assert '<span class="more-hide">show less</span>' in out
    # The point of the change: the overflow names are present, not dropped, and
    # they are wrapped so the reveal can be styled as a continuation rather than
    # landing as an unexplained line break.
    assert '<span class="more-list">C, D, E</span>' in out


def test_overflow_boundary_is_not_a_disclosure():
    assert "<details" not in more_list(["A", "B", "C"], 3)


def bible_with_lore():
    return {
        "lore": {
            "incidents": [
                {"year": 2022, "title": "The Vetoed Trade", "involved": ["Roger That"],
                 "story": "Line one.\nLine two."},
                {"year": 2019, "title": "The Sleeper Pick"},
                # No title: not renderable, and inventing one would be fabrication.
                {"year": 2020, "story": "orphan"},
            ],
            "curses": [],
        }
    }


def test_lore_entries_drop_the_untitled_and_sort_by_year():
    entries = lore_entries(bible_with_lore(), "incidents")
    assert [e["title"] for e in entries] == ["The Sleeper Pick", "The Vetoed Trade"]


def test_lore_entries_of_a_missing_block():
    assert lore_entries({}, "curses") == []


def test_lore_block_is_a_collapsible_admonition_with_indented_body():
    out = lore_blocks(lore_entries(bible_with_lore(), "incidents"), "empty")
    assert '??? quote "2022 - The Vetoed Trade"' in out
    assert "    **Involved:** [[Roger That]]" in out
    # Zensical drops un-indented content out of the admonition block.
    assert "    Line one." in out
    assert "    Line two." in out
    # No story in the bible means _TBD_, never an invented one.
    assert f"    {TBD}" in out


def test_empty_lore_prints_the_invitation():
    assert lore_blocks([], "_Nothing recorded yet._") == "_Nothing recorded yet._"


def test_lore_page_exists_even_with_an_empty_bible():
    # Every page links to [[Lore]]; the page has to resolve on a fresh checkout.
    page = gen_lore_page({})
    assert "title: Lore" in page
    assert "No incidents recorded." in page
    assert "No curses recorded." in page
    assert "## Incidents" in page and "## Curses" in page


# --------------------------------------------------------------------------- #
# Awards page and league history
# --------------------------------------------------------------------------- #
def test_career_leaders_skip_awards_nobody_has_won_twice():
    from scripts.generate import award_leader_rows

    awards = {
        "Repeat": {"mvp": [2020, 2023]},
        "Once": {"mvp": [2021]},
        # Eight players tied on one Finals MVP apiece is not a leaderboard.
        "A": {"finals": [2018]}, "B": {"finals": [2019]},
    }
    rows = award_leader_rows(awards)
    joined = "\n".join(rows)
    assert "Most MVP Awards" in joined
    assert "Repeat" in joined and "Once" not in joined
    assert "Finals" not in joined


def test_career_leaders_list_a_tie_under_one_label():
    from scripts.generate import award_leader_rows

    rows = award_leader_rows({
        "One": {"all_league": [2018, 2019]}, "Two": {"all_league": [2020, 2021]},
    })
    assert rows[0].startswith("| Most Team of the Season Selections (2-way tie) |")
    assert rows[1].startswith("|  |")


def test_the_first_captured_season_reads_NA_not_TBD():
    from scripts.generate import NA, gen_awards_page

    page = gen_awards_page(
        {2018: {}, 2019: {}}, {}, {}, {}, {}, {}, {}, 2018,
    )
    # Wikilinks are still unresolved here, and "[[2018 Season|2018]]" carries a
    # pipe of its own, so the row is matched rather than split into cells.
    rows = {
        year: next(line for line in page.splitlines() if line.startswith(f"| [[{year}"))
        for year in (2018, 2019)
    }
    # NA says the award does not apply; TBD would say it is merely missing.
    assert NA in rows[2018]
    assert NA not in rows[2019]


def test_awards_page_lists_every_season():
    from scripts.generate import gen_awards_page

    page = gen_awards_page({2024: {}, 2025: {}}, {}, {}, {}, {}, {}, {}, 2018)
    assert "[[2025 Season|2025]]" in page
    assert "## Career Leaders" in page
    assert "_No award has been won twice by the same player._" in page


def bible_with_eras():
    return {"eras": [
        {"name": "Pine Hills V2", "platform": "Sleeper", "first_season": 2026,
         "note": "Moved for 2026."},
        {"name": "Pine Hills", "platform": "Yahoo", "first_season": 2018,
         "last_season": 2025},
    ]}


def test_eras_are_ordered_oldest_first_and_junk_is_dropped():
    from scripts.generate import get_eras

    bible = bible_with_eras()
    bible["eras"].append({"platform": "No first season"})
    assert [era["name"] for era in get_eras(bible)] == ["Pine Hills", "Pine Hills V2"]


def test_a_running_era_reads_as_present():
    from scripts.generate import era_seasons

    assert era_seasons({"first_season": 2018, "last_season": 2025}) == "2018-2025"
    assert era_seasons({"first_season": 2026}) == "2026-present"
    assert era_seasons({"first_season": 2020, "last_season": 2020}) == "2020"


def test_history_counts_what_the_wiki_actually_holds():
    from scripts.generate import gen_history_page

    page = gen_history_page(bible_with_eras(), {2018: {}, 2019: {}})
    # The Yahoo era is captured in part; the Sleeper era not at all, and saying
    # so is the point of the column.
    assert "2 seasons (2018-2019)" in page
    assert "None captured" in page
    assert "Moved for 2026." in page


def test_history_without_any_eras():
    from scripts.generate import gen_history_page

    assert TBD in gen_history_page({}, {2018: {}})
