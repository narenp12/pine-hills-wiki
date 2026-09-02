import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.generate import (
    BUST_MAX_ROUND,
    BUST_MIN_AVAILABILITY,
    best_and_bust,
    draft_value_awards,
    draft_value_scored,
    draft_value_winners,
    gen_awards_page,
)


def season(picks, weekly):
    """A season where `weekly` maps player -> list of weekly point totals.

    A None entry is a week the player was rostered on IR rather than scoring,
    which is how the captured data records an injury when the owner uses the
    slot at all.
    """
    weeks = {}
    for index in range(max(len(scores) for scores in weekly.values())):
        players = []
        for name, scores in weekly.items():
            if index >= len(scores):
                continue
            points = scores[index]
            players.append({
                "name": name,
                "points": 0.0 if points is None else points,
                "position": "RB",
                "slot": "IR" if points is None else "RB",
            })
        weeks[str(index + 1)] = {"rosters": {"Team A": {"players": players}}}
    return {"draft": {"draft_results": picks}, "weeks": weeks}


def pick(overall, player, rnd=1):
    return {
        "pick": overall,
        "overall": overall,
        "player": player,
        "position": "RB",
        "round": rnd,
        "team": "Team A",
    }


def test_injured_first_rounder_is_not_the_bust():
    """A player who misses most of the year finishes last at his position on
    season points. That is a lost season, not a bad pick, and the healthy
    underperformer taken behind him should win the award instead."""
    data = season(
        [pick(1, "Torn ACL"), pick(2, "Played Badly"), pick(3, "Fine")],
        {
            "Torn ACL": [20.0, 20.0] + [0.0] * 8,
            "Played Badly": [1.0] * 10,
            "Fine": [15.0] * 10,
        },
    )
    _, bust = draft_value_winners(data)
    assert bust is not None
    assert bust["player"] == "Played Badly"


def test_ir_weeks_disqualify_even_when_the_weeks_played_pass():
    data = season(
        [pick(1, "Hurt"), pick(2, "Healthy Miss")],
        {
            # Nine scoring weeks out of ten clears the availability bar on its
            # own; the IR week is the owner saying outright that he was hurt.
            "Hurt": [1.0] * 9 + [None],
            "Healthy Miss": [2.0] * 10,
        },
    )
    _, bust = draft_value_winners(data)
    assert bust is not None
    assert bust["player"] == "Healthy Miss"


def test_bust_stays_inside_the_early_rounds():
    data = season(
        [pick(1, "Early Miss"), pick(60, "Late Miss", rnd=BUST_MAX_ROUND + 1)],
        {"Early Miss": [1.0] * 10, "Late Miss": [0.5] * 10},
    )
    _, bust = draft_value_winners(data)
    assert bust is not None
    assert bust["player"] == "Early Miss"


def test_no_eligible_bust_leaves_the_cell_tbd():
    """Every early pick hurt means the award goes unawarded rather than to
    whoever was unluckiest."""
    data = season(
        [pick(1, "Hurt One"), pick(2, "Hurt Two")],
        {"Hurt One": [10.0, 10.0] + [0.0] * 8, "Hurt Two": [9.0] + [0.0] * 9},
    )
    best, bust = draft_value_winners(data)
    assert best is not None
    assert bust is None
    _, bust_cell = draft_value_awards(data)
    assert bust_cell == "_TBD_"


def test_the_bust_cell_reports_availability():
    data = season(
        [pick(1, "Played Badly"), pick(2, "Fine")],
        {"Played Badly": [1.0] * 9 + [0.0], "Fine": [15.0] * 10},
    )
    _, bust_cell = draft_value_awards(data)
    assert "played 9 of 10 weeks" in bust_cell


def test_renderer_and_winners_agree():
    """The prose cell and the player-page winner come from one scorer, so they
    cannot name different players."""
    data = season(
        [pick(1, "Played Badly"), pick(2, "Fine"), pick(3, "Also Fine")],
        {
            "Played Badly": [1.0] * 10,
            "Fine": [15.0] * 10,
            "Also Fine": [14.0] * 10,
        },
    )
    scored, _ = draft_value_scored(data)
    best, bust = best_and_bust(scored)
    best_cell, bust_cell = draft_value_awards(data)
    assert best["player"] in best_cell
    assert bust["player"] in bust_cell


def test_no_draft_or_no_rosters_is_tbd():
    assert draft_value_awards({}) == ("_TBD_", "_TBD_")
    assert draft_value_winners({}) == (None, None)


def test_the_page_states_the_rule_the_code_enforces():
    """The Awards page explains the gate in prose. Hardcoding the numbers there
    is how the explanation ends up describing a rule the code stopped using."""
    page = gen_awards_page(
        seasons={}, season_mvps={}, finals_mvps={}, newcomers={},
        undrafted_awards={}, all_league_teams={}, player_awards={},
        first_season=2018,
    )
    share = f"{int(BUST_MIN_AVAILABILITY * 100)}%"
    assert page.count(f"rounds 1-{BUST_MAX_ROUND}") == 2
    assert page.count(share) == 2
    # No prose spelling of a threshold that a constant change would not reach.
    assert "three quarters" not in page
    assert "rounds 1-3 " not in page.replace(f"rounds 1-{BUST_MAX_ROUND} ", "")
