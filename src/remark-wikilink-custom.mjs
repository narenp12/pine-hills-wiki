// src/remark-wikilink-custom.mjs
// Custom remark transformer that resolves [[Target|label]] Obsidian-style
// wikilinks into real <a> elements using the title->slug permalink map
// (permalinks.json, produced by scripts/wikilink-map.mjs).
//
// We use a hand-rolled mdast walker (no extra deps) and emit proper mdast
// `link` nodes with `data.hProperties` for the CSS class, so resolution works
// under Starlight WITHOUT blanking page content (the regression reported in
// datopian/portaljs#1507 with @portaljs/remark-wiki-link).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const permalinks = JSON.parse(
  readFileSync(fileURLToPath(new URL('../permalinks.json', import.meta.url)), 'utf8')
);

const BASE = '/pine-hills-wiki';
const WIKILINK = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;

// Turn a [[Target|label]] match into a resolved or "new" (missing) link node.
function linkNode(target, label) {
  const slug = permalinks[target];
  if (slug) {
    return {
      type: 'link',
      url: BASE + slug,
      title: null,
      data: { hProperties: { class: 'wiki-link' } },
      children: [{ type: 'text', value: label }],
    };
  }
  return {
    type: 'link',
    url: '#',
    title: `Missing page: ${target}`,
    data: { hProperties: { class: 'wiki-link wiki-new', 'data-target': target } },
    children: [{ type: 'text', value: label }],
  };
}

function transformText(value) {
  const out = [];
  let last = 0;
  let m;
  WIKILINK.lastIndex = 0;
  while ((m = WIKILINK.exec(value)) !== null) {
    if (m.index > last) out.push({ type: 'text', value: value.slice(last, m.index) });
    const target = m[1].trim();
    const label = (m[2] ?? target).trim();
    out.push(linkNode(target, label));
    last = m.index + m[0].length;
  }
  if (!out.length) return null;
  if (last < value.length) out.push({ type: 'text', value: value.slice(last) });
  return out;
}

export function remarkWikilinkCustom() {
  return (tree) => {
    const walk = (nodes) => {
      if (!Array.isArray(nodes)) return;
      const replacement = [];
      for (const node of nodes) {
        if (node && node.type === 'text' && typeof node.value === 'string' && node.value.includes('[[')) {
          const transformed = transformText(node.value);
          if (transformed) {
            replacement.push(...transformed);
            continue;
          }
        }
        if (node && node.children) walk(node.children);
        replacement.push(node);
      }
      nodes.length = 0;
      nodes.push(...replacement);
    };
    walk(tree.children);
  };
}

export default remarkWikilinkCustom;
