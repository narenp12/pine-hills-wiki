# Pine Hills Fantasy Football League Wiki

A static, Markdown-driven encyclopedia of the Pine Hills Fantasy Football League (est. 2018). The site is built with **Zensical** from raw Yahoo data (`raw/*.json`) plus a hand-maintained *league bible* (`raw/bible.yaml`) of facts the data cannot supply.

**Never fabricate** is the governing rule: anything derivable from the captured data is computed (records, points, finishes, playoff seeds, draft boards, owners, champions), anything else comes from the bible, and anything missing from both renders as `_TBD_` rather than a guess.

Records are computed from the full weekly matchup log - every captured game, not just the standings line.

Two rules shape where a record lands, both borrowed from how the NBA keeps its book:

- **Regular season and postseason never mix.** Records lives on regular-season games; Playoffs carries its own single-game book, a Finals-only book on top of that, career playoff leaders, and the ledger. A huge October week is a regular-season record and nothing else.
- **Careers belong to people, franchises own single events.** Championships, career records and everything postseason are keyed to the **person**, since a franchise-keyed career splits a serial renamer into eight short ones. A single game or single season stays with the franchise that played it.

Alongside the split books, Records carries **Outright Marks** (every game, phase ignored), **Blowouts** and **Nailbiters** (every game past a margin threshold, not just the single extreme), and **All-Time Totals** (career games, W-L-T, points), so "best regular season" and "most, full stop" are answerable separately.

The two margin thresholds come from the actual spread rather than round-number instinct: across every captured game the median margin is 23.4 and the 90th percentile 61.2, so `BLOWOUT_MARGIN = 80` is the top ~3% of games and `NAILBITER_MARGIN = 1` the bottom ~4%. Both land near 20 rows; retune the constants in `generate.py` if the league drifts.

Two details the small sample forces:

- **Records are shared, never arbitrated.** Every holder tied at the top is listed and the row is marked `(tied)`. Two different games really are both decided by 0.02, and two managers really do both have two titles.
- **Rate minimums are one complete unit of play** - a full regular season (11 games, the shortest captured one) and a full bracket run (3). Anything higher drops managers who played exactly one, and at four playoff games the league's best postseason scoring average disappears from the page. Every rate is printed with its sample size so a thin one is visible rather than hidden.

**Rivalries are the deliberate exception to the phase split.** Team and owner pages both carry a head-to-head table counting every meeting, bracket games included, with the playoff record shown in its own column. The books split by phase so a regular-season score cannot win a Finals record; a rivalry is the opposite case, where the playoff meetings are the ones that define it. Owner rivalries are keyed person-to-person, so they survive both sides renaming their franchise.

Games can end level. Yahoo drops a drawn game from the standings W-L entirely, so the matchup log is the only place it survives: ties are counted, shown as W-L-T when non-zero, rated as half a win, and listed in the record book on their own, since a tie has no winner and belongs to neither margin record. Weeks that hold both bracket and consolation games are split by reading each season's bracket, so regular-season, playoff and consolation play never contaminate each other, and playoff qualification is read from the bracket rather than assumed from a seed cutoff (the field has grown from six teams to eight).

## Sections

| Section | Contents |
|---------|----------|
| Home | League summary and the champions-by-year table |
| Seasons | One page per year: standings, playoff bracket, awards |
| Teams | One page per franchise: infobox, season log, rivalries |
| Owners | One page per manager: career totals across every franchise they have run |
| Records | Regular season only: single-season and single-game leaders by franchise, career records by manager |
| Draft History | One draft board per year |
| Playoffs | The postseason record book: format, field by year, championships, playoff and Finals records, career playoff leaders, per-manager ledger |
| Champions | List of champions, runners-up, and top seeds |

## Project layout

- `raw/` - source data: JSON season files and `bible.yaml`. **Gitignored**, so it exists only on machines that have run the scraper.
- `scraper/` - Rust capture tool that writes `raw/<year>.json` from Yahoo.
- `scripts/` - Python generation pipeline:
  - `generate.py` loads the season JSON and the bible, computes franchise and owner aggregates, and emits Markdown into `zensical/.stage/`.
  - `extract.py` is the Yahoo extraction toolkit; `import_export.py` adapts Fantasy Helper CSV/JSON exports into the canonical `raw/<year>.json`.
  - `make_social_card.py` renders the Open Graph card at `assets/images/social-card.png`.
- `zensical/` - the site:
  - `build.mjs` is the entry point for the whole pipeline.
  - `transform.py` resolves `[[wikilinks]]`, injects the Wikipedia-style infoboxes, and writes the final Markdown to `zensical/docs/`.
  - `zensical.toml` holds the nav, theme, and feature config.
  - `docs/` is the committed site source (Markdown, `stylesheets/`, `javascripts/`, `assets/`).
  - `site/` is the built HTML. Gitignored.
- `tests/` - pytest suite over the generator and transform helpers.

Generated Markdown under `zensical/docs/` **is committed**. Because `raw/` is not, CI has no season JSON to work from and builds straight from those committed pages.

## Development workflow

```bash
uv sync --group dev
```

```bash
node zensical/build.mjs
```

That one command runs the whole pipeline: `generate.py` -> `zensical/.stage`, `transform.py` -> `zensical/docs`, then `zensical build --clean` -> `zensical/site`. With no JSON in `raw/` it skips the first two steps and builds from the committed Markdown, exactly as CI does.

To run a stage on its own:

```bash
uv run python scripts/generate.py && uv run python zensical/transform.py
```

To preview with live reload (`zensical.toml` sets `dev_addr` to `localhost:7860`):

```bash
cd zensical && uv run zensical serve
```

`zensical/docs` holds Markdown, not HTML - serve `zensical/site` if you want to inspect the built output directly.

## Tests

```bash
uv run pytest -q
```

Covers franchise aggregation, season and root-index rendering, champion fallbacks, bible parse errors, owner name merging and career aggregation, team-image path resolution, infobox injection, and the matchup layer (phase splitting, head-to-head, streaks, single-game records, bracket-derived playoff membership).

## Adding new data

1. **Update the league bible** (`raw/bible.yaml`) with franchise aliases, owner aliases, franchise notes, team images, or lore. Champions and owners are derived from the data and must not be hand-edited.
2. **Add new season JSON** (`raw/<year>.json`) - the generator ingests every file it finds.
3. **Re-run** `node zensical/build.mjs` and commit the regenerated `zensical/docs/`.

### Team images

Yahoo's capture carries no logo, so franchise images are hand-supplied:

1. Drop the file in `zensical/docs/assets/teams/`.
2. Map it to the team in the bible's `team_images` block, by file name:

   ```yaml
   team_images:
     "Roger That": roger-that.png
   ```

   A docs-relative path or an absolute `https://` URL works too.
3. Re-run the pipeline. The image heads that team's infobox and appears as a thumbnail in the Teams and Owners tables. Teams absent from the map render without an image - never a broken placeholder.

### Owners

Owner pages are fully derived: every manager Yahoo reports gets a page under `owners/` with career totals spanning every franchise they have run, so a serial renamer keeps one page instead of eight. Championships are attributed through the champion team name for each year.

Casing variants of a name ("lokesh" / "Lokesh") merge on their own. Genuinely different spellings for one person go in the bible's `owner_aliases` block, where the canonical name is what the page is titled and slugged from:

```yaml
owner_aliases:
  Lokesh: [lokesh, Loki]
```

## Design & style

- **Anti-slop policy** - no generic variable names, no magic numbers (all are named constants), and all dashes are plain ASCII hyphens (`-`); `generate.py` and `transform.py` both normalize em/en-dashes out of generated Markdown.
- **Typography** - serif body for editorial copy, system-sans headings for clarity.
- **Colour scheme** - pine-green accent, dark/light dual-scheme, champion gold highlight.
- **CSS tokens** - spacing and border-radius variables are defined at the top of `zensical.css` for consistency.
- **Infoboxes** are assembled by `transform.py` from the stable `**Label:**` lines the generator emits, so page content stays plain Markdown.

## Deploy

`.github/workflows/deploy.yml` builds on every push to `main` (and on manual dispatch): it runs `node zensical/build.mjs` and publishes `zensical/site` straight to GitHub Pages via `actions/deploy-pages`. There is no `gh-pages` branch.

---

*Built with love for the Pine Hills community - see the source for details and feel free to contribute!*
