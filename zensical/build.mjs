#!/usr/bin/env node
// Build the Zensical edition of the Pine Hills wiki.
//
// Pipeline (when raw/ JSON is present — local dev with fresh data):
//   1. scripts/generate.py  (WIKI_CONTENT_DIR -> zensical/.stage)  generates Markdown
//   2. zensical/transform.py  resolves [[wikilinks]] -> zensical/docs
//   3. zensical build --clean  -> zensical/site
//
// When raw/ is absent (CI: raw/*.json is gitignored, but the generated
// zensical/docs/*.md are committed), skip steps 1-2 and build directly from
// the committed Markdown. This keeps the deploy hermetic.
//
// The hand-authored skin (zensical/docs/stylesheets, zensical/docs/javascripts)
// and zensical/docs/index.md are committed in git and are NOT regenerated.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { existsSync, readdirSync } from "node:fs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stage = resolve(root, "zensical", ".stage");
const raw = resolve(root, "raw");

function py() {
  return process.env.VIRTUAL_ENV ? process.env.VIRTUAL_ENV + "/bin/python" : "python3";
}

function rawHasData() {
  try {
    return readdirSync(raw).some((f) => f.endsWith(".json"));
  } catch {
    return false;
  }
}

if (rawHasData()) {
  console.log("[build] 1/3 generate.py ->", stage);
  execFileSync(py(), ["scripts/generate.py"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, WIKI_CONTENT_DIR: stage },
  });
  console.log("[build] 2/3 transform.py -> zensical/docs");
  execFileSync(py(), ["zensical/transform.py"], { cwd: root, stdio: "inherit" });
} else {
  console.log("[build] raw/ has no JSON (CI) — building from committed zensical/docs");
}

console.log("[build] zensical build --clean -> zensical/site");
execFileSync("zensical", ["build", "--clean"], {
  cwd: resolve(root, "zensical"),
  stdio: "inherit",
});
console.log("[build] done.");
