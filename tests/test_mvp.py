"""MVP awards: wins swung over a season, and the title game's top lineup score."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (
    TBD,
    build_decisive_wins,
    build_player_awards,
    finals_mvp,
    finals_mvp_cell,
    league_debut_years,
    newcomer_of_the_year,
    player_awards_line,
    season_lineup_shape,
    season_mvp,
    season_mvp_cell,
    team_of_the_season,
    team_of_the_season_rows,
    top_draft_contributor,
    top_n_holders,
    undrafted_player_of_the_year,
)


def game(year, week, team, opponent, margin, won=True, tied=False, round_=""):
    return {
        "year": year, "week": week, "team": team, "opponent": opponent,
        "margin": margin, "won": won, "tied": tied, "round": round_,
        "phase": "regular", "score": 100.0 + margin, "opponent_score": 100.0,
    }


def week(year, week_no, team, player, points, started=True):
    return {
        "year": year, "week": week_no, "team": team, "player": player,
        "points": points, "started": started, "position": "RB",
        "phase": "regular", "round": "", "slot": "RB" if started else "BN",
    }


def log_pair():
    game_log = [
        # Won by 5: a starter who scored more than 5 decided it.
        game(2024, 1, "A", "B", 5.0),
        game(2024, 1, "B", "A", -5.0, won=False),
        # Won by 40: nobody who scored under 40 swung this one.
        game(2024, 2, "A", "B", 40.0),
        # A tie is not a win, so nothing about it can be swung.
        game(2024, 3, "A", "B", 0.0, won=True, tied=True),
    ]
    player_log = [
        week(2024, 1, "A", "Swinger", 20.0),
        week(2024, 1, "A", "Small", 3.0),
        # Outscored the margin, but from the bench: not in the lineup that won.
        week(2024, 1, "A", "Benched", 30.0, started=False),
        week(2024, 2, "A", "Swinger", 25.0),
        week(2024, 3, "A", "Swinger", 50.0),
    ]
    return player_log, game_log


def test_a_win_is_swung_only_when_the_starter_outscored_the_margin():
    decisive = build_decisive_wins(*log_pair())
    # Week 1 only: week 2 was a 40-point win and week 3 was a tie.
    record = decisive[(2024, "Swinger")]
    assert (record["wins"], record["points"]) == (1, 20.0)
    # The record carries what the per-position team needs to slot the player.
    assert record["positions"] == {"RB": 1}
    assert record["teams"] == {"A": 1}
    assert (2024, "Small") not in decisive


def test_a_benched_player_swings_nothing():
    decisive = build_decisive_wins(*log_pair())
    assert (2024, "Benched") not in decisive


def test_a_loss_swings_nothing():
    player_log, game_log = log_pair()
    player_log.append(week(2024, 1, "B", "Loser", 60.0))
    decisive = build_decisive_wins(player_log, game_log)
    assert (2024, "Loser") not in decisive


def test_season_mvp_is_the_most_wins_swung_not_the_most_points():
    game_log = [game(2025, w, "A", "B", 5.0) for w in (1, 2, 3)]
    player_log = [
        week(2025, 1, "A", "Steady", 10.0),
        week(2025, 2, "A", "Steady", 10.0),
        week(2025, 3, "A", "Steady", 10.0),
        # One enormous week, but it swung only one game.
        week(2025, 1, "A", "Spiky", 90.0),
    ]
    mvp = season_mvp(2025, build_decisive_wins(player_log, game_log))
    assert [row["player"] for row in mvp] == ["Steady"]
    assert "3 wins swung" in season_mvp_cell(mvp)


def test_season_mvp_ties_are_listed_not_arbitrated():
    game_log = [game(2025, 1, "A", "B", 5.0)]
    player_log = [week(2025, 1, "A", "One", 20.0), week(2025, 1, "A", "Two", 20.0)]
    mvp = season_mvp(2025, build_decisive_wins(player_log, game_log))
    assert sorted(row["player"] for row in mvp) == ["One", "Two"]


def test_season_mvp_cell_without_a_winner():
    assert season_mvp_cell([]) == TBD


def finals_logs():
    game_log = [
        game(2024, 16, "Winner", "Loser", 12.0, round_="Final"),
        game(2024, 16, "Loser", "Winner", -12.0, won=False, round_="Final"),
        # A bigger score in an earlier round must not win the Finals award.
        game(2024, 15, "Winner", "Other", 30.0, round_="Semifinal"),
    ]
    player_log = [
        week(2024, 16, "Winner", "Hero", 34.0),
        week(2024, 16, "Winner", "Bench Hero", 99.0, started=False),
        week(2024, 16, "Loser", "Best Loser", 50.0),
        week(2024, 15, "Winner", "Semi Star", 60.0),
    ]
    return player_log, game_log


def test_finals_mvp_is_the_winning_lineup_top_score():
    holders = finals_mvp(2024, *finals_logs())
    assert [row["player"] for row in holders] == ["Hero"]
    cell = finals_mvp_cell(holders)
    assert "34.00 pts" in cell and "[[Winner]]" in cell


def test_finals_mvp_ignores_the_bench_the_loser_and_earlier_rounds():
    holders = finals_mvp(2024, *finals_logs())
    named = {row["player"] for row in holders}
    assert "Bench Hero" not in named
    assert "Best Loser" not in named
    assert "Semi Star" not in named


def test_no_captured_final_means_no_finals_mvp():
    player_log, game_log = log_pair()
    assert finals_mvp(2024, player_log, game_log) == []
    assert finals_mvp_cell([]) == TBD


def test_draft_contributor_names_the_pick_it_came_from():
    decisive = {
        (2024, "Swinger"): {
            "player": "Swinger", "wins": 4, "points": 80.0,
            "positions": {"RB": 4}, "teams": {"A": 4},
        },
        (2024, "Undrafted Star"): {
            "player": "Undrafted Star", "wins": 9, "points": 300.0,
            "positions": {"WR": 9}, "teams": {"B": 9},
        },
    }
    season = {"draft": {"draft_results": [
        {"player": "Swinger", "round": 4, "overall": 41, "team": "A"},
        {"player": "Never Played", "round": 1, "overall": 1, "team": "B"},
    ]}}
    cell = top_draft_contributor(2024, season, decisive)
    # Scoped to that draft: the undrafted leader is the MVP, not a draft result.
    assert cell == "[[Swinger]] - 4 (R4 P41)"


def test_draft_contributor_without_a_draft():
    assert top_draft_contributor(2024, {}, {}) == TBD


def test_player_awards_are_inverted_per_player_and_sorted():
    awards = build_player_awards(
        {2023: [{"player": "Ace"}], 2020: [{"player": "Ace"}], 2021: [{"player": "Other"}]},
        {2024: [{"player": "Ace"}]},
        {2022: [{"slot": "QB", "slots": 1, "holders": [{"player": "Ace"}]}]},
    )
    assert awards["Ace"] == {"mvp": [2020, 2023], "finals": [2024], "all_league": [2022]}
    assert player_awards_line(awards["Ace"]) == (
        "MVP 2020, 2023 · Finals MVP 2024 · Team of the Season 2022"
    )


def test_a_player_with_no_awards_gets_no_line():
    assert player_awards_line({}) == ""


# --------------------------------------------------------------------------- #
# Team of the season
# --------------------------------------------------------------------------- #
def roster(slots):
    return {"players": [{"name": f"p{i}", "slot": s, "position": s, "points": 1.0}
                        for i, s in enumerate(slots)]}


def season_with_shape(slots, weeks=3):
    return {"weeks": {str(w): {"rosters": {"A": roster(slots)}} for w in range(1, weeks + 1)}}


def decisive_record(player, position, wins, points, team="A"):
    # `position` is what team_of_the_season stamps on a selection; carrying it
    # here lets the row renderer be tested without going through the selector.
    return {"player": player, "wins": wins, "points": points, "position": position,
            "positions": {position: wins}, "teams": {team: wins}}


def test_lineup_shape_is_read_off_the_rosters_in_slot_order():
    season = season_with_shape(["DEF", "K", "W/R/T", "TE", "WR", "WR", "RB", "RB", "QB", "BN"])
    assert season_lineup_shape(season) == [
        "QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "K", "DEF"
    ]


def test_lineup_shape_ignores_bench_and_ir():
    assert season_lineup_shape(season_with_shape(["QB", "BN", "IR", "BN"])) == ["QB"]


def test_lineup_shape_takes_the_modal_week_not_an_outlier():
    season = season_with_shape(["QB", "RB"], weeks=5)
    # One malformed week must not redefine the league's lineup.
    season["weeks"]["9"] = {"rosters": {"A": roster(["QB", "RB", "RB", "RB"])}}
    assert season_lineup_shape(season) == ["QB", "RB"]


def test_lineup_shape_without_rosters():
    assert season_lineup_shape({"weeks": {}}) == []


def test_top_n_holders_keeps_everyone_tied_with_the_last_pick():
    rows = [{"w": 5}, {"w": 4}, {"w": 4}, {"w": 1}]
    key = lambda r: (r["w"],)  # noqa: E731
    assert [r["w"] for r in top_n_holders(rows, key, 2)] == [5, 4, 4]
    assert top_n_holders([], key, 2) == []
    assert top_n_holders(rows, key, 0) == []


def test_each_slot_goes_to_the_most_wins_swung_at_that_position():
    season = season_with_shape(["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "K", "DEF"])
    decisive = {
        (2024, "QB1"): decisive_record("QB1", "QB", 7, 200.0),
        (2024, "RB1"): decisive_record("RB1", "RB", 6, 150.0),
        (2024, "RB2"): decisive_record("RB2", "RB", 5, 120.0),
        (2024, "RB3"): decisive_record("RB3", "RB", 4, 110.0),
        (2024, "WR1"): decisive_record("WR1", "WR", 6, 140.0),
        (2024, "WR2"): decisive_record("WR2", "WR", 3, 90.0),
        (2024, "TE1"): decisive_record("TE1", "TE", 2, 40.0),
        (2024, "K1"): decisive_record("K1", "K", 2, 20.0),
        (2024, "DEF1"): decisive_record("DEF1", "DEF", 1, 10.0),
    }
    selected = team_of_the_season(2024, season, decisive)
    picked = {entry["slot"]: [row["player"] for row in entry["holders"]] for entry in selected}
    assert picked["QB"] == ["QB1"]
    assert picked["RB"] == ["RB1", "RB2"]
    assert picked["WR"] == ["WR1", "WR2"]
    # The flex takes the best player the position slots did not already claim.
    assert picked["W/R/T"] == ["RB3"]


def test_nobody_is_selected_twice():
    season = season_with_shape(["QB", "RB", "W/R/T"])
    decisive = {
        (2024, "RB1"): decisive_record("RB1", "RB", 9, 200.0),
        (2024, "WR1"): decisive_record("WR1", "WR", 2, 30.0),
    }
    selected = team_of_the_season(2024, season, decisive)
    names = [row["player"] for entry in selected for row in entry["holders"]]
    assert names.count("RB1") == 1
    assert sorted(names) == ["RB1", "WR1"]


def test_an_empty_position_is_left_unfilled_rather_than_borrowed():
    season = season_with_shape(["QB", "K"])
    decisive = {(2024, "QB1"): decisive_record("QB1", "QB", 3, 60.0)}
    selected = team_of_the_season(2024, season, decisive)
    assert [entry["slot"] for entry in selected] == ["QB"]


def test_rows_label_a_tie_only_when_it_exceeds_the_slots():
    two_slots = [{"slot": "RB", "slots": 2, "holders": [
        decisive_record("RB1", "RB", 5, 100.0), decisive_record("RB2", "RB", 4, 90.0)]}]
    rows = team_of_the_season_rows(two_slots)
    # Two backs filling two RB slots is not a tie.
    assert rows[0].startswith("| RB |")
    assert rows[1].startswith("|  |")

    tied = [{"slot": "TE", "slots": 1, "holders": [
        decisive_record("TE1", "TE", 4, 80.0), decisive_record("TE2", "TE", 4, 80.0)]}]
    assert team_of_the_season_rows(tied)[0].startswith("| TE (2-way tie) |")


def test_rows_without_a_selection():
    assert TBD in team_of_the_season_rows([])[0]


# --------------------------------------------------------------------------- #
# Newcomer and undrafted awards
# --------------------------------------------------------------------------- #
def test_league_debut_is_the_first_season_on_any_roster():
    log = [
        week(2021, 1, "A", "Veteran", 5.0),
        week(2019, 1, "B", "Veteran", 5.0),
        week(2023, 1, "A", "New", 5.0),
    ]
    assert league_debut_years(log) == {"Veteran": 2019, "New": 2023}


def test_newcomer_is_restricted_to_players_debuting_that_season():
    decisive = {
        (2024, "Debutant"): decisive_record("Debutant", "RB", 4, 90.0),
        (2024, "Veteran"): decisive_record("Veteran", "RB", 9, 300.0),
    }
    debuts = {"Debutant": 2024, "Veteran": 2019}
    holders = newcomer_of_the_year(2024, decisive, debuts, 2018)
    # The veteran swung more wins and is still not eligible.
    assert [row["player"] for row in holders] == ["Debutant"]


def test_the_first_captured_season_has_no_newcomer():
    decisive = {(2018, "Anyone"): decisive_record("Anyone", "RB", 5, 100.0)}
    assert newcomer_of_the_year(2018, decisive, {"Anyone": 2018}, 2018) == []


def test_undrafted_award_excludes_everyone_taken_in_that_draft():
    decisive = {
        (2024, "Drafted"): decisive_record("Drafted", "WR", 8, 200.0),
        (2024, "Waiver Add"): decisive_record("Waiver Add", "K", 3, 40.0),
    }
    season = {"draft": {"draft_results": [{"player": "Drafted", "round": 1, "overall": 1}]}}
    holders = undrafted_player_of_the_year(2024, season, decisive)
    assert [row["player"] for row in holders] == ["Waiver Add"]


def test_no_captured_draft_means_no_undrafted_award():
    decisive = {(2024, "Anyone"): decisive_record("Anyone", "RB", 5, 100.0)}
    # Without a draft every player looks undrafted, which would flatter the lot.
    assert undrafted_player_of_the_year(2024, {}, decisive) == []
