// scripts/wikilink-map.mjs
// Scans src/content/docs and emits permalinks.json mapping every page's
// frontmatter `title` (and its note-name / path) -> its Starlight slug
// (directory path without `index`, `/`-prefixed, trailing slash).
// Consumed by the wikilink resolver (astro.config.mjs / src/remark-wikilink-custom.mjs)
// and the link-checker.

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = 'src/content/docs';
const permalinks = {};

function titleOf(raw) {
  const fm = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!fm) return null;
  const m = fm[1].match(/^title:\s*(.+)$/m);
  if (!m) return null;
  return m[1].trim().replace(/^["']|["']$/g, '');
}

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      walk(p);
      continue;
    }
    if (!/\.mdx?$/.test(name)) continue;
    const raw = readFileSync(p, 'utf8');
    const title = titleOf(raw);
    // Relative path without leading ROOT, single leading slash, no extension / index.
    let rel = p.slice(ROOT.length);
    if (!rel.startsWith('/')) rel = '/' + rel;
    let slug = rel.replace(/\.mdx?$/, '').replace(/index$/, '');
    if (!slug.endsWith('/')) slug += '/';
    // key by frontmatter title (how wikilinks reference pages)
    if (title) permalinks[title] = slug;
    // also key by note name (path relative to ROOT without extension/index)
    const note = p.slice(ROOT.length + 1).replace(/\.mdx?$/, '').replace(/index$/, '');
    permalinks[note || 'index'] = slug;
  }
}

walk(ROOT);
writeFileSync('permalinks.json', JSON.stringify(permalinks, null, 2));
console.log(`Wrote permalinks.json with ${Object.keys(permalinks).length} entries`);
