# Zensical Modern Redesign — Design Spec

**Date:** 2026-08-30
**Status:** Proposed (awaiting approval)
**Scope:** `zensical/` edition only (parallel to the Astro/Starlight edition). The Starlight edition is untouched.

---

## 0. Design Read

*Reading this as: a community **encyclopedia / knowledge base** for a fantasy football league, audience = league members + curious visitors, with an **editorial-publication + modern-docs** language, leaning toward **Zensical's native `modern` variant** themed with a custom brand system.*

Visual direction decisions (confirmed with user):
- **Brand accent:** Pine Green (evokes "Pine Hills", on-brand, not generic AI-blue/purple).
- **Typography:** Serif body + sans chrome/headings (encyclopedic editorial read).
- **Home hero:** Editorial split (league name + value prop left, quick-stat / explore tiles right).

---

## 1. The Problem (Root Cause)

The current site is on `variant = "classic"` (the legacy Material-for-MkDocs look) with a hand-bolted `wikipedia-v2.css` painting vintage gray Wikipedia chrome on top. Zensical **0.0.57 (installed)** ships a native `modern` variant with a sophisticated HSL token system and genuine dark-mode parity, but it is not being used. The result is an outdated base *and* a fake skin fighting it. Verified: switching to `variant = "modern"` builds clean (`zensical build --clean` → 0.58s, no issues).

**Fix:** switch to the `modern` base and theme it properly. Keep Wikipedia's *writing/formatting* (lead section, right-rail infobox, summary tables, see-also, footnotes, sortable tables); modernize only the chrome. This is a **Redesign — Overhaul of visuals, Preserve content + IA** (per Taste Skill §11.A): page slugs, nav labels, and all generated content stay exactly as they are.

---

## 2. Dials (Taste Skill §1)

| Dial | Value | Rationale |
|------|-------|-----------|
| `DESIGN_VARIANCE` | 6 | Reference content, not a hero-driven landing page. Clean but not symmetrical-corporate. |
| `MOTION_INTENSITY` | 4 | Fluid CSS only: hover, focus, instant-nav transitions Zensical provides. No cinematic loops. |
| `VISUAL_DENSITY` | 5 | Reference/wiki density: readable, structured, but not cockpit-tight. |

---

## 3. Approach

**Approach A — Modern-variant re-theme (chosen).**
1. `zensical/zensical.toml`: `variant = "classic"` → `"modern"`.
2. Retire `zensical/docs/stylesheets/wikipedia-v2.css`; add `zensical/docs/stylesheets/zensical.css` (lean, token-driven, dual-scheme).
3. Keep `transform.py` (infobox injection) and `tablesort` JS — they are content-level, variant-independent.
4. Keep `zensical/docs/index.md` content; restructure its hero into the editorial split.
5. Re-point `extra_css` at the new sheet; adjust `features` for modern UX.

Rejected:
- **B — deep CSS reskin on classic:** still reads "docs template", more fighting the framework.
- **C — full `overrides/` custom components:** max control, high divergence risk from Zensical updates, overkill for a theming task.

---

## 4. Palette (dual-scheme tokens)

Single accent = **Pine Green**. Chrome (header/active-nav) stays a neutral near-black ink so the green reads as editorial accent, not branding noise. No pure `#000`/`#fff`. Champion gold reserved as a *semantic* highlight only.

### Light scheme (`default`)
```
--md-hue: 150
--md-default-bg-color: #fbfbfa          /* off-white, not pure white */
--md-default-fg-color: #1b1f1a           /* warm near-black ink */
--md-default-fg-color--light: #5b625b
--md-primary-fg-color: #1b1f1a          /* chrome: deep ink */
--md-primary-bg-color: #ffffff
--md-accent-fg-color: #15633d           /* pine green, AA on off-white */
--md-typeset-a-color: #15633d
--md-typeset-mark-color: #15633d22      /* selection tint */
--md-typeset-table-color: #e6e7e3       /* hairline tables */
--wiki-border: #d9dbd5
--wiki-panel: #f1f2ee
--wiki-panel-2: #e6e7e3
--wiki-gold: #a67c00                    /* champion highlight only */
```

### Slate scheme (`dark`)
```
--md-hue: 150
--md-default-bg-color: #16181a          /* off-black, not pure black */
--md-default-fg-color: #e6e9e6          /* light text */
--md-default-fg-color--light: #9aa39a
--md-primary-fg-color: #e6e9e6
--md-primary-bg-color: #16181a
--md-accent-fg-color: #57c98a           /* lighter pine for dark bg, AA */
--md-typeset-a-color: #57c98a
--md-typeset-mark-color: #57c98a22
--md-typeset-table-color: #2a2e2c
--wiki-border: #2f3431
--wiki-panel: #1f2321
--wiki-panel-2: #2a2e2c
--wiki-gold: #d4af37
```

Set via `[data-md-color-scheme="default"]` and `[data-md-color-scheme="slate"]` blocks (the form the installed `modern` variant actually consumes).

---

## 5. Typography

- **Body (article):** `Source Serif 4` (loaded via `theme.font.text`), a screen-optimized serif for long-form reading. This delivers the "encyclopedia editorial read" the user asked for.
- **Chrome + headings:** a clean **system sans stack** (`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`) so no second network font is needed; overridden onto `.md-typeset h1..h6`, `.md-header`, `.md-nav`, `.md-tabs`, `.md-footer`, buttons. (Keeps one Google font load; serif body + sans chrome = the requested split.)
- **Code/numbers:** `JetBrains Mono` via `theme.font.code`.
- Body `font-size` lifted slightly from the current `0.7rem` to a comfortable `~0.8rem`; line-height `1.65`. Headings keep a hairline bottom border (Wikipedia-style section dividers) but with the modern border token color.

---

## 6. Home Page Hero (editorial split)

Replace the blue-gradient `tx-hero` (an AI-tell: generic gradient + sun-moon) with a custom `.ph-hero` block built on modern surface tokens:

- **DOM contract (deterministic):** a single `<div class="ph-hero">` containing two children: `<div class="ph-hero__lead">` (the league `<h1>` + one-line `<p>` value prop + 2–3 quick-explore `.md-button` links) and `<div class="ph-hero__stats">` (3 stat tiles: seasons covered, years active, champions logged, values pulled from `index.md` — no invented precision).
- Asymmetric (lead wider), single accent on links/buttons, off-white bg with a subtle `--wiki-panel` right panel. Collapses to single column `< 768px`.

No em-dashes, no decorative status dots, no eyebrow above every section.

---

## 7. Infobox + Tables (Wikipedia formatting preserved)

- `.infobox` (injected by `transform.py`): right-floated, bordered, `--wiki-panel` bg, `border-top: 3px solid var(--md-accent-fg-color)` (pine), responsive `max-width` 90% on narrow.
- Tables: bordered + zebra (`--wiki-panel` even rows), header `var(--wiki-panel-2)`, hairline `--wiki-border` (single token, no second table-color var). Keep `tablesort` JS.
- Champion rows: `tr.champion-row > td` tinted with `color-mix(in srgb, var(--wiki-gold) 14%, bg)` (already working; re-express with tokens).
- All colors via tokens so both schemes render correctly.

---

## 8. Zensical Config Changes (`zensical.toml`)

- `variant = "modern"`.
- `extra_css = ["stylesheets/zensical.css"]` (drop `wikipedia-v2.css`).
- `font.text = "Source Serif 4"`, `font.code = "JetBrains Mono"`.
- `primary = "custom"` (neutral ink via CSS) ; `accent = "custom"` (pine via CSS). **Deterministic: full custom, no named-color fallback.** All required `--md-primary-*` / `--md-accent-*` vars are provided in `zensical.css` scheme blocks (per zensical-setup custom-color contract).
- Palette: keep the two `[[project.theme.palette]]` blocks (default + slate) with toggle icons.
- `features` (modern UX): `navigation.instant`, `navigation.instant.prefetch`, `navigation.instant.progress`, `navigation.tabs`, `navigation.sections`, `navigation.top`, `navigation.footer`, `navigation.indexes`, `toc.follow`, `search.highlight`, `content.code.copy`, `content.tooltips`, `content.footnote.tooltips`, `announce.dismiss`, `header.autohide`.
  - Drop nothing that breaks content. Note `navigation.indexes` ↔ `toc.integrate` incompatibility (we keep `indexes`, drop `integrate`).

---

## 9. Files

| Action | File |
|--------|------|
| Edit | `zensical/zensical.toml` (variant, css, fonts, features, palette) |
| Create | `zensical/docs/stylesheets/zensical.css` (tokens + hero + infobox + table + typography) |
| Edit | `zensical/docs/index.md` (hero → editorial split) |
| Delete (retire) | `zensical/docs/stylesheets/wikipedia-v2.css` |
| Untouched | `zensical/transform.py`, `zensical/build.mjs`, `zensical/docs/javascripts/tablesort.js`, all generated content, Starlight edition |

---

## 10. AI-Tell Audit (Taste Skill §9, mandatory before ship)

- [ ] Zero em-dashes (`—`/`–`) anywhere visible (use hyphen/` - `/colon).
- [ ] No pure `#000000` / `#ffffff` (off-black/off-white only).
- [ ] Single accent (pine green) used on whole page; gold only for champion highlight.
- [ ] No version labels / "BETA" / "v0.x" eyebrows on home.
- [ ] Eyebrows used ≤ 1 per 3 sections (hero counts as 1).
- [ ] No decorative status dots, no scroll cues, no locale/weather strips.
- [ ] No div-based fake screenshots; real data tables only.
- [ ] Numbers are real (from `index.md`/`raw`), not fake-precise.
- [ ] Hero text ≤ 4 elements (name, value prop, links, stats); CTAs visible without scroll.

---

## 11. Verification

1. `cd zensical && zensical build --clean` (expect "No issues found").
2. `zensical serve` (or `build` + preview) and inspect:
   - Home (editorial split, both schemes), a team page (infobox + season-log table), a records/index page.
3. Toggle light/dark; confirm no white panels on dark, no near-black-on-dark text, accent visible in both.
4. `grep -Rn '—\|–' zensical/docs` → expect no matches in visible content.
5. `grep -Rn '#000000\|#ffffff' zensical/docs/stylesheets/zensical.css` → expect none (tokens only).
6. Confirm `transform.py` still injects infoboxes and `tablesort` still sorts.

---

## 12. Risks

- **`modern` hero:** the variant has no built-in `tx-hero`; we supply `.ph-hero` markup + CSS. Low risk (pure CSS block, DOM contract pinned in §6).
- **Font split:** serif body via `theme.font.text` + sans override on headings is well-supported; verify heading weight contrast in both schemes.
- **Custom primary/accent:** resolved deterministically (§8) — full custom with all vars supplied. No named fallback. If a specific `modern` internal chrome element ignores the var, that is caught in §11 verification (build + visual check both schemes) and fixed with an explicit override, not a revert.

## 13. Rollback (reversible change)

All changes are per-file and committed independently, so rollback is a targeted revert, not a redeploy:
- `git revert` (or `git checkout <prev> --`) the three changed files: `zensical/zensical.toml`, `zensical/docs/stylesheets/zensical.css`, `zensical/docs/index.md`.
- Restore `extra_css` to `wikipedia-v2.css` and `variant = "classic"` if a full revert is needed.
- No content, `transform.py`, `build.mjs`, or Starlight edition is touched, so a partial revert cannot break data generation.
- CI deploy (GitHub Pages) rebuilds from committed sources on push; a revert commit redeploys automatically.
