//! Table extraction from rendered Yahoo HTML using the `scraper` crate.
//!
//! Fully config-driven: column names come from selectors.toml. We locate the
//! first table matching any of the configured selectors, read its header row
//! to map columns -> canonical fields, then emit rows. If a selector misses,
//! we log it so --dump + selector tuning closes the gap.

use anyhow::Result;
use scraper::{Html, Selector};
use std::collections::BTreeMap;
use tracing::warn;

use crate::model::*;
use crate::parse_rendered::clean_name;
use crate::selectors::TableCfg;

fn norm(s: &str) -> String {
    s.trim().to_lowercase().replace([' ', '-'], "_")
}

/// Try each candidate CSS selector, then return the matching table with the
/// MOST body rows. Yahoo pages often contain small legend/summary tables that
/// also match a loose selector; the real data table is the one with rows.
///
/// Shared by every `extract_*` function so the four surfaces can't drift in how
/// they pick the target table.
fn find_table<'a>(document: &'a Html, candidates: &[String]) -> Option<scraper::ElementRef<'a>> {
    let mut best: Option<(usize, scraper::ElementRef<'a>)> = None;
    for sel in candidates {
        if let Ok(s) = Selector::parse(sel) {
            for table in document.select(&s) {
                let n = table
                    .select(&Selector::parse("tbody tr, tr").unwrap())
                    .count();
                if best.as_ref().map(|(c, _)| n > *c).unwrap_or(true) {
                    best = Some((n, table));
                }
            }
        }
    }
    best.map(|(_, t)| t)
}

/// Resolve the configured `table` selector list, splitting on commas.
fn table_selectors(cfg: &TableCfg) -> Vec<String> {
    cfg.table
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// Locate the data table described by `cfg`, or warn and return `None`. Centralizes
/// the "no table matched" branch that every `extract_*` previously duplicated.
fn select_best_table<'a>(
    document: &'a Html,
    cfg: &TableCfg,
    label: &str,
) -> Option<scraper::ElementRef<'a>> {
    let sels = table_selectors(cfg);
    match find_table(document, &sels) {
        Some(t) => Some(t),
        None => {
            warn!(label, selectors = ?cfg.table, "no table matched selectors");
            None
        }
    }
}

/// Map header text -> canonical field, given the candidate column lists.
fn header_map(headers: &[String], cfg: &TableCfg) -> Vec<Option<String>> {
    let fields = [
        ("team", &cfg.team_col),
        ("owner", &cfg.owner_col),
        ("wins", &cfg.wins_col),
        ("losses", &cfg.losses_col),
        ("pf", &cfg.pf_col),
        ("pa", &cfg.pa_col),
        ("rank", &cfg.rank_col),
        ("pick", &cfg.pick_col),
        ("round", &cfg.round_col),
        ("player", &cfg.player_col),
        ("pos", &cfg.pos_col),
        ("week", &cfg.week_col),
        ("opp", &cfg.opp_col),
        ("score", &cfg.score_col),
        ("opp_score", &cfg.opp_score_col),
        ("win", &cfg.win_col),
    ];
    headers
        .iter()
        .map(|h| {
            let nh = norm(h);
            fields
                .iter()
                .find(|(_, cand)| cand.split(',').any(|c| norm(c) == nh))
                .map(|(field, _)| field.to_string())
        })
        .collect()
}

fn cells(row: &scraper::ElementRef) -> Vec<String> {
    row.select(&Selector::parse("td,th").unwrap())
        .map(|c| c.text().collect::<Vec<_>>().join(" ").trim().to_string())
        .collect()
}

/// Return true only if `v` is a canonical US-formatted number: an integer part
/// with commas every 3 digits (and never after a decimal point), at most one
/// decimal point. This REJECTS ambiguous locale forms like "1.800,50"
/// (decimal-comma) or "12,34.56" (bad grouping) that would otherwise parse as
/// ~1.8 / 1234.56 and silently corrupt the value, while accepting "1,800.50",
/// "1800", "1800.5", etc.
fn is_valid_us_number(v: &str) -> bool {
    // At most one decimal point.
    let mut parts = v.splitn(2, '.');
    let int_part = match parts.next() {
        Some(s) => s,
        None => return false,
    };
    let frac_part = parts.next(); // None = no decimal; Some("") = trailing dot (invalid)
    if frac_part.is_some_and(|f| f.is_empty()) {
        return false;
    }
    if frac_part.is_some_and(|f| !f.bytes().all(|b| b.is_ascii_digit())) {
        return false;
    }
    // Integer part: optional comma groups. Split on ','. The first group may be
    // 1-3 digits; every later group must be exactly 3.
    let groups: Vec<&str> = int_part.split(',').collect();
    if groups.len() == 1 {
        return !groups[0].is_empty() && groups[0].bytes().all(|b| b.is_ascii_digit());
    }
    // Multiple groups: leading group 1-3 digits, rest exactly 3.
    let first = groups[0];
    if first.is_empty() || first.len() > 3 || !first.bytes().all(|b| b.is_ascii_digit()) {
        return false;
    }
    groups[1..]
        .iter()
        .all(|g| g.len() == 3 && g.bytes().all(|b| b.is_ascii_digit()))
}

pub fn parse_f64(v: &str) -> f64 {
    let v = v.trim();
    if v.is_empty() {
        return 0.0;
    }
    // Validate canonical US formatting BEFORE parsing: this rejects
    // locale-formatted numbers (e.g. "1.800,50") that would otherwise parse as
    // ~1.8 and silently corrupt the value.
    if !is_valid_us_number(v) {
        warn!(
            value = v,
            "non-numeric / locale-formatted score cell, defaulting to 0.0"
        );
        return 0.0;
    }
    match v.replace(',', "").parse() {
        Ok(n) => n,
        Err(_) => {
            warn!(value = v, "non-numeric score cell, defaulting to 0.0");
            0.0
        }
    }
}
pub fn parse_i64(v: &str) -> i64 {
    let v = v.trim();
    if v.is_empty() {
        return 0;
    }
    if !is_valid_us_number(v) {
        warn!(
            value = v,
            "non-numeric / locale-formatted integer cell, defaulting to 0"
        );
        return 0;
    }
    match v.replace(',', "").parse() {
        Ok(n) => n,
        Err(_) => {
            warn!(value = v, "non-numeric integer cell, defaulting to 0");
            0
        }
    }
}
fn parse_bool(v: &str) -> bool {
    let s = v.trim().to_lowercase();
    s == "w" || s == "win" || s == "won" || s == "true" || s == "yes" || s == "1"
}

/// Extract standings/teams from HTML.
pub fn extract_standings(html: &str, cfg: &TableCfg) -> Vec<Team> {
    let doc = Html::parse_document(html);
    let table = match select_best_table(&doc, cfg, "standings") {
        Some(t) => t,
        None => return Vec::new(),
    };
    let rows: Vec<_> = table.select(&Selector::parse("tr").unwrap()).collect();
    if rows.len() < 2 {
        return Vec::new();
    }
    let headers = cells(&rows[0]);
    let hmap = header_map(&headers, cfg);
    let mut out = Vec::new();
    for r in &rows[1..] {
        let c = cells(r);
        if c.len() < 2 {
            continue;
        }
        let get = |field: &str| -> String {
            hmap.iter()
                .position(|h| h.as_deref() == Some(field))
                .and_then(|i| c.get(i))
                .cloned()
                .unwrap_or_default()
        };
        let name = clean_name(&get("team"));
        if name.is_empty() {
            continue;
        }
        out.push(Team {
            team_key: name.clone(),
            name,
            owner: get("owner"),
            wins: parse_i64(&get("wins")),
            losses: parse_i64(&get("losses")),
            points_for: parse_f64(&get("pf")),
            points_against: parse_f64(&get("pa")),
            rank: parse_i64(&get("rank")),
        });
    }
    out
}

/// Extract draft picks from HTML.
pub fn extract_draft(html: &str, cfg: &TableCfg) -> Vec<DraftPick> {
    let doc = Html::parse_document(html);
    let table = match select_best_table(&doc, cfg, "draft") {
        Some(t) => t,
        None => return Vec::new(),
    };
    let rows: Vec<_> = table.select(&Selector::parse("tr").unwrap()).collect();
    if rows.len() < 2 {
        return Vec::new();
    }
    let headers = cells(&rows[0]);
    let hmap = header_map(&headers, cfg);
    let mut out = Vec::new();
    for r in &rows[1..] {
        let c = cells(r);
        let get = |field: &str| -> String {
            hmap.iter()
                .position(|h| h.as_deref() == Some(field))
                .and_then(|i| c.get(i))
                .cloned()
                .unwrap_or_default()
        };
        let player = get("player");
        if player.is_empty() {
            continue;
        }
        out.push(DraftPick {
            pick: parse_i64(&get("pick")),
            round: parse_i64(&get("round")),
            team: clean_name(&get("team")),
            player,
            position: get("pos"),
        });
    }
    out
}

/// Extract weekly matchups from HTML -> playoff weeks (>= playoff_week).
pub fn extract_matchups(
    html: &str,
    cfg: &TableCfg,
    playoff_week: u32,
) -> BTreeMap<String, Vec<Matchup>> {
    let doc = Html::parse_document(html);
    let table = match select_best_table(&doc, cfg, "matchups") {
        Some(t) => t,
        None => return BTreeMap::new(),
    };
    let rows: Vec<_> = table.select(&Selector::parse("tr").unwrap()).collect();
    if rows.len() < 2 {
        return BTreeMap::new();
    }
    let headers = cells(&rows[0]);
    let hmap = header_map(&headers, cfg);
    let mut weeks: BTreeMap<String, Vec<Matchup>> = BTreeMap::new();
    for r in &rows[1..] {
        let c = cells(r);
        let get = |field: &str| -> String {
            hmap.iter()
                .position(|h| h.as_deref() == Some(field))
                .and_then(|i| c.get(i))
                .cloned()
                .unwrap_or_default()
        };
        let week = get("week");
        if week.is_empty() {
            continue;
        }
        let wk: u32 = week.parse().unwrap_or(0);
        if wk < playoff_week {
            continue;
        }
        let tname = clean_name(&get("team"));
        let opp = clean_name(&get("opp"));
        if tname.is_empty() {
            continue;
        }
        let teams = if opp.is_empty() {
            vec![MatchTeam {
                name: tname,
                score: parse_f64(&get("score")),
                is_winner: parse_bool(&get("win")),
            }]
        } else {
            vec![
                MatchTeam {
                    name: tname,
                    score: parse_f64(&get("score")),
                    is_winner: parse_bool(&get("win")),
                },
                MatchTeam {
                    name: opp,
                    score: parse_f64(&get("opp_score")),
                    is_winner: !parse_bool(&get("win")),
                },
            ]
        };
        weeks.entry(week).or_default().push(Matchup { teams });
    }
    weeks
}

/// Extract per-week rosters from HTML -> week -> team -> players.
///
/// `final_week` is used as the fallback week label. Yahoo's /rosters page is a
/// week-dropdown (the displayed table has no `week` column), so when we can't
/// detect a week column every row is bucketed under `final_week` (the
/// end-of-season snapshot). The post-draft snapshot is taken from `weeks["1"]`
/// by the generator, which requires a week-labeled roster source or a separate
/// draft-day roster page — callers should prefer a week-scoped roster URL when
/// Yahoo history is linked.
pub fn extract_rosters(
    html: &str,
    cfg: &TableCfg,
    final_week: u32,
) -> BTreeMap<String, BTreeMap<String, Roster>> {
    let doc = Html::parse_document(html);
    let table = match select_best_table(&doc, cfg, "roster") {
        Some(t) => t,
        None => return BTreeMap::new(),
    };
    let rows: Vec<_> = table.select(&Selector::parse("tr").unwrap()).collect();
    if rows.len() < 2 {
        return BTreeMap::new();
    }
    let headers = cells(&rows[0]);
    let hmap = header_map(&headers, cfg);
    let has_week_col = hmap.iter().any(|h| h.as_deref() == Some("week"));
    let fallback_week = final_week.to_string();
    let mut out: BTreeMap<String, BTreeMap<String, Roster>> = BTreeMap::new();
    for r in &rows[1..] {
        let c = cells(r);
        let get = |field: &str| -> String {
            hmap.iter()
                .position(|h| h.as_deref() == Some(field))
                .and_then(|i| c.get(i))
                .cloned()
                .unwrap_or_default()
        };
        let week = if has_week_col {
            get("week")
        } else {
            fallback_week.clone()
        };
        let team = get("team");
        let player = get("player");
        if team.is_empty() || player.is_empty() {
            continue;
        }
        out.entry(week)
            .or_default()
            .entry(team)
            .or_default()
            .players
            .push(RosterPlayer {
                name: player,
                position: get("pos"),
            });
    }
    out
}

/// Smoke test used by `phf-scraper --self-test`: parse a fixture file and
/// report row counts. Lets us validate the parser without Yahoo.
pub fn self_test(fixture: &std::path::Path, sel: &crate::selectors::Selectors) -> Result<()> {
    let html = std::fs::read_to_string(fixture)?;
    let teams = extract_standings(&html, &sel.standings);
    let picks = extract_draft(&html, &sel.draft);
    let mus = extract_matchups(&html, &sel.matchups, sel.opts.playoff_week);
    let ros = extract_rosters(&html, &sel.roster, sel.opts.final_week);
    println!("self-test on {}:", fixture.display());
    println!("  standings rows : {}", teams.len());
    println!("  draft picks    : {}", picks.len());
    println!("  matchup weeks  : {:?}", mus.keys().collect::<Vec<_>>());
    println!("  roster weeks   : {:?}", ros.keys().collect::<Vec<_>>());
    Ok(())
}

/// Assemble a `Season` from the `innerText` captures produced by `capture_season.py`
/// (the proven, ban-safe pipeline: logged-in Edge + in-app nav clicks). Reads:
///   <dir>/<year>-<league>-standings.innerText.txt
///   <dir>/<year>-<league>-draftresults.innerText.txt
///   <dir>/<year>-<league>-matchups.innerText.txt   (optional; supplies owner)
/// The standings file carries rank/W-L/PF/PA for all 12 teams; draft carries picks;
/// matchups header supplies the manager/owner for the viewed team (best-effort).
pub fn from_dump_dir(dir: &std::path::Path, season: u32, league_id: &str) -> Result<Season> {
    use crate::parse_rendered::{parse_draft_with_teams, parse_matchups_header, parse_standings};
    let read = |suffix: &str| -> String {
        let p = dir.join(format!("{}-{}-{}.innerText.txt", season, league_id, suffix));
        std::fs::read_to_string(&p).unwrap_or_default()
    };
    let (mut s, _lid) = parse_standings(&read("standings"), season, league_id);
    // The draft page renders team labels TRUNCATED ("Sharman’s ..."); resolve them
    // against the full standings names so picks attribute to real teams.
    let full_names: Vec<String> = s.teams.teams.iter().map(|t| t.name.clone()).collect();
    s.draft = parse_draft_with_teams(&read("draftresults"), season, league_id, &full_names);
    let mtext = read("matchups");
    if !mtext.is_empty() {
        let ms = parse_matchups_header(&mtext, season, league_id);
        // merge owner from matchups into standings teams by name
        for t in &ms.teams.teams {
            if let Some(dst) = s.teams.teams.iter_mut().find(|x| x.name == t.name) {
                if dst.owner.is_empty() {
                    dst.owner = t.owner.clone();
                }
            }
        }
    }
    // generate.py renders the "Final Standings" table from `standings.teams` and
    // numbers rows positionally, so it must be populated AND ordered by rank —
    // leaving it empty (while only filling `teams.teams`) shipped season pages
    // with an empty standings table.
    s.teams.teams.sort_by_key(|t| t.rank);
    s.standings = s.teams.clone();
    Ok(s)
}
