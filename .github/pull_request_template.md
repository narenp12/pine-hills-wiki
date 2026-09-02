<!--
Name the pull request with a Conventional Commits prefix, e.g.
"feat: add per-position playoff highs":

  feat      new capability on the site or in the generator
  fix       corrects wrong output or a broken build
  docs      README, CONTRIBUTING, comments
  style     formatting only, no change to generated output
  refactor  restructures code without changing output
  perf      faster build or smaller output
  test      adds or reworks tests only
  chore     dependencies, tooling, CI

Then describe the change below. Screenshots help for anything visual.
-->

## What this changes

<!-- One or two sentences. -->

## Checklist

- [ ] `uv run pytest -q` passes.
- [ ] `node zensical/build.mjs` runs clean, with no new warnings on stderr.
- [ ] Regenerated `zensical/docs/` is committed alongside any change to `raw/`
      or `scripts/`, so CI's rebuild produces no diff.
- [ ] Prose follows the house style in CONTRIBUTING: encyclopedic, plain ASCII
      hyphens, nothing fabricated.
