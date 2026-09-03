// DuckDB-WASM boot and query execution for Stat Search.
//
// The version is pinned exactly. The `latest` dist-tag on @duckdb/duckdb-wasm
// currently points at a -dev prerelease, so a range here would ship a
// prerelease engine to readers.
//
// The `eh` bundle is deliberate: the threaded `coi` bundle needs
// cross-origin-isolation response headers, which GitHub Pages cannot set.

const VERSION = "1.32.0";
const DIST = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${VERSION}/dist`;
const ESM = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${VERSION}/+esm`;
// The `+esm` bundle is deliberate: jsDelivr rewrites the bare `apache-arrow`
// and `flatbuffers` specifiers to absolute `/npm/.../+esm` URLs. Importing
// `dist/duckdb-browser.mjs` directly leaves those bare specifiers unresolved
// and the browser throws `Failed to resolve module specifier "flatbuffers"`.
// The wasm and worker still come from `dist/` (same version).

let bootPromise = null;

// The reader below yields DECODED bytes, while `content-length` reports the
// ENCODED transfer size. jsDelivr serves the wasm with `content-encoding: br`
// (6.7 MB on the wire, 34.2 MB decoded), so dividing one by the other ran the
// bar to 506% and pinned it full from a fifth of the way in. There is no header
// carrying the decoded size, so a compressed response reports bytes and no
// fraction, and the caller shows an indeterminate bar instead of a wrong one.
async function fetchWithProgress(url, onProgress) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} fetching ${url}`);
  const encoded = response.headers.get("content-encoding");
  const total = encoded ? 0 : Number(response.headers.get("content-length")) || 0;
  if (!response.body) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(total ? loaded / total : null, loaded);
  }
  const merged = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged.buffer;
}

async function boot(base, onProgress) {
  const duckdb = await import(ESM);
  const wasm = await fetchWithProgress(`${DIST}/duckdb-eh.wasm`, onProgress);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${DIST}/duckdb-browser-eh.worker.js");`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(workerUrl);
  try {
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(URL.createObjectURL(new Blob([wasm], { type: "application/wasm" })));
    URL.revokeObjectURL(workerUrl);

    const connection = await db.connect();
    const response = await fetch(`${base}schema.json`);
    if (!response.ok) throw new Error(`${response.status} fetching ${base}schema.json`);
    const schema = await response.json();
    for (const table of Object.keys(schema.tables)) {
      const url = new URL(`${base}${table}.parquet`, window.location.href).href;
      const safeTable = table.replaceAll('"', '""');
      const safeUrl = url.replaceAll("'", "''");
      await connection.query(
        `CREATE VIEW "${safeTable}" AS SELECT * FROM read_parquet('${safeUrl}')`,
      );
    }
    return { db, connection, schema };
  } catch (error) {
    try {
      worker.terminate();
    } catch {
      // Ignore termination errors on the failure path.
    }
    URL.revokeObjectURL(workerUrl);
    throw error;
  }
}

export function startEngine(base, onProgress = () => {}) {
  if (!bootPromise) {
    bootPromise = boot(base, onProgress).catch((error) => {
      bootPromise = null; // let a later attempt retry rather than caching failure
      throw error;
    });
  }
  return bootPromise;
}

// Autocomplete for the columns schema.json carries no enum for -- `player` and
// `team`, mostly, whose value lists are too long and too churn-prone to ship in
// a static file. The engine is already loaded and the parquet already local, so
// the distinct list costs one scan of one column.
//
// The identifiers are the caller's, so both are checked against the live schema
// before they reach the SQL text: this is the one query the compiler does not
// build, and an unchecked column name here would be the whole injection surface
// the compiler exists to close.
export async function distinctValues(base, table, column, limit = 2000) {
  const { connection, schema } = await startEngine(base);
  const entry = schema.tables[table];
  if (!entry) throw new Error(`unknown table: ${table}`);
  if (!entry.columns.some((candidate) => candidate.name === column)) {
    throw new Error(`unknown column: ${column}`);
  }
  const safeTable = table.replaceAll('"', '""');
  const safeColumn = column.replaceAll('"', '""');
  const result = await connection.query(
    `SELECT DISTINCT "${safeColumn}" AS value FROM "${safeTable}" ` +
      `WHERE "${safeColumn}" IS NOT NULL AND CAST("${safeColumn}" AS VARCHAR) <> '' ` +
      `ORDER BY 1 LIMIT ${Math.trunc(limit)}`,
  );
  return result.toArray().map((row) => String(row.toJSON().value));
}

export async function runSql(base, sql, params) {
  const { connection } = await startEngine(base);
  const statement = await connection.prepare(sql);
  try {
    const table = await statement.query(...params);
    const columns = table.schema.fields.map((field) => field.name);
    const rows = table.toArray().map((row) => {
      const record = row.toJSON();
      // Arrow returns BigInt for 64-bit integers; JSON and sorting want Number.
      for (const key of Object.keys(record)) {
        if (typeof record[key] === "bigint") record[key] = Number(record[key]);
      }
      return record;
    });
    return { columns, rows };
  } finally {
    await statement.close();
  }
}
