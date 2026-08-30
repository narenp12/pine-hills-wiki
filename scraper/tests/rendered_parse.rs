//! TDD tests: parse RENDERED Yahoo Fantasy pages (innerText/HTML) into the canonical model.
//! Fixtures are real captures from a logged-in Edge session (see docs/superpowers/plans/...).
//! No network, no browser — pure offline parsing.

use phf_scraper::model::{Season, Team};
use phf_scraper::parse_rendered::{parse_standings, parse_draft};
use std::path::Path;

fn fixture(name: &str) -> String {
    let p = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("dump")
        .join(name);
    std::fs::read_to_string(&p)
        .unwrap_or_else(|e| panic!("missing fixture {}: {}", p.display(), e))
}

#[test]
fn standings_parse_save_me_rank_and_points() {
    let text = fixture("2025-484479-standings.innerText.txt");
    let (season, _league_id) = parse_standings(&text, 2025, "484479");
    let teams = &season.teams.teams;
    let save_me = teams
        .iter()
        .find(|t: &&Team| t.name == "Save Me")
        .expect("Save Me team present in standings");
    assert_eq!(save_me.rank, 4, "Save Me ranked 4th in 2025");
    assert!(
        (save_me.points_for - 1657.02).abs() < 0.5,
        "Save Me points_for ~1657.02, got {}",
        save_me.points_for
    );
    assert!(
        (save_me.points_against - 1648.02).abs() < 0.5,
        "Save Me points_against ~1648.02, got {}",
        save_me.points_against
    );
    assert_eq!(save_me.wins, 7, "Save Me 7 wins");
    assert_eq!(save_me.losses, 7, "Save Me 7 losses");
    assert_eq!(teams.len(), 12, "12 teams in league");
}

#[test]
fn draft_parse_picks_populated() {
    let text = fixture("2025-484479-draftresults.innerText.txt");
    let draft = parse_draft(&text, 2025, "484479");
    assert!(
        draft.draft_results.len() >= 120,
        "2025 draft has >=120 picks, got {}",
        draft.draft_results.len()
    );
    let first = &draft.draft_results[0];
    assert!(!first.player.is_empty(), "first pick has a player name");
    assert!(first.round >= 1, "first pick has a round");
    assert!(!first.team.is_empty(), "first pick mapped to a team");
    // spot-check a known pick
    let mccaffrey = draft
        .draft_results
        .iter()
        .find(|p| p.player.contains("Christian McCaffrey"))
        .expect("CMC drafted");
    assert_eq!(mccaffrey.round, 1);
}

// Team name + manager come from the matchups page header (nav-clicked capture).
#[test]
fn matchups_header_wl_record() {
    let text = fixture("2025-484479-matchups-nav.innerText.txt");
    let season: Season = phf_scraper::parse_rendered::parse_matchups_header(&text, 2025, "484479");
    let save_me = season
        .teams
        .teams
        .iter()
        .find(|t| t.name == "Save Me")
        .expect("Save Me in matchups");
    assert_eq!(save_me.wins, 7);
    assert_eq!(save_me.losses, 7);
}
