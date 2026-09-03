// The builder half of Stat Search: which columns each control offers, and what
// happens to the verb stack when the shape of the query changes underneath it.
//
// The compiler has had tests since it was written; this file did not exist, and
// that is exactly where the join-removal wedge shipped from -- an AST the
// builder could reach but no test ever built. Everything here runs without a
// DOM: these methods read `schema`, `ast` and `types` and touch nothing else,
// so instances are made with Object.create rather than the constructor, which
// needs `window`.

import assert from "node:assert/strict";
import { test } from "node:test";
import { StatSearch, formatCell, kindOf } from "../../zensical/docs/javascripts/query.js";

const schema = {
  tables: {
    player_weeks: {
      columns: [
        { name: "year", type: "INTEGER" },
        { name: "week", type: "INTEGER" },
        { name: "owner", type: "VARCHAR" },
        { name: "team", type: "VARCHAR" },
        { name: "player", type: "VARCHAR" },
        { name: "position", type: "VARCHAR" },
        { name: "started", type: "BOOLEAN" },
        { name: "points", type: "DOUBLE" },
      ],
    },
    awards: {
      columns: [
        { name: "year", type: "INTEGER" },
        { name: "award", type: "VARCHAR" },
        { name: "player", type: "VARCHAR" },
        { name: "owner", type: "VARCHAR" },
        { name: "wins_swung", type: "INTEGER" },
      ],
    },
    // Shares no join key at all with player_weeks: nothing here can be joined
    // on, so it must never appear in the "Combine with" menu.
    weather: {
      columns: [
        { name: "stadium", type: "VARCHAR" },
        { name: "degrees", type: "DOUBLE" },
      ],
    },
  },
};

function builder(ast) {
  const self = Object.create(StatSearch.prototype);
  self.schema = schema;
  self.ast = ast;
  self.types = new Map();
  for (const [table, entry] of Object.entries(schema.tables)) {
    for (const column of entry.columns) {
      self.types.set(`${table}.${column.name}`, column.type);
    }
  }
  return self;
}

const joined = () => ({
  from: "player_weeks",
  join: { table: "awards", on: ["player", "year"] },
});

// --- which columns the controls offer ------------------------------------

test("without a join the controls offer the driving table's columns", () => {
  const self = builder({ from: "player_weeks" });
  assert.deepEqual(self.availableColumns(), [
    "year", "week", "owner", "team", "player", "position", "started", "points",
  ]);
});

test("a join adds the columns it brings in, and adds each name once", () => {
  const columns = builder(joined()).availableColumns();
  assert.ok(columns.includes("award"), "join-only column is offered");
  assert.ok(columns.includes("wins_swung"), "join-only column is offered");
  // `year`, `player` and `owner` are on both sides.
  assert.equal(new Set(columns).size, columns.length, "no duplicates");
  assert.equal(columns.filter((name) => name === "year").length, 1);
});

test("a name both tables carry resolves to the driving table", () => {
  // Matches how the compiler qualifies it. Resolving `year` to `awards` here
  // would type and enum it off the wrong table.
  const self = builder(joined());
  assert.equal(self.tableOf("year"), "player_weeks");
  assert.equal(self.tableOf("player"), "player_weeks");
  assert.equal(self.tableOf("award"), "awards");
  assert.equal(self.tableOf("wins_swung"), "awards");
});

test("column kind is read from the table the column belongs to", () => {
  const self = builder(joined());
  assert.equal(self.kindFor("points"), "numeric");
  assert.equal(self.kindFor("started"), "boolean");
  assert.equal(self.kindFor("award"), "text");
  assert.equal(self.kindFor("wins_swung"), "numeric");
});

test("an unknown column falls back to the driving table rather than throwing", () => {
  const self = builder({ from: "player_weeks" });
  assert.equal(self.tableOf("nonexistent"), "player_weeks");
});

// --- join keys ------------------------------------------------------------

test("join keys rank an entity column first, then a time column", () => {
  const self = builder({ from: "player_weeks" });
  assert.deepEqual(self.defaultJoinKeys(["year", "player", "week"]), ["player", "year"]);
});

test("sharing no join key yields none, rather than a guess", () => {
  // A guess landing on a measure joins on a number that means something
  // different on each side and matches nothing -- zero rows, no error.
  const self = builder({ from: "player_weeks" });
  assert.deepEqual(self.defaultJoinKeys(["points", "degrees"]), []);
  assert.deepEqual(self.defaultJoinKeys([]), []);
});

test("at most one entity key and one time key are taken", () => {
  // Not every shared key: `player` AND `owner` AND `team` would join on three
  // equalities that are already implied by the first.
  const self = builder({ from: "player_weeks" });
  assert.deepEqual(
    self.defaultJoinKeys(["owner", "team", "player", "year", "week"]),
    ["player", "year"],
  );
});

test("with no entity column shared, only the time key is taken", () => {
  // Pinning current behaviour. No pair of shipped tables reaches this: every
  // join the menu offers has an entity key, checked against schema.json.
  const self = builder({ from: "player_weeks" });
  assert.deepEqual(self.defaultJoinKeys(["year", "week"]), ["year"]);
});

test("a table with no usable join key is not offered", () => {
  const targets = builder({ from: "player_weeks" }).joinTargets();
  const tables = targets.map((entry) => entry.table);
  assert.ok(tables.includes("awards"));
  assert.ok(!tables.includes("weather"), "shares no join key, so nothing to join on");
});

// --- sort menu ------------------------------------------------------------

test("an ungrouped query can sort by any available column", () => {
  assert.deepEqual(
    builder(joined()).sortOptions(),
    builder(joined()).availableColumns(),
  );
});

test("a grouped query sorts only by grouping columns and aggregate aliases", () => {
  const self = builder({
    from: "player_weeks",
    groupBy: ["owner"],
    summarise: [{ fn: "sum", field: "points", as: "total" }],
  });
  // The full column list would offer keys the SQL rejects.
  assert.deepEqual(self.sortOptions(), ["owner", "total"]);
});

// --- dropping a join must not wedge the builder ---------------------------

test("dropping a join removes the verbs that named its columns", () => {
  // The regression this file exists for. Before the fix these clauses survived
  // the join going away, every later compile threw `unknown column: award`,
  // and the offending menu no longer listed the value it was holding -- so the
  // reader had no way to see which control to fix.
  const self = builder({
    from: "player_weeks",
    filter: [
      { field: "award", op: "=", value: "Most Valuable Player" },
      { field: "points", op: ">", value: "10" },
    ],
    groupBy: ["award", "owner"],
    summarise: [
      { fn: "sum", field: "wins_swung", as: "swung" },
      { fn: "sum", field: "points", as: "scored" },
    ],
    having: [{ field: "swung", op: ">", value: "1" }],
  });
  self.dropMissingColumns();

  assert.deepEqual(self.ast.filter, [{ field: "points", op: ">", value: "10" }]);
  assert.deepEqual(self.ast.groupBy, ["owner"]);
  assert.deepEqual(self.ast.summarise, [{ fn: "sum", field: "points", as: "scored" }]);
  // `swung` went with the summary that defined it.
  assert.deepEqual(self.ast.having, []);
});

test("a join still in place keeps the verbs that name its columns", () => {
  const self = builder({
    ...joined(),
    filter: [{ field: "award", op: "=", value: "Most Valuable Player" }],
    groupBy: ["award"],
    summarise: [{ fn: "sum", field: "wins_swung", as: "swung" }],
    having: [{ field: "swung", op: ">", value: "1" }],
  });
  self.dropMissingColumns();

  assert.equal(self.ast.filter.length, 1);
  assert.deepEqual(self.ast.groupBy, ["award"]);
  assert.equal(self.ast.summarise.length, 1);
  assert.equal(self.ast.having.length, 1);
});

test("a HAVING clause on a surviving alias is kept", () => {
  const self = builder({
    from: "player_weeks",
    summarise: [{ fn: "sum", field: "points", as: "scored" }],
    having: [{ field: "scored", op: ">", value: "100" }],
  });
  self.dropMissingColumns();
  assert.deepEqual(self.ast.having, [{ field: "scored", op: ">", value: "100" }]);
});

test("a count with no column survives, having no column to lose", () => {
  const self = builder({
    from: "player_weeks",
    summarise: [{ fn: "count", as: "rows" }],
  });
  self.dropMissingColumns();
  assert.deepEqual(self.ast.summarise, [{ fn: "count", as: "rows" }]);
});

test("dropping columns on an empty verb stack yields empty arrays, not undefined", () => {
  const self = builder({ from: "player_weeks" });
  self.dropMissingColumns();
  assert.deepEqual(self.ast.filter, []);
  assert.deepEqual(self.ast.groupBy, []);
  assert.deepEqual(self.ast.summarise, []);
  assert.deepEqual(self.ast.having, []);
});

// --- empty columns are not rendered ---------------------------------------

test("a column that is null in every row is dropped from the table", () => {
  const rows = [
    { year: 2024, round: null, points: 10 },
    { year: 2025, round: null, points: 20 },
  ];
  assert.deepEqual(
    StatSearch.nonEmpty(["year", "round", "points"], rows),
    ["year", "points"],
  );
});

test("one value anywhere in the page keeps the column", () => {
  const rows = [
    { year: 2024, round: null },
    { year: 2025, round: "Final" },
  ];
  assert.deepEqual(StatSearch.nonEmpty(["year", "round"], rows), ["year", "round"]);
});

test("undefined and empty string count as empty, but zero and false do not", () => {
  const rows = [{ a: undefined, b: "", c: 0, d: false }];
  assert.deepEqual(StatSearch.nonEmpty(["a", "b", "c", "d"], rows), ["c", "d"]);
});

test("an all-empty page renders its columns rather than no table at all", () => {
  // A grouped count over an all-null column is a legitimate empty result.
  const rows = [{ a: null, b: null }];
  assert.deepEqual(StatSearch.nonEmpty(["a", "b"], rows), ["a", "b"]);
});

// --- cell and type formatting ---------------------------------------------

test("cells format numbers, booleans and blanks for reading", () => {
  assert.equal(formatCell(1.5), "1.50");
  assert.equal(formatCell(12), "12");
  assert.equal(formatCell(true), "yes");
  assert.equal(formatCell(false), "no");
  assert.equal(formatCell(null), "");
  assert.equal(formatCell(undefined), "");
});

test("column kinds come from the declared SQL type", () => {
  assert.equal(kindOf("BOOLEAN"), "boolean");
  assert.equal(kindOf("INTEGER"), "numeric");
  assert.equal(kindOf("DOUBLE"), "numeric");
  assert.equal(kindOf("HUGEINT"), "numeric");
  assert.equal(kindOf("DECIMAL(10,2)"), "numeric");
  assert.equal(kindOf("VARCHAR"), "text");
  assert.equal(kindOf(undefined), "text");
});
