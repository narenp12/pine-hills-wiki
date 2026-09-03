"""The Stat Search tables and the Records page, held to the same numbers.

Both derive from the same capture by different code paths: the Records page
reads `build_matchup_stats`' per-phase record books, Stat Search reads the
Parquet `matchup_rows` writes. Nothing forces the two to agree, so this asserts
it -- a marquee record that reads one way on the page and another in a query is
the wiki contradicting itself, and it would ship unnoticed.

Every expected value is parsed out of the Records markdown generated in this
process, never typed in. A hardcoded number would keep passing while the two
paths drifted apart, which is the exact failure these tests exist to catch.

The page's Single-Game Records (Regular Season) book is regular season only --
the page says so, and the playoff and Finals books live on the Playoffs page --
so every query here filters `phase = 'regular'` to match. The two other filters
mirror `single_game_leaders`: a score of 0 is an unplayed game rather than a
league low, and a margin of 0 is a tie, which belongs to neither margin record.
"""
import os
import re
import sys

import duckdb
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_query_db import (
    MATCHUP_COLUMNS,
    build_all,
    load_league,
    matchup_rows,
    owner_index,
)
from scripts.generate import (
    build_matchup_stats,
    build_owner_aggregates,
    build_owner_game_stats,
    build_owner_map,
    build_player_log,
    build_season_records,
    canonical_owner,
    gen_records_index,
    set_team_owners,
    standings_teams,
)

# The heading the marquee book sits under. The all-phases book below it renders
# through the same `single_game_rows` with the same unscoped labels, so a search
# for "Highest Score" over the whole page would find both and could not tell
# them apart. Slice to the section first, then read labels.
REGULAR_SECTION = "## Single-Game Records (Regular Season)"

# Label in the page's Record column -> the SQL that should reproduce its value.
# Written out per record rather than parameterized over a comparison operator so
# each query reads as the question it answers.
QUERIES = {
    "Highest Score": (
        "SELECT max(score) FROM matchups WHERE phase = 'regular' AND score > 0"
    ),
    "Lowest Score": (
        "SELECT min(score) FROM matchups WHERE phase = 'regular' AND score > 0"
    ),
    "Biggest Blowout": (
        "SELECT max(margin) FROM matchups WHERE phase = 'regular' AND margin > 0"
    ),
    "Closest Game": (
        "SELECT min(margin) FROM matchups WHERE phase = 'regular' AND margin > 0"
    ),
}


def records_markdown(seasons: dict, bible: dict) -> str:
    """Render the Records page the way generate.main() does, from given data.

    Takes the already-normalized dicts rather than loading its own, so the
    caller can hand the page and the Parquet the same four normalization passes.
    `set_team_owners` is called for the same reason main() calls it: `team_link`
    resolves a team name to a manager through that module global, and an unset
    one would render the page against a different name map than the site does.
    """
    set_team_owners(
        {
            team.get("name"): canonical_owner(
                team.get("owner") or "", build_owner_map(bible, seasons)
            )
            for year in sorted(seasons)
            for team in standings_teams(seasons[year])
            if team.get("name") and team.get("owner")
        }
    )
    owner_map = build_owner_map(bible, seasons)
    matchup_stats = build_matchup_stats(seasons, bible)
    return gen_records_index(
        seasons,
        bible,
        matchup_stats,
        build_season_records(seasons, bible),
        build_owner_aggregates(
            seasons, bible, owner_map, matchup_stats["playoff_teams"]
        ),
        build_owner_game_stats(seasons, owner_map, matchup_stats),
        build_player_log(seasons),
    )


def section(markdown: str, heading: str) -> str:
    """The lines under one `##` heading, up to the next one."""
    start = markdown.index(heading)
    rest = markdown[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def table_cells(line: str) -> list:
    """Split one Markdown table row into cells, ignoring pipes inside wikilinks.

    `team_link` renders "[[Lokesh|Curry's legit team]]", so a plain
    `line.split("|")` cuts every holder cell in two and shifts the Value column
    a different distance on every row. Depth counting on the brackets keeps a
    labelled wikilink whole.
    """
    cells, current, depth = [], [], 0
    for index, char in enumerate(line):
        if line.startswith("[[", index):
            depth += 1
        elif line.startswith("]]", index):
            depth = max(depth - 1, 0)
        if char == "|" and depth == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    # A table row opens and closes with a pipe, so the split leaves an empty
    # cell at each end.
    return cells[1:-1]


def page_value(markdown: str, label: str) -> str:
    """The Value cell of one record row in the regular-season game book.

    Matches the label loosely at its head because `shared_label_cells` appends
    "(N-way tie)" when a record has more than one holder -- and every holder
    prints the same value, so the first row is the record either way.
    """
    for line in section(markdown, REGULAR_SECTION).splitlines():
        cells = table_cells(line.strip())
        if len(cells) == 4 and cells[0].split(" (")[0] == label:
            return cells[2]
    raise AssertionError(f"no {label!r} row under {REGULAR_SECTION!r}")


def leading_number(cell: str) -> str:
    """The first number in a Value cell, as the page printed it.

    Both cell shapes lead with the number this compares: a score cell reads
    "218.24 - 120.00 vs [[Roger That]]" and a margin cell "98.24 (218.24 - ...)".
    """
    found = re.match(r"-?\d+\.\d{2}", cell)
    assert found, f"no leading number in {cell!r}"
    return found.group(0)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build the query tables once, alongside the Records page they must match.

    Module scoped because `build_all` walks the whole capture and writes four
    Parquet files; per-test it would run four times over identical inputs.

    Both sides of every comparison start from `load_league`, the one function
    that applies generate.main()'s four normalization passes in main()'s order.
    `build_all` calls it internally and this fixture calls it again for the page,
    off the same raw/ files with no cache between them -- and
    `test_parquet_matches_a_fresh_normalized_load` asserts the two loads really
    did land on the same rows, so "same normalization" is checked rather than
    assumed.
    """
    content = tmp_path_factory.mktemp("content")
    build_all(content)
    seasons, bible = load_league()
    con = duckdb.connect()
    parquet = (content / "query" / "matchups.parquet").as_posix()
    con.execute(f"CREATE VIEW matchups AS SELECT * FROM read_parquet('{parquet}')")
    try:
        yield con, records_markdown(seasons, bible), seasons, bible
    finally:
        con.close()


def test_parquet_matches_a_fresh_normalized_load(built):
    """The Parquet holds exactly the rows a second `load_league` produces.

    This is what makes the record comparisons below mean anything. `build_all`
    loads and normalizes the capture itself, so the page in this fixture is
    rendered from a different dict object than the Parquet was written from. If
    those two loads could diverge -- a cached read, a pass that mutates state
    surviving between them, an order-dependent alias map -- then a passing
    comparison would only prove the two halves agreed about different data.
    """
    con, _, seasons, bible = built
    expected = matchup_rows(seasons, bible, owner_index(seasons, bible))
    columns = ", ".join(f'"{name}"' for name in MATCHUP_COLUMNS)
    found = con.execute(f"SELECT {columns} FROM matchups").fetchall()
    assert sorted(found) == sorted(
        tuple(row[name] for name in MATCHUP_COLUMNS) for row in expected
    )


@pytest.mark.parametrize("label", sorted(QUERIES))
def test_sql_reproduces_the_records_page(built, label):
    """SQL over matchups.parquet returns the value the Records page prints.

    Compared as the page's own two-decimal rendering, not to a tolerance: that
    is the precision the page publishes, and `build_game_log` has already
    rounded `margin` to two places before either path sees it.

    A failure here is a real divergence, not a flaky assertion. The likely
    causes are a phase classification that moved (a bracket week newly counted
    as consolation, say) or one path filtering zero scores and ties where the
    other does not -- fix the path that is wrong, never the expected value,
    which is parsed from the page and cannot be edited here.
    """
    con, markdown, _, _ = built
    found = con.execute(QUERIES[label]).fetchone()[0]
    assert f"{found:.2f}" == leading_number(page_value(markdown, label))
