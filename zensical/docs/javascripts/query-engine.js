// DuckDB-WASM boot and query execution for Stat Search.
//
// The version is pinned exactly. The `latest` dist-tag on @duckdb/duckdb-wasm
// currently points at a -dev prerelease, so a range here would ship a
// prerelease engine to readers.
//
// The `eh` bundle is deliberate: the threaded `coi` bundle needs
// cross-origin-isolation response headers, which GitHub Pages cannot set.

const VERSION = "1.32.0";
const CDN = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${VERSION}/dist`;

let bootPromise = null;

async function fetchWithProgress(url, onProgress) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} fetching ${url}`);
  const total = Number(response.headers.get("content-length")) || 0;
  if (!response.body || !total) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(loaded / total);
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
  const duckdb = await import(`${CDN}/duckdb-browser.mjs`);
  const wasm = await fetchWithProgress(`${CDN}/duckdb-eh.wasm`, onProgress);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${CDN}/duckdb-browser-eh.worker.js");`], {
      type: "text/javascript",
    }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(URL.createObjectURL(new Blob([wasm], { type: "application/wasm" })));
  URL.revokeObjectURL(workerUrl);

  const connection = await db.connect();
  const schema = await (await fetch(`${base}schema.json`)).json();
  for (const table of Object.keys(schema.tables)) {
    const url = new URL(`${base}${table}.parquet`, window.location.href).href;
    await connection.query(
      `CREATE VIEW "${table}" AS SELECT * FROM read_parquet('${url}')`,
    );
  }
  return { db, connection, schema };
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
