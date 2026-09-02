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
    assert '??? abstract "Team A"' in out
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

    # Labels are unscoped now: the section heading says which book it is, the
    # same way single_game_rows works for the team books.
    rows = player_book_rows(build_player_log(two_week_season()))
    joined = "\n".join(rows)
    assert "Highest Week" in joined
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
    from scripts.generate import PHASE_PLAYOFF

    rows = player_book_rows(build_player_log(season), PHASE_PLAYOFF)
    rows += player_book_rows(build_player_log(season))

    playoff_row = [r for r in rows if "Highest Week" in r][0]
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


def overall_pick_season():
    """A 3-team league, two rounds. Yahoo numbers picks within the round."""
    return {"draft": {"draft_results": [
        {"round": 1, "pick": 1, "player": "A", "position": "RB", "team": "T1"},
        {"round": 1, "pick": 2, "player": "B", "position": "RB", "team": "T2"},
        {"round": 1, "pick": 3, "player": "C", "position": "RB", "team": "T3"},
        {"round": 2, "pick": 1, "player": "D", "position": "RB", "team": "T3"},
        {"round": 2, "pick": 2, "player": "E", "position": "RB", "team": "T2"},
    ]}}


def test_overall_pick_numbers_run_through_the_whole_draft():
    from scripts.generate import annotate_overall_picks

    season = overall_pick_season()
    annotate_overall_picks(season)
    picks = season["draft"]["draft_results"]
    # Round 1 is unchanged; round 2 continues from 4 rather than restarting at 1.
    assert [p["overall"] for p in picks] == [1, 2, 3, 4, 5]


def test_overall_pick_handles_a_short_final_round():
    from scripts.generate import annotate_overall_picks

    season = overall_pick_season()
    # Drop a round-2 pick: round size still comes from the full round, not the
    # short one, or every later round would be numbered too low.
    season["draft"]["draft_results"].pop()
    annotate_overall_picks(season)
    assert [p["overall"] for p in season["draft"]["draft_results"]] == [1, 2, 3, 4]


def test_overall_pick_leaves_sleeper_numbering_alone():
    """Sleeper's `pick_no` is already the overall number, so offsetting it by the
    round size would push round 2 of a three-team draft into the 4s and beyond."""
    from scripts.generate import annotate_overall_picks

    season = {"draft": {"draft_results": [
        {"round": 1, "pick": 1, "player": "A", "position": "RB", "team": "T1"},
        {"round": 1, "pick": 2, "player": "B", "position": "RB", "team": "T2"},
        {"round": 1, "pick": 3, "player": "C", "position": "RB", "team": "T3"},
        {"round": 2, "pick": 4, "player": "D", "position": "RB", "team": "T3"},
        {"round": 2, "pick": 5, "player": "E", "position": "RB", "team": "T2"},
        {"round": 2, "pick": 6, "player": "F", "position": "RB", "team": "T1"},
    ]}}
    annotate_overall_picks(season)
    assert [p["overall"] for p in season["draft"]["draft_results"]] == [1, 2, 3, 4, 5, 6]


def test_draft_award_ranks_by_overall_not_round_pick():
    """Round 2 pick 1 is a LATER pick than round 1 pick 3, so it must rank as
    one — sorting on the within-round number inverts the draft order."""
    from scripts.generate import annotate_overall_picks, draft_value_awards

    season = overall_pick_season()
    season["weeks"] = {"1": {"rosters": {"T1": {"players": [
        # The round-2 player outscores everyone; he is the steal, and the
        # round-1 first overall pick is the bust.
        {"name": "D", "position": "RB", "slot": "RB", "points": 300.0},
        {"name": "A", "position": "RB", "slot": "RB", "points": 10.0},
        {"name": "B", "position": "RB", "slot": "RB", "points": 50.0},
        {"name": "C", "position": "RB", "slot": "RB", "points": 40.0},
    ]}}}}
    annotate_overall_picks(season)
    best, bust = draft_value_awards(season)
    assert "D" in best and "pick 4" in best
    assert "A" in bust


def finals_season():
    """One regular week, one semifinal week, one Final — plus a consolation game
    running in the same week as the Final."""
    return {2025: {
        "standings": {"teams": [{"name": "Team A", "rank": 1}, {"name": "Team B", "rank": 2}]},
        "matchups": {
            "1": [{"teams": [{"name": "Team A", "score": 100.0, "is_winner": True},
                             {"name": "Team B", "score": 90.0, "is_winner": False}]}],
            "16": [{"teams": [{"name": "Team A", "score": 120.0, "is_winner": True},
                              {"name": "Team B", "score": 80.0, "is_winner": False}]}],
            "17": [{"teams": [{"name": "Team A", "score": 130.0, "is_winner": True},
                              {"name": "Team B", "score": 110.0, "is_winner": False}],},
                   {"teams": [{"name": "Team C", "score": 60.0, "is_winner": True},
                              {"name": "Team D", "score": 50.0, "is_winner": False}]}],
        },
        "bracket": {"games": [
            {"id": "W16G1", "week": 16, "round": "Semifinal", "advances_to": "W17G1",
             "teams": [{"name": "Team A", "score": 120.0, "is_winner": True},
                       {"name": "Team B", "score": 80.0, "is_winner": False}]},
            {"id": "W17G1", "week": 17, "round": "Final",
             "teams": [{"name": "Team A", "score": 130.0, "is_winner": True},
                       {"name": "Team B", "score": 110.0, "is_winner": False}]},
        ]},
        "weeks": {
            "1":  {"rosters": {"Team A": {"players": [
                {"name": "Regular Guy", "position": "RB", "slot": "RB", "points": 40.0}]}}},
            "16": {"rosters": {"Team A": {"players": [
                {"name": "Semi Guy", "position": "RB", "slot": "RB", "points": 60.0}]}}},
            "17": {"rosters": {
                "Team A": {"players": [
                    {"name": "Finals Guy", "position": "RB", "slot": "RB", "points": 50.0},
                    {"name": "Finals Bench", "position": "WR", "slot": "BN", "points": 70.0}]},
                # Consolation team playing the same week — must not reach either
                # postseason book.
                "Team C": {"players": [
                    {"name": "Toilet Guy", "position": "RB", "slot": "RB", "points": 99.0}]},
            }},
        },
    }}


def test_finals_player_book_is_finals_only():
    from scripts.generate import FINALS_ROUND, build_player_log, player_book_rows

    rows = player_book_rows(build_player_log(finals_season()), FINALS_ROUND)
    joined = "\n".join(rows)
    assert "Finals Guy" in joined
    # The semifinal is a playoff game but not a Final; the consolation game in
    # the same week as the Final is neither.
    assert "Semi Guy" not in joined
    assert "Toilet Guy" not in joined


def test_playoff_player_book_spans_the_bracket_but_not_consolation():
    from scripts.generate import PHASE_PLAYOFF, build_player_log, player_book_rows

    rows = player_book_rows(build_player_log(finals_season()), PHASE_PLAYOFF)
    joined = "\n".join(rows)
    # Highest playoff week is the semifinal's 60.0, not the Final's 50.0.
    assert "Semi Guy" in joined
    assert "Toilet Guy" not in joined


def test_regular_player_book_excludes_postseason():
    from scripts.generate import PHASE_REGULAR, build_player_log, player_book_rows

    rows = player_book_rows(build_player_log(finals_season()), PHASE_REGULAR)
    # Weeks rostered counts time on a roster regardless of phase, so it lists
    # postseason players by design; the single-week marks must not. A shared
    # record labels its first row only, so the block is cut at that label rather
    # than filtered row by row - the continuation rows carry no label to match.
    start = next(i for i, row in enumerate(rows) if "Most Weeks Rostered" in row)
    weekly = rows[:start]
    joined = "\n".join(weekly)
    assert "Regular Guy" in joined
    assert "Semi Guy" not in joined
    assert "Finals Guy" not in joined


def test_scoped_books_drop_the_career_marks():
    """Season totals and weeks-rostered are career/whole-season marks; repeating
    them inside the Finals book would say nothing about the Finals."""
    from scripts.generate import FINALS_ROUND, PHASE_REGULAR, build_player_log, player_book_rows

    log = build_player_log(finals_season())
    assert "Most Weeks Rostered" in "\n".join(player_book_rows(log, PHASE_REGULAR))
    assert "Most Weeks Rostered" not in "\n".join(player_book_rows(log, FINALS_ROUND))
