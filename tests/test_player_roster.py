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
