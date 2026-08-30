//! TDD tests: parse RENDERED Yahoo Fantasy pages (innerText/HTML) into the canonical model.
//! Fixtures are real captures from a logged-in Edge session, committed under
//! `tests/fixtures/` so the suite is reproducible without a live capture
//! (`dump/` is gitignored — depending on it made these tests fail on a clean clone).
//! No network, no browser — pure offline parsing.

use phf_scraper::model::{Season, Team};
use phf_scraper::parse_rendered::{parse_draft, parse_draft_with_teams, parse_standings};
use std::path::Path;

fn fixture(name: &str) -> String {
    let p = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join(name);
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("missing fixture {}: {}", p.display(), e))
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

/// REGRESSION: Yahoo's 2020 standings table renders a DUPLICATE rank (two teams
/// both shown as rank 7: "Sharman’s Scorpions" and "Aryan's Amazing Team").
/// Deduping by rank silently DROPPED a real team (10 teams -> 9). The draft has
/// 150 picks / 15 rounds = 10 teams, confirming 10 is correct. Dedupe must key on
/// the whole row identity (name), never on rank alone.
#[test]
fn standings_keeps_all_teams_when_yahoo_duplicates_a_rank() {
    let text = fixture("2020-698987-standings.innerText.txt");
    let (season, _lid) = parse_standings(&text, 2020, "698987");
    let teams = &season.teams.teams;
    assert_eq!(
        teams.len(),
        10,
        "2020 league had 10 teams (150 draft picks / 15 rounds), got {}: {:?}",
        teams.len(),
        teams.iter().map(|t| &t.name).collect::<Vec<_>>()
    );
    let aryan = teams
        .iter()
        .find(|t| t.name.contains("Aryan"))
        .expect("Aryan's Amazing Team must not be dropped by rank dedupe");
    assert_eq!(aryan.wins, 6);
    assert_eq!(aryan.losses, 7);
    assert!(
        (aryan.points_for - 1538.10).abs() < 0.5,
        "got {}",
        aryan.points_for
    );
    // and the team sharing rank 7 is still present
    assert!(
        teams.iter().any(|t| t.name.contains("Sharman")),
        "Sharman’s Scorpions also present"
    );
}

/// The standings table renders twice in the page (desktop + duplicate block);
/// true duplicate rows (same name AND same rank) must still collapse to one.
#[test]
fn standings_dedupes_true_duplicate_rows() {
    let text = fixture("2025-484479-standings.innerText.txt");
    let (season, _lid) = parse_standings(&text, 2025, "484479");
    let names: Vec<&String> = season.teams.teams.iter().map(|t| &t.name).collect();
    let mut uniq = names.clone();
    uniq.sort();
    uniq.dedup();
    assert_eq!(
        names.len(),
        uniq.len(),
        "no duplicated team names: {names:?}"
    );
}

/// Team names must be free of Yahoo's injected private-use / bidi control chars,
/// otherwise the wiki renders mojibake and cross-season name joins break.
#[test]
fn standings_strips_unicode_control_marks_from_names() {
    let text = fixture("2020-698987-standings.innerText.txt");
    let (season, _lid) = parse_standings(&text, 2020, "698987");
    for t in &season.teams.teams {
        assert!(
            !t.name
                .chars()
                .any(|c| ('\u{e000}'..='\u{f8ff}').contains(&c)
                    || matches!(c, '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}')),
            "team name has control/private-use chars: {:?}",
            t.name
        );
    }
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

/// REGRESSION: pick numbers >= 10 were DROPPED. `strip_prefix(char::is_ascii_digit)`
/// removes only ONE digit, so "10.\tPlayer\tTeam" left "0." and failed the '.' check.
/// A 12-team league drafts 12 picks/round x 15 rounds = 180; we were getting 135.
#[test]
fn draft_parses_double_digit_pick_numbers() {
    let text = fixture("2024-489811-draftresults.innerText.txt");
    let draft = parse_draft(&text, 2024, "489811");
    assert_eq!(
        draft.draft_results.len(),
        180,
        "2024: 12 teams x 15 rounds = 180 picks, got {}",
        draft.draft_results.len()
    );
    // Round 1 must contain all 12 picks, including 10, 11, 12.
    let r1: Vec<i64> = draft
        .draft_results
        .iter()
        .filter(|p| p.round == 1)
        .map(|p| p.pick)
        .collect();
    assert_eq!(r1.len(), 12, "round 1 has 12 picks, got {r1:?}");
    for want in 1..=12 {
        assert!(r1.contains(&want), "round 1 missing pick {want}: {r1:?}");
    }
    // pick 12 of round 1 was Derrick Henry -> Super Squirrels
    let dh = draft
        .draft_results
        .iter()
        .find(|p| p.player.contains("Derrick Henry"))
        .expect("Derrick Henry drafted in 2024");
    assert_eq!(dh.round, 1);
    assert_eq!(dh.pick, 12);
}

/// REGRESSION: the draft page renders team labels TRUNCATED with an ellipsis
/// ("Sharman’s ...", "Jeremy's Nea..."), so draft picks were attributed to a
/// name that matches no team in standings. Picks must resolve to full team names.
#[test]
fn draft_team_names_are_resolved_to_full_standings_names() {
    let stand = fixture("2024-489811-standings.innerText.txt");
    let (season, _lid) = parse_standings(&stand, 2024, "489811");
    let full: Vec<String> = season.teams.teams.iter().map(|t| t.name.clone()).collect();

    let text = fixture("2024-489811-draftresults.innerText.txt");
    let draft = parse_draft_with_teams(&text, 2024, "489811", &full);

    for p in &draft.draft_results {
        assert!(
            !p.team.contains("..") && !p.team.contains('…'),
            "pick {} team name still truncated: {:?}",
            p.pick,
            p.team
        );
        assert!(
            full.contains(&p.team),
            "pick {} team {:?} is not a real 2024 team ({:?})",
            p.pick,
            p.team,
            full
        );
    }
    // every team should own exactly 15 picks (15 rounds, snake draft)
    let mut per_team: std::collections::BTreeMap<&str, usize> = Default::default();
    for p in &draft.draft_results {
        *per_team.entry(p.team.as_str()).or_default() += 1;
    }
    assert_eq!(per_team.len(), 12, "all 12 teams own picks: {per_team:?}");
    for (t, n) in &per_team {
        assert_eq!(*n, 15, "team {t} should have 15 picks, got {n}");
    }
}

/// The 2022 draft page truncates a name containing a multi-byte char into a
/// REPLACEMENT CHAR ("Hill We Go\u{fffd}..."), which a naive prefix match misses.
/// Resolution must tolerate it and still land on "Hill We Go… Again (feat Kyler)".
#[test]
fn draft_team_resolution_tolerates_replacement_chars() {
    let stand = fixture("2022-703496-standings.innerText.txt");
    let (season, _lid) = parse_standings(&stand, 2022, "703496");
    let full: Vec<String> = season.teams.teams.iter().map(|t| t.name.clone()).collect();

    let text = fixture("2022-703496-draftresults.innerText.txt");
    let draft = parse_draft_with_teams(&text, 2022, "703496", &full);

    assert_eq!(draft.draft_results.len(), 150, "2022: 10 teams x 15 rounds");
    let hill = draft
        .draft_results
        .iter()
        .find(|p| p.team.starts_with("Hill We Go"))
        .expect("the 'Hill We Go…' team owns picks");
    assert_eq!(
        hill.team, "Hill We Go… Again (feat Kyler)",
        "truncated name with U+FFFD must resolve to the full standings name"
    );
    for p in &draft.draft_results {
        assert!(
            full.contains(&p.team),
            "pick {} team {:?} unresolved",
            p.pick,
            p.team
        );
    }
}

// Team name + manager come from the matchups page header (nav-clicked capture).
#[test]
fn matchups_header_wl_record() {
    let text = fixture("2025-484479-matchups.innerText.txt");
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
