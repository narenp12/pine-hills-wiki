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

function columnsOf(schema, table) {
  const entry = schema.tables[table];
  if (!entry) throw new Error(`unknown table: ${table}`);
  return entry.columns.map((c) => c.name);
}

function resolveColumn(schema, ast, field, extraNames = []) {
  const known = new Set(columnsOf(schema, ast.from));
  if (ast.join) for (const name of columnsOf(schema, ast.join.table)) known.add(name);
  for (const name of extraNames) known.add(name);
  if (!known.has(field)) throw new Error(`unknown column: ${field}`);
  return quote(field);
}

function compilePredicates(schema, ast, clauses, params, extraNames) {
  return clauses.map((clause) => {
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
      const [low, high] = clause.value;
      params.push(low, high);
      return `${column} BETWEEN ? AND ?`;
    }
    if (NO_VALUE.has(clause.op)) return build(column);
    params.push(clause.op === "contains" ? `%${clause.value}%` : clause.value);
    return build(column);
  });
}

export function compileAst(ast, schema) {
  if (!ast || typeof ast !== "object") throw new Error("ast must be an object");
  for (const verb of ["filter", "having", "groupBy", "arrange"]) {
    if (ast[verb] !== undefined && !Array.isArray(ast[verb])) {
      throw new Error(`${verb} must be an array`);
    }
  }
  const params = [];
  const from = quote(ast.from);
  columnsOf(schema, ast.from);

  const summarise = ast.summarise ?? [];
  const groupBy = ast.groupBy ?? [];
  const aliases = summarise.map((s) => s.as);

  let select = "*";
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

  const arrange = (ast.arrange ?? []).map((spec) => {
    const column = resolveColumn(schema, ast, spec.field, aliases);
    return `${column} ${spec.dir === "asc" ? "ASC" : "DESC"}`;
  });
  if (arrange.length) parts.push(`ORDER BY ${arrange.join(", ")}`);

  const limit = Math.min(Math.max(Math.trunc(Number(ast.limit)) || 200, 1), MAX_LIMIT);
  parts.push(`LIMIT ${limit}`);

  return { sql: parts.join("\n"), params };
}

export function renderSql(sql, params) {
  let index = 0;
  return sql.replaceAll("?", () => {
    const value = params[index++];
    return typeof value === "string" ? `'${value.replaceAll("'", "''")}'` : String(value);
  });
}
