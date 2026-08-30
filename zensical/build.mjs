#!/usr/bin/env node
// Build the Zensical edition of the Pine Hills wiki.
//
// Pipeline:
//   1. scripts/generate.py  (WIKI_CONTENT_DIR -> zensical/.stage)  generates Markdown
//   2. zensical/transform.py  resolves [[wikilinks]] -> zensical/docs
//   3. zensical build --clean  -> zensical/site
//
// The hand-authored skin (zensical/docs/stylesheets, zensical/docs/javascripts)
// and zensical/docs/index.md are committed in git and are NOT regenerated.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stage = resolve(root, "zensical", ".stage");
const venv = resolve(root, ".venv");

function py() {
  // Prefer the repo's .venv; fall back to system python3.
  return process.env.VIRTUAL_ENV ? process.env.VIRTUAL_ENV + "/bin/python" : "python3";
}

console.log("[build] 1/3 generate.py ->", stage);
execFileSync(py(), ["scripts/generate.py"], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, WIKI_CONTENT_DIR: stage },
});

console.log("[build] 2/3 transform.py -> zensical/docs");
execFileSync(py(), ["zensical/transform.py"], {
  cwd: root,
  stdio: "inherit",
});

console.log("[build] 3/3 zensical build --clean -> zensical/site");
execFileSync("zensical", ["build", "--clean"], {
  cwd: resolve(root, "zensical"),
  stdio: "inherit",
});
console.log("[build] done.");
