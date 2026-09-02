#!/usr/bin/env node
// Build the Zensical edition of the Pine Hills wiki.
//
// Run with node, not python: `node zensical/build.mjs`.
//
// Pipeline (when raw/ JSON is present - the normal case, local and CI):
//   1. scripts/generate.py  (WIKI_CONTENT_DIR -> zensical/.stage)  generates Markdown
//   2. zensical/transform.py  resolves [[wikilinks]] -> zensical/docs
//   3. zensical build --clean  -> zensical/site
//
// raw/*.json and raw/bible.yaml are committed, so CI takes that same path and
// regenerates zensical/docs on every build. Editing a generated page by hand
// does not survive: change raw/ instead.
//
// The fallback below (skip steps 1-2, build from the committed Markdown) only
// fires in a checkout with no JSON in raw/ at all.
//
// The hand-authored skin (zensical/docs/stylesheets, zensical/docs/javascripts)
// and zensical/docs/index.md are committed in git and are NOT regenerated.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { readdirSync } from "node:fs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stage = resolve(root, "zensical", ".stage");
const raw = resolve(root, "raw");

// Everything Python-side runs through uv so deps resolve from uv.lock.
// execFileSync takes (file, args) - passing an array as `file` throws
// TypeError, so the command and its arguments are kept separate here.
const HAS_UV = (() => {
  try {
    execFileSync("uv", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

if (!HAS_UV) {
  console.error(
    "[build] uv not found. Install it (https://docs.astral.sh/uv/) - the build " +
      "resolves Python and the zensical binary through `uv run`.",
  );
  process.exit(1);
}

function uvRun(args, options = {}) {
  execFileSync("uv", ["run", ...args], { stdio: "inherit", ...options });
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
  uvRun(["python", "scripts/generate.py"], {
    cwd: root,
    env: { ...process.env, WIKI_CONTENT_DIR: stage },
  });
  console.log("[build] 2/3 transform.py -> zensical/docs");
  uvRun(["python", "zensical/transform.py"], { cwd: root });
} else {
  console.log("[build] raw/ has no JSON - building from committed zensical/docs");
}

console.log("[build] zensical build --clean -> zensical/site");
// cwd must be zensical/ so the CLI picks up zensical.toml; uv still discovers
// the project by walking up to the repo-root pyproject.toml.
uvRun(["zensical", "build", "--clean"], { cwd: resolve(root, "zensical") });
console.log("[build] done.");
