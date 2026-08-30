# Pine Hills Wiki — Wikipedia styling, navigation & writing guide

How we make the Pine Hills Fantasy Football League wiki *read* as Wikipedia,
and how to write pages in that voice. Combines Wikipedia's real Manual of Style
conventions (https://en.wikipedia.org/wiki/Wikipedia:Manual_of_Style) with what
our Astro/Starlight skin actually supports.

## 1. Visual styling (what the skin does)

Built in `src/styles/wikipedia.css` (Vector-like). Tokens are defined for both
light and dark (`--wiki-bg`, `--wiki-text`, `--wiki-border`, `--wiki-panel`,
`--wiki-link`, `--wiki-accent`).

- **Typography:** serif everywhere (`Georgia, 'Linux Libertine', 'Times New Roman', serif`).
- **Top bar:** league title left, search right, thin bottom rule.
- **Article `<h1>`:** a horizontal rule directly underneath (Wikipedia signature).
- **Body:** single content column (Starlight's default panes still present;
  see §3 for the navigation trade-off).
- **Infobox:** floated top-right, bordered, `#eaecf0` header band, key/value rows.
- **Tables:** bordered, header row `#eaecf0`, zebra striping on `#f8f9fa`.
- **Links:** Wikipedia blue; unresolved (`wiki-new`) render red.
- **Footer:** GitHub + Yahoo League links, "community-maintained" note.

### Palette
| Token | Light | Dark |
|---|---|---|
| `--wiki-bg` | `#ffffff` | `#202122` |
| `--wiki-text` | `#202122` | `#eaecf0` |
| `--wiki-border` | `#a2a9b1` | `#4c5760` |
| `--wiki-panel` | `#f8f9fa` | `#2a2e33` |
| `--wiki-panel-2` | `#eaecf0` | `#373b40` |
| `--wiki-link` | `#3366cc` | `#6b8cff` |
| `--wiki-accent` | `#0d47a1` | `#8ab4f8` |

## 2. Article layout (follow Wikipedia's element order)

From Wikipedia:Manual of Style/Layout, the order is:
1. **Lead section** — a concise summary, *never* divided into headings.
2. Infobox + lead images, right-aligned, in the lead.
3. Body sections (History, Records, Draft history, …).
4. **See also**.
5. **Navbox** (navigation template) at the very bottom.
6. Categories (implicit here — we use the sidebar instead).

### Lead section rules
- First sentence should establish the subject: "**CHOPSTIX** is a franchise in the
  Pine Hills Fantasy Football League, owned by …". Bold the article title.
- No section headings inside the lead.
- Keep it summary-only; details go in later sections.

## 3. Navigation

Wikipedia uses three navigation mechanisms. Our skin maps them as:

| Wikipedia | Our implementation | Notes |
|---|---|---|
| **Sidebar** (left) | Starlight `sidebar` config (`astro.config.mjs`) | Autogenerate from `seasons/`, `teams/`, `draft/`; hand-link `Records`, `Lore`. This is our "toolbox". |
| **Navbox** (bottom of article) | A `<Navbox>` component, or a "See also" section | Not yet built. Per Wikipedia, a navbox groups related pages (e.g. all 2020 teams). Add when we have a reusable component. |
| **See also** | A `## See also` section with `[[wikilinks]]` | Preferred for small link sets (<5). Use instead of a navbox when few links. |
| **Categories** | (n/a — sidebar covers discovery) | Wikipedia categories have no direct Starlight equivalent; the sidebar is the discovery surface. |
| **Breadcrumbs** | Starlight breadcrumbs (optional) | Enable per-page via frontmatter if wanted. |
| **Hatnotes** | A one-line "For X, see [[Y]]." at the very top of the lead | Use for disambiguation (e.g. team vs season pages). |

### Wikilinks
- Use `[[Page Title]]` or `[[Page Title|display text]]`. Our remark resolver maps
  the title to the real slug via `permalinks.json`.
- Link on **first mention** of a concept in the lead, then sparingly.
- Don't over-link: Wikipedia guidance is to link a term once, on first occurrence.
- Red links (`wiki-new`) mean the target page doesn't exist yet — that's fine for
  forward references (e.g. not-yet-generated roster pages); they're whitelisted in CI.

## 4. Content writing style

Following Wikipedia's tone (neutral, encyclopedic), adapted for a league wiki:

- **Neutral point of view.** Describe events; don't cheer. "The commissioner
  vetoed the trade" not "The commissioner savagely killed the trade."
- **Past tense for completed seasons**, present for standing facts:
  "The 2020 season ended with …"; "The league has 12 teams."
- **Lead with the summary.** A reader should get the gist from the first paragraph.
- **Use infoboxes** for at-a-glance facts (owner, joined, titles, finish).
- **Section headings** are sentence-case, not Title Case: "Draft history", not
  "Draft History".
- **Tables** for standings, draft boards, season logs. Keep them bordered (skin does this).
- **Citations / sources:** when stating a controversial or surprising fact, add a
  footnote or a link to the source (Yahoo page, group chat screenshot, etc.).
  Our skin styles footnotes; citation hover is a future enhancement.
- **Avoid "we"** and personal anecdote in article voice; community commentary
  belongs on **Lore** pages, not team/season pages.
- **Dates:** ISO-ish consistency, e.g. "2020-09-12" or "September 12, 2020".
- **Don't sign articles** ("— written by …"). Wikipedia articles are unsigned;
  attribution is via git history.

## 5. Page templates (recommended shape)

### Team / franchise page (`teams/<slug>.mdx`)
```mdx
---
title: "CHOPSTIX"
description: "Franchise history for CHOPSTIX in the Pine Hills Fantasy Football League."
---
import Infobox from '../../../components/Infobox.astro';

<Infobox title="CHOPSTIX" rows={[
  { label: 'Owner', value: 'TBD' },
  { label: 'Joined', value: '2018' },
  { label: 'Titles', value: '1' },
  { label: '2020 Season', value: '[[2020 Season]]' },
]} />

**CHOPSTIX** is a franchise in the Pine Hills Fantasy Football League, owned by ….

## History
…

## Records
…

## See also
- [[2020 Season]]
- [[Draft History]]
```

### Season page (`seasons/<year>-season.md`)
Lead: "The **2020 Pine Hills season** was the league's fifth, running …".
Sections: Standings, Playoffs, Awards, Draft, Notable moments.

### Lore page
First-person/community voice is OK here (it's the "talk" space), but keep it
readable and dated.
