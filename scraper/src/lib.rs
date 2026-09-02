//! phf-scraper library: table extraction, canonical model, browser glue, and
//! selector config for the Pine Hills Yahoo FF history scraper. The `main`
//! binary drives the per-season loop; integration tests use these modules.

pub mod extract;
pub mod model;
pub mod parse_rendered;
pub mod parse_v2;
pub mod scrape;
pub mod selectors;
pub mod sleeper;

use clap::{Parser, ValueEnum};
use std::path::PathBuf;

/// The Sleeper league id for "Pine Hills V2", the 2026 era of this league.
/// Recorded here so the id lives in the repo rather than in someone's history.
pub const PINE_HILLS_SLEEPER_LEAGUE: &str = "1393689200049537024";

/// Shared CLI definition (used by the binary and the lib's browser glue).
#[derive(Parser)]
#[command(
    name = "phf-scraper",
    about = "Scrape Pine Hills Yahoo FF history -> raw/<year>.json"
)]
pub struct Cli {
    /// League id (default 447010).
    #[arg(long, default_value = "447010")]
    pub league_id: String,

    /// Seasons to scrape, e.g. 2018,2019,2024 or 2018-2025.
    /// Default is every season this league actually has (2018-2025); seasons
    /// 2016/2017 never existed for this league, so the default omits them to
    /// avoid fetching dead URLs.
    #[arg(long, default_value = "2018-2025")]
    pub seasons: String,

    /// Where to write raw/<year>.json (default repo root raw/).
    #[arg(long, default_value = "raw")]
    pub out: PathBuf,

    /// Selector config file.
    #[arg(long, default_value = "selectors.toml")]
    pub selectors: PathBuf,

    /// Chrome/Chromium executable. Auto-detected from ms-playwright cache if omitted.
    #[arg(long)]
    pub chrome: Option<PathBuf>,

    /// Reuse a persistent Chrome user-data-dir (your logged-in session).
    #[arg(long)]
    pub user_data_dir: Option<PathBuf>,

    /// Connect to an already-running Chrome on this CDP endpoint (e.g. http://127.0.0.1:9222).
    #[arg(long)]
    pub connect: Option<String>,

    /// Dump rendered HTML per page into this dir (for tuning selectors).
    #[arg(long)]
    pub dump: Option<PathBuf>,

    /// Only do auth + the first standings page, then exit (fast debug).
    #[arg(long)]
    pub dry_run: bool,

    /// Validate the parser against a dumped HTML fixture (no browser needed).
    #[arg(long)]
    pub self_test: Option<PathBuf>,

    /// Verbose: emit parser warnings/diagnostics (selector misses, non-numeric
    /// cells). Off by default so clean progress output isn't cluttered. Env
    /// override: RUST_LOG=warn also works.
    #[arg(short, long)]
    pub verbose: bool,

    /// Build raw/<year>.json from existing `capture_season.py` innerText dumps in
    /// this directory (no browser needed). Files: <dir>/<year>-<league>-<view>.innerText.txt
    #[arg(long)]
    pub from_dump: Option<PathBuf>,

    /// Build raw/<year>.json from harvested Yahoo v2 API payloads in this
    /// directory (no browser needed). Files come from `scripts/harvest_v2.py`.
    ///
    /// This MERGES over any existing raw/<year>.json: standings, matchups and
    /// champions are replaced with the v2 data, and everything else already in
    /// the file (notably draft picks, which the v2 harvest does not fetch) is
    /// preserved.
    #[arg(long)]
    pub from_v2: Option<PathBuf>,

    /// Build raw/<year>.json from the Sleeper API for this league id (no browser,
    /// no key, no harvest step — Sleeper's read-only API is public).
    ///
    /// This is the 2026+ "Pine Hills V2" era. It writes a season file the same
    /// way the Yahoo paths do; the Yahoo seasons (2018-2025) are untouched.
    ///
    /// Pine Hills V2 is league 1393689200049537024, which is what the flag
    /// defaults to when given no value — the same courtesy `--league-id` does
    /// for the Yahoo era. A Sleeper league id is stable for one season; a later
    /// season gets a new id, chained backward by `previous_league_id`.
    #[arg(long, num_args = 0..=1, default_missing_value = PINE_HILLS_SLEEPER_LEAGUE)]
    pub sleeper_league: Option<String>,

    /// Last week to treat as played, for `--sleeper-league`. Sleeper publishes
    /// the whole schedule up front, so without a bound an in-progress season
    /// would emit unplayed weeks as 0-0 games. Auto-detected from `/state/nfl`
    /// when omitted.
    #[arg(long)]
    pub sleeper_weeks: Option<u32>,

    /// Where to cache Sleeper's ~15 MB player dictionary. Deleting the file
    /// forces a refresh; Sleeper asks that it be pulled at most once a day.
    #[arg(long, default_value = ".cache/sleeper-players-nfl.json")]
    pub sleeper_player_cache: PathBuf,

    /// Which datasets to extract. Standings+Draft are proven; Matchups+Roster are
    /// EXPERIMENTAL (unvalidated SPA selectors — may yield empty/mis-attributed data).
    #[arg(long, value_enum, default_values_t = vec![Dataset::Standings, Dataset::Draft, Dataset::Matchups, Dataset::Roster])]
    pub datasets: Vec<Dataset>,
}

/// Dataset selection (CLI-facing).
///
/// `Standings` and `Draft` are the proven, fully-tested surfaces (validated
/// against real captures). `Matchups` and `Roster` are EXPERIMENTAL: their
/// Yahoo pages are SPA-routed (only reachable by in-app nav clicks, not direct
/// URLs) and their selectors are unvalidated guesses, so they may emit empty or
/// mis-attributed data. Prefer `--from-dump` with the `capture_season.py` innerText
/// captures for anything you intend to publish.
#[derive(Copy, Clone, PartialEq, Eq, ValueEnum)]
pub enum Dataset {
    Standings,
    Draft,
    /// EXPERIMENTAL — SPA-only page, unvalidated selectors. May produce empty data.
    Matchups,
    /// EXPERIMENTAL — /rosters is a week-dropdown with no week column; every row
    /// buckets under `final_week` and is not a real per-week snapshot.
    Roster,
}
