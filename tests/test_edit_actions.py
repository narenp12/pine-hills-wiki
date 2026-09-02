"""Page actions: the pencil sends editors to the source that survives a build.

Every page under zensical/docs except index.md is regenerated from raw/ on
every build, so a pencil pointing at the generated Markdown invites an edit the
next build discards. zensical/overrides/partials/actions.html redirects those
pages to raw/bible.yaml.

These assertions are over rendered HTML because the behaviour lives in a Jinja
template, which no amount of Python coverage reaches. The build runs once per
session against the committed zensical/docs - the raw/ pipeline is not needed.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ZENSICAL = REPO / "zensical"
SITE = ZENSICAL / "site"
EDIT_BASE = "https://github.com/narenp12/pine-hills-wiki"


@pytest.fixture(scope="session")
def site():
    """Build the site once, then hand back its output directory."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed; the zensical binary resolves through it")
    result = subprocess.run(
        ["uv", "run", "zensical", "build", "--clean"],
        cwd=ZENSICAL,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"zensical build failed:\n{result.stdout}\n{result.stderr}")
    return SITE


def action(page: Path, title: str) -> str:
    """The href of the page action whose tooltip starts with `title`."""
    html = page.read_text()
    match = re.search(rf'href="([^"]+)"\s+title="{title}[^"]*"', html)
    assert match, f"no action titled {title!r} in {page}"
    return match.group(1)


def test_a_generated_page_sends_the_pencil_to_the_bible(site):
    """lore.md is written by generate.py; editing it directly does not stick."""
    assert action(site / "lore" / "index.html", "Edit") == (
        f"{EDIT_BASE}/edit/main/raw/bible.yaml"
    )


def test_a_nested_generated_page_sends_the_pencil_to_the_bible(site):
    """The redirect is not anchored to top-level pages."""
    assert action(site / "owners" / "naren" / "index.html", "Edit") == (
        f"{EDIT_BASE}/edit/main/raw/bible.yaml"
    )


def test_a_section_index_is_still_a_generated_page(site):
    """teams/index.md is generated too - only the site root is hand-authored."""
    assert action(site / "teams" / "index.html", "Edit") == (
        f"{EDIT_BASE}/edit/main/raw/bible.yaml"
    )


def test_the_hand_authored_home_page_keeps_its_own_pencil(site):
    """index.md is in transform.py's HAND_AUTHORED set, so it is editable."""
    assert action(site / "index.html", "Edit") == (
        f"{EDIT_BASE}/edit/main/zensical/docs/index.md"
    )


def test_the_view_action_still_shows_the_page_it_rendered_from(site):
    """The eye is unchanged by the override - it must not follow the pencil.

    This is the assertion that fails first if a zensical upgrade reshapes the
    stock partial the override was copied from.
    """
    assert action(site / "lore" / "index.html", "View") == (
        f"{EDIT_BASE}/raw/main/zensical/docs/lore.md"
    )
    assert action(site / "index.html", "View") == (
        f"{EDIT_BASE}/raw/main/zensical/docs/index.md"
    )
