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
use phf_scraper::{Cli, Dataset, extract, parse_v2, scrape, selectors};

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

/// Build every requested season's raw/<year>.json from capture_season.py dumps.
fn build_from_dump(cli: &Cli, dir: &std::path::Path, sel: &selectors::Selectors) -> Result<()> {
    let seasons = parse_seasons(&cli.seasons);
    println!(
        ">> building {} seasons from dumps in {}",
        seasons.len(),
        dir.display()
    );
    std::fs::create_dir_all(&cli.out)?;
    for year in seasons {
        let lid = sel
            .league
            .season_ids
            .get(&year.to_string())
            .cloned()
            .unwrap_or_else(|| cli.league_id.clone());
        let season = extract::from_dump_dir(dir, year, &lid)?;
        let dest = cli.out.join(format!("{year}.json"));
        std::fs::write(&dest, serde_json::to_string_pretty(&season)?)?;
        println!(
            "   wrote {}  (teams={}, picks={})",
            dest.display(),
            season.teams.teams.len(),
            season.draft.draft_results.len()
        );
        if cli.dry_run {
            println!(">> dry-run: stopping after first season.");
            break;
        }
    }
    println!("\n>> done. Next: run scripts/generate.py to build the wiki.");
    Ok(())
}

/// Build every requested season's raw/<year>.json from harvested v2 API payloads.
///
/// Merges rather than overwrites: the v2 harvest fetches standings and
/// scoreboards but NOT the draft, so blindly writing a fresh `Season` here would
/// silently blank 1170 draft picks that the rendered-page pipeline captured. We
/// splice through `serde_json::Value` so every key we do not own survives.
fn build_from_v2(cli: &Cli, dir: &std::path::Path, sel: &selectors::Selectors) -> Result<()> {
    use anyhow::Context;

    let index = std::fs::read_to_string(dir.join("leagues.json"))
        .context("reading leagues.json — run scripts/harvest_v2.py first")?;

    let seasons = parse_seasons(&cli.seasons);
    println!(
        ">> building {} seasons from v2 payloads in {}",
        seasons.len(),
        dir.display()
    );
    std::fs::create_dir_all(&cli.out)?;

    for year in seasons {
        let lid = sel
            .league
            .season_ids
            .get(&year.to_string())
            .cloned()
            .unwrap_or_else(|| cli.league_id.clone());
        let Some(key) = parse_v2::find_league_key(&index, year, &lid) else {
            println!("   {year}: no league key for league_id {lid} — skipped");
            continue;
        };

        let season = parse_v2::from_v2_dir(dir, year, &key)?;
        let fresh = serde_json::to_value(&season)?;
        let dest = cli.out.join(format!("{year}.json"));

        // Start from what is already on disk so draft picks (and anything else
        // this path does not produce) are carried forward.
        let mut merged = match std::fs::read_to_string(&dest) {
            Ok(existing) => serde_json::from_str::<serde_json::Value>(&existing)
                .with_context(|| format!("parsing existing {}", dest.display()))?,
            Err(_) => serde_json::json!({}),
        };
        let picks_before = merged
            .pointer("/draft/draft_results")
            .and_then(|v| v.as_array())
            .map_or(0, Vec::len);

        let obj = merged
            .as_object_mut()
            .context("existing raw JSON is not an object")?;
        // Exactly the keys the v2 path is authoritative for.
        for k in [
            "season",
            "standings",
            "teams",
            "playoffs",
            "matchups",
            "champions",
            "bracket",
            // Rosters live here. Without it every rebuild drops them, the same
            // way omitting "draft" would drop the picks.
            "weeks",
        ] {
            match fresh.get(k) {
                Some(v) => {
                    obj.insert(k.to_string(), v.clone());
                }
                // `champions`/`matchups` are skipped when empty; drop any stale
                // value rather than leaving last run's behind.
                None => {
                    obj.remove(k);
                }
            }
        }

        let picks_after = merged
            .pointer("/draft/draft_results")
            .and_then(|v| v.as_array())
            .map_or(0, Vec::len);
        anyhow::ensure!(
            picks_before == picks_after,
            "{year}: merge dropped draft picks ({picks_before} -> {picks_after})"
        );

        std::fs::write(&dest, serde_json::to_string_pretty(&merged)?)?;
        let champ = season
            .champions
            .as_ref()
            .map(|c| c.champion.clone())
            .unwrap_or_default();
        println!(
            "   wrote {}  (teams={}, weeks={}, picks kept={}, champion={:?})",
            dest.display(),
            season.teams.teams.len(),
            season.matchups.len(),
            picks_after,
            champ
        );

        if cli.dry_run {
            println!(">> dry-run: stopping after first season.");
            break;
        }
    }
    println!("\n>> done. Next: run scripts/generate.py to build the wiki.");
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    // Structured logging: only emit warnings/diagnostics when -v is passed (or
    // RUST_LOG is set). Keeps the default run's progress output clean.
    let env = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| {
            if cli.verbose {
                tracing_subscriber::EnvFilter::new("warn")
            } else {
                tracing_subscriber::EnvFilter::new("off")
            }
        });
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(env)
        .with_target(false)
        .init();

    let sel = selectors::load(&cli.selectors)?;

    // Offline parser validation (no Yahoo, no browser).
    if let Some(fixture) = &cli.self_test {
        return extract::self_test(fixture, &sel);
    }

    // Offline build from capture_season.py dumps (no Yahoo, no browser).
    if let Some(dir) = &cli.from_dump {
        return build_from_dump(&cli, dir, &sel);
    }

    // Offline build from harvested v2 API payloads (no Yahoo, no browser).
    if let Some(dir) = &cli.from_v2 {
        return build_from_v2(&cli, dir, &sel);
    }

    let seasons = parse_seasons(&cli.seasons);
    println!(">> scraping {} seasons: {:?}", seasons.len(), seasons);

    let mut browser = scrape::connect_browser(&cli).await?;

    // Run the scrape loop, but ALWAYS close the browser afterward so a failed
    // fetch (or any error) can't orphan the Chrome child process.
    let run_result = async {
        for year in seasons {
            let lid = sel
                .league
                .season_ids
                .get(&year.to_string())
                .cloned()
                .unwrap_or_else(|| cli.league_id.clone());
            let base = sel
                .league
                .url_template
                .replace("{id}", &lid)
                .replace("{season}", &year.to_string());

            let want = |d: Dataset| cli.datasets.contains(&d);

            let mut season = Season {
                season: year,
                ..Default::default()
            };

            // Standings / teams
            if want(Dataset::Standings) {
                let url = format!("{base}/standings");
                let html =
                    scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-standings"))
                        .await?;
                let teams = extract::extract_standings(&html, &sel.standings);
                season.standings.teams = teams.clone();
                season.teams.teams = teams;
                println!("   standings: {} teams", season.standings.teams.len());
            }

            // Draft
            if want(Dataset::Draft) {
                let url = format!("{base}/draftresults");
                let html =
                    scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-draft")).await?;
                season.draft.draft_results = extract::extract_draft(&html, &sel.draft);
                println!("   draft: {} picks", season.draft.draft_results.len());
            }

            // Matchups (playoff weeks)
            if want(Dataset::Matchups) {
                let url = format!("{base}/matchups");
                let html =
                    scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-matchups"))
                        .await?;
                season.playoffs.weeks =
                    extract::extract_matchups(&html, &sel.matchups, sel.opts.playoff_week);
                println!(
                    "   matchup weeks: {:?}",
                    season.playoffs.weeks.keys().collect::<Vec<_>>()
                );
            }

            // Rosters (post-draft = week 1, end-of-season = final week). Yahoo's
            // /rosters page is a week-dropdown; extract_rosters uses final_week as the
            // fallback week label when no `week` column is present.
            if want(Dataset::Roster) {
                let url = format!("{base}/rosters");
                let html =
                    scrape::fetch_page(&browser, &url, &cli.dump, &format!("{year}-rosters"))
                        .await?;
                let ros = extract::extract_rosters(&html, &sel.roster, sel.opts.final_week);
                // distribute into weeks[1] (post-draft placeholder) and weeks[final_week]
                for (wk, teams) in ros {
                    season.weeks.entry(wk).or_default().rosters = teams;
                }
                println!(
                    "   roster weeks: {:?}",
                    season.weeks.keys().collect::<Vec<_>>()
                );
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
