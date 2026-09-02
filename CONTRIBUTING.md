# Contributing to Pine Hills Wiki

The wiki is generated. Almost nothing under `zensical/docs/` is edited by hand -
`scripts/generate.py` writes those pages from `raw/`, so an edit made directly to
a generated page is overwritten on the next build. Change the source, then
regenerate.

## Where to make a change

| To change | Edit | Notes |
|-----------|------|-------|
| Lore, franchise notes, team images, owner or player aliases | `raw/bible.yaml` | The usual contribution. No code needed. |
| Season results, standings, rosters, draft boards | `raw/<year>.json` | Captured data. Champions and owners are derived and must not be hand-edited. |
| Page structure, wording, a new table or section | `scripts/generate.py` | Add a pytest case under `tests/`. |
| Site skin, nav, theme | `zensical/docs/stylesheets/`, `zensical/docs/javascripts/`, `zensical/zensical.toml` | Hand-authored; the generator never touches these. |

### Adding lore

**Without cloning anything**, open a [Submit lore][lore-form] issue. Fill in the
form and a maintainer transcribes it into the bible. That is the intended path
for most contributors.

[lore-form]: https://github.com/narenp12/pine-hills-wiki/issues/new?template=lore.yml

To add it yourself: `lore.md` is generated on every run, but its content comes
only from the bible's `lore` block. An empty block prints a note saying so; it
never invents an incident.

```yaml
lore:
  incidents:
    - year: 2022
      title: The Vetoed Trade
      involved: ["Roger That", "Save Me"]
      story: |
        What happened, and why it is still brought up.
  curses:
    - title: The Kicker Curse
      involved: ["Stroud Boys"]
      story: Every kicker they start goes cold the same week.
```

`title` and `story` are printed. `year` and `involved` are optional; an undated
entry is listed after the dated ones. Names in `involved` become links to that
team or manager page, so they must match a team or owner name the wiki already
knows - the build prints a warning naming any that do not, rather than leaving a
broken link on the page.

## Style

- **Never fabricate.** Anything derivable from the captured data is computed.
  Anything else comes from the bible. Anything missing from both renders as
  `_TBD_` rather than a guess.
- **Encyclopedic prose.** State what the league did. Not how the wiki is built,
  and not what the reader should click. A section note belongs on a page only
  where a table would otherwise be misread.
- **Lead with the summary.** The first paragraph should stand on its own, with
  the subject bolded on first mention. Details go in later sections.
- **No first person, no anecdote** in article voice. Community commentary
  belongs on the Lore page, which exists for exactly that.
- **Articles are unsigned.** Attribution is the git history, not a byline.
- **Plain ASCII hyphens** (`-`). No em or en dashes; `generate.py` and
  `transform.py` both normalize them out of generated Markdown.
- **Design tokens.** When adding CSS, use the existing `--spacing-*` and
  `--border-radius` variables rather than hard-coded values.

## Workflow

Fork, branch, then install the locked environment:

```bash
uv sync --group dev
```

Make the change, then run the full pipeline - the same command CI runs:

```bash
node zensical/build.mjs
```

That runs `generate.py` -> `zensical/.stage`, `transform.py` -> `zensical/docs`,
then `zensical build --clean` -> `zensical/site`.

Preview with live reload at `localhost:7860`:

```bash
cd zensical && uv run zensical serve
```

Run the tests:

```bash
uv run pytest -q
```

Commit the regenerated `zensical/docs/` along with your source change. CI
rebuilds from `raw/`, so a stale `zensical/docs/` shows up as an unexplained
diff. Then open a pull request.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
