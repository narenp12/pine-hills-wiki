//! phf-scraper — free, no-key Yahoo Fantasy Football history scraper.
//!
//! Reuses YOUR logged-in Chrome session (no Yahoo API key, no 2FA toggle):
//!   - either via a persistent user-data-dir, or
//!   - by connecting to a Chrome you launch with --remote-debugging-port=9222.
//!
//! For each season it navigates the league pages, waits for JS to render,
//! pulls the rendered HTML, parses tables with `scraper`, and writes the
//! canonical raw/<year>.json that scripts/generate.py consumes.
//!
//! Selectors live in selectors.toml (edit without recompiling). Use --dump to
//! capture real Yahoo HTML so we can tune selectors against actual markup.

mod extract;
mod model;
mod scrape;
mod selectors;

use anyhow::Result;
use clap::{Parser, ValueEnum};
use std::path::PathBuf;

use model::Season;

#[derive(Parser)]
#[command(name = "phf-scraper", about = "Scrape Pine Hills Yahoo FF history -> raw/<year>.json")]
struct Cli {
    /// League id (default 447010).
    #[arg(long, default_value = "447010")]
    league_id: String,

    /// Seasons to scrape, e.g. 2016,2017,2024 or 2016-2025.
    #[arg(long, default_value = "2016-2025")]
    seasons: String,

    /// Where to write raw/<year>.json (default repo root raw/).
    #[arg(long, default_value = "raw")]
    out: PathBuf,

    /// Selector config file.
    #[arg(long, default_value = "selectors.toml")]
    selectors: PathBuf,

    /// Chrome/Chromium executable. Auto-detected from ms-playwright cache if omitted.
    #[arg(long)]
    chrome: Option<PathBuf>,

    /// Reuse a persistent Chrome user-data-dir (your logged-in session).
    #[arg(long)]
    user_data_dir: Option<PathBuf>,

    /// Connect to an already-running Chrome on this CDP endpoint (e.g. http://127.0.0.1:9222).
    #[arg(long)]
    connect: Option<String>,

    /// Dump rendered HTML per page into this dir (for tuning selectors).
    #[arg(long)]
    dump: Option<PathBuf>,

    /// Only do auth + the first standings page, then exit (fast debug).
    #[arg(long)]
    dry_run: bool,

    /// Validate the parser against a dumped HTML fixture (no browser needed).
    #[arg(long)]
    self_test: Option<PathBuf>,

    /// Which datasets to extract.
    #[arg(long, value_enum, default_values_t = vec![Dataset::Standings, Dataset::Draft, Dataset::Matchups, Dataset::Roster])]
    datasets: Vec<Dataset>,
}

#[derive(Copy, Clone, PartialEq, Eq, ValueEnum)]
enum Dataset {
    Standings,
    Draft,
    Matchups,
    Roster,
}

fn parse_seasons(s: &str) -> Vec<u32> {
    let mut out = Vec::new();
    for part in s.split(',') {
        let part = part.trim();
        if let Some((a, b)) = part.split_once('-') {
            if let (Ok(lo), Ok(hi)) = (a.trim().parse::<u32>(), b.trim().parse::<u32>()) {
                for y in lo..=hi {
                    out.push(y);
                }
            }
        } else if let Ok(y) = part.parse::<u32>() {
            out.push(y);
        }
    }
    out
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let sel = selectors::load(&cli.selectors)?;

    // Offline parser validation (no Yahoo, no browser).
    if let Some(fixture) = &cli.self_test {
        return extract::self_test(fixture, &sel);
    }

    let seasons = parse_seasons(&cli.seasons);
    println!(">> scraping {} seasons: {:?}", seasons.len(), seasons);

    let mut browser = scrape::connect_browser(&cli).await?;

    for year in seasons {
        let lid = sel.league
            .season_ids
            .get(&year)
            .cloned()
            .unwrap_or_else(|| cli.league_id.clone());
        let base = sel.league.url_template.replace("{id}", &lid).replace("{season}", &year.to_string());

        let want = |d: Dataset| cli.datasets.contains(&d);

        let mut season = Season {
            season: year,
            ..Default::default()
        };

        // Standings / teams
        if want(Dataset::Standings) {
            let url = format!("{base}/standings");
            let html = scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-standings")).await?;
            let teams = extract::extract_standings(&html, &sel.standings);
            season.standings.teams = teams.clone();
            season.teams.teams = teams;
            println!("   standings: {} teams", season.standings.teams.len());
        }

        // Draft
        if want(Dataset::Draft) {
            let url = format!("{base}/draftresults");
            let html = scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-draft")).await?;
            season.draft.draft_results = extract::extract_draft(&html, &sel.draft);
            println!("   draft: {} picks", season.draft.draft_results.len());
        }

        // Matchups (playoff weeks)
        if want(Dataset::Matchups) {
            let url = format!("{base}/matchups");
            let html = scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-matchups")).await?;
            season.playoffs.weeks = extract::extract_matchups(&html, &sel.matchups, sel.opts.playoff_week);
            println!("   matchup weeks: {:?}", season.playoffs.weeks.keys().collect::<Vec<_>>());
        }

        // Rosters (post-draft = week 1, end-of-season = final week)
        if want(Dataset::Roster) {
            let url = format!("{base}/rosters");
            let html = scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-rosters")).await?;
            let ros = extract::extract_rosters(&html, &sel.roster);
            // distribute into weeks[1] and weeks[final_week]
            for (wk, teams) in ros {
                season.weeks.entry(wk).or_default().rosters = teams;
            }
            println!("   roster weeks: {:?}", season.weeks.keys().collect::<Vec<_>>());
        }

        // Emit canonical JSON
        std::fs::create_dir_all(&cli.out)?;
        let dest = cli.out.join(format!("{year}.json"));
        std::fs::write(&dest, serde_json::to_string_pretty(&season)?)?;
        println!("   wrote {}", dest.display());

        if cli.dry_run {
            println!(">> dry-run: stopping after first season.");
            break;
        }
    }

    scrape::close(&mut browser).await?;
    println!("\n>> done. Next: run scripts/generate.py to build the wiki.");
    Ok(())
}
