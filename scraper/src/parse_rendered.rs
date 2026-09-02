//! Parse RENDERED Yahoo Fantasy pages (innerText / HTML) captured from a logged-in
//! Edge session into the canonical `model`. Offline, browser-free.
//!
//! Proven sources (Phase-1, 2026-08-29):
//!  - standings "Overall Points" table: team name + rank (1..12) + season total points.
//!  - draftresults page: Round N / <pick>. <Player> -> <Team>.
//!  - matchups header (nav-clicked): "<Team> <Manager> <W-L-T> | <rank>th".

use crate::model::{Draft, DraftPick, Season, Standings, Team};

/// Parse the standings page innerText into the canonical team records.
///
/// The in-app "Standings" nav renders a table (TAB-separated per row):
///   Rank<TAB>Team<TAB>W-L-T<TAB>PF<TAB>PA<TAB>Streak<TAB>Waiver<TAB>Moves
///   *1<TAB> Stroud Boys<TAB>8-6-0<TAB>1688.16<TAB>1665.30<TAB>W-3<TAB>7<TAB>9
/// Some captures fall back to the "Overall Points" stat view (rank + total points only);
/// that path still yields rank + points_for.
pub fn parse_standings(text: &str, season: u32, league_id: &str) -> (Season, String) {
    let mut teams: Vec<Team> = Vec::new();
    let lines: Vec<&str> = text.lines().map(|l| l.trim()).collect();

    // Fast path: a header line "Rank\tTeam\tW-L-T\tPF\tPA" marks the full table.
    let has_full = lines.iter().any(|l| {
        l.starts_with("Rank") && l.contains("W-L-T") && l.contains("PF") && l.contains("PA")
    });
    if has_full {
        for line in &lines {
            if let Some(team) = parse_standings_row(line, league_id) {
                teams.push(team);
            }
        }
    } else {
        // Fallback: scan for "N." rank markers + trailing points (Overall Points view).
        let mut i = 0;
        while i < lines.len() {
            let line = lines[i];
            if let Some(rank) = parse_rank(line) {
                let mut j = i + 1;
                while j < lines.len() && lines[j].is_empty() {
                    j += 1;
                }
                if j >= lines.len() {
                    break;
                }
                let name = lines[j].to_string();
                let mut points_for = 0.0_f64;
                let mut k = j + 1;
                while k < lines.len() {
                    if parse_rank(lines[k]).is_some() {
                        break;
                    }
                    if let Ok(v) = lines[k].replace(',', "").parse::<f64>() {
                        points_for = v;
                    }
                    k += 1;
                }
                teams.push(Team {
                    team_key: format!("{}-{}", league_id, rank),
                    name,
                    owner: String::new(),
                    wins: 0,
                    losses: 0,
                    points_for,
                    points_against: 0.0,
                    rank: rank as i64,
                    // Rendered pages never expose the real seed.
                    playoff_seed: None,
                });
                i = k;
            } else {
                i += 1;
            }
        }
    }
    // The standings table is rendered twice in the page (desktop + duplicate block),
    // so we must collapse repeats — but NOT by rank. Yahoo sometimes renders a
    // DUPLICATE rank for two different teams (verified: 2020 shows both
    // "Sharman’s Scorpions" and "Aryan's Amazing Team" at rank 7), and deduping by
    // rank silently dropped a real team. Key on the team name instead: repeated
    // render blocks share the same name, distinct teams don't.
    let mut seen = std::collections::HashSet::new();
    teams.retain(|t| seen.insert(t.name.clone()));
    let mut s = Season::default();
    s.season = season;
    s.teams = Standings { teams };
    (s, league_id.to_string())
}

/// Parse one standings table row: "*4\t Save Me\t7-7-0\t1657.02\t1648.02\tL-1\t7\t67".
/// Returns `None` for header/non-team lines.
fn parse_standings_row(line: &str, league_id: &str) -> Option<Team> {
    if !line.contains('\t') {
        return None;
    }
    let cols: Vec<&str> = line.split('\t').collect();
    if cols.len() < 5 {
        return None;
    }
    // rank = "*4" or "4" or "4." -> strip non-digits
    let rank_str = cols[0].trim().trim_start_matches('*').trim_end_matches('.');
    let rank: i64 = rank_str.parse().ok()?;
    // strip Unicode LTR/RTL marks + variation selectors that Yahoo injects into team names
    let name: String = cols[1]
        .trim()
        .chars()
        .filter(|c| !matches!(c, '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{e010}'..='\u{e01f}'))
        .collect();
    let name = name.trim().to_string();
    // W-L-T = "7-7-0"
    let mut wins = 0;
    let mut losses = 0;
    if let Some((w, rest)) = cols[2].trim().split_once('-') {
        if let (Ok(wv), Ok(lv)) = (
            w.trim().parse::<i64>(),
            rest.split('-').next().unwrap_or("0").trim().parse::<i64>(),
        ) {
            wins = wv;
            losses = lv;
        }
    }
    let points_for = cols[3].trim().replace(',', "").parse::<f64>().ok()?;
    let points_against = cols[4]
        .trim()
        .replace(',', "")
        .parse::<f64>()
        .unwrap_or(0.0);
    Some(Team {
        // Rank is NOT unique — Yahoo can render two teams at the same rank (2020
        // has two rank-7 rows), so a rank-based key would collide. Key on the team
        // name, which is what generate.py joins on across seasons anyway.
        team_key: format!("{}-{}", league_id, name),
        name,
        owner: String::new(),
        wins,
        losses,
        points_for,
        points_against,
        rank,
        // Rendered pages never expose the real seed.
        playoff_seed: None,
    })
}

/// Strip the Unicode control / private-use characters Yahoo injects into rendered
/// team names (bidi marks, and the `\u{e0xx}` private-use glyphs used for icons).
///
/// Public so the HTML-based `extract` path can reuse the exact same sanitizer as
/// the innerText parser — otherwise the two surfaces drift and the wiki renders
/// mojibake from one but not the other.
pub fn clean_name(s: &str) -> String {
    s.trim()
        .chars()
        .filter(|c| {
            !matches!(c, '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}')
                && !('\u{e000}'..='\u{f8ff}').contains(c)
        })
        .collect::<String>()
        .trim()
        .to_string()
}

/// Resolve a TRUNCATED draft-page team label to its full standings name.
///
/// The draft page renders team labels clipped to a fixed width, e.g.
/// `"Sharman’s ..."`, `"Jeremy's Nea..."`, and — when the clip lands mid-codepoint —
/// `"Hill We Go\u{fffd}..."`. We match by longest common prefix against the real
/// team names from standings, ignoring any trailing ellipsis / replacement char.
/// Returns the label unchanged when it is not truncated or nothing matches.
fn resolve_team_label(label: &str, teams: &[String]) -> String {
    let label = clean_name(label);
    if teams.contains(&label) {
        return label; // already a full name
    }
    // Drop trailing "...", "…", and any U+FFFD produced by a mid-codepoint clip.
    let core = label
        .trim_end_matches(['.', '…', '\u{fffd}', ' '])
        .trim_end();
    if core.is_empty() {
        return label;
    }
    let matches: Vec<&String> = teams.iter().filter(|t| t.starts_with(core)).collect();
    match matches.len() {
        1 => matches[0].clone(),
        0 => label,
        // Ambiguous prefix: keep the longest common-prefix match so we still
        // land on a real team rather than emitting a truncated label.
        _ => matches
            .iter()
            .max_by_key(|t| t.len())
            .map(|t| (*t).clone())
            .unwrap_or(label),
    }
}

/// Parse draftresults innerText into Draft picks.
///
/// Team labels are left as rendered (possibly truncated). Prefer
/// [`parse_draft_with_teams`] when standings are available, so picks resolve to
/// the real team names the generator joins on.
pub fn parse_draft(text: &str, season: u32, league_id: &str) -> Draft {
    parse_draft_with_teams(text, season, league_id, &[])
}

/// Parse draftresults innerText, resolving truncated team labels against the
/// full team names from standings (pass `&[]` to skip resolution).
pub fn parse_draft_with_teams(
    text: &str,
    _season: u32,
    _league_id: &str,
    teams: &[String],
) -> Draft {
    let mut picks: Vec<DraftPick> = Vec::new();
    let mut current_round: i64 = 0;
    for line in text.lines().map(|l| l.trim()) {
        if let Some(r) = line.strip_prefix("Round ") {
            if let Ok(n) = r.trim().parse::<i64>() {
                current_round = n;
            }
        }
        // pattern: "<pick>.<TAB><Player><TAB><Team>"  (player may contain spaces).
        // NOTE: the pick number can be MULTI-DIGIT (up to 12+ in a 12-team league),
        // so consume ALL leading digits — stripping a single digit dropped picks 10-12.
        let trimmed = line.trim_start();
        let pick_str: String = trimmed.chars().take_while(|c| c.is_ascii_digit()).collect();
        if pick_str.is_empty() {
            continue;
        }
        let Some(rest) = trimmed[pick_str.len()..].strip_prefix('.') else {
            continue;
        };
        if !(rest.starts_with('\t') || rest.starts_with(' ')) {
            continue;
        }
        let body = &rest[1..];
        let Ok(pick) = pick_str.parse::<i64>() else {
            continue;
        };
        let parts: Vec<&str> = body.split('\t').collect();
        let player = parts[0].trim().to_string();
        let team = if parts.len() > 1 {
            let raw = parts[1].trim();
            if teams.is_empty() {
                clean_name(raw)
            } else {
                resolve_team_label(raw, teams)
            }
        } else {
            String::new()
        };
        // Accept any non-empty player name. An earlier `is_alphabetic()` guard on the
        // first char silently DROPPED real picks whose name starts with a digit —
        // e.g. the "49ers" defense (2024 round 8). Only skip rows with no team, which
        // is what actually distinguishes a pick row from stray page text.
        if !player.is_empty() && !team.is_empty() {
            picks.push(DraftPick {
                pick,
                round: current_round,
                team,
                player,
                position: String::new(),
            });
        }
    }
    Draft {
        draft_results: picks,
    }
}

/// Parse the matchups header ("<Team> <Manager> <W-L-T> | <rank>th") into team W-L.
pub fn parse_matchups_header(text: &str, season: u32, league_id: &str) -> Season {
    let mut teams: Vec<Team> = Vec::new();
    let lines: Vec<&str> = text.lines().map(|l| l.trim()).collect();
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        // record pattern e.g. "7-7-0 | 4th"
        if let Some((wl, rank_str)) = line.split_once(" | ") {
            if let Some((w, rest)) = wl.split_once('-') {
                if let (Ok(wins), Ok(losses)) = (
                    w.parse::<i64>(),
                    rest.split('-').next().unwrap_or("0").parse::<i64>(),
                ) {
                    if let Some(rk) = rank_str
                        .strip_suffix("th")
                        .or_else(|| rank_str.strip_suffix("st"))
                        .or_else(|| rank_str.strip_suffix("nd"))
                        .or_else(|| rank_str.strip_suffix("rd"))
                    {
                        if let Ok(rank) = rk.trim().parse::<i64>() {
                            // team name = first non-empty line above the record; manager = the one just above
                            let mut name = String::new();
                            let mut owner = String::new();
                            let mut j = i as isize - 1;
                            while j >= 0 {
                                let prev = lines[j as usize];
                                if !prev.is_empty() && !prev.contains('|') && !prev.contains('-') {
                                    if owner.is_empty() {
                                        owner = prev.to_string();
                                    } else {
                                        name = prev.to_string();
                                        break;
                                    }
                                }
                                j -= 1;
                            }
                            teams.push(Team {
                                team_key: format!("{}-{}", league_id, rank),
                                name,
                                owner,
                                wins,
                                losses,
                                points_for: 0.0,
                                points_against: 0.0,
                                rank,
                                // Rendered pages never expose the real seed.
                                playoff_seed: None,
                            });
                        }
                    }
                }
            }
        }
        i += 1;
    }
    let mut s = Season::default();
    s.season = season;
    s.teams = Standings { teams };
    s
}

fn parse_rank(line: &str) -> Option<u32> {
    let t = line.trim();
    if let Some(n) = t.strip_suffix('.') {
        if n.chars().all(|c| c.is_ascii_digit()) && !n.is_empty() {
            return n.parse::<u32>().ok();
        }
    }
    None
}
