import pathlib, sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.generate import gen_season, gen_root_index, champ_fields

def test_gen_season_basic(tmp_path: pathlib.Path):
    # Minimal season data with one team, no champion info
    season = {
        "standings": {"teams": [{"name": "Team X", "wins": 2, "losses": 3, "rank": 5, "points_for": 100, "points_against": 120}]},
        "draft": {}
    }
    # Use empty bible – champ fields will be TBD
    bible = {}
    # Minimal aggregates (empty dict is acceptable for this test)
    aggregates = {}
    md = gen_season(2025, season, bible, aggregates)
    assert "# 2025 Season" in md
    assert "**Champion:** _TBD_" in md
    assert "Team X" in md

def test_gen_root_index_header(tmp_path: pathlib.Path):
    # Empty bible => TBD values; years list
    years = [2025, 2024]
    bible = {}
    rows = gen_root_index(years, bible)
    # First two rows should be the header & separator
    assert rows[0].startswith("| Year | Champion")
    assert rows[1].startswith("|------")
    # Data rows follow
    assert any("2025" in r for r in rows)
