import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import matchup_rows, owner_index
from scripts.generate import load_bible, load_raw


def test_matchup_rows_shape():
    seasons = load_raw()
    rows = matchup_rows(seasons, owner_index(seasons, load_bible()))
    assert len(rows) == 1230
    for row in rows:
        assert row["owner"], f"blank owner in {row}"
        assert row["opp_owner"], f"blank opp_owner in {row}"
        assert abs(row["margin"] - (row["score"] - row["opp_score"])) < 1e-9
        assert row["phase"] in {"regular", "playoff", "consolation"}


def test_matchup_rows_are_mirrored():
    seasons = load_raw()
    rows = matchup_rows(seasons, owner_index(seasons, load_bible()))
    by_game = {}
    for row in rows:
        key = (row["year"], row["week"], frozenset((row["team"], row["opp_team"])))
        by_game.setdefault(key, []).append(row)
    for key, pair in by_game.items():
        assert len(pair) == 2, f"{key} produced {len(pair)} rows"
        a, b = pair
        assert a["score"] == b["opp_score"]
        assert a["margin"] == -b["margin"]
