// tests/wikilink-migration.test.mjs
// Verifies the wikilink migration validator (scripts/migrate-wikilinks.mjs):
//   - a well-formed link to an existing page is "resolved"
//   - a well-formed link to a missing page is a non-fatal "new" (red) link
//   - a malformed (empty-target) wikilink is "broken" (hard error)
// Run: node --test tests/wikilink-migration.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { analyze } from '../scripts/migrate-wikilinks.mjs';

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), 'wikilink-migrate-'));
  writeFileSync(join(dir, 'permalinks.json'), JSON.stringify({ 'My Page': '/my-page/' }));
  const docs = join(dir, 'docs');
  mkdirSync(docs, { recursive: true });
  writeFileSync(join(docs, 'valid.md'), 'See [[My Page]] here.\n');
  writeFileSync(join(docs, 'missing.md'), 'Future [[Ghost Team]] page.\n');
  writeFileSync(join(docs, 'broken.md'), 'Bad: [[]] link.\n');
  return { dir, docs };
}

test('resolves a link to an existing page', () => {
  const { dir, docs } = fixture();
  try {
    const r = analyze(docs, join(dir, 'permalinks.json'));
    assert.ok(r.ok.some((x) => x.target === 'My Page'), 'My Page should resolve');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('treats a missing-but-well-formed link as a non-fatal new/red link', () => {
  const { dir, docs } = fixture();
  try {
    const r = analyze(docs, join(dir, 'permalinks.json'));
    assert.ok(r.warned.some((x) => x.target === 'Ghost Team'), 'Ghost Team should be a new/red link');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('flags a malformed (empty-target) wikilink as broken', () => {
  const { dir, docs } = fixture();
  try {
    const r = analyze(docs, join(dir, 'permalinks.json'));
    assert.ok(r.broken.length >= 1, 'empty-target wikilink must be broken');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
