"""Wikilink resolution: aliases, section anchors, and unresolved targets."""
import importlib.util
from pathlib import Path


def load_transform():
    """zensical/transform.py is a script, not a package module."""
    path = Path(__file__).resolve().parent.parent / "zensical" / "transform.py"
    spec = importlib.util.spec_from_file_location("phf_transform_links", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transform = load_transform()
TITLE_MAP = {"2018 season": "seasons/2018-season.md"}


def test_a_plain_wikilink_resolves_to_the_page():
    out = transform.transform("See [[2018 Season]].", TITLE_MAP, "lore.md")
    assert out == "See [2018 Season](seasons/2018-season.md)."


def test_an_anchor_lands_on_the_section():
    out = transform.transform(
        "[[2018 Season#Playoff Bracket|2018 semifinal]]", TITLE_MAP, "lore.md"
    )
    assert out == "[2018 semifinal](seasons/2018-season.md#playoff-bracket)"


def test_an_anchor_survives_the_relative_path_from_a_nested_page():
    out = transform.transform("[[2018 Season#Team Rosters]]", TITLE_MAP, "teams/x.md")
    assert out == "[2018 Season#Team Rosters](../seasons/2018-season.md#team-rosters)"


def test_the_anchor_does_not_break_the_page_lookup():
    """The "#" half is stripped before the title map is consulted."""
    assert "seasons/2018-season.md" in transform.transform(
        "[[2018 Season#Anything At All]]", TITLE_MAP, "lore.md"
    )


def test_an_unknown_target_is_a_red_link_not_a_dead_anchor():
    out = transform.transform("[[No Such Page#Section]]", TITLE_MAP, "lore.md")
    assert "href" not in out and "](" not in out


def test_heading_slug_matches_the_rendered_anchor():
    assert transform.heading_slug("Playoff Bracket") == "playoff-bracket"
    assert transform.heading_slug("Team of the Season") == "team-of-the-season"
    assert transform.heading_slug("🏈 2025 Season") == "2025-season"
