"""Re-wrapping a lore story so a contributor need not wrap it by hand."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import LORE_WRAP, gen_lore_page, lore_blocks, wrap_story

LONG = (
    "D4rthSi Dragons lost the 2018 semifinal to Curry's legit team, 129.76 to "
    "127.56, after a touchdown was reversed on replay and Todd Gurley scored "
    "on the next play instead."
)


def test_one_long_line_is_wrapped():
    lines = wrap_story(LONG)
    assert len(lines) > 1
    assert all(len(line) <= LORE_WRAP + 4 for line in lines)


def test_every_line_is_indented_into_the_admonition():
    assert all(line.startswith("    ") for line in wrap_story(LONG))


def test_wrapping_is_the_same_however_the_source_was_wrapped():
    ragged = "D4rthSi Dragons lost\nthe 2018 semifinal to Curry's legit team,\n129.76 to 127.56."
    assert wrap_story(ragged) == wrap_story(" ".join(ragged.split()))


def test_blank_lines_keep_paragraphs_apart():
    lines = wrap_story("First paragraph.\n\nSecond paragraph.")
    assert lines == ["    First paragraph.", "", "    Second paragraph."]


def test_a_markdown_link_is_never_split():
    link = "[2018 semifinal](seasons/2018-season.md#playoff-bracket)"
    lines = wrap_story(f"They lost the {link} to Curry's legit team, 129.76 to 127.56.")
    assert any(link in line for line in lines)


def test_a_list_keeps_its_line_breaks():
    """Joining these would render one run-on sentence instead of three items."""
    lines = wrap_story("- first\n- second\n- third")
    assert lines == ["    - first", "    - second", "    - third"]


def test_a_table_keeps_its_line_breaks():
    lines = wrap_story("| Year | Team |\n|------|------|\n| 2018 | Dragons |")
    assert lines == ["    | Year | Team |", "    |------|------|", "    | 2018 | Dragons |"]


def test_a_story_with_no_text_still_renders_the_placeholder():
    out = lore_blocks([{"title": "Untold"}], "empty")
    assert '??? note "Untold"' in out
    assert "    _TBD_" in out


def test_the_lore_page_wires_warning_to_curses_and_quote_to_incidents():
    """lore_blocks takes the type as an argument, so the page has to pass it."""
    bible = {
        "lore": {
            "incidents": [{"year": 2018, "title": "An Incident", "story": "It happened."}],
            "curses": [{"title": "A Curse", "story": "It persists."}],
        }
    }
    page = gen_lore_page(bible)
    assert '??? quote "2018 - An Incident"' in page
    assert '??? warning "A Curse"' in page
