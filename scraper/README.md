# phf-scraper — Pine Hills FF Yahoo history scraper (Rust)

Free, **no Yahoo API key** required. It reuses *your* logged-in Chrome session
via the Chrome DevTools Protocol, renders each season's Yahoo pages, parses the
tables, and writes the canonical `raw/<year>.json` that `scripts/generate.py`
turns into the Quartz wiki.

> **Note on the Rust edition:** this uses `edition = "2024"` (the latest
> released edition as of 2026). There is **no "Rust 2026" edition** — the next
> edition is planned for 2027. Claiming `edition = "2026"` would fail to build.

## Why Rust
- `chromiumoxide` (async CDP) is the best-maintained Rust browser crate and
  needs **no separate WebDriver/driver binary**.
- `scraper` does browser-grade HTML parsing.
- The whole thing is fast and produces zero runtime deps beyond a Chromium.

## Build
```bash
cd scraper
cargo build --release
```

## Run

You need a Chromium. One is already in the ms-playwright cache; point at it:
```bash
CHROME=$(ls -d ~/Library/Caches/ms-playwright/chromium-*/chrome-mac/ChromeForTesting 2>/dev/null | head -1)
```
(On Linux it's `chromium-*/chrome-linux/chrome`.)

### Recommended: connect to a Chrome you log into once
1. Launch Chrome with remote debugging:
   ```bash
   "$CHROME" --remote-debugging-port=9222 --user-data-dir=$HOME/.phf-chrome
   ```
2. In that Chrome, go to `https://football.fantasysports.yahoo.com/f1/447010`
   and log in. Keep it open.
3. Run the scraper against it:
   ```bash
   ./target/release/phf-scraper --connect http://127.0.0.1:9222 --out ../raw
   ```

### Or: persistent profile
```bash
./target/release/phf-scraper --user-data-dir=$HOME/.phf-chrome --chrome "$CHROME" --out ../raw
```
(first run is headed so you can log in; later runs reuse the session)

## Tuning selectors (you will need this)
Yahoo's DOM is JS-rendered and I can't see it from here, so selectors in
`selectors.toml` are **starting guesses**. To tune them against real markup:

```bash
./target/release/phf-scraper --connect http://127.0.0.1:9222 --dump dump --dry-run
# inspect dump/2016-standings.html etc., then edit selectors.toml and re-run
```

You can validate the parser offline against any dumped file:
```bash
./target/release/phf-scraper --self-test dump/2016-standings.html
```

## Output
Writes `../raw/<year>.json` for every season (2016–2025 by default; override
with `--seasons 2024` or `--seasons 2016,2018,2024`). Then:
```bash
cd ..
python3 scripts/generate.py
npx quartz build --serve
```
