//! Table extraction from rendered Yahoo HTML using the `scraper` crate.
//!
//! Fully config-driven: column names come from selectors.toml. We locate the
//! first table matching any of the configured selectors, read its header row
//! to map columns -> canonical fields, then emit rows. If a selector misses,
//! we log it so --dump + selector tuning closes the gap.

use anyhow::Result;
use scraper::{Html, Selector};
use std::collections::BTreeMap;

use crate::model::*;
use crate::selectors::TableCfg;

fn norm(s: &str) -> String {
    s.trim().to_lowercase().replace([' ', '-'], "_")
}

/// Try each candidate CSS selector, then return the matching table with the
/// MOST body rows. Yahoo pages often contain small legend/summary tables that
/// also match a loose selector; the real data table is the one with rows.
fn find_table<'a>(document: &'a Html, candidates: &[String]) -> Option<scraper::ElementRef<'a>> {
    let mut best: Option<(usize, scraper::ElementRef<'a>)> = None;
    for sel in candidates {
        if let Ok(s) = Selector::parse(sel) {
            for table in document.select(&s) {
                let n = table.select(&Selector::parse("tbody tr, tr").unwrap()).count();
                if best.as_ref().map(|(c, _)| n > *c).unwrap_or(true) {
                    best = Some((n, table));
                }
            }
        }
    }
    best.map(|(_, t)| t)
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
                .find(|(_, cand)| {
                    cand.split(',').any(|c| norm(c) == nh)
                })
                .map(|(field, _)| field.to_string())
        })
        .collect()
}

fn cells(row: &scraper::ElementRef) -> Vec<String> {
    row.select(&Selector::parse("td,th").unwrap())
        .map(|c| c.text().collect::<Vec<_>>().join(" ").trim().to_string())
        .collect()
}

fn parse_f64(v: &str) -> f64 {
    let v = v.trim();
    if v.is_empty() {
        return 0.0;
    }
    match v.replace(',', "").parse() {
        Ok(n) => n,
        Err(_) => {
            // Non-numeric cell (e.g. "—", "TBD", "—"). Coercing to 0 silently
            // corrupts the data, so warn instead of failing silently.
            eprintln!("   ! non-numeric score cell {v:?}, defaulting to 0.0");
            0.0
        }
    }
}
fn parse_i64(v: &str) -> i64 {
    let v = v.trim();
    if v.is_empty() {
        return 0;
    }
    match v.replace(',', "").parse() {
        Ok(n) => n,
        Err(_) => {
            eprintln!("   ! non-numeric integer cell {v:?}, defaulting to 0");
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
    let table = match find_table(&doc, &cfg.table.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>()) {
        Some(t) => t,
        None => {
            eprintln!("   ! standings: no table matched selectors {:?}", cfg.table);
            return Vec::new();
        }
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
        let name = get("team");
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
    let table = match find_table(&doc, &cfg.table.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>()) {
        Some(t) => t,
        None => {
            eprintln!("   ! draft: no table matched selectors {:?}", cfg.table);
            return Vec::new();
        }
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
            hmap.iter().position(|h| h.as_deref() == Some(field)).and_then(|i| c.get(i)).cloned().unwrap_or_default()
        };
        let player = get("player");
        if player.is_empty() {
            continue;
        }
        out.push(DraftPick {
            pick: parse_i64(&get("pick")),
            round: parse_i64(&get("round")),
            team: get("team"),
            player,
            position: get("pos"),
        });
    }
    out
}

/// Extract weekly matchups from HTML -> playoff weeks (>= playoff_week).
pub fn extract_matchups(html: &str, cfg: &TableCfg, playoff_week: u32) -> BTreeMap<String, Vec<Matchup>> {
    let doc = Html::parse_document(html);
    let table = match find_table(&doc, &cfg.table.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>()) {
        Some(t) => t,
        None => {
            eprintln!("   ! matchups: no table matched selectors {:?}", cfg.table);
            return BTreeMap::new();
        }
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
            hmap.iter().position(|h| h.as_deref() == Some(field)).and_then(|i| c.get(i)).cloned().unwrap_or_default()
        };
        let week = get("week");
        if week.is_empty() {
            continue;
        }
        let wk: u32 = week.parse().unwrap_or(0);
        if wk < playoff_week {
            continue;
        }
        let tname = get("team");
        let opp = get("opp");
        if tname.is_empty() {
            continue;
        }
        let teams = if opp.is_empty() {
            vec![MatchTeam { name: tname, score: parse_f64(&get("score")), is_winner: parse_bool(&get("win")) }]
        } else {
            vec![
                MatchTeam { name: tname, score: parse_f64(&get("score")), is_winner: parse_bool(&get("win")) },
                MatchTeam { name: opp, score: parse_f64(&get("opp_score")), is_winner: !parse_bool(&get("win")) },
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
    let table = match find_table(&doc, &cfg.table.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>()) {
        Some(t) => t,
        None => {
            eprintln!("   ! roster: no table matched selectors {:?}", cfg.table);
            return BTreeMap::new();
        }
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
            hmap.iter().position(|h| h.as_deref() == Some(field)).and_then(|i| c.get(i)).cloned().unwrap_or_default()
        };
        let week = if has_week_col { get("week") } else { fallback_week.clone() };
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
            .push(RosterPlayer { name: player, position: get("pos") });
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
    use crate::parse_rendered::{parse_draft, parse_matchups_header, parse_standings};
    let read = |suffix: &str| -> String {
        let p = dir.join(format!("{}-{}-{}.innerText.txt", season, league_id, suffix));
        std::fs::read_to_string(&p).unwrap_or_default()
    };
    let (mut s, _lid) = parse_standings(&read("standings"), season, league_id);
    s.draft = parse_draft(&read("draftresults"), season, league_id);
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
    Ok(s)
}
