# Task 7: The AST Compiler — Report

## Status: ✅ Complete

## What shipped

### `zensical/docs/javascripts/query-compile.js`
- Pure `compileAst(ast, schema)` → parameterized DuckDB SQL
- Zero imports — no DOM, no DuckDB, no network
- All identifiers validated against schema before SQL is built
- Literals go into `params[]`, never inline into SQL string
- `MAX_LIMIT = 5000` exported, oversized limits clamped
- Supported AST nodes: filter, groupBy, summarise, having, arrange, limit, join
- Operators: =, !=, <, <=, >, >=, contains (ILIKE), is_null, in, not_in, between
- Aggregates: count, count_distinct, sum, avg, min, max, median, stddev
- `renderSql(sql, params)` display helper inlines params for Show Query panel

### `tests/js/query-compile.test.mjs`
- 10 tests, all passing:
  1. Filtered projection with parameters
  2. Group by with aggregates and having
  3. Two-table join
  4. SQL injection safety (literal never inlined)
  5. Unknown table rejection
  6. Unknown column rejection
  7. Injected column name rejection
  8. Unknown operator rejection
  9. Unknown aggregate rejection
  10. Oversized limit clamping

### `.github/workflows/deploy.yml`
- Test step now runs `uv run pytest -q` then `node --test tests/js/`

## Verification

- `node --test tests/js/` — 10/10 pass
- `uv run pytest -q` — 324/324 pass
- Commit: `328d849` on `feat/stat-search`

## Not implemented (by design)

- Window functions — excluded per task constraints
- No ES module imports in `query-compile.js`

## Review Fixes (2026-09-03)

### Finding 1: MODULE_TYPELESS_PACKAGE_JSON warning
- **Action:** Renamed `query-compile.js` → `query-compile.mjs` (site/javascripts/)
- **Action:** Updated import in `tests/js/query-compile.test.mjs` to `.mjs` path
- **Result:** No MODULE_TYPELESS_PACKAGE_JSON warnings

### Finding 2: renderSql untested
- **Action:** Added test verifying `renderSql('SELECT * FROM t WHERE name = ?', ["O'Brien"])` → `"SELECT * FROM t WHERE name = 'O''Brien'"`
- **Result:** 11/11 JS tests pass, 324/324 pytest pass

### Verification
- `node --test tests/js/` — 11/11 pass, no warnings
- `uv run pytest -q` — 324/324 pass
- Commit: `88c313b` on `feat/stat-search`
