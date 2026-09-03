import assert from "node:assert/strict";
import { test } from "node:test";
import { compileAst, renderSql, MAX_LIMIT } from "../../zensical/docs/javascripts/query-compile.mjs";

const schema = {
  tables: {
    matchups: {
      columns: [
        { name: "year", type: "BIGINT" },
        { name: "owner", type: "VARCHAR" },
        { name: "score", type: "DOUBLE" },
        { name: "margin", type: "DOUBLE" },
        { name: "phase", type: "VARCHAR" },
      ],
      row_count: 1230,
    },
    team_seasons: {
      columns: [
        { name: "year", type: "BIGINT" },
        { name: "owner", type: "VARCHAR" },
        { name: "wins", type: "BIGINT" },
      ],
      row_count: 88,
    },
  },
  enums: {},
};

test("compiles a filtered projection with parameters", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "score", op: ">", value: 150 }],
      arrange: [{ field: "score", dir: "desc" }],
      limit: 10,
    },
    schema,
  );
  assert.match(sql, /FROM "matchups"/);
  assert.match(sql, /WHERE "score" > \?/);
  assert.match(sql, /ORDER BY "score" DESC/);
  assert.match(sql, /LIMIT 10/);
  assert.deepEqual(params, [150]);
});

test("compiles group by with aggregates and having", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "phase", op: "=", value: "regular" }],
      groupBy: ["owner"],
      summarise: [
        { fn: "count", as: "games" },
        { fn: "avg", field: "score", as: "avg_score" },
      ],
      having: [{ field: "games", op: ">", value: 50 }],
      arrange: [{ field: "avg_score", dir: "desc" }],
    },
    schema,
  );
  assert.match(sql, /count\(\*\) AS "games"/);
  assert.match(sql, /avg\("score"\) AS "avg_score"/);
  assert.match(sql, /GROUP BY "owner"/);
  assert.match(sql, /HAVING "games" > \?/);
  assert.deepEqual(params, ["regular", 50]);
});

test("compiles a join between two tables", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      limit: 5,
    },
    schema,
  );
  assert.match(sql, /JOIN "team_seasons"/);
  assert.match(sql, /"matchups"\."year" = "team_seasons"\."year"/);
  assert.match(sql, /"matchups"\."owner" = "team_seasons"\."owner"/);
});

test("never inlines a literal into the sql text", () => {
  const { sql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "owner", op: "=", value: "'; DROP TABLE matchups; --" }],
    },
    schema,
  );
  assert.ok(!sql.includes("DROP TABLE"));
  assert.deepEqual(params, ["'; DROP TABLE matchups; --"]);
});

test("rejects an unknown table", () => {
  assert.throws(() => compileAst({ from: "secrets" }, schema), /unknown table/i);
});

test("rejects an unknown column", () => {
  assert.throws(
    () => compileAst({ from: "matchups", filter: [{ field: "ssn", op: "=", value: 1 }] }, schema),
    /unknown column/i,
  );
});

test("rejects an injected column name", () => {
  assert.throws(
    () =>
      compileAst(
        { from: "matchups", arrange: [{ field: 'score" FROM x; --', dir: "asc" }] },
        schema,
      ),
    /unknown column/i,
  );
});

test("rejects an unknown operator", () => {
  assert.throws(
    () => compileAst({ from: "matchups", filter: [{ field: "score", op: "~~", value: 1 }] }, schema),
    /unknown operator/i,
  );
});

test("rejects an unknown aggregate", () => {
  assert.throws(
    () =>
      compileAst(
        { from: "matchups", groupBy: ["owner"], summarise: [{ fn: "exec", as: "x" }] },
        schema,
      ),
    /unknown aggregate/i,
  );
});

test("clamps an oversized limit", () => {
  const { sql } = compileAst({ from: "matchups", limit: 999999 }, schema);
  assert.match(sql, new RegExp(`LIMIT ${MAX_LIMIT}`));
});

test("renderSql inlines a string parameter with escaped single quotes", () => {
  const result = renderSql("SELECT * FROM t WHERE name = ?", ["O'Brien"]);
  assert.equal(result, "SELECT * FROM t WHERE name = 'O''Brien'");
});

test("sorting by a summarise alias is allowed", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "score", as: "total" }],
      arrange: [{ field: "total", dir: "desc" }],
    },
    schema,
  );
  assert.match(sql, /ORDER BY "total" DESC/);
});

test("sorting by an unknown alias still throws", () => {
  assert.throws(
    () =>
      compileAst(
        {
          from: "matchups",
          groupBy: ["owner"],
          summarise: [{ fn: "sum", field: "score", as: "total" }],
          arrange: [{ field: "nonsense", dir: "desc" }],
        },
        schema,
      ),
    /unknown column/i,
  );
});

test("countSql measures the same rows without the ordering or the limit", () => {
  const { countSql, params } = compileAst(
    {
      from: "matchups",
      filter: [{ field: "score", op: ">", value: 150 }],
      arrange: [{ field: "score", dir: "desc" }],
      limit: 10,
    },
    schema,
  );
  assert.match(countSql, /^SELECT count\(\*\) AS "n" FROM \(/);
  assert.match(countSql, /WHERE "score" > \?/);
  assert.doesNotMatch(countSql, /ORDER BY/);
  assert.doesNotMatch(countSql, /LIMIT/);
  // Same list, same order: the caller binds one parameter array to both.
  assert.deepEqual(params, [150]);
});

test("countSql over a grouped query counts groups, not underlying rows", () => {
  const { countSql } = compileAst(
    {
      from: "matchups",
      groupBy: ["owner"],
      summarise: [{ fn: "count", as: "games" }],
      having: [{ field: "games", op: ">", value: 50 }],
    },
    schema,
  );
  assert.match(countSql, /GROUP BY "owner"/);
  assert.match(countSql, /HAVING "games" > \?/);
});

test("the compiled limit is reported back to the caller", () => {
  assert.equal(compileAst({ from: "matchups", limit: 25 }, schema).limit, 25);
  assert.equal(compileAst({ from: "matchups" }, schema).limit, 200);
  assert.equal(compileAst({ from: "matchups", limit: 1e9 }, schema).limit, MAX_LIMIT);
});

test("a join disambiguates the columns both tables carry", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      limit: 5,
    },
    schema,
  );
  // Scoped to the select list: the ON clause names each key on both sides, so
  // the whole statement is the wrong thing to assert against.
  const [selectList] = sql.split("\n");
  // The join keys are equal by definition, so only the driving table's copy is
  // selected.
  assert.match(selectList, /"matchups"\."year"/);
  assert.doesNotMatch(selectList, /"team_seasons"\."year"/);
  // `wins` is unique to the joined table, so it needs no alias.
  assert.match(selectList, /"team_seasons"\."wins"(?! AS)/);
  // Never `SELECT *` on a join: that is what produced duplicate column names.
  assert.doesNotMatch(sql, /SELECT \*/);
});

test("a non-key column both tables carry is aliased, not duplicated", () => {
  const wide = {
    tables: {
      a: { columns: [{ name: "id", type: "BIGINT" }, { name: "points", type: "DOUBLE" }], row_count: 1 },
      b: { columns: [{ name: "id", type: "BIGINT" }, { name: "points", type: "DOUBLE" }], row_count: 1 },
    },
    enums: {},
  };
  const { sql } = compileAst({ from: "a", join: { table: "b", on: ["id"] } }, wide);
  // Assert the select list itself rather than counting occurrences: the ON
  // clause names the key on both sides, so a count conflates the two places a
  // column legitimately appears.
  const [selectList] = sql.split("\n");
  assert.equal(
    selectList,
    'SELECT "a"."id", "a"."points", "b"."points" AS "b_points"',
  );
});

test("a filter naming a shared column is qualified so the sql is unambiguous", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      filter: [{ field: "year", op: "=", value: 2024 }],
    },
    schema,
  );
  assert.match(sql, /WHERE "matchups"\."year" = \?/);
});

test("a summarise alias is never qualified with a table name", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "score", as: "total" }],
      having: [{ field: "total", op: ">", value: 10 }],
      arrange: [{ field: "total", dir: "desc" }],
    },
    schema,
  );
  assert.match(sql, /HAVING "total" > \?/);
  assert.match(sql, /ORDER BY "total" DESC/);
  assert.match(sql, /GROUP BY "matchups"\."owner"/);
});

// --- Robustness -----------------------------------------------------------
//
// Every AST below is something a hand-edited `?q=` link can deliver. The
// compiler is the only thing between that link and the SQL text, so each case
// must produce either a sentence naming what is wrong or a statement whose
// only variable parts are bound parameters. None may produce a TypeError, and
// none may put caller text into the SQL outside a quoted identifier.
test("a malformed ast is rejected with a sentence, never a TypeError", () => {
  const bad = [
    [null, /ast must be an object/],
    [[], /ast must be an object/],
    ["matchups", /ast must be an object/],
    [{ filter: [] }, /unknown table/],
    [{ from: "matchups", filter: [null] }, /each filter must be an object/],
    [{ from: "matchups", filter: ["owner"] }, /each filter must be an object/],
    [{ from: "matchups", filter: "owner" }, /filter must be an array/],
    [{ from: "matchups", summarise: "count" }, /summarise must be an array/],
    [{ from: "matchups", join: "team_seasons" }, /join must be an object/],
  ];
  for (const [ast, expected] of bad) {
    assert.throws(() => compileAst(ast, schema), expected, JSON.stringify(ast));
  }
});

test("a table name that is not a string is refused, never coerced", () => {
  // Reading `ast.from` twice let a toString() pass the schema lookup on the
  // first call and emit something else into the SQL on the second.
  const sneaky = { toString: () => "matchups" };
  assert.throws(
    () => compileAst({ from: sneaky }, schema),
    /unknown table/,
  );
  assert.throws(
    () => compileAst({ from: "matchups", join: { table: sneaky, on: ["year"] } }, schema),
    /unknown table/,
  );
});

test("between refuses anything that is not exactly two values", () => {
  for (const value of [[1], [], 5, null, [1, 2, 3]]) {
    assert.throws(
      () => compileAst(
        { from: "matchups", filter: [{ field: "score", op: "between", value }] },
        schema,
      ),
      /between needs two values/,
      JSON.stringify(value),
    );
  }
});

test("a hostile limit is clamped to the allowed range, never emitted", () => {
  const limitOf = (limit) => compileAst({ from: "matchups", limit }, schema);
  assert.equal(limitOf("5; DROP TABLE x").limit, 200); // NaN falls back
  assert.equal(limitOf(-10).limit, 1);
  assert.equal(limitOf(Infinity).limit, MAX_LIMIT);
  assert.equal(limitOf(12.9).limit, 12);
  for (const limit of ["5; DROP TABLE x", -10, Infinity, 12.9, "abc"]) {
    assert.match(limitOf(limit).sql, /LIMIT \d+$/);
  }
});

test("a sort direction is one of two literals, never caller text", () => {
  const { sql } = compileAst(
    { from: "matchups", arrange: [{ field: "score", dir: "DESC; DROP TABLE x" }] },
    schema,
  );
  assert.match(sql, /ORDER BY "score" DESC$/m);
  assert.doesNotMatch(sql, /DROP/);
});

test("an injected identifier stays inside one quoted identifier", () => {
  // Proven against DuckDB: `"x"" , (SELECT 1) AS ""y"` parses as a single
  // column named `x" , (SELECT 1) AS "y`, so the doubled quote is the whole
  // defence and it holds.
  const { sql } = compileAst(
    {
      from: "matchups",
      groupBy: ["owner"],
      summarise: [{ fn: "count", as: 'x" , (SELECT 1) AS "y' }],
    },
    schema,
  );
  assert.match(sql, /AS "x"" , \(SELECT 1\) AS ""y"/);
  // Every embedded quote is doubled, which is what keeps it one identifier.
  const alias = sql.match(/AS ("(?:[^"]|"")*")/)[1];
  assert.equal(alias.slice(1, -1).split('"').length % 2, 1);
});

test("__proto__ in a parsed ast is refused outright", () => {
  // JSON.parse makes this an ordinary own property, so the verb allowlist sees
  // it and rejects the whole AST. Stronger than the previous behaviour, which
  // compiled the query and merely happened not to pollute anything.
  const ast = JSON.parse('{"from":"matchups","__proto__":{"polluted":true}}');
  assert.throws(() => compileAst(ast, schema), /unsupported verb: __proto__/);
  assert.equal({}.polluted, undefined);
});

test("a verb the compiler does not implement is refused, not ignored", () => {
  // Silently dropping these made a shared link mean something other than what
  // it said: `offset: 100` returned page one, `type: "left"` inner-joined.
  assert.throws(
    () => compileAst({ from: "matchups", offset: 100 }, schema),
    /unsupported verb: offset/,
  );
  assert.throws(
    () => compileAst({ from: "matchups", distinct: true }, schema),
    /unsupported verb: distinct/,
  );
  assert.throws(
    () => compileAst(
      { from: "matchups", join: { table: "team_seasons", on: ["year"], type: "left" } },
      schema,
    ),
    /unsupported join option: type/,
  );
});

test("every verb the builder writes is accepted", () => {
  // The UI's full AST shape, so tightening the verb list above cannot lock the
  // builder out of its own compiler.
  const { sql } = compileAst(
    {
      from: "matchups",
      join: { table: "team_seasons", on: ["year", "owner"] },
      filter: [{ field: "phase", op: "=", value: "regular" }],
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "score", as: "total" }],
      having: [{ field: "total", op: ">", value: 0 }],
      arrange: [{ field: "total", dir: "desc" }],
      limit: 25,
    },
    schema,
  );
  assert.match(sql, /LIMIT 25/);
});

test("arrange takes more than one key", () => {
  const { sql } = compileAst(
    {
      from: "matchups",
      arrange: [{ field: "year", dir: "desc" }, { field: "margin", dir: "asc" }],
    },
    schema,
  );
  assert.match(sql, /ORDER BY "year" DESC, "margin" ASC/);
});
