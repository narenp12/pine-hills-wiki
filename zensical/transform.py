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

REPO = Path(__file__).resolve().parent.parent
STAGE = REPO / "zensical" / ".stage"   # raw generated Markdown (gitignored)
DST = REPO / "zensical" / "docs"        # final Zensical sources

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TITLE_CLEAN = re.compile(r"\s+")

# Pages intentionally forward-referenced (red-links like Starlight wiki-new).
FORWARD_REFS = {"lore", "roster", "post-draft", "end-of-season"}


def _norm(s: str) -> str:
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
                m[_norm(tm.group(1).strip())] = rel
        h1 = re.search(r"(?m)^#\s+(.+)$", text)
        if h1:
            m[_norm(h1.group(1).strip())] = rel
        m[_norm(f.stem)] = rel
    return m


def transform(text: str, title_map: dict[str, str], cur_rel: str) -> str:
    cur_dir = Path(cur_rel).parent

    def repl(mm: re.Match) -> str:
        inner = mm.group(1).strip()
        if "|" in inner:
            target, display = inner.split("|", 1)
        else:
            target, display = inner, inner
        target = target.strip()
        display = display.strip()
        key = _norm(target)
        if key in FORWARD_REFS:
            return f"[{display}](#)"
        dest = title_map.get(key)
        if not dest:
            return f"[{display}](#)"  # intentional red-link
        dest_path = Path(dest)
        try:
            rel = dest_path.relative_to(cur_dir)
        except ValueError:
            rel = Path(os.path.relpath(str(dest_path.parent), str(cur_dir))) / dest_path.name
        rel = rel.as_posix()
        if not rel.endswith(".md"):
            rel += ".md"
        return f"[{display}]({rel})"

    out = WIKILINK_RE.sub(repl, text)
    # Team franchise pages: promote the "Franchie Summary" fields into a
    # Wikipedia-style right-rail infobox (Zensical-only enhancement).
    if re.match(r"teams/[^/]+\.md$", cur_rel):
        out = inject_team_infobox(out)
    return out


def inject_team_infobox(text: str) -> str:
    """Build a right-rail infobox from the stable **Label:** summary lines that
    generate.py emits. Defensive: returns text unchanged if already present or
    if the expected shape isn't found."""
    if 'class="infobox"' in text or "<div class=\"infobox\"" in text:
        return text
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if not m:
        return text
    title = m.group(1).strip()
    fields = {
        "Owner": r"\*\*Owner:\*\*\s*(.+)",
        "Joined": r"\*\*Joined:\*\*\s*(.+)",
        "Status": r"\*\*Status:\*\*\s*(.+)",
        "All-Time": r"\*\*All-Time Record:\*\*\s*(.+)",
        "Points For/Ag.": r"\*\*All-Time Points For / Against:\*\*\s*(.+)",
    }
    rows = ""
    for label, pat in fields.items():
        fm = re.search(pat, text)
        val = fm.group(1).strip() if fm else "_TBD_"
        rows += (
            f'<div class="infobox-row"><div class="label">{label}</div>'
            f'<div class="value">{val}</div></div>\n'
        )
    # Championships line lives under "## Franchise Summary" as a bullet.
    champ = re.search(r"^- \*\*Championships:\*\*\s*(.+)$", text, re.MULTILINE)
    if champ:
        rows += (
            '<div class="infobox-row"><div class="label">Championships</div>'
            f'<div class="value">{champ.group(1).strip()}</div></div>\n'
        )
    if not rows:
        return text
    # Insert right after the H1 heading line.
    infobox = (
        f'<div class="infobox">\n'
        f'  <div class="infobox-title">{title}</div>\n'
        f"{rows}</div>\n\n"
    )
    return re.sub(r"^(#\s+.+)$", r"\1\n" + infobox, text, count=1, flags=re.MULTILINE)


def main() -> None:
    if not STAGE.exists():
        raise SystemExit(f"Stage dir {STAGE} missing — run scripts/generate.py first "
                         f"(WIKI_CONTENT_DIR={STAGE}).")
    title_map = build_title_map(STAGE)
    print(f"[transform] title map size: {len(title_map)}")
    count = 0
    for f in sorted(STAGE.rglob("*.md")):
        rel = f.relative_to(STAGE).as_posix()
        out = transform(f.read_text(), title_map, rel)
        dst = DST / rel
        # The home page (index.md) is hand-authored chrome (hero, explore links)
        # committed in git; only its champions table is generated data. Inject
        # the generated table between the markers instead of overwriting.
        if rel == "index.md" and dst.exists():
            out = inject_champions_table(dst.read_text(), out)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out)
        count += 1
    print(f"[transform] wrote {count} pages -> {DST}")
    print("[transform] NOTE: zensical/docs/stylesheets and zensical/docs/javascripts "
          "are hand-authored skin assets kept in git; this script never touches them.")


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
