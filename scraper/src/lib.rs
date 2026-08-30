//! phf-scraper library: table extraction, canonical model, browser glue, and
//! selector config for the Pine Hills Yahoo FF history scraper. The `main`
//! binary drives the per-season loop; integration tests use these modules.

pub mod extract;
pub mod model;
pub mod parse_rendered;
pub mod scrape;
pub mod selectors;

use clap::{Parser, ValueEnum};
use std::path::PathBuf;

/// Shared CLI definition (used by the binary and the lib's browser glue).
#[derive(Parser)]
#[command(name = "phf-scraper", about = "Scrape Pine Hills Yahoo FF history -> raw/<year>.json")]
pub struct Cli {
    /// League id (default 447010).
    #[arg(long, default_value = "447010")]
    pub league_id: String,

    /// Seasons to scrape, e.g. 2016,2017,2024 or 2016-2025.
    #[arg(long, default_value = "2016-2025")]
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

    /// Build raw/<year>.json from existing `capture_season.py` innerText dumps in
    /// this directory (no browser needed). Files: <dir>/<year>-<league>-<view>.innerText.txt
    #[arg(long)]
    pub from_dump: Option<PathBuf>,

    /// Which datasets to extract.
    #[arg(long, value_enum, default_values_t = vec![Dataset::Standings, Dataset::Draft, Dataset::Matchups, Dataset::Roster])]
    pub datasets: Vec<Dataset>,
}

/// Dataset selection (CLI-facing).
#[derive(Copy, Clone, PartialEq, Eq, ValueEnum)]
pub enum Dataset {
    Standings,
    Draft,
    Matchups,
    Roster,
}
