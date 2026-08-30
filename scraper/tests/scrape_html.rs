//! Integration tests for the LIVE HTML-extraction path (`extract::extract_*`).
//!
//! The proven, ban-safe pipeline is `--from-dump` (innerText + `parse_rendered`),
//! which `rendered_parse.rs` already covers. But `scrape.rs`/`extract.rs` also
//! implement a direct-HTML extraction path that was previously UNTESTED — if
//! Yahoo changes its DOM, selectors in selectors.toml could silently miss and the
//! HTML path would emit empty tables with no test catching it. These fixtures
//! + tests lock the HTML parser's behavior so that path can't rot silently.
//!
//! Fixtures are committed HTML that matches the REAL selectors in selectors.toml
//! (e.g. `table.table-data`, `div.standings table`, `table.draftresults`), so the
//! selectors don't need tuning just to run the suite.

use phf_scraper::extract::*;
use phf_scraper::selectors;
use std::path::Path;

fn sel() -> selectors::Selectors {
    // selectors.toml shipped in the repo (validated at runtime by the binary too).
    selectors::load(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("selectors.toml").as_path(),
    )
        .expect("load selectors.toml")
}

fn fixture(name: &str) -> String {
    let p = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join(name);
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("missing fixture {}: {e}", p.display()))
}

#[test]
fn standings_html_picks_the_real_table_not_the_legend() {
    // The fixture includes a 1-row "summary" table that also matches a loose
    // selector; find_table must pick the standings table (4 body rows).
    let html = fixture("sample-standings.html");
    let teams = extract_standings(&html, &sel().standings);
    assert_eq!(teams.len(), 4, "4 standings rows, not the 1-row legend");
    assert_eq!(teams[0].name, "Stroud Boys");
    assert_eq!(teams[0].rank, 1);
    assert_eq!(teams[0].wins, 12);
    assert_eq!(teams[0].losses, 2);
    assert!((teams[0].points_for - 1800.50).abs() < 1e-6);
    assert!((teams[0].points_against - 1500.25).abs() < 1e-6);
}

#[test]
fn standings_html_strips_bidi_marks_and_resolves_names() {
    // row 2 name is wrapped in U+200E, row 3 in U+200F + U+2026; both must come
    // out clean (same sanitizer the innerText path uses, via clean_name()).
    let html = fixture("sample-standings.html");
    let teams = extract_standings(&html, &sel().standings);
    let super_sq = teams.iter().find(|t| t.name == "Super Squirrels").expect("bidi-stripped");
    assert!(!super_sq.name.contains('\u{200e}'));
    let hill = teams
        .iter()
        .find(|t| t.name.starts_with("Hill We Go"))
        .expect("row 3 present");
    assert_eq!(hill.name, "Hill We Go… Again (feat Kyler)");
    assert!(!hill.name.contains('\u{200f}'));
}

#[test]
fn draft_html_parses_double_digit_picks() {
    // pick 10 / 12 in round 1 must NOT be dropped (regression class from the
    // innerText path, exercised here on the HTML path).
    let html = fixture("sample-draftresults.html");
    let picks = extract_draft(&html, &sel().draft);
    assert_eq!(picks.len(), 4, "all 4 picks parsed");
    assert!(picks.iter().any(|p| p.pick == 10 && p.round == 1));
    assert!(picks.iter().any(|p| p.pick == 12 && p.round == 1));
    let dh = picks
        .iter()
        .find(|p| p.player.contains("Derrick Henry"))
        .expect("Derrick Henry present");
    assert_eq!(dh.team, "Super Squirrels");
    assert_eq!(dh.position, "RB");
}

#[test]
fn draft_html_strips_bidi_from_team_labels() {
    let html = fixture("sample-draftresults.html");
    let picks = extract_draft(&html, &sel().draft);
    assert!(
        picks.iter().all(|p| !p.team.contains('\u{200e}') && !p.team.contains('\u{200f}')),
        "HTML draft teams sanitized like the innerText path"
    );
}

#[test]
fn matchups_html_keeps_only_playoff_weeks_and_strips_bidi() {
    let html = fixture("sample-matchups.html");
    let cfg = sel();
    let weeks = extract_matchups(&html, &cfg.matchups, cfg.opts.playoff_week);
    // weeks < playoff_week (14) must be dropped; only week 15 survives.
    assert_eq!(weeks.len(), 1, "only playoff weeks (>=14) kept");
    assert!(weeks.contains_key("15"));
    let w15 = &weeks["15"];
    assert_eq!(w15.len(), 2, "two matchups in week 15");
    // the bidi-wrapped team name must resolve cleanly
    assert!(w15
        .iter()
        .flat_map(|m| m.teams.iter())
        .all(|t| !t.name.contains('\u{200f}')));
    // winner flag derived from Result column
    let sb_win = w15
        .iter()
        .flat_map(|m| m.teams.iter())
        .find(|t| t.name == "Stroud Boys")
        .expect("Stroud Boys in week 15");
    assert!(sb_win.is_winner);
}

#[test]
fn parse_f64_rejects_locale_formatted_numbers() {
    // "1.800,50" (decimal-comma locale) must NOT silently parse as ~1.8; the
    // hardened parser rejects the bad grouping and defaults to 0.0 (with a
    // warning), instead of corrupting the value.
    assert_eq!(
        phf_scraper::extract::parse_f64("1.800,50"),
        0.0,
        "locale-formatted number rejected, not mis-parsed"
    );
    // A comma in the wrong place (not 3 from the end) is also rejected.
    assert_eq!(phf_scraper::extract::parse_f64("12,34.56"), 0.0);
    // Normal US thousands separators still parse correctly.
    assert!((phf_scraper::extract::parse_f64("1,800.50") - 1800.50).abs() < 1e-6);
    assert!((phf_scraper::extract::parse_f64("1800.50") - 1800.50).abs() < 1e-6);
    assert_eq!(phf_scraper::extract::parse_i64("1,234"), 1234);
    assert_eq!(phf_scraper::extract::parse_i64("1234"), 1234);
}
