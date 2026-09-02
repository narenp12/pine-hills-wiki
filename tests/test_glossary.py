"""Which shorthand gets an abbreviation tooltip, and which deliberately does not."""
import importlib.util
from pathlib import Path


def load_transform():
    """zensical/transform.py is a script, not a package module."""
    path = Path(__file__).resolve().parent.parent / "zensical" / "transform.py"
    spec = importlib.util.spec_from_file_location("phf_transform_glossary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transform = load_transform()


def test_roster_positions_are_not_glossed():
    """Regressing this puts a tooltip back on every position cell in the wiki."""
    for position in ("QB", "RB", "WR", "TE", "DEF"):
        assert position not in transform.GLOSSARY


def test_league_shorthand_is_still_glossed():
    for term in ("PHFL", "PF", "PA", "W/R/T", "BN", "IR", "MVP"):
        assert term in transform.GLOSSARY


def test_only_the_terms_a_page_uses_are_defined():
    page = "The MVP swung it. PF was not close."
    out = transform.with_glossary(page)
    assert "*[MVP]: Most Valuable Player" in out
    assert "*[PF]: Points For - total points a team scored" in out
    assert "*[IR]:" not in out


def test_a_page_with_no_shorthand_is_returned_unchanged():
    page = "Nothing here needs a definition.\n"
    assert transform.with_glossary(page) == page


def test_definitions_are_appended_after_the_body():
    page = "# Title\n\nThe MVP.\n"
    out = transform.with_glossary(page)
    assert out.startswith("# Title")
    assert out.index("*[MVP]:") > out.index("The MVP.")


def test_a_term_inside_a_longer_word_does_not_fire():
    assert "*[PA]:" not in transform.with_glossary("This is only PART of it.")
    assert "*[IR]:" not in transform.with_glossary("A FIRST-round pick.")


def test_a_slash_term_matches_whole_but_its_letters_do_not():
    out = transform.with_glossary("Started in the W/R/T slot.")
    assert "*[W/R/T]: Flex slot - a receiver, back or tight end may start in it" in out
    assert "*[PA]:" not in transform.with_glossary("Scored 10 PA/game.")
