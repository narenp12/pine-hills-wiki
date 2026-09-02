"""Port Starlight Markdown -> Zensical Markdown for the Pine Hills wiki.

Single responsibility: resolve [[Title]] / [[Title|text]] wikilinks to
engine-native relative .md links using a title->slug map built from the
generated tree. Zensical's LinksExtension rewrites .md -> .html and resolves
links relative to the *source file's directory*, so we emit
os.path.relpath(...) from each page.

Run by zensical/build.mjs (or directly) AFTER scripts/generate.py has written
the generated Markdown into zensical/.stage/. This script writes the final
Zensical sources into zensical/docs/ and never touches skin assets
(zensical/docs/stylesheets, zensical/docs/javascripts) which live in git.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Em-dash (—) and en-dash (–) are banned by the site style guide (AI-tell lint).
# Collapse generated/transformed Markdown dashes to a plain ASCII hyphen.
_DASHES = {"—": "-", "–": "-"}
_DASH_RE = re.compile("|".join(re.escape(k) for k in _DASHES))


def dash_normalize(text: str) -> str:
    return _DASH_RE.sub(lambda m: _DASHES[m.group(0)], text)

REPO = Path(__file__).resolve().parent.parent
STAGE = REPO / "zensical" / ".stage"   # raw generated Markdown (gitignored)
DST = REPO / "zensical" / "docs"        # final Zensical sources

# Shorthand the tables use in column headers and lineup-slot cells. Zensical's
# default extension set includes `abbr`, and the theme has `content.tooltips`
# on, so a definition here renders as a hover tooltip wherever the term appears.
# Defining them per page rather than in the config keeps the whole thing out of
# zensical.toml, where declaring one markdown_extensions key would silently
# replace the entire default set.
GLOSSARY = {
    "PHFL": "Pine Hills Fantasy League",
    "PF": "Points For - total points a team scored",
    "PA": "Points Against - total points scored against a team",
    "W/R/T": "Flex slot - a receiver, back or tight end may start in it",
    "BN": "Bench - rostered that week, but not in the starting lineup",
    "IR": "Injured Reserve",
    "MVP": "Most Valuable Player",
}
# Roster positions (QB/RB/WR/TE/DEF) are deliberately absent: not jargon here,
# and a tooltip on every position cell is noise.
#
# Whole-token match: "PA" must not fire inside "PART". Slashes are excluded on
# both sides so "W/R/T" matches as one token while "R" and "T" alone never do.
_GLOSSARY_RES = {
    term: re.compile(rf"(?<![\w/]){re.escape(term)}(?![\w/])")
    for term in GLOSSARY
}


def with_glossary(md: str) -> str:
    """Append `*[TERM]: definition` lines for the shorthand this page uses.

    Only terms the page actually contains are defined, so a player page does not
    carry a definition of PF it never uses.
    """
    # A term already defined is skipped, which keeps this idempotent. index.md
    # is merged from its own previous output rather than regenerated, so without
    # the check it collected another copy of every definition on every build.
    used = [
        term
        for term, rx in _GLOSSARY_RES.items()
        if rx.search(md) and f"*[{term}]:" not in md
    ]
    if not used:
        return md
    defs = "\n".join(f"*[{term}]: {GLOSSARY[term]}" for term in used)
    return f"{md.rstrip()}\n\n{defs}\n"

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TITLE_CLEAN = re.compile(r"\s+")
# Headings are authored with a leading emoji ("# 🏈 2025 Season"). Strip any
# leading run of non-word characters so the heading keys the same as the
# wikilink that points at it.
LEADING_SYMBOLS = re.compile(r"^[^\w]+", re.UNICODE)

# Pages intentionally forward-referenced (red-links like Starlight wiki-new).
# "lore" is NOT here: generate.py emits lore.md on every run, so the link
# resolves whether or not the bible has any entries yet.
FORWARD_REFS = {"roster", "post-draft", "end-of-season"}
# Per-team/per-year roster pages that generate.py links to but does not yet
# emit, e.g. "2021 save-me Post-Draft". Matched as a suffix so the whole family
# is recognised as forward-referenced rather than looking broken.
FORWARD_REF_SUFFIXES = ("post-draft", "end-of-season", "roster", "template")


def _is_forward_ref(key: str) -> bool:
    return key in FORWARD_REFS or key.endswith(FORWARD_REF_SUFFIXES)


def red_link(display: str) -> str:
    """Render a link to a page that does not exist yet.

    Emitting `[text](#)` produces an anchor that looks live, scrolls the reader
    to the top of the page, and does nothing else. A non-anchor span carries the
    same "not written yet" meaning without pretending to be navigable.
    """
    return (
        f'<span class="wiki-new" title="This page has not been written yet">'
        f"{display}</span>"
    )


def _norm(s: str) -> str:
    """Normalize a title or wikilink target into a lookup key.

    Strips surrounding YAML quotes, any leading emoji/punctuation, and collapses
    whitespace. Without the first two, `title: "2025 Season"` keys as
    '"2025 season"' and `# 🏈 2025 Season` keys as '🏈 2025 season', so neither
    matches the `[[2025 Season]]` that points at them.
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    s = LEADING_SYMBOLS.sub("", s)
    return TITLE_CLEAN.sub(" ", s).strip().lower()


def build_title_map(src: Path) -> dict[str, str]:
    m: dict[str, str] = {}
    for f in sorted(src.rglob("*.md")):
        rel = f.relative_to(src).as_posix()
        text = f.read_text()
        fm = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
        if fm:
            tm = re.search(r"(?m)^title:\s*(.+)$", fm.group(1))
            if tm:
                m[_norm(tm.group(1))] = rel
        h1 = re.search(r"(?m)^#\s+(.+)$", text)
        if h1:
            m[_norm(h1.group(1))] = rel
        # Slug fallback: "2025-season" should also answer to "2025 season".
        m[_norm(f.stem)] = rel
        m[_norm(f.stem.replace("-", " ").replace("_", " "))] = rel
    return m


def heading_slug(text: str) -> str:
    """A heading's anchor id, as the Markdown renderer generates it."""
    return re.sub(r"[^a-z0-9]+", "-", _norm(text)).strip("-")


def transform(text: str, title_map: dict[str, str], cur_rel: str) -> str:
    cur_dir = Path(cur_rel).parent

    def repl(mm: re.Match) -> str:
        inner = mm.group(1).strip()
        if "|" in inner:
            target, display = inner.split("|", 1)
        else:
            target, display = inner, inner
        # `[[2018 Season#Playoff Bracket]]` lands on the section, not the page
        # top. The display half keeps the "#" so an un-aliased link still reads.
        target, _, anchor = target.partition("#")
        target = target.strip()
        display = display.strip()
        key = _norm(target)
        if _is_forward_ref(key):
            return red_link(display)
        dest = title_map.get(key)
        if not dest:
            return red_link(display)
        dest_path = Path(dest)
        try:
            rel = dest_path.relative_to(cur_dir)
        except ValueError:
            rel = Path(os.path.relpath(str(dest_path.parent), str(cur_dir))) / dest_path.name
        rel = rel.as_posix()
        if not rel.endswith(".md"):
            rel += ".md"
        if anchor:
            rel += f"#{heading_slug(anchor)}"
        return f"[{display}]({rel})"

    out = WIKILINK_RE.sub(repl, text)
    # Franchise and manager pages: promote the summary fields into a
    # Wikipedia-style right-rail infobox (Zensical-only enhancement).
    # Skip the section *indexes* (category/list pages) so they don't get a
    # meaningless _TBD_ stub infobox floating over their tables.
    for section, fields in (("teams", TEAM_INFOBOX_FIELDS), ("owners", OWNER_INFOBOX_FIELDS)):
        if re.match(rf"{section}/[^/]+\.md$", cur_rel) and cur_rel != f"{section}/index.md":
            out = inject_infobox(out, fields)
    return out


def infobox_value(value: str) -> str:
    """Convert the inline Markdown that appears in summary values to HTML.

    The infobox is raw HTML. Relying on md_in_html to reach into a nested
    `markdown="span"` div proved unreliable, so the handful of inline
    constructs generate.py actually emits are converted here instead. `_TBD_`
    additionally gets a class so unrecorded values are visually distinct.
    """
    value = value.strip()
    # Links reach here already resolved to source-relative .md paths (the
    # wikilink pass runs first). Zensical rewrites href/src in raw HTML the same
    # way it does in Markdown, so the path is handed over untouched.
    value = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda mm: f'<a href="{mm.group(2)}">{mm.group(1)}</a>',
        value,
    )
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", value)
    if value == "<em>TBD</em>":
        value = '<em class="tbd">TBD</em>'
    return value


# Infobox row labels -> the generated "**Label:**" line each one reads. Lead
# lines (the ones above the first "## " heading) are removed after the box is
# built, since the box repeats them verbatim.
TEAM_INFOBOX_FIELDS = {
    "Owner": r"\*\*Owner:\*\*\s*(.+)",
    "Joined": r"\*\*Joined:\*\*\s*(.+)",
    "Status": r"\*\*Status:\*\*\s*(.+)",
    "All-Time": r"\*\*All-Time Record:\*\*\s*(.+)",
    "Points For/Ag.": r"\*\*All-Time Points For / Against:\*\*\s*(.+)",
}
OWNER_INFOBOX_FIELDS = {
    "Franchises": r"\*\*Franchises:\*\*\s*(.+)",
    "Seasons": r"\*\*Seasons:\*\*\s*(.+)",
    "Status": r"\*\*Status:\*\*\s*(.+)",
    "All-Time": r"\*\*All-Time Record:\*\*\s*(.+)",
    "Points For/Ag.": r"\*\*All-Time Points For / Against:\*\*\s*(.+)",
}
LEAD_LINE_LABELS = ("Owner", "Joined", "Status", "Franchises", "Seasons", "Image")
IMAGE_LINE_RE = re.compile(r"^- \*\*Image:\*\*\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$", re.MULTILINE)


def inject_infobox(text: str, fields: dict) -> str:
    """Build a right-rail infobox from the stable **Label:** summary lines that
    generate.py emits. Defensive: returns text unchanged if already present or
    if the expected shape isn't found."""
    if 'class="infobox"' in text or "<div class=\"infobox\"" in text:
        return text
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if not m:
        return text
    title = m.group(1).strip()
    # Optional hand-supplied image, emitted by generate.py as a lead
    # "- **Image:** ![alt](src)" line. It heads the box like a Wikipedia lead
    # photo; teams with no bible entry simply have no line and no row.
    image = IMAGE_LINE_RE.search(text)
    image_html = ""
    if image:
        alt, src = image.group(1), image.group(2)
        image_html = (
            f'<div class="infobox-image"><img src="{src}" alt="{alt}" loading="lazy"></div>\n'
        )
    rows = ""
    row_pairs = []
    for label, pat in fields.items():
        fm = re.search(pat, text)
        val = fm.group(1).strip() if fm else "_TBD_"
        row_pairs.append((label, val))
        rows += (
            f'<div class="infobox-row"><div class="label">{label}</div>'
            f'<div class="value">{infobox_value(val)}</div></div>\n'
        )
    # Championships line lives under "## Franchise Summary" as a bullet.
    champ = re.search(r"^- \*\*Championships:\*\*\s*(.+)$", text, re.MULTILINE)
    if champ:
        # Drop the trailing "_(playoff titles - record in `raw/bible.yaml`)_"
        # helper note; it is guidance for editors, not an infobox value.
        champ_val = re.sub(r"\s*_\(.*?\)_\s*$", "", champ.group(1).strip())
        rows += (
            '<div class="infobox-row"><div class="label">Championships</div>'
            f'<div class="value">{infobox_value(champ_val)}</div>'
            "</div>\n"
        )
    if not rows:
        return text
    # Don't emit a meaningless stub: require at least one real (non-_TBD_) value.
    if all(val == "_TBD_" for _, val in row_pairs) and not champ and not image_html:
        return text
    # markdown="1" opts the block into the md_in_html extension (on by default in
    # Zensical). Without it the values ship as literal "_TBD_" and backticks.
    infobox = (
        f'<div class="infobox">\n'
        f'  <div class="infobox-title">{infobox_value(title)}</div>\n'
        f"{image_html}{rows}</div>\n\n"
    )
    # The blank line after the heading matters: Python-Markdown only treats this
    # as an HTML block (and so only honours markdown="1") when it starts a new
    # block. Without it the attribute is ignored and values ship as "_TBD_".
    text = re.sub(r"^(#\s+.+)$", r"\1\n\n" + infobox, text, count=1, flags=re.MULTILINE)
    # The lead lines were the infobox's data source; leaving them in place
    # repeats the top rows immediately under the box.
    text = re.sub(
        rf"^- \*\*(?:{'|'.join(LEAD_LINE_LABELS)}):\*\*.*\n", "", text, flags=re.MULTILINE
    )
    return text


def main() -> None:
    if not STAGE.exists():
        raise SystemExit(f"Stage dir {STAGE} missing — run scripts/generate.py first "
                         f"(WIKI_CONTENT_DIR={STAGE}).")
    title_map = build_title_map(STAGE)
    print(f"[transform] title map size: {len(title_map)}")
    count = 0
    written: set[str] = set()
    for f in sorted(STAGE.rglob("*.md")):
        rel = f.relative_to(STAGE).as_posix()
        out = transform(f.read_text(), title_map, rel)
        dst = DST / rel
        # The home page (index.md) is hand-authored chrome (hero, explore links)
        # committed in git; only its champions table is generated data. Inject
        # the generated table between the markers instead of overwriting, then
        # run the result back through transform() so the hand-authored
        # [[wikilinks]] resolve too - without this pass they ship as literal
        # "[[Seasons]]" text in the site's main navigation block.
        if rel == "index.md" and dst.exists():
            merged = inject_champions_table(dst.read_text(), out)
            out = transform(merged, title_map, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(with_glossary(dash_normalize(out)))
        written.add(rel)
        count += 1
    print(f"[transform] wrote {count} pages -> {DST}")
    prune_stale(written)
    print("[transform] NOTE: zensical/docs/stylesheets and zensical/docs/javascripts "
          "are hand-authored skin assets kept in git; this script never touches them.")


# Pages in zensical/docs that are hand-authored rather than generated, and so
# must survive a prune. index.md is the site's hero page; build.mjs documents it
# as committed chrome that the generator never writes.
HAND_AUTHORED = {"index.md"}


def prune_stale(written: set[str]) -> None:
    """Delete generated pages that this run did not write.

    Without this the site keeps serving pages for things that no longer exist.
    Renaming a manager in the bible (Yahoo's "Super" -> the real "Abhinav") adds
    owners/abhinav.md but leaves owners/super.md behind, so the same person's
    history is live at two URLs, one of them frozen and wrong.
    """
    stale = [
        f
        for f in sorted(DST.rglob("*.md"))
        if f.relative_to(DST).as_posix() not in written
        and f.relative_to(DST).as_posix() not in HAND_AUTHORED
    ]
    for f in stale:
        f.unlink()
        print(f"[transform] pruned stale {f.relative_to(DST).as_posix()}")
    if stale:
        print(f"[transform] pruned {len(stale)} stale pages")


def inject_champions_table(committed: str, generated: str) -> str:
    """Replace the champions-table block in the committed home page with the
    generated one (between <!-- champions-table:start/end --> markers)."""
    m_gen = re.search(
        r"<!-- champions-table:start -->.*?<!-- champions-table:end -->",
        generated, re.DOTALL,
    )
    if not m_gen:
        return committed
    return re.sub(
        r"<!-- champions-table:start -->.*?<!-- champions-table:end -->",
        m_gen.group(0), committed, flags=re.DOTALL,
    )


if __name__ == "__main__":
    main()
