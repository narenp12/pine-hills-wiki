# Pine Hills Wiki → Astro (Starlight + Wikipedia skin) Implementation Plan

> **For Hermes:** Use delegate_task (subagent-driven) or execute inline to implement task-by-task. Steps use `- [ ]` checkbox syntax.

**Goal:** Migrate the Pine Hills Fantasy Football wiki from Quartz 5 to Astro + Starlight with a faithful Wikipedia skin, preserving all Markdown content and resolving every `[[wikilink]]`, deployed to the same GitHub Pages base path.

**Architecture:** Astro 6 + `@astrojs/starlight` (official default docs theme, used only as a layout foundation) builds Markdown/MDX from `src/content/docs/`. A Wikipedia look is applied via `src/styles/wikipedia.css` + component overrides (`<Infobox>`, header/sidebar). `[[wikilinks]]` are resolved by `@portaljs/remark-wiki-link` (or a tiny custom remark plugin fallback) wired into `markdown.remarkPlugins`, driven by a `title → slug` permalink map. The existing Python `generate.py` / Rust scraper keep emitting Markdown, repointed to `src/content/docs/`.

**Tech Stack:** Astro 6, `@astrojs/starlight`, `@astrojs/pagefind` (search), `@portaljs/remark-wiki-link`, `@astrojs/sitemap` (optional), Node 22+ (CI Node 24).

**User decisions (already made):**
- Foundation: Astro + Starlight default theme + custom Wikipedia skin (NOT `starlight-theme-obsidian` — it lacks working wikilinks and is single-maintainer).
- Look: faithful Wikipedia clone (serif, top bar, left toolbox, right infobox, citation hover).
- Wikilinks: own resolver via remark plugin; graph/backlinks deferred.
- Math/KaTeX: deferred (verified no pages use it).

**Spec:** `docs/superpowers/specs/2026-08-29-astro-wiki-migration-design.md`

---

## Task 1: Scaffold Astro + Starlight on a feature branch

**Goal:** A bare Starlight site builds and serves locally with `base: '/pine-hills-wiki'` and no Quartz deps.

**Files:**
- Create: `astro.config.mjs`, `src/env.d.ts`, `src/content/docs/index.md`, `tsconfig.json`
- Modify: `package.json` (scripts + deps)
- Remove: `quartz/`, `quartz.config.yaml`, `quartz.config.default.yaml`, `quartz.ts`, `tsconfig.tsbuildinfo`

**Acceptance Criteria:**
- [ ] `npm run build` produces `dist/` with no errors.
- [ ] `npm run dev` serves at `http://localhost:4321/pine-hills-wiki/`.
- [ ] `package.json` no longer references `quartz` or `@quartz-community/*`.

**Verify:** `npm run build 2>&1 | tail -5` → expects `complete` with no error; `ls dist/index.html` exists.

**Steps:**
- [ ] Step 1: Create branch `feat/astro-wiki`: `git checkout -b feat/astro-wiki`.
- [ ] Step 2: Install deps: `npm pkg set type=module` then `npm install @astrojs/starlight @astrojs/pagefind @astrojs/sitemap astro` (Astro is a peer; ensure `astro@^6` resolves). Confirm `astro` bin present.
- [ ] Step 3: Write `astro.config.mjs`:
```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  base: '/pine-hills-wiki',
  site: 'https://narenp12.github.io',
  integrations: [
    starlight({
      title: 'Pine Hills Fantasy Football League',
      description: 'The collaborative history of the Pine Hills Fantasy Football League, established 2016.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/narenp12/pine-hills-wiki' }],
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Seasons', autogenerate: { directory: 'seasons' } },
        { label: 'Teams', autogenerate: { directory: 'teams' } },
        { label: 'Records', link: '/records/' },
        { label: 'Draft History', autogenerate: { directory: 'draft' } },
        { label: 'Lore', link: '/lore/' },
      ],
    }),
    sitemap(),
  ],
});
```
- [ ] Step 4: Write `tsconfig.json` (extends Astro's strict preset):
```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```
- [ ] Step 5: Write minimal `src/content/docs/index.md`:
```md
---
title: Pine Hills Fantasy Football League
description: The collaborative history of the Pine Hills Fantasy Football League, established 2016.
---

# 🏈 Pine Hills Fantasy Football League

Welcome to the unofficial Wikipedia of the Pine Hills Fantasy Football League (PHFFL).
```
- [ ] Step 6: Remove Quartz engine + dead config: `rm -rf quartz quartz.config.yaml quartz.config.default.yaml quartz.ts tsconfig.tsbuildinfo` (keep `quartz/` out of git later via commit).
- [ ] Step 7: Update `package.json` scripts: replace `quartz`/`docs`/`profile`/`install-plugins` with:
```json
"scripts": {
  "dev": "astro dev",
  "build": "astro build",
  "preview": "astro preview",
  "check": "astro check && prettier . --check",
  "format": "prettier . --write"
}
```
- [ ] Step 8: Run `npm run build` and confirm `dist/index.html` exists.
- [ ] Step 9: Commit: `git add -A && git commit -m "build(astro): scaffold Starlight site with /pine-hills-wiki base, drop Quartz engine"`.

---

## Task 2: Move content into `src/content/docs/` and repoint the generator

**Goal:** All existing wiki Markdown lives under `src/content/docs/` and `scripts/generate.py` writes there; site still builds.

**Files:**
- Move: `content/*` → `src/content/docs/` (git mv)
- Modify: `scripts/generate.py` (CONTENT path), `content.config.ts` (loose docs schema)

**Acceptance Criteria:**
- [ ] `npm run build` succeeds with the real content present (e.g. `dist/seasons/2020-season/index.html` exists).
- [ ] `scripts/generate.py` writes into `src/content/docs/` without error.
- [ ] No `content/` directory remains at repo root.

**Verify:** `npm run build 2>&1 | tail -3`; `ls src/content/docs/seasons/2020-season.md`; `grep -n "CONTENT =" scripts/generate.py`.

**Steps:**
- [ ] Step 1: `mkdir -p src/content/docs && git mv content/* src/content/docs/ && rmdir content 2>/dev/null; git rm -r --cached content 2>/dev/null || true`.
- [ ] Step 2: In `scripts/generate.py`, change the CONTENT root. Find `CONTENT = Path(...)`:
```python
# was: CONTENT = Path(__file__).resolve().parent.parent / "content"
CONTENT = Path(__file__).resolve().parent.parent / "src" / "content" / "docs"
```
- [ ] Step 3: Create `src/content/config.ts` (loose schema so missing frontmatter doesn't fail):
```ts
import { defineCollection, z } from 'astro:content';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    schema: docsSchema({
      extend: z.object({
        season: z.number().optional(),
        year: z.number().optional(),
      }),
    }),
  }),
};
```
- [ ] Step 4: Build: `npm run build`. Fix any frontmatter schema errors by loosening the extend (do NOT edit content prose).
- [ ] Step 5: Run generator to confirm repoint: `python3 scripts/generate.py` (or `uv run python scripts/generate.py`); then `git status` shows changes under `src/content/docs/`.
- [ ] Step 6: Commit: `git add -A && git commit -m "build(content): move wiki Markdown to src/content/docs; repoint generate.py"`.

---

## Task 3: Wikilink resolver — prototype against Starlight loader

**Goal:** Decide and prove a working `[[wikilink]]` resolution approach under Starlight before touching all 59 links.

**Files:**
- Create: `scripts/wikilink-map.mjs` (builds title→slug permalink map)
- Create/Modify: `astro.config.mjs` (`markdown.remarkPlugins`)
- Test: `tests/wikilink-resolver.test.mjs`

**Acceptance Criteria:**
- [ ] A sample page containing `[[2020 Season]]` and `[[2020 chopstix Post-Draft|chopstix]]` renders a real `<a href="/pine-hills-wiki/seasons/2020-season/">` (and the second resolves or is visibly "new").
- [ ] Pages containing wikilinks do NOT render empty (regression vs datopian/portaljs#1507).

**Verify:** `npm run build` then `grep -o 'href="/pine-hills-wiki/seasons/2020-season/"' dist/seasons/<sample>/index.html` returns a match; `grep -c 'class="[^"]*new' dist/.../index.html` shows expected new-link count.

**Steps:**
- [ ] Step 1: Write failing test `tests/wikilink-resolver.test.mjs` (uses `unified` + the plugin on a fixture string, asserts it emits an `<a>` with expected href). Run `node --test tests/wikilink-resolver.test.mjs` → FAILS (plugin not wired yet).
- [ ] Step 2: Write `scripts/wikilink-map.mjs` that scans `src/content/docs` and emits `permalinks.json` mapping every page's `title` → its Starlight slug (directory path without `index`, `/`-prefixed):
```js
import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = 'src/content/docs';
const permalinks = {};
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { walk(p); continue; }
    if (!/\.mdx?$/.test(name)) continue;
    const raw = readFileSync(p, 'utf8');
    const fm = raw.match(/^---\n([\s\S]*?)\n---/);
    const title = fm?.[1]?.match(/^title:\s*(.+)$/m)?.[1]?.trim().replace(/^["']|["']$/g, '');
    let slug = '/' + p.slice(ROOT.length).replace(/\.mdx?$/, '').replace(/index$/, '');
    if (!slug.endsWith('/')) slug += '/';
    if (title) permalinks[title] = slug;
    permalinks[slug.replace(/^\/|\/$/g, '') || 'index'] = slug; // also key by note name
  }
}
walk(ROOT);
writeFileSync('permalinks.json', JSON.stringify(permalinks, null, 2));
```
- [ ] Step 3: Wire the plugin in `astro.config.mjs`:
```js
import wikiLinkPlugin from '@portaljs/remark-wiki-link';
// (after build step 1) generate permalinks.json before build, or import the map:
const permalinks = JSON.parse(readFileSync('permalinks.json', 'utf8'));
// inside defineConfig:
markdown: {
  remarkPlugins: [[wikiLinkPlugin, {
    pathFormat: 'obsidian-short',
    permalinks: Object.values(permalinks),
    wikiLinkResolver: (name) => [name],
    hrefTemplate: (permalink) => permalink,
  }]],
},
```
- [ ] Step 4: Run `node scripts/wikilink-map.mjs && npm run build`. Inspect a wikilink page. **If pages render empty**, abandon `@portaljs` and implement the custom plugin (Task 3 fallback, Step 6).
- [ ] Step 5: If working, commit: `git add -A && git commit -m "feat(wikilinks): resolve [[...]] via @portaljs/remark-wiki-link + title->slug map"`.
- [ ] Step 6 (FALLBACK only if Step 4 blanked pages): write `src/remark-wikilink-custom.mjs` (~40 LOC) that transforms `[[Target|label]]` → `<a href={map[Target] or '#' class='new'}>{label||Target}</a>`, import `permalinks.json`, and replace the plugin in `astro.config.mjs`. Commit with message `feat(wikilinks): custom remark resolver (portaljs blanked Starlight pages)`.

---

## Task 4: Wikilink migration script + tolerant CI link-check

**Goal:** All 59 existing `[[...]]` resolve (or are correctly flagged as not-yet-generated), enforced in CI.

**Files:**
- Create: `scripts/migrate-wikilinks.mjs` (idempotent rewriter/validator), `.github/workflows/linkcheck.yml`
- Test: `tests/wikilink-migration.test.mjs`

**Acceptance Criteria:**
- [ ] Script reports 0 unexpected broken links against current content (after `generate.py` runs).
- [ ] CI link-check job passes on the branch.

**Verify:** `node scripts/migrate-wikilinks.mjs --check` exits 0; `cat linkcheck-report.txt` lists only whitelisted targets.

**Steps:**
- [ ] Step 1: Write failing test that asserts `migrate-wikilinks.mjs --check` on a temp fixture with one broken + one valid link returns the broken one. Run → FAILS.
- [ ] Step 2: Implement `scripts/migrate-wikilinks.mjs`:
```js
// scans src/content/docs for [[Target|label]], looks Target up in permalinks.json
// (by title or by slug). If found -> OK. If not found AND matches whitelist
// (/End-of-Season$|/Post-Draft$|<TEAM>|<YEAR>/) -> warn (not-yet-generated).
// Else -> error (broken). --check prints report + exits 1 on broken.
```
- [ ] Step 3: Whitelist patterns: `End-of-Season`, `Post-Draft`, `<TEAM>`, `<YEAR>` (template placeholders).
- [ ] Step 4: Run `node scripts/wikilink-map.mjs && uv run python scripts/generate.py && node scripts/migrate-wikilinks.mjs --check` → expect exit 0 (only whitelisted warnings).
- [ ] Step 5: Add `.github/workflows/linkcheck.yml` running the same three commands on push/PR.
- [ ] Step 6: Commit: `git add -A && git commit -m "test(wikilinks): migration validator + tolerant CI link-check"`.

---

## Task 5: Wikipedia skin — CSS + header/sidebar overrides

**Goal:** The site visibly reads as Wikipedia (serif, top bar, left toolbox, article HR).

**Files:**
- Create: `src/styles/wikipedia.css`, `src/components/Header.astro` (override), `src/components/Sidebar.astro` (override if needed)
- Modify: `astro.config.mjs` (`customCss: ['./src/styles/wikipedia.css']`, `components`)

**Acceptance Criteria:**
- [ ] Body/headings render serif (Georgia fallback).
- [ ] Top bar shows league title left, search right; `<h1>` followed by a horizontal rule.

**Verify:** `npm run dev`, open `/pine-hills-wiki/`; visually confirm serif + top bar + HR under title. (USER-ORDERED GATE — NON-SKIPPABLE: confirm in a real browser.)

**Steps:**
- [ ] Step 1: Write `src/styles/wikipedia.css` with the Vector-ish tokens described in spec §7 (serif stack, top-bar border, `.article h1` bottom border, neutral panels `#f6f6f6`/`#eaecf0`, accent `#0d47a1`).
- [ ] Step 2: Register in `astro.config.mjs`: `starlight({ customCss: ['./src/styles/wikipedia.css'], ... })`.
- [ ] Step 3: Override `Header` component (Starlight `components: { Header: './src/components/Header.astro' }`) rendering league title + search slot.
- [ ] Step 4: Build + visually verify (gate). Commit: `git add -A && git commit -m "style(wiki): Wikipedia Vector skin (serif, top bar, HR, panels)"`.

---

## Task 6: `<Infobox>` component (MDX) + sample usage

**Goal:** A reusable Wikipedia infobox renders floated right with key–value rows, used on team/season pages.

**Files:**
- Create: `src/components/Infobox.astro`
- Modify: one sample page (e.g. `src/content/docs/teams/chopstix.md`) to import + use it (MDX)

**Acceptance Criteria:**
- [ ] Infobox appears floated right with bordered header `#eaecf0` and rows.
- [ ] Wikilink inside an infobox value still resolves.

**Verify:** `npm run build` then `grep -o 'class="infobox"' dist/teams/chopstix/index.html` matches; infobox contains a resolved `<a href>`.

**Steps:**
- [ ] Step 1: Write `src/components/Infobox.astro`:
```astro
---
interface Props { title: string; image?: string; imageCaption?: string; rows: { label: string; value: string }[]; }
const { title, image, imageCaption, rows } = Astro.props;
---
<aside class="infobox">
  <header class="infobox-title">{title}</header>
  {image && <img src={image} alt={title} />}
  {imageCaption && <p class="infobox-caption">{imageCaption}</p>}
  <table><tbody>
    {rows.map(r => (<tr><th>{r.label}</th><td set:html={r.value} /></tr>))}
  </tbody></table>
</aside>
```
- [ ] Step 2: Convert `teams/chopstix.md` → `chopstix.mdx`, add `import Infobox from '../../components/Infobox.astro';` and an `<Infobox>` with one row whose `value` is a `[[2020 Season]]` wikilink (to confirm intra-component resolution).
- [ ] Step 3: Build + grep verification. Commit: `git add -A && git commit -m "feat(infobox): Wikipedia-style Infobox component + sample on a team page"`.

---

## Task 7: Deploy reconfiguration + cutover

**Goal:** GitHub Pages builds Astro and serves at the same URL; Quartz workflow removed.

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Remove: any remaining quartz references

**Acceptance Criteria:**
- [ ] `deploy.yml` builds with `npm run build` and uploads `dist/`.
- [ ] Live site at `https://narenp12.github.io/pine-hills-wiki/` has no 404s on known pages.

**Verify:** Trigger workflow (or `npm run build && npx serve dist` locally); check `dist/seasons/2020-season/index.html` and a wikilink target resolve. (USER-ORDERED GATE — NON-SKIPPABLE: confirm live deploy.)

**Steps:**
- [ ] Step 1: Rewrite `.github/workflows/deploy.yml`:
```yaml
name: Deploy to GitHub Pages
on:
  push: { branches: [main] }
  workflow_dispatch:
permissions: { contents: read, pages: write, id-token: write }
concurrency: { group: pages, cancel-in-progress: false }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with: { fetch-depth: 0 }
      - uses: actions/setup-node@v6
        with: { node-version: 24 }
      - run: npm install
      - run: node scripts/wikilink-map.mjs
      - run: npm run build
      - uses: actions/upload-pages-artifact@v4
        with: { path: dist }
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```
- [ ] Step 2: Ensure no stray Quartz refs: `grep -rn quartz package.json .github 2>/dev/null` returns nothing.
- [ ] Step 3: Build locally to sanity check; commit: `git add -A && git commit -m "ci(deploy): build Astro, upload dist/ to GitHub Pages"`.
- [ ] Step 4: Merge `feat/astro-wiki` → `main` (PR) and let Pages deploy; verify live URL (gate).

---

## Self-review notes
- Spec coverage: §2 goals → Tasks 1–7; §9 parity → Task 3 (wikilinks), 5 (skin), 6 (infobox), 7 (deploy); §10 plan → mirrored as Tasks 1–7.
- No placeholders: every code step shows real config/snippet.
- Type consistency: `permalinks.json` consumed by Task 3 (astro.config) and Task 4 (validator).
- Known risk carried as Task 3 Step 6 fallback (resolver blanks pages).
