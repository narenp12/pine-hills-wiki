import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (
    apply_bible_positions,
    backfill_draft_positions,
    build_player_index,
    build_player_log,
    draft_picks_by_player,
    gen_player_page,
    gen_players_index,
    player_positions,
    team_owners_by_year,
)


def two_team_seasons():
    """Two seasons in which one player changes hands and one is never rostered."""

    def roster(name, slot, points, position="RB"):
        return {"name": name, "position": position, "slot": slot, "points": points}

    return {
        2024: {
            "season": 2024,
            "standings": {"teams": [
                {"name": "Team A", "rank": 1, "owner": "ana"},
                {"name": "Team B", "rank": 2, "owner": "Bo"},
            ]},
            "draft": {"draft_results": [
                {"round": 1, "pick": 1, "overall": 1, "team": "Team A",
                 "player": "Traded Back", "position": "RB"},
                # Cut before week one, so no roster ever supplied a position:
                # backfill_draft_positions has nothing to read and leaves it blank.
                {"round": 1, "pick": 2, "overall": 2, "team": "Team B",
                 "player": "Cut Before Week One", "position": ""},
            ]},
            "weeks": {
                "1": {"rosters": {
                    "Team A": {"players": [roster("Traded Back", "RB", 20.0)]},
                    "Team B": {"players": [roster("Bench Arm", "BN", 30.0, "QB")]},
                }},
                "2": {"rosters": {
                    "Team B": {"players": [roster("Traded Back", "RB", 25.0)]},
                }},
            },
        },
        2025: {
            "season": 2025,
            "standings": {"teams": [{"name": "Team B", "rank": 1, "owner": "Bo"}]},
            "draft": {"draft_results": [
                {"round": 2, "pick": 1, "overall": 11, "team": "Team B",
                 "player": "Traded Back", "position": "WR"},
            ]},
            "weeks": {
                "1": {"rosters": {
                    "Team B": {"players": [roster("Traded Back", "WR", 10.0, "WR")]},
                }},
            },
        },
    }


def index_for(seasons=None):
    seasons = seasons or two_team_seasons()
    return build_player_index(seasons, build_player_log(seasons), {})


def test_stints_split_by_season_and_team():
    record = index_for()["Traded Back"]
    # Mid-season trade: 2024 is two rows, not one merged row.
    assert sorted(record["stints"]) == [
        (2024, "Team A"), (2024, "Team B"), (2025, "Team B")
    ]
    assert record["stints"][(2024, "Team A")]["weeks"] == 1
    assert record["weeks"] == 3
    assert record["years"] == [2024, 2025]


def test_lineup_and_bench_points_stay_apart():
    record = index_for()["Bench Arm"]
    # A benched 30.0 was never fielded, so it is not lineup scoring.
    assert record["points"] == 0.0
    assert record["bench_points"] == 30.0
    assert record["starts"] == 0
    assert record["best"]["started"] is False


def test_positions_ordered_by_how_often_they_were_listed():
    record = index_for()["Traded Back"]
    # Yahoo re-filed the player for 2025; both positions survive, RB leads.
    assert player_positions(record) == ["RB", "WR"]


def test_drafted_but_never_rostered_still_gets_a_record():
    record = index_for()["Cut Before Week One"]
    assert record["weeks"] == 0
    assert record["stints"] == {}
    assert [pick["year"] for pick in record["drafts"]] == [2024]
    # No roster ever carried them and the board is blank, so the position stays
    # empty rather than being guessed. The bible is what fills it.
    assert player_positions(record) == []


def test_draft_picks_are_ordered_and_carry_the_overall_number():
    picks = draft_picks_by_player(two_team_seasons())["Traded Back"]
    assert [pick["year"] for pick in picks] == [2024, 2025]
    assert picks[1]["overall"] == 11
    assert picks[0]["team"] == "Team A"


def test_owner_lookup_is_canonicalized():
    owners = team_owners_by_year(two_team_seasons(), {"ana": "Ana"})
    assert owners[(2024, "Team A")] == "Ana"
    assert owners[(2025, "Team B")] == "Bo"


def test_player_page_lists_every_team_the_player_sat_on():
    seasons = two_team_seasons()
    index = build_player_index(seasons, build_player_log(seasons), {})
    page = gen_player_page("Traded Back", index["Traded Back"], 2025)
    assert 'title: "Traded Back"' in page
    assert "| 2024 | [[Team A]]" in page
    assert "| 2024 | [[Team B]]" in page
    assert "| 2025 | [[Team B]]" in page
    assert "**Seasons:** 2024-present" in page
    assert "**Fantasy Teams:** 2" in page
    # Draft history is on the page too, so the board and the page agree.
    assert "| 2025 | 2 | 11 | [[Team B]] |" in page


def test_player_page_without_a_roster_says_so():
    index = index_for()
    page = gen_player_page("Cut Before Week One", index["Cut Before Week One"], 2025)
    assert "never appeared on a captured weekly roster" in page
    assert "| Season | Team |" not in page


def test_player_page_flags_a_benched_best_week():
    index = index_for()
    page = gen_player_page("Bench Arm", index["Bench Arm"], 2025)
    assert "30.00 (benched) - 2024 Wk 1" in page


def test_bible_fills_only_the_positions_the_rosters_could_not():
    seasons = two_team_seasons()
    for season_data in seasons.values():
        season_data["draft"]["draft_results"][0]["position"] = ""
        backfill_draft_positions(season_data)
    bible = {"player_positions": {"Cut Before Week One": "TE", "Traded Back": "K"}}
    apply_bible_positions(seasons, bible)

    picks = {p["player"]: p for p in seasons[2024]["draft"]["draft_results"]}
    # Rostered: the captured roster wins, and the bible's "K" is ignored.
    assert picks["Traded Back"]["position"] == "RB"
    # Never rostered: nothing in the data to read, so the bible answers.
    assert picks["Cut Before Week One"]["position"] == "TE"


def test_bible_position_reaches_the_player_page():
    seasons = two_team_seasons()
    apply_bible_positions(seasons, {"player_positions": {"Cut Before Week One": "TE"}})
    index = build_player_index(seasons, build_player_log(seasons), {})
    assert player_positions(index["Cut Before Week One"]) == ["TE"]


def test_players_index_groups_by_position():
    page = gen_players_index(index_for(), 2025)
    assert "title: Players" in page
    # Primary position leads: the RB section holds the player listed RB twice.
    assert "### RB (1)" in page
    assert "### QB (1)" in page
    assert "[[Traded Back]]" in page
    assert "[[Cut Before Week One]]" in page
