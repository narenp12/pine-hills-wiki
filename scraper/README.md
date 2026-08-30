# phf-scraper — Pine Hills FF Yahoo history scraper (Rust)

Free, **no Yahoo API key** required. It attaches to *your* already-logged-in
Chrome over the Chrome DevTools Protocol, renders each season's Yahoo pages,
parses the tables, and writes the canonical `raw/<year>.json` that
`scripts/generate.py` turns into the Quartz wiki.

> **Rust edition:** uses `edition = "2024"` (latest released edition as of
> 2026). There is **no "Rust 2026" edition** — the next one is planned for
> 2027. `edition = "2026"` would fail to build.

---

## 1. Build

```bash
cd scraper
cargo build --release
```

## 2. Get a Chrome you can log into (one-time)

You need *some* Chrome running with remote debugging enabled, and you must be
logged into Yahoo in it. Two options:

**Option A — your normal Google Chrome (easiest; reuses your saved Yahoo login).**
Quit Chrome, then relaunch it from Terminal with the debug port:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.phf-chrome
```

**Option A2 — Microsoft Edge (Chromium-based, same DevTools Protocol; already
installed on this machine).** Log into Yahoo in Edge, then relaunch with the
debug port:

```bash
/Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.phf-edge
```

**Option B — Playwright's Chromium (managed, headless-capable).**
The browser is *not* installed by default. Install it, then launch the binary:

```bash
npx playwright install chromium
CHROME=$(ls -d ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/ChromeForTesting | head -1)
"$CHROME" --remote-debugging-port=9222 --user-data-dir=$HOME/.phf-chrome
```

Either way, a Chrome/Edge window opens. Go to
`https://football.fantasysports.yahoo.com/f1/447010` and **log in**. Keep that
browser running for the whole scrape — the scraper drives it over port 9222,
which is how it reuses your session.

> Linux path for Option B: `chromium-*/chrome-linux/chrome`.

## 3. Recommended path — capture rendered pages, then parse offline (no 2016)

Yahoo's standings/draft/matchups render as **JS-rendered pages**, not static HTML, and
the private JSON API only returns pre-draft zeros. The reliable flow captures the
rendered `innerText` via in-app nav clicks (direct-URL nav 404s for matchups/scoreboard),
then parses offline:

```bash
# 1) launch Edge logged in on :9222 (run-edge.sh), then:
cd scraper
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2025 484479
uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2024 489811

# 2) parse the innerText dumps -> raw/<year>.json (no browser needed)
cargo run -- --from-dump dump --seasons 2024,2025 --out raw

# 3) build the wiki
cp raw/2024.json raw/2025.json ../raw/
cd .. && python3 scripts/generate.py
```

`capture_season.py` clicks the in-app nav (Standings / Draft Results / Matchups) and
saves `<year>-<league>-<view>.innerText.txt`. The parser (`src/parse_rendered.rs`)
reads those and emits the canonical `raw/<year>.json`. Seasons are **2018+** (each has a
distinct league id in `selectors.toml` `[league].season_ids`); 2016/2017 don't exist for
this league.

You can self-validate the parser offline against any dumped file:

```bash
./target/release/phf-scraper --self-test dump/2025-484479-standings.innerText.txt
```

## 4. Full scrape (live `--connect` path, experimental)

The browser capture is also implementable in Rust via `chromiumoxide` (`--connect`),
but the matchups/rosters SPA routes need in-app navigation that the current
`--connect` fetch path does not yet perform. Prefer the `--from-dump` path in section 3
until that is solved. When it works:

```bash
./target/release/phf-scraper --connect http://127.0.0.1:9222 --out ../raw
```

- Default seasons: **2018–2025**. Narrow it with `--seasons`:
  - `--seasons 2024`            one year
  - `--seasons 2018,2020,2024`  a few
  - `--seasons 2018-2025`       a range
- Default datasets: standings, draft, matchups, rosters. Limit with
  `--datasets Standings Draft` (space-separated `Standings|Draft|Matchups|Roster`).
- Writes `../raw/<year>.json` for every scraped season.

To re-dump everything while tuning (no early stop): drop `--dry-run` and keep
`--dump dump`.

## 5. Build the wiki

```bash
cd ..
python3 scripts/generate.py
npx quartz build --serve
```

## How the connection works (why `--connect` takes the HTTP URL)

`--remote-debugging-port=9222` exposes an HTTP endpoint at
`http://127.0.0.1:9222` (browse `/json/version` to inspect it). The underlying
CDP library (`chromiumoxide`) needs the **WebSocket** debugger URL
(`ws://127.0.0.1:9222/devtools/browser/<id>`), so the scraper fetches
`/json/version` and extracts `webSocketDebuggerUrl` for you. You can also pass
that `ws://` URL directly if you prefer.

## Notes / known caveats

- **Post-draft vs end-of-season rosters.** Yahoo's `/rosters` page is a
  week-*dropdown* — the rendered table has no `week` column. When no week column
  is detected, `extract_rosters` buckets every row under `final_week` (default
  18; see `selectors.toml [opts]`). The generator reads `weeks["1"]` and the
  highest non-empty week for the two snapshots. To get a real post-draft snapshot
  you'll want a week-labeled roster source (e.g. a draft-week view when Yahoo
  history is linked, or a roster export). This is the main thing the `--dump`
  step exists to sort out.
- The Chrome you launched in step 2 must **stay running** while the scraper runs.
- Pages and the browser are always closed by the scraper (one tab per fetch, and
  a finally-guard on the browser), so nothing leaks between seasons.

## Troubleshooting

- `could not reach Chrome HTTP debugger` → the Chrome from step 2 isn't running,
  or wasn't launched with `--remote-debugging-port=9222`.
- Login wall in the dump → you weren't logged into Yahoo in that Chrome. Log in,
  then re-run.
- Empty/garbage tables → selectors missed the real Yahoo markup. Send me the
  `dump/*.html` and I'll adjust `selectors.toml`.
