// Compile a Stat Search AST into parameterized DuckDB SQL.
//
// Pure: no DOM, no DuckDB, no network, no imports. That is what lets the
// node:test suite load it directly, and it is why every identifier must be
// validated against the schema rather than trusted from the AST.

export const MAX_LIMIT = 5000;

const OPERATORS = {
  "=": (col) => `${col} = ?`,
  "!=": (col) => `${col} != ?`,
  "<": (col) => `${col} < ?`,
  "<=": (col) => `${col} <= ?`,
  ">": (col) => `${col} > ?`,
  ">=": (col) => `${col} >= ?`,
  contains: (col) => `${col} ILIKE ?`,
  is_null: (col) => `${col} IS NULL`,
};

const AGGREGATES = {
  count: (col) => (col ? `count(${col})` : "count(*)"),
  count_distinct: (col) => `count(DISTINCT ${col})`,
  sum: (col) => `sum(${col})`,
  avg: (col) => `avg(${col})`,
  min: (col) => `min(${col})`,
  max: (col) => `max(${col})`,
  median: (col) => `median(${col})`,
  stddev: (col) => `stddev(${col})`,
};

const MULTI_VALUE = new Set(["in", "not_in"]);
const NO_VALUE = new Set(["is_null"]);

function quote(identifier) {
  return `"${String(identifier).replaceAll('"', '""')}"`;
}

// Table names are coerced to a primitive string ONCE, here, and every later use
// is of the returned value. Reading `ast.from` twice let an object with a
// toString() pass `columnsOf`'s lookup on the first call and emit something
// else on the second, because both the lookup and `quote()` coerce
// independently. A `?q=` link cannot deliver a live object today (it arrives
// through JSON.parse), but the compiler is the only thing between an untrusted
// AST and the SQL text, so it does not rely on that.
function tableName(value) {
  if (typeof value !== "string") throw new Error(`unknown table: ${String(value)}`);
  return value;
}

function columnsOf(schema, table) {
  const entry = Object.hasOwn(schema.tables, table) ? schema.tables[table] : null;
  if (!entry) throw new Error(`unknown table: ${table}`);
  return entry.columns.map((c) => c.name);
}

function resolveColumn(schema, ast, field, extraNames = []) {
  const fromColumns = columnsOf(schema, ast.from);
  const known = new Set(fromColumns);
  if (ast.join) for (const name of columnsOf(schema, ast.join.table)) known.add(name);
  for (const name of extraNames) known.add(name);
  if (!known.has(field)) throw new Error(`unknown column: ${field}`);
  // In a join, a bare name that both tables carry is ambiguous and DuckDB
  // rejects the statement. An alias from `summarise` is never qualified: it
  // belongs to the select list, not to either table.
  if (ast.join && !extraNames.includes(field)) {
    const table = fromColumns.includes(field) ? ast.from : ast.join.table;
    return `${quote(table)}.${quote(field)}`;
  }
  return quote(field);
}

// The select list for a join. `SELECT *` across two tables emits every column
// of both, so a join of player_weeks to awards came back with 23 columns of
// which 10 shared a name -- `year`, `player`, `points` and the rest twice over.
// Arrow hands those to the UI as one object per row, so the duplicates
// collapsed into each other and the table silently showed one table's value
// under the other's heading. Overlapping names from the joined side are
// prefixed with their table instead; the join keys are equal by definition, so
// the joined side's copy is dropped rather than aliased.
function joinedSelect(schema, ast) {
  const fromColumns = columnsOf(schema, ast.from);
  const joinColumns = columnsOf(schema, ast.join.table);
  const keys = new Set(ast.join.on ?? []);
  const overlap = new Set(fromColumns);
  return [
    ...fromColumns.map((name) => `${quote(ast.from)}.${quote(name)}`),
    ...joinColumns
      .filter((name) => !keys.has(name))
      .map((name) =>
        overlap.has(name)
          ? `${quote(ast.join.table)}.${quote(name)} AS ` +
            `${quote(`${ast.join.table}_${name}`)}`
          : `${quote(ast.join.table)}.${quote(name)}`,
      ),
  ].join(", ");
}

function compilePredicates(schema, ast, clauses, params, extraNames) {
  return clauses.map((clause) => {
    // Checked before any property is read. A `?q=` link carrying a null or a
    // string here used to surface as "Cannot read properties of null (reading
    // 'op')" in the reader's results panel: an internal TypeError shown where a
    // sentence about their query belongs.
    if (!clause || typeof clause !== "object" || Array.isArray(clause)) {
      throw new Error("each filter must be an object");
    }
    const build = OPERATORS[clause.op];
    if (!build && !MULTI_VALUE.has(clause.op) && clause.op !== "between") {
      throw new Error(`unknown operator: ${clause.op}`);
    }
    const column = resolveColumn(schema, ast, clause.field, extraNames);
    if (MULTI_VALUE.has(clause.op)) {
      const values = Array.isArray(clause.value) ? clause.value : [clause.value];
      if (values.length === 0) throw new Error(`empty value list for ${clause.field}`);
      params.push(...values);
      const holes = values.map(() => "?").join(", ");
      return clause.op === "in" ? `${column} IN (${holes})` : `${column} NOT IN (${holes})`;
    }
    if (clause.op === "between") {
      // Exactly two, checked. `value: [1]` used to bind `undefined` as the
      // upper bound, and `value: 5` threw "number 5 is not iterable" from the
      // destructuring rather than saying what was wrong.
      if (!Array.isArray(clause.value) || clause.value.length !== 2) {
        throw new Error(`between needs two values for ${clause.field}`);
      }
      const [low, high] = clause.value;
      params.push(low, high);
      return `${column} BETWEEN ? AND ?`;
    }
    if (NO_VALUE.has(clause.op)) return build(column);
    params.push(clause.op === "contains" ? `%${clause.value}%` : clause.value);
    return build(column);
  });
}

// Exactly the verbs this compiler implements. Anything else is refused rather
// than dropped: an AST asking for `offset: 100`, a `left` join or a second join
// used to compile to a statement that quietly did none of those, so a shared
// `?q=` link could mean something other than what it said. Refusing is the only
// answer that cannot mislead.
const VERBS = new Set([
  "from",
  "join",
  "filter",
  "groupBy",
  "summarise",
  "having",
  "arrange",
  "limit",
]);

const JOIN_KEYS = new Set(["table", "on"]);

export function compileAst(ast, schema) {
  if (!ast || typeof ast !== "object" || Array.isArray(ast)) {
    throw new Error("ast must be an object");
  }
  for (const verb of Object.keys(ast)) {
    if (!VERBS.has(verb)) throw new Error(`unsupported verb: ${verb}`);
  }
  for (const verb of ["filter", "having", "groupBy", "arrange", "summarise"]) {
    if (ast[verb] !== undefined && !Array.isArray(ast[verb])) {
      throw new Error(`${verb} must be an array`);
    }
  }
  // Normalized once, up front, and used everywhere below in place of the raw
  // AST values. See tableName.
  ast = { ...ast, from: tableName(ast.from) };
  if (ast.join) {
    if (typeof ast.join !== "object" || Array.isArray(ast.join)) {
      throw new Error("join must be an object");
    }
    for (const key of Object.keys(ast.join)) {
      // `type: "left"` compiled to an inner join in silence.
      if (!JOIN_KEYS.has(key)) throw new Error(`unsupported join option: ${key}`);
    }
    ast.join = { ...ast.join, table: tableName(ast.join.table) };
  }
  const params = [];
  const from = quote(ast.from);
  columnsOf(schema, ast.from);

  const summarise = ast.summarise ?? [];
  const groupBy = ast.groupBy ?? [];
  const aliases = summarise.map((s) => s.as);

  let select = ast.join ? joinedSelect(schema, ast) : "*";
  if (groupBy.length || summarise.length) {
    const grouped = groupBy.map((field) => resolveColumn(schema, ast, field));
    const aggregated = summarise.map((spec) => {
      const build = AGGREGATES[spec.fn];
      if (!build) throw new Error(`unknown aggregate: ${spec.fn}`);
      const inner = spec.field ? resolveColumn(schema, ast, spec.field) : null;
      if (!spec.as) throw new Error(`aggregate ${spec.fn} needs an alias`);
      return `${build(inner)} AS ${quote(spec.as)}`;
    });
    select = [...grouped, ...aggregated].join(", ");
  }

  const parts = [`SELECT ${select}`, `FROM ${from}`];

  if (ast.join) {
    const joinTable = quote(ast.join.table);
    columnsOf(schema, ast.join.table);
    const fromColumns = new Set(columnsOf(schema, ast.from));
    const joinColumns = new Set(columnsOf(schema, ast.join.table));
    const conditions = (ast.join.on ?? []).map((field) => {
      if (!fromColumns.has(field) || !joinColumns.has(field)) {
        throw new Error(`unknown column: ${field}`);
      }
      resolveColumn(schema, ast, field);
      return `${from}.${quote(field)} = ${joinTable}.${quote(field)}`;
    });
    if (!conditions.length) throw new Error("join needs at least one column");
    parts.push(`JOIN ${joinTable} ON ${conditions.join(" AND ")}`);
  }

  const where = compilePredicates(schema, ast, ast.filter ?? [], params, []);
  if (where.length) parts.push(`WHERE ${where.join(" AND ")}`);

  if (groupBy.length) {
    parts.push(`GROUP BY ${groupBy.map((f) => resolveColumn(schema, ast, f)).join(", ")}`);
  }

  const having = compilePredicates(schema, ast, ast.having ?? [], params, aliases);
  if (having.length) parts.push(`HAVING ${having.join(" AND ")}`);

  // Everything the row count is measured over: the same FROM, WHERE, GROUP BY
  // and HAVING, and none of the ORDER BY or LIMIT. Captured here rather than
  // rebuilt so the count can never be taken over a different query than the
  // rows -- "200 of 1,320" is a claim about this query, and a second builder
  // would be a second chance for it to be a claim about another one.
  const body = parts.join("\n");

  const arrange = (ast.arrange ?? []).map((spec) => {
    const column = resolveColumn(schema, ast, spec.field, aliases);
    return `${column} ${spec.dir === "asc" ? "ASC" : "DESC"}`;
  });
  if (arrange.length) parts.push(`ORDER BY ${arrange.join(", ")}`);

  const limit = Math.min(Math.max(Math.trunc(Number(ast.limit)) || 200, 1), MAX_LIMIT);
  parts.push(`LIMIT ${limit}`);

  // Wrapped rather than a bare `count(*)` with the WHERE spliced in, because a
  // grouped query's row count is its number of GROUPS, which only the subquery
  // reports. The parameters are the same list in the same order, so the caller
  // binds `params` to either statement.
  return {
    sql: parts.join("\n"),
    countSql: `SELECT count(*) AS "n" FROM (\n${body}\n)`,
    params,
    limit,
  };
}

export function renderSql(sql, params) {
  let index = 0;
  return sql.replaceAll("?", () => {
    const value = params[index++];
    return typeof value === "string" ? `'${value.replaceAll("'", "''")}'` : String(value);
  });
}
