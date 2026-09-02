"""A team name is a label on a manager, not a franchise with a page.

69% of the names in this league's history were used for a single season, so the
site gives the manager the page and points every team name at him. These tests
pin that down: the name still shows, the link goes to the person, and nothing
that is not a team name changes behaviour.
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (  # noqa: E402
    TBD,
    gen_teams_index,
    normalize_apostrophes,
    season_has_games,
    set_team_owners,
    team_link,
    warn_slug_collisions,
)


def setup_function():
    set_team_owners({"Save Me": "Naren", "Stroud Boys": "Tanmay"})


def teardown_function():
    set_team_owners({})


def test_team_name_shows_but_links_to_the_manager():
    # The record book names the team-season; the link underneath is the person.
    assert team_link("Stroud Boys") == "[[Tanmay|Stroud Boys]]"


def test_an_explicit_label_still_wins():
    assert team_link("Save Me", "that team") == "[[Naren|that team]]"


def test_an_unknown_name_is_left_as_an_ordinary_link():
    # The lore block mixes franchise and manager names in one list, so anything
    # that is not a known team has to keep behaving exactly as it did.
    assert team_link("Naren") == "[[Naren]]"


def test_an_empty_name_is_tbd_not_a_dead_link():
    assert team_link("") == TBD
    assert team_link(None) == TBD


def test_teams_index_lists_every_name_against_its_manager():
    index = gen_teams_index(
        {"Save Me": [2025], "Stroud Boys": [2024, 2025]}, {}, latest_year=2025
    )
    # The name is plain text and the manager carries the link: two links to the
    # same page on one row is noise.
    assert "| Save Me | [[Naren]]" in index
    assert "| Stroud Boys | [[Tanmay]]" in index
    # The page states the case for not giving names their own pages.
    assert "1 of 2 names (50%)" in index


def test_one_season_share_is_reported_honestly():
    index = gen_teams_index({"Save Me": [2025], "Stroud Boys": [2025]}, {})
    assert "2 of 2 names (100%)" in index


def test_curly_and_straight_apostrophes_fold_to_one_name():
    # Both platforms mix them, and slug() strips punctuation, so two spellings
    # of one franchise silently overwrote each other's page.
    node = {"teams": [{"name": "Kaushal’s Potatoes"}]}
    assert normalize_apostrophes(node) == {"teams": [{"name": "Kaushal's Potatoes"}]}


def test_normalize_apostrophes_rewrites_dict_keys_too():
    # Weekly rosters are keyed BY team name, so keys need folding as well.
    node = {"rosters": {"Sharman’s Scorpions": {"players": []}}}
    assert node != normalize_apostrophes(node)
    assert "Sharman's Scorpions" in normalize_apostrophes(node)["rosters"]


def test_slug_collision_is_reported(capsys):
    warn_slug_collisions("team", ["Kaushal's Potatoes", "Kaushal’s Potatoes"])
    assert "slug collision" in capsys.readouterr().err


def test_distinct_names_do_not_warn(capsys):
    warn_slug_collisions("team", ["Save Me", "Stroud Boys"])
    assert capsys.readouterr().err == ""


def test_a_season_with_no_games_is_not_treated_as_played():
    # The 2026 shape: a full team list, a draft, and nothing played.
    unplayed = {
        "standings": {"teams": [{"name": "A", "wins": 0, "losses": 0, "points_for": 0}]}
    }
    assert season_has_games(unplayed) is False

    played = {
        "standings": {"teams": [{"name": "A", "wins": 1, "losses": 0, "points_for": 90}]}
    }
    assert season_has_games(played) is True


def test_champion_cells_link_the_manager_and_show_the_team_name():
    # A title is won by a manager, not by the name he played under that August.
    from scripts.generate import champ_cell

    set_team_owners({"Stroud Boys": "Tanmay"})
    assert champ_cell("Stroud Boys") == "[[Tanmay|Stroud Boys]]"


def test_a_missing_champion_stays_tbd_rather_than_becoming_a_link():
    from scripts.generate import TBD as _TBD, champ_cell

    assert champ_cell(_TBD) == _TBD
    assert champ_cell("") == _TBD


def test_draft_awards_name_a_winner_that_can_carry_the_award():
    # draft_value_awards renders prose for a table; draft_value_winners returns
    # who won, so the award reaches the player page and the career leaderboard.
    from scripts.generate import draft_value_winners

    season = {
        "draft": {
            "draft_results": [
                {"player": "Early Bust", "position": "RB", "round": 1, "overall": 1,
                 "team": "A", "pick": 1},
                {"player": "Late Steal", "position": "RB", "round": 9, "overall": 90,
                 "team": "B", "pick": 90},
            ]
        },
        "weeks": {
            "1": {
                "rosters": {
                    "A": {"players": [{"name": "Early Bust", "points": 1.0}]},
                    "B": {"players": [{"name": "Late Steal", "points": 300.0}]},
                }
            }
        },
    }
    best, bust = draft_value_winners(season)
    assert best["player"] == "Late Steal"
    assert best["gap"] > 0
    # The bust is restricted to the early rounds, which is where round 1 sits.
    assert bust["player"] == "Early Bust"


def test_no_early_round_pick_means_no_bust_rather_than_a_late_round_scapegoat():
    from scripts.generate import draft_value_winners

    season = {
        "draft": {
            "draft_results": [
                {"player": "Late One", "position": "WR", "round": 11, "overall": 110,
                 "team": "A", "pick": 110},
                {"player": "Late Two", "position": "WR", "round": 12, "overall": 120,
                 "team": "B", "pick": 120},
            ]
        },
        "weeks": {
            "1": {
                "rosters": {
                    "A": {"players": [{"name": "Late One", "points": 5.0}]},
                    "B": {"players": [{"name": "Late Two", "points": 200.0}]},
                }
            }
        },
    }
    _, bust = draft_value_winners(season)
    assert bust is None
