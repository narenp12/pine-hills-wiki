import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import roster_snapshot_weeks, roster_table, team_roster_blocks


def season_with_rosters():
    def roster(pts):
        return {
            "players": [
                {"name": "Bench Guy", "position": "WR", "slot": "BN", "points": 30.0},
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": pts},
            ]
        }

    return {
        "standings": {"teams": [{"name": "Team A", "rank": 1}]},
        "weeks": {
            "3": {"rosters": {"Team A": roster(20.0)}},
            "9": {"rosters": {}},
            "16": {"rosters": {"Team A": roster(25.0)}},
        },
    }


def test_snapshot_weeks_skip_empty_weeks():
    # 2018 ran weeks 3-16, so 1 and 17 must never be assumed.
    assert roster_snapshot_weeks(season_with_rosters()) == (3, 16)


def test_snapshot_weeks_when_no_rosters():
    assert roster_snapshot_weeks({"weeks": {}}) == (None, None)


def test_roster_table_puts_starters_above_bench():
    rows = roster_table(season_with_rosters()["weeks"]["3"]["rosters"]["Team A"])
    body = [r for r in rows if r.startswith("| ") and "Slot" not in r]
    # The bench player outscored the starter; slot order still wins.
    assert "Starter QB" in body[0]
    assert "Bench Guy" in body[1]


def test_roster_blocks_render_both_snapshots():
    out = team_roster_blocks(season_with_rosters(), [{"name": "Team A"}])
    assert '??? note "Team A"' in out
    assert "**Post-draft — week 3**" in out
    assert "**End of season — week 16**" in out
    # Admonition content must be indented or Zensical drops it out of the block.
    assert "    | Slot | Player | Pos | Pts |" in out


def test_roster_blocks_without_data():
    out = team_roster_blocks({"weeks": {}}, [{"name": "Team A"}])
    assert "_TBD" in out
    assert "???" not in out


def test_season_log_roster_cells():
    from scripts.generate import roster_cell

    with_data = {"weeks": {"3": {"rosters": {"Team A": {"players": []}}}}}
    assert "2018 Season" in roster_cell(2018, with_data)
    # No data means no link — the old code linked to pages that were never generated.
    assert roster_cell(2018, {"weeks": {}}) == "_TBD_"


def test_backfill_positions():
    from scripts.generate import backfill_draft_positions

    season = {
        "draft": {"draft_results": [
            {"pick": 1, "player": "Starter QB", "position": ""},
            {"pick": 2, "player": "Never Rostered", "position": ""},
        ]},
        "weeks": {"1": {"rosters": {"Team A": {"players": [
            {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 20.0},
        ]}}}},
    }
    backfill_draft_positions(season)
    picks = season["draft"]["draft_results"]
    assert picks[0]["position"] == "QB"
    # Never fabricate: an unmatched pick stays blank rather than getting a guess.
    assert picks[1]["position"] == ""


def two_week_season():
    return {2025: {
        "standings": {"teams": [{"name": "Team A", "rank": 1}, {"name": "Team B", "rank": 2}]},
        "matchups": {
            "1": [{"teams": [{"name": "Team A", "score": 100.0, "is_winner": True},
                             {"name": "Team B", "score": 90.0, "is_winner": False}]}],
            "2": [{"teams": [{"name": "Team A", "score": 110.0, "is_winner": True},
                             {"name": "Team B", "score": 95.0, "is_winner": False}]}],
        },
        "playoffs": {"weeks": {
            "2": [{"teams": [{"name": "Team A", "score": 110.0, "is_winner": True},
                             {"name": "Team B", "score": 95.0, "is_winner": False}]}],
        }},
        "weeks": {
            "1": {"rosters": {"Team A": {"players": [
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 30.0},
                {"name": "Bench Guy", "position": "WR", "slot": "BN", "points": 40.0},
            ]}}},
            "2": {"rosters": {"Team A": {"players": [
                {"name": "Starter QB", "position": "QB", "slot": "QB", "points": 35.0},
            ]}}},
        },
    }}


def test_player_log_rows_and_phases():
    from scripts.generate import PHASE_REGULAR, build_player_log

    log = build_player_log(two_week_season())
    assert len(log) == 3
    week1 = [r for r in log if r["week"] == 1]
    assert all(r["phase"] == PHASE_REGULAR for r in week1)
    assert {r["player"] for r in week1} == {"Starter QB", "Bench Guy"}


def test_player_log_marks_started():
    from scripts.generate import build_player_log

    log = build_player_log(two_week_season())
    bench = [r for r in log if r["player"] == "Bench Guy"][0]
    assert bench["started"] is False
    starter = [r for r in log if r["player"] == "Starter QB"][0]
    assert starter["started"] is True


def test_player_book_rows_cover_every_record():
    from scripts.generate import build_player_log, player_book_rows

    rows = player_book_rows(build_player_log(two_week_season()))
    joined = "\n".join(rows)
    assert "Highest Regular-Season Week" in joined
    assert "Highest Playoff Week" in joined
    assert "Highest Season Total" in joined
    # The benched 40.0 outscored every starter that week; it belongs to the
    # bench book and to no other.
    bench_row = [r for r in rows if "Benched" in r][0]
    assert "Bench Guy" in bench_row and "40.00" in bench_row
    assert "Most Weeks Rostered" in joined


def test_weekly_score_awards():
    from scripts.generate import weekly_score_awards

    high, low = weekly_score_awards(two_week_season()[2025])
    assert "110" in high and "Team A" in high
    assert "90" in low and "Team B" in low


def test_weekly_score_awards_without_matchups():
    from scripts.generate import weekly_score_awards

    high, low = weekly_score_awards({"matchups": {}})
    assert high == "_TBD_" and low == "_TBD_"


def draft_value_season():
    return {
        "draft": {"draft_results": [
            {"pick": 1, "round": 1, "player": "Bust QB", "position": "QB", "team": "Team A"},
            {"pick": 2, "round": 1, "player": "Steal QB", "position": "QB", "team": "Team B"},
        ]},
        "weeks": {"1": {"rosters": {
            "Team A": {"players": [{"name": "Bust QB", "position": "QB", "slot": "QB", "points": 5.0}]},
            "Team B": {"players": [{"name": "Steal QB", "position": "QB", "slot": "QB", "points": 50.0}]},
        }}},
    }


def test_draft_value_awards():
    from scripts.generate import draft_value_awards

    best, bust = draft_value_awards(draft_value_season())
    assert "Steal QB" in best
    assert "Bust QB" in bust


def test_draft_value_awards_without_rosters():
    from scripts.generate import draft_value_awards

    best, bust = draft_value_awards({"draft": {"draft_results": []}, "weeks": {}})
    assert best == "_TBD_" and bust == "_TBD_"


def test_player_book_names_the_fantasy_team_and_round():
    from scripts.generate import build_player_log, player_book_rows

    season = two_week_season()
    # Give week 2 a real bracket so the round label has something to report.
    season[2025]["bracket"] = {"games": [{
        "id": "W2G1", "week": 2, "round": "Final",
        "teams": [{"name": "Team A", "score": 110.0, "is_winner": True},
                  {"name": "Team B", "score": 95.0, "is_winner": False}],
    }]}
    rows = player_book_rows(build_player_log(season))

    playoff_row = [r for r in rows if "Highest Playoff Week" in r][0]
    # The specific round beats the generic "(playoffs)" tag, and the fantasy
    # team that rostered the player is named.
    assert "(Final)" in playoff_row
    assert "Team A" in playoff_row

    # Career marks name the teams that did the rostering, not a bare "career".
    weeks_row = [r for r in rows if "Most Weeks Rostered" in r][0]
    assert "Team A" in weeks_row


def test_draft_award_names_the_drafting_team():
    from scripts.generate import draft_value_awards

    best, _ = draft_value_awards(draft_value_season())
    assert "drafted by" in best
    assert "Team B" in best


def test_playoff_appearances_read_from_the_bracket():
    """Franchise playoff appearances must come from who actually reached the
    bracket, not a fixed top-4 cutoff — this league's field grew to eight."""
    from scripts.generate import build_aggregates

    seasons = {2025: {"standings": {"teams": [
        {"name": "Made It", "wins": 6, "losses": 8, "rank": 6,
         "points_for": 1200, "points_against": 1250},
        {"name": "Missed It", "wins": 8, "losses": 6, "rank": 3,
         "points_for": 1300, "points_against": 1200},
    ]}}}
    # The 6 seed reached the bracket; the 3 seed did not.
    playoff_teams = {(2025, "Made It")}

    agg = build_aggregates(seasons, playoff_teams)
    assert agg["Made It"]["playoff_appears"] == 1
    assert agg["Missed It"]["playoff_appears"] == 0


def test_playoff_appearances_fall_back_without_bracket_data():
    from scripts.generate import build_aggregates

    seasons = {2025: {"standings": {"teams": [
        {"name": "Top Seed", "wins": 10, "losses": 4, "rank": 1,
         "points_for": 1400, "points_against": 1100},
    ]}}}
    # No bracket data: the seed cutoff is the only thing left to go on.
    assert build_aggregates(seasons)["Top Seed"]["playoff_appears"] == 1
