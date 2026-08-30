// scripts/migrate-wikilinks.mjs
// Scans src/content/docs for [[Target|label]] wikilinks and validates each
// against permalinks.json (produced by scripts/wikilink-map.mjs).
//
//   - resolved   : Target maps to a real page (by title or note-name, case/spacing
//                  insensitive) -> OK
//   - new        : Target does not resolve but is well-formed. In a wiki this is a
//                  normal "red link" (the page just hasn't been created yet) — e.g.
//                  forward-references (Post-Draft / End-of-Season / <TEAM> / <YEAR>
//                  placeholders) or genuinely-missing pages. Non-fatal.
//   - broken     : Malformed wikilink (empty target) -> hard error.
//
// Usage:
//   node scripts/migrate-wikilinks.mjs --check     # exits 1 if any broken
//   node scripts/migrate-wikilinks.mjs --report    # also writes linkcheck-report.txt
//   node scripts/migrate-wikilinks.mjs --root DIR --permalinks FILE
//
// Exported `analyze()` is used by the test suite with fixtures.

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const DEFAULT_ROOT = 'src/content/docs';
const DEFAULT_PERMALINKS = 'permalinks.json';

// Forward-reference patterns that point at pages generate.py has not created yet.
const WHITELIST = [
  /End-of-Season$/i,
  /Post-Draft$/i,
  /<TEAM>/i,
  /<YEAR>/i,
  /^<.+>$/, // any bare <placeholder>
];

const WIKILINK = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;
// Malformed: [[ ]] or [[]] (empty target) -> hard error.
const EMPTY_WIKILINK = /\[\[\s*\]\]/g;

export function analyze(root = DEFAULT_ROOT, permalinksPath = DEFAULT_PERMALINKS) {
  if (!existsSync(permalinksPath)) {
    throw new Error(`permalinks.json not found at ${permalinksPath}; run scripts/wikilink-map.mjs first`);
  }
  const permalinks = JSON.parse(readFileSync(permalinksPath, 'utf8'));

  // Case/spacing-insensitive index for tolerant lookup.
  const byLower = new Map();
  for (const [key, slug] of Object.entries(permalinks)) {
    byLower.set(key.trim().toLowerCase(), slug);
  }
  const resolve = (target) => permalinks[target] ?? byLower.get(target.trim().toLowerCase());

  const ok = [];
  const warned = [];
  const broken = [];
  const seenTargets = new Set();

  const isWhitelisted = (target) => WHITELIST.some((re) => re.test(target));

  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) {
        walk(p);
        continue;
      }
      if (!/\.mdx?$/.test(name)) continue;
      const raw = readFileSync(p, 'utf8');
      // Malformed empty wikilinks -> broken (hard error).
      let e;
      EMPTY_WIKILINK.lastIndex = 0;
      while ((e = EMPTY_WIKILINK.exec(raw)) !== null) {
        broken.push({ target: '(empty)', label: '', file: p });
      }
      let m;
      WIKILINK.lastIndex = 0;
      while ((m = WIKILINK.exec(raw)) !== null) {
        const target = m[1].trim();
        const label = (m[2] ?? target).trim();
        const loc = `${p.replace(root + '/', '')}:${target}`;
        if (seenTargets.has(loc)) continue; // avoid duplicate counting within a file
        seenTargets.add(loc);
        if (!target) {
          broken.push({ target: '(empty)', label, file: p });
        } else if (resolve(target)) {
          ok.push({ target, label, file: p });
        } else {
          // Well-formed but unresolved -> wiki "red link" (non-fatal).
          // Tag forward-references for clarity but never fail the build on these.
          warned.push({ target, label, file: p, forwardRef: isWhitelisted(target) });
        }
      }
    }
  };

  walk(root);
  return { ok, warned, broken };
}

function printReport({ ok, warned, broken }, root) {
  const forwardRefs = warned.filter((w) => w.forwardRef);
  const lines = [];
  lines.push(`Wikilink link-check (root: ${root})`);
  lines.push(`  resolved   : ${ok.length}`);
  lines.push(`  new/red    : ${warned.length} (not-yet-generated / missing pages; non-fatal)`);
  lines.push(`    of which forward-refs (Post-Draft/End-of-Season/<TEAM>/<YEAR>): ${forwardRefs.length}`);
  lines.push(`  broken     : ${broken.length} (malformed only)`);
  if (warned.length) {
    lines.push('');
    lines.push('New / red links (rendered as wiki-new; page not present yet):');
    for (const w of warned) lines.push(`  - [[${w.target}]] (${w.file})${w.forwardRef ? '  [forward-ref]' : ''}`);
  }
  if (broken.length) {
    lines.push('');
    lines.push('Broken (malformed wikilinks — must fix):');
    for (const b of broken) lines.push(`  - [[${b.target}]] (${b.file})`);
  }
  return lines.join('\n');
}

// ---- CLI ------------------------------------------------------------------
const args = process.argv.slice(2);
const has = (flag) => args.includes(flag);
if (import.meta.url === `file://${process.argv[1]}`) {
  const root = args.includes('--root') ? args[args.indexOf('--root') + 1] : DEFAULT_ROOT;
  const permalinks = args.includes('--permalinks')
    ? args[args.indexOf('--permalinks') + 1]
    : DEFAULT_PERMALINKS;
  const report = analyze(root, permalinks);
  const text = printReport(report, root);
  console.log(text);
  if (has('--report')) {
    writeFileSync('linkcheck-report.txt', text + '\n');
    console.log(`\nWrote linkcheck-report.txt`);
  }
  if (has('--check') && report.broken.length > 0) {
    process.exit(1);
  }
  process.exit(0);
}
