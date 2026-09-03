import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import matchup_rows, owner_index
from scripts.generate import load_bible, load_raw

# The Parquet schema and the browser's column dropdowns are both derived from
# these dicts, so a renamed or added key silently propagates to the front end.
# Assert the exact set rather than reading keys one at a time.
MATCHUP_COLUMNS = {
    "year",
    "week",
    "phase",
    "owner",
    "team",
    "score",
    "opp_owner",
    "opp_team",
    "opp_score",
    "margin",
    "won",
}


def test_matchup_rows_have_the_declared_schema():
    seasons = load_raw()
    rows = matchup_rows(seasons, owner_index(seasons, load_bible()))
    for row in rows:
        assert set(row) == MATCHUP_COLUMNS


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
        # Mirror both directions: a one-sided check passes even if one row's
        # opponent fields were filled from the wrong side of the game.
        assert a["score"] == b["opp_score"], key
        assert b["score"] == a["opp_score"], key
        assert a["team"] == b["opp_team"], key
        assert b["team"] == a["opp_team"], key
        assert a["owner"] == b["opp_owner"], key
        assert b["owner"] == a["opp_owner"], key
        assert a["margin"] == -b["margin"], key
        # One game has one phase, whichever side you read it from.
        assert a["phase"] == b["phase"], key
