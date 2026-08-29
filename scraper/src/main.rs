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

use anyhow::Result;
use clap::Parser;

use phf_scraper::model::Season;
use phf_scraper::{extract, scrape, selectors, Cli, Dataset};

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

    // Run the scrape loop, but ALWAYS close the browser afterward so a failed
    // fetch (or any error) can't orphan the Chrome child process.
    let run_result = async {
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

            // Rosters (post-draft = week 1, end-of-season = final week). Yahoo's
            // /rosters page is a week-dropdown; extract_rosters uses final_week as the
            // fallback week label when no `week` column is present.
            if want(Dataset::Roster) {
                let url = format!("{base}/rosters");
                let html = scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-rosters")).await?;
                let ros = extract::extract_rosters(&html, &sel.roster, sel.opts.final_week);
                // distribute into weeks[1] (post-draft placeholder) and weeks[final_week]
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
        Ok::<(), anyhow::Error>(())
    }
    .await;

    // Clean up the browser no matter what (prevents orphaned Chrome process).
    let _ = scrape::close(&mut browser).await;
    run_result?;
    println!("\n>> done. Next: run scripts/generate.py to build the wiki.");
    Ok(())
}
