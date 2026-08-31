import json, pathlib, sys

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.generate import build_aggregates, champ_fields, get_owners

def test_build_aggregates_basic(tmp_path: pathlib.Path):
    # minimal season data with two teams
    seasons = {2025: {
        "standings": {
            "teams": [
                {"name": "Team A", "wins": 5, "losses": 3, "rank": 1, "points_for": 1200, "points_against": 1100},
                {"name": "Team B", "wins": 4, "losses": 4, "rank": 2, "points_for": 1150, "points_against": 1150}
            ]
        }
    }}
    agg = build_aggregates(seasons)
    assert "Team A" in agg
    assert agg["Team A"]["wins"] == 5
    assert agg["Team A"]["losses"] == 3

def test_champ_fields_missing(tmp_path: pathlib.Path):
    # Load empty bible – should return TBD for everything
    bible = {}
    year = 2025
    champ, ru, ts, tw = champ_fields(bible, year)
    assert champ == "_TBD_" and ru == "_TBD_" and ts == "_TBD_" and tw == "_TBD_"

