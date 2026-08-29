# Handoff — Pine Hills FF scraper (end of 2026-08-29 session)

## Where we are
We proved the data source and found the real Yahoo Fantasy API response shape.
The DOM-table approach (old `selectors.toml`) is **obsolete** — Yahoo renders from
a private JSON API, not `<table>` tags. The next build parses that JSON.

## Confirmed facts (evidence-backed)
- Standings/draft/matchups/rosters are fetched by the page as **JSON** (sometimes
  JSONP-wrapped: `callback({...})`). The data is NOT in the page HTML, not in a
  `<table>`, and not in an embedded `<script>` blob.
- The real payload: `dump/2016-standings.api.11.json` (captured live, 92 KB).
  Envelope (see `API_SHAPE.md` for full detail):
  ```
  service.leagues."447010".teams."<id>" → {
    id, name, rank, wins, losses, ties, pf, pa,
    managers: { "1": { id, nickName } },
    players: [ { id, position, ... }, ... ]
  }
  ```
- `pf` = points for, `pa` = points against. `managers.<n>.nickName` = owner.
  `players[]` = roster (slots empty pre-draft: `id:null`).
- **Gotcha that cost us time:** the data endpoint host does NOT contain
  "fantasy" or "yahoo" in the URL. First capture filtered URLs by those words and
  MISSED the payload. Capture ALL response bodies, match on the JSON envelope.

## What works
- `scraper/run-edge.sh` — one-command launch of Edge with remote debugging +
  `--remote-allow-origins=*`, waits for the port, prints the login URL.
- `scraper/scripts/capture_api.py` — CDP capture tool (uv-managed:
  `uv run --with websocket-client python3 scripts/capture_api.py <cdp> <url> <dir> <tag>`).
  Saves every response body whose URL matches `fantasy`/`yahoo` to `<dir>/<tag>.api.<n>.json`.
  This is the one that produced the 38 bodies including the real payload.
- `scraper/src/scrape.rs` --connect ws-endpoint fix (resolves `ws://` from
  `/json/version`) — committed earlier as cd30f87-adjacent; README + fix in tree.

## What does NOT work (do not rely on)
- `scraper/scripts/capture_all.py` — throwaway, saves 0 bodies (bug: getResponseBody
  result handler never matches). Left untracked on purpose. Replace logic by
  extending `capture_api.py` to drop the URL filter, OR bake capture into the Rust
  scraper (preferred — see below).
- The old `selectors.toml` `<table>` selectors — wrong for modern Yahoo.

## Next session (the actual build)
1. **Rebuild the Rust extractor** (`src/extract.rs`) to consume the JSON envelope
   in `API_SHAPE.md`, NOT DOM tables. Keep the `raw/<year>.json` contract so
   `scripts/generate.py` stays untouched.
2. **Add CDP response capture into the Rust scraper** (chromiumoxide):
   `Network.enable` → on `Network.loadingFinished` → `Network.getResponseBody`.
   One ban-safe Rust tool, zero extra requests, sequential. This retires the
   Python capture sidecar.
3. **Code-review pass** with skills: `systematic-debugging` → `requesting-code-review`
   → `simplify-code`, then a 1-season dry-run before the full 10-season run.
4. Validate against the captured `api.11.json` as a fixture, then live 2016.

## Environment to resume
- Edge running on `127.0.0.1:9222`, logged in, uBlock Origin Lite installed in the
  `.phf-edge` profile (cuts ad noise + fewer outbound requests = more ban-safe).
- League id `447010` (non-secret). Repo: `narenp12/pine-hills-wiki`, branch `main`.
- `uv` for Python tooling; `cargo` for the Rust scraper (`edition="2024"`).
