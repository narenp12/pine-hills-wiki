# Pine Hills Fantasy League Wiki

A static, Markdown-driven encyclopedia of the Pine Hills Fantasy League (est. 2018). The site is built with **Zensical** from raw Yahoo data (`raw/*.json`) plus a hand-maintained *league bible* (`raw/bible.yaml`) of facts the data cannot supply.

**Never fabricate** is the governing rule: anything derivable from the captured data is computed (records, points, finishes, playoff seeds, draft boards, owners, champions), anything else comes from the bible, and anything missing from both renders as `_TBD_` rather than a guess. `_NA_` is the separate case for a question that does not apply - a fact nobody should go looking for, rather than one still to be recorded.

Records are computed from the full weekly matchup log - every captured game, not just the standings line.

Two rules shape where a record lands, both borrowed from how the NBA keeps its book:

- **Regular season and postseason never mix.** Records lives on regular-season games; Playoffs carries its own single-game book, a Finals-only book on top of that, career playoff leaders, and the ledger. A huge October week is a regular-season record and nothing else.
- **Careers belong to people, franchises own single events.** Championships, career records and everything postseason are keyed to the **person**, since a franchise-keyed career splits a serial renamer into eight short ones. A single game or single season stays with the franchise that played it.

Alongside the split books, Records carries **Single-Game Records (All Phases)** (every game, phase ignored), **Blowouts** and **Nailbiters** (every game past a margin threshold, not just the single extreme), and **All-Time Totals** (career games, W-L-T, points), so the best regular season and the best across all phases are answerable separately.

The two margin thresholds come from the observed spread rather than round numbers: across every captured game the median margin is 23.4 and the 90th percentile 61.2, so `BLOWOUT_MARGIN = 80` is the top ~3% of games and `NAILBITER_MARGIN = 1` the bottom ~4%. Both land near 20 rows; retune the constants in `generate.py` if the league drifts.

Two details the small sample forces:

- **Records are shared, never arbitrated.** Every holder tied at the top is listed. The first row carries the label and the count (`Most Weeks Rostered (6-way tie)`) and the rest run under it with a blank label cell, so the holders read as one group; `Tie` on its own stays reserved for a game that ended level. Two different games are both decided by 0.02, and two managers both have two titles.
- **Rate minimums are one complete unit of play** - a full regular season (11 games, the shortest captured one) and a full bracket run (3). Anything higher drops managers who played exactly one, and at four playoff games the league's best postseason scoring average disappears from the page. Every rate is printed with its sample size so a thin one is visible rather than hidden.

**Rivalries are the deliberate exception to the phase split.** Team and owner pages both carry a head-to-head table counting every meeting, bracket games included, with the playoff record shown in its own column. The books split by phase so a regular-season score cannot win a Finals record; a rivalry is the opposite case, where the playoff meetings are the ones that define it. Owner rivalries are keyed person-to-person, so they survive both sides renaming their franchise.

**Players are a third key, alongside the person and the franchise.** Every week's rosters are captured with each player's lineup slot and that week's points, so Records carries a player book: highest regular-season week, highest playoff week, highest season total, highest-scoring benched player, and most weeks rostered. It splits by phase like every other book, and each mark names the fantasy team that had the player rostered and the bracket round when there was one, so a Final reads as a Final rather than a generic postseason week. Slot data is what makes the bench mark possible at all.

Season awards are **computed rather than voted**, and print their formula beside the result so they read as arithmetic. MVP, Finals MVP, Newcomer of the Year, Undrafted Player of the Year and Team of the Season are described under [MVP awards](#mvp-awards) below. Best Draft Pick is the largest positive gap between where a player was drafted and where they finished on season points among players at the same position; Biggest Bust is the inverse, restricted to the first three rounds. Both name the drafting team, and say so when the points were scored for someone else after a trade or waiver claim.

Games can end level. Yahoo drops a drawn game from the standings W-L entirely, so the matchup log is the only place it survives: ties are counted, shown as W-L-T when non-zero, rated as half a win, and listed in the record book on their own, since a tie has no winner and belongs to neither margin record. Weeks that hold both bracket and consolation games are split by reading each season's bracket, so regular-season, playoff and consolation play never contaminate each other, and playoff qualification is read from the bracket rather than assumed from a seed cutoff (the field has grown from six teams to eight).

## Sections

| Section | Contents |
|---------|----------|
| Home | League summary and the champions-by-year table |
| Seasons | One page per year: standings, playoff bracket, awards, post-draft and end-of-season rosters |
| Teams | One page per franchise: infobox, season log, rivalries |
| Owners | One page per manager: career totals across every franchise they have run |
| Players | One page per player ever rostered: team history, draft history, awards |
| Records | Regular season only: single-season and single-game leaders by franchise, career records by manager, and a player book keyed to the player |
| Awards | Every computed award by season, each Team of the Season, and career leaders |
| Draft History | One draft board per year, with the wins-swung leader of each draft class |
| Playoffs | The postseason record book: format, field by year, championships, playoff and Finals records, career playoff leaders, per-manager ledger |
| Champions | List of champions, runners-up, top seeds, and Finals MVPs |
| Lore | Community-contributed incidents and curses, from the bible |
| History | The league's eras and the platforms it has run on |

## Project layout

- `raw/` - source data: JSON season files and `bible.yaml`. **Committed**, so the pipeline runs from a plain checkout without the scraper.
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

Generated Markdown under `zensical/docs/` **is committed** as well, so a diff shows what a data or generator change did to the pages. CI regenerates it from `raw/` on every build, so the committed pages must be kept in step: re-run the pipeline and commit the result alongside any change to `raw/` or `scripts/`.

## Development workflow

```bash
uv sync --group dev
```

```bash
node zensical/build.mjs
```

That one command runs the whole pipeline: `generate.py` -> `zensical/.stage`, `transform.py` -> `zensical/docs`, then `zensical build --clean` -> `zensical/site`. With no JSON in `raw/` it skips the first two steps and builds from the committed Markdown; because `raw/` is committed, that fallback does not fire in CI.

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

### Players

Every player who ever appeared on a weekly roster gets a page under `players/`, built from the same roster log the record books read. The page's core is the team history: one row per franchise per season, with weeks rostered, starts, lineup points, and that stint's best week. A player traded mid-season gets one row per manager rather than a single merged row.

Lineup points and bench points are counted separately - a 30-point week on the bench was never fielded, so it is not credited to the team. Weeks counts roster spots, not games played.

Players taken in a draft but cut before the first captured roster still get a page, so the draft boards have somewhere to link. Rosters, draft boards, and the player record books all link into these pages.

Those same players are the one place the data carries no position at all - draft boards have no position column, and `backfill_draft_positions()` fills them from the rosters a cut player never reached. They are listed in the bible's `player_positions` block, each with the source that confirms it, in Yahoo's fantasy vocabulary (`QB` / `RB` / `WR` / `TE` / `K` / `DEF`) rather than the NFL's roster designation:

```yaml
player_positions:
  "Doug Baldwin": WR
```

Captured data always wins: the block is applied after the roster backfill, so it can only fill a blank, never overwrite a position Yahoo reported.

### MVP awards

Both MVP awards are computed, never voted, and both are derived entirely from captured data.

**Season MVP** is the player who swung the most wins: games their team won by a margin smaller than the player scored from the starting lineup, so removing them flips the result. It deliberately is not the season's top scorer - points piled up in losses win nothing, and a bench week is not a lineup result. It appears on the season page, in the Seasons index, and on the player's own page.

**Finals MVP** is the top scorer in the title game's winning lineup. One game leaves nothing to rank by wins, so this is the ordinary sporting definition. A season with no captured Final has no Finals MVP rather than a guessed one. It appears on the season page, in the Champions table, and on the player's page.

**Team of the Season** applies the same measure per position: each starting slot goes to the player who swung the most wins playing it. The lineup shape is read off the rosters rather than hardcoded - whatever most team-weeks started that year - so a season that adds a flex or drops a kicker selects a team matching its own rules. Fixed slots fill first and the flex takes the best eligible player left, so a flex-worthy back cannot cost the team its second running back. It appears on the season page and on each selected player's page.

**Undrafted Player of the Year** is the same measure among players nobody took in that year's draft - waiver claims and free-agent adds only. A season with no captured draft has no award rather than one that flatters the whole league.

**Newcomer of the Year** is the same measure among players making their first appearance on a Pine Hills roster. The first captured season shows `_NA_`, not `_TBD_`: every player in it is new, so the award does not apply rather than being unrecorded. It is deliberately *not* called Rookie of the Year: the captured data records no NFL service time, so a veteran claimed off waivers debuts here on arrival. In practice the two nearly coincide - six of the seven awarded seasons went to a genuine NFL rookie, the exception being 2019 Lamar Jackson, an NFL rookie in 2018 whom nobody in this league rostered until 2019. A true Rookie of the Year would need NFL debut years recorded in the bible.

All of it is collected on the **Awards** page - every season's winners in one table, each season's Team of the Season in a collapsed block, and the career leaders. A career leaderboard is printed only for an award somebody has won twice; eight players tied on one apiece is not a leaderboard, and the by-season table already covers it.

Ties are listed rather than arbitrated, the same rule the record books follow: a slot is marked `(N-way tie)` only when more players are tied than the slot has places, so two backs filling two RB slots is not a tie. The Draft History index applies the same wins-swung measure scoped to one draft class, so a late-round pick that decided games is visible next to where it was taken.

### Eras and league history

The league has not always run on one platform, and which platform a season ran on decides whether this wiki has data for it. The bible's `eras` block records each continuous stretch, and `history.md` is generated from it:

```yaml
eras:
  - name: Pine Hills
    platform: Yahoo Fantasy Football
    first_season: 2018
    last_season: 2025
    captured: true
  - name: Pine Hills V2
    platform: Sleeper
    first_season: 2026
    captured: false
```

Omit `last_season` while an era is still running. The History page's "In This Wiki" column counts the seasons actually present in `raw/`, so an era whose data has not landed yet reads "None captured" rather than implying pages that do not exist.

The 2018-2025 seasons on this wiki are the Yahoo era. The league moved to Sleeper for 2026 as **Pine Hills V2**, a new ten-team league rather than a continuation. Sleeper publishes a free read-only API, so 2026 needs no browser capture and lands in `raw/2026.json` directly; the scraper in `scraper/` remains Yahoo-only. The 2026 draft is captured; no game has been played, so the season carries a roster and a draft board but no record, finish or champion.

### Lore

`lore.md` is generated on every run so that every `[[Lore]]` link resolves, but its content comes only from the bible's `lore` block - an empty block prints an invitation to fill it in, never an invented incident. Each entry renders as a collapsible admonition:

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

`title` and `story` are printed; `year` and `involved` are optional, and names in `involved` become links to that team or manager page.

## Design & style

- **Anti-slop policy** - no generic variable names, no magic numbers (all are named constants), and all dashes are plain ASCII hyphens (`-`); `generate.py` and `transform.py` both normalize em/en-dashes out of generated Markdown.
- **Typography** - serif body for editorial copy, system-sans headings for clarity. The theme's `font` key is deliberately `false`: it builds its Google Fonts URL with `display=fallback`, whose block period paints text invisible on a cold load. The same families are requested from `extra_css` with `display=swap`, which has no block period, and `--md-text-font-family` in `zensical.css` names a real local fallback so first paint is readable even if the request never lands.
- **Prose** is encyclopedic - what the league did, not how the wiki is built and not what the reader should click. Section notes exist only where a table would otherwise be misread (what Weeks counts, which phase a book covers, what qualifies a rate).
- **Colour scheme** - pine-green accent, dark/light dual-scheme, champion gold highlight.
- **CSS tokens** - spacing and border-radius variables are defined at the top of `zensical.css` for consistency.
- **Infoboxes** are assembled by `transform.py` from the stable `**Label:**` lines the generator emits, so page content stays plain Markdown.
- **Icons, not emoji** - page headings carry no decoration. The nine section landmarks declare a Lucide icon in front matter (`icon: lucide/calendar`), which the theme renders in the nav; a leaf page gets none, because 600 identical footballs are decoration rather than navigation. Players is the one Material icon (`material/football`) - Lucide has no American football.
- **Shared records** are labelled once with their count (`Most Weeks Rostered (6-way tie)`) and the remaining holders run underneath in rows whose label cell is blank. "Tie" on its own is reserved for a game that actually ended level. `tablesort.js` leaves a grouped table unsorted, since sorting it would strand the continuation rows away from the label that names them.
- **Overflow lists** (`+5 more` in a table cell) fold into a `<details>` that names everyone. A count that lists nobody is a dead end when the names are right there in the data.
- **`md_in_html` is active**, so a raw HTML block carrying the `markdown` attribute renders Markdown inside it. Card grids (`<div class="grid cards" markdown>`) take bold, links and lists; a block without the attribute ships its contents literally, which is what the hero panel relies on.

## Deploy

`.github/workflows/deploy.yml` builds on every push to `main` (and on manual dispatch): it runs `node zensical/build.mjs` and publishes `zensical/site` straight to GitHub Pages via `actions/deploy-pages`. There is no `gh-pages` branch.

---

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
