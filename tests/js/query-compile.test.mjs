import assert from "node:assert/strict";
import { test } from "node:test";
import { compileAst, MAX_LIMIT } from "../../zensical/docs/javascripts/query-compile.js";

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
