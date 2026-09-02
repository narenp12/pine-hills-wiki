"""The Awards page's per-season Team of the Season blocks."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import gen_awards_page

SELECTION = [
    {
        "slot": "QB",
        "slots": 1,
        "holders": [
            {"player": "Kyler Murray", "position": "QB", "wins": 9,
             "points": 300.0, "teams": {"Anish's Awesome Team": 9}}
        ],
    }
]


def page(all_league_teams):
    return gen_awards_page(
        seasons={2020: {}},
        season_mvps={},
        finals_mvps={},
        newcomers={},
        undrafted_awards={},
        all_league_teams=all_league_teams,
        player_awards={},
        first_season=2018,
    )


def test_each_season_is_a_success_admonition():
    """`success` rather than `note`, so its icon differs from lore and rosters."""
    assert '??? success "2020"' in page({2020: SELECTION})


def test_the_lineup_table_is_indented_into_the_block():
    out = page({2020: SELECTION})
    assert "    | Slot | Player | Pos | Wins Swung | Rostered By |" in out
    assert "    | QB | [[Kyler Murray]] | QB | 9 | [[Anish's Awesome Team]] |" in out


def test_a_season_with_no_selection_gets_no_block():
    assert "???" not in page({2020: []})
