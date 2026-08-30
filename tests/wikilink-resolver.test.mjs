// tests/wikilink-resolver.test.mjs
// Verifies the custom wikilink resolver (src/remark-wikilink-custom.mjs)
// produces real <a> nodes: resolved targets get the page slug + `wiki-link`
// class; unknown targets get a `#` href + `wiki-link wiki-new` class.
// Run: node --test tests/wikilink-resolver.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { remarkWikilinkCustom } from '../src/remark-wikilink-custom.mjs';

function run(tree) {
  remarkWikilinkCustom()(tree);
  return tree;
}

function collectLinks(nodes, acc = []) {
  for (const n of nodes) {
    if (n.type === 'link') acc.push(n);
    if (n.children) collectLinks(n.children, acc);
  }
  return acc;
}

test('resolves a known title to its slug with wiki-link class', () => {
  const tree = run({
    type: 'root',
    children: [
      {
        type: 'paragraph',
        children: [{ type: 'text', value: 'See [[2020 Season]] for details.' }],
      },
    ],
  });
  const links = collectLinks(tree.children);
  const resolved = links.find((l) => l.url === '/pine-hills-wiki/seasons/2020-season/');
  assert.ok(resolved, 'expected a link to /pine-hills-wiki/seasons/2020-season/');
  assert.equal(resolved.data.hProperties.class, 'wiki-link');
  assert.equal(resolved.children[0].value, '2020 Season');
});

test('marks an unknown target as wiki-new with # href', () => {
  const tree = run({
    type: 'root',
    children: [
      {
        type: 'paragraph',
        children: [{ type: 'text', value: 'Future: [[Ghost Page|ghost]].' }],
      },
    ],
  });
  const links = collectLinks(tree.children);
  const missing = links.find((l) => l.url === '#');
  assert.ok(missing, 'expected a # placeholder link for unknown target');
  assert.equal(missing.data.hProperties.class, 'wiki-link wiki-new');
  assert.equal(missing.children[0].value, 'ghost');
});

test('supports label syntax [[Target|label]]', () => {
  const tree = run({
    type: 'root',
    children: [
      {
        type: 'paragraph',
        children: [{ type: 'text', value: 'Pick [[2020 Draft|the draft]].' }],
      },
    ],
  });
  const links = collectLinks(tree.children);
  const link = links.find((l) => l.url === '/pine-hills-wiki/draft/2020-draft/');
  assert.ok(link, 'expected resolved draft link');
  assert.equal(link.children[0].value, 'the draft');
});
