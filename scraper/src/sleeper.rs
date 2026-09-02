//! Sleeper API client + parser for the Pine Hills V2 era (2026-).
//!
//! Sleeper publishes a free, key-less, read-only JSON API, so this path needs
//! no browser, no CDP and no selectors: it fetches straight over HTTPS and maps
//! the payloads onto the same canonical `model::Season` the Yahoo paths emit.
//! `scripts/generate.py` therefore needs no change to read a Sleeper season.
//!
//! The split mirrors `parse_v2`: `fetch_payloads` does the network, and
//! `build_season` is a pure function over already-fetched JSON, so the whole
//! mapping is testable against committed fixtures without touching the network.
//!
//! Two things Sleeper does NOT give us, and how they are recovered:
//!   * There is no `rank` field. The final playoff-adjusted finish is read off
//!     the bracket placement games (`p: 1/3/5/7` plus the losers bracket).
//!   * There is no `points_against`, and `fpts`/`fpts_decimal` split a score
//!     across two integers. Both season point totals are summed from the weekly
//!     matchups instead, which is unambiguous and self-consistent.

use anyhow::{Context, Result};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};

use crate::model::{
    Bracket, BracketGame, Champions, Draft, DraftPick, MatchTeam, Matchup, Playoffs, Roster,
    RosterPlayer, Season, Standings, Team, Week,
};

/// Sleeper's public read-only API. No key, no auth; the documented ceiling is
/// 1000 calls/minute and a full season costs roughly two dozen.
pub const API_BASE: &str = "https://api.sleeper.app/v1";

/// Last NFL week Sleeper will schedule fantasy matchups for. Week 19 returns an
/// empty array, so this is the upper bound on the weekly fetch loop.
const MAX_WEEK: u32 = 18;

// --------------------------------------------------------------------------- //
// JSON helpers
// --------------------------------------------------------------------------- //

fn as_f64(v: &Value) -> f64 {
    v.as_f64()
        .or_else(|| v.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
        .unwrap_or(0.0)
}

fn as_i64(v: &Value) -> i64 {
    v.as_i64()
        .or_else(|| v.as_str().and_then(|s| s.trim().parse::<i64>().ok()))
        .unwrap_or(0)
}

fn as_str(v: &Value) -> String {
    v.as_str().unwrap_or_default().trim().to_string()
}

/// `null` and absent are the same thing here: a bracket slot not yet decided.
fn opt_i64(v: &Value) -> Option<i64> {
    match v {
        Value::Null => None,
        other => other.as_i64(),
    }
}

// --------------------------------------------------------------------------- //
// payloads
// --------------------------------------------------------------------------- //

/// Every raw Sleeper response needed to build one season.
///
/// Held as `Value` rather than typed structs deliberately: Sleeper adds fields
/// without warning, and the Yahoo parsers in this crate already take the same
/// tolerant-pointer approach.
#[derive(Debug, Default, Clone)]
pub struct Payloads {
    /// `/league/<id>` — name, season, `roster_positions`, playoff settings.
    pub league: Value,
    /// `/league/<id>/users` — `display_name`, `metadata.team_name`.
    pub users: Value,
    /// `/league/<id>/rosters` — `roster_id` -> `owner_id`, W/L record.
    pub rosters: Value,
    /// `/league/<id>/winners_bracket` — the championship + placement games.
    pub winners_bracket: Value,
    /// `/league/<id>/losers_bracket` — the toilet bowl.
    pub losers_bracket: Value,
    /// `/draft/<id>/picks` — carries player names inline, so the draft needs no
    /// player dictionary at all.
    pub picks: Value,
    /// week -> `/league/<id>/matchups/<week>`. Only weeks that have actually
    /// been played belong here; see `scored_through`.
    pub matchups: BTreeMap<u32, Value>,
    /// `player_id` -> `(name, position)`, from the cached player dictionary.
    /// Absent means weekly rosters are skipped rather than filled with ids.
    pub players: HashMap<String, (String, String)>,
}

// --------------------------------------------------------------------------- //
// team identity
// --------------------------------------------------------------------------- //

/// One franchise, resolved across the three payloads that describe it.
#[derive(Debug, Default, Clone)]
struct TeamRef {
    roster_id: i64,
    /// Display name for the franchise. Sleeper only stores `metadata.team_name`
    /// when a manager actually sets one; most do not, so this falls back to the
    /// manager's handle. `raw/bible.yaml`'s `aliases` block is what ties those
    /// handles back to the Yahoo-era franchise names.
    name: String,
    /// Manager handle. `owner_aliases` in the bible maps it to a real person, so
    /// a manager's history spans the Yahoo and Sleeper eras.
    owner: String,
    wins: i64,
    losses: i64,
}

/// Resolve `roster_id` -> franchise, joining rosters to users on `owner_id`.
fn team_refs(p: &Payloads, league_id: &str) -> Result<BTreeMap<i64, TeamRef>> {
    let users = p.users.as_array().context("users payload is not an array")?;

    // user_id -> (team name, manager handle)
    let mut by_user: HashMap<String, (String, String)> = HashMap::new();
    for u in users {
        let user_id = as_str(&u["user_id"]);
        let handle = as_str(&u["display_name"]);
        let team_name = u
            .pointer("/metadata/team_name")
            .map(as_str)
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| handle.clone());
        by_user.insert(user_id, (team_name, handle));
    }

    let rosters = p
        .rosters
        .as_array()
        .context("rosters payload is not an array")?;

    let mut out = BTreeMap::new();
    for r in rosters {
        let roster_id = as_i64(&r["roster_id"]);
        let owner_id = as_str(&r["owner_id"]);
        let (name, owner) = by_user.get(&owner_id).cloned().unwrap_or_else(|| {
            // An abandoned roster has no owner_id. Name it by roster so the
            // season still balances rather than dropping a team.
            (format!("Roster {roster_id}"), String::new())
        });
        let settings = &r["settings"];
        out.insert(
            roster_id,
            TeamRef {
                roster_id,
                name,
                owner,
                wins: as_i64(&settings["wins"]),
                losses: as_i64(&settings["losses"]),
            },
        );
    }
    if out.is_empty() {
        anyhow::bail!("league {league_id} has no rosters");
    }
    Ok(out)
}

// --------------------------------------------------------------------------- //
// matchups
// --------------------------------------------------------------------------- //

/// One team's line in one week's matchup.
#[derive(Debug, Clone)]
struct WeekEntry {
    roster_id: i64,
    matchup_id: Option<i64>,
    points: f64,
    starters: Vec<String>,
    players: Vec<String>,
    player_points: HashMap<String, f64>,
}

fn week_entries(week_json: &Value) -> Vec<WeekEntry> {
    week_json
        .as_array()
        .map(|rows| {
            rows.iter()
                .map(|m| WeekEntry {
                    roster_id: as_i64(&m["roster_id"]),
                    matchup_id: opt_i64(&m["matchup_id"]),
                    // `custom_points` is a commissioner override and wins when set.
                    points: match &m["custom_points"] {
                        Value::Null => as_f64(&m["points"]),
                        v => as_f64(v),
                    },
                    starters: m["starters"]
                        .as_array()
                        .map(|a| a.iter().map(as_str).collect())
                        .unwrap_or_default(),
                    players: m["players"]
                        .as_array()
                        .map(|a| a.iter().map(as_str).collect())
                        .unwrap_or_default(),
                    player_points: m["players_points"]
                        .as_object()
                        .map(|o| o.iter().map(|(k, v)| (k.clone(), as_f64(v))).collect())
                        .unwrap_or_default(),
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Pair a week's entries into head-to-head games on `matchup_id`.
///
/// A team on a bye (odd league size) has a `matchup_id` all to itself and is
/// dropped rather than emitted as a one-sided game.
fn pair_week(entries: &[WeekEntry]) -> Vec<(WeekEntry, WeekEntry)> {
    let mut by_id: BTreeMap<i64, Vec<&WeekEntry>> = BTreeMap::new();
    for e in entries {
        if let Some(id) = e.matchup_id {
            by_id.entry(id).or_default().push(e);
        }
    }
    by_id
        .into_values()
        .filter(|pair| pair.len() == 2)
        .map(|pair| (pair[0].clone(), pair[1].clone()))
        .collect()
}

fn to_matchup(a: &WeekEntry, b: &WeekEntry, teams: &BTreeMap<i64, TeamRef>) -> Matchup {
    let name = |id: i64| {
        teams
            .get(&id)
            .map(|t| t.name.clone())
            .unwrap_or_else(|| format!("Roster {id}"))
    };
    Matchup {
        teams: vec![
            MatchTeam {
                name: name(a.roster_id),
                score: a.points,
                // A tie makes neither team a winner, matching the Yahoo paths.
                is_winner: a.points > b.points,
            },
            MatchTeam {
                name: name(b.roster_id),
                score: b.points,
                is_winner: b.points > a.points,
            },
        ],
    }
}

// --------------------------------------------------------------------------- //
// rosters
// --------------------------------------------------------------------------- //

/// Translate Sleeper's lineup-slot vocabulary into the Yahoo vocabulary the
/// generator already sorts and groups on (`ROSTER_SLOT_ORDER` in generate.py).
fn slot_label(sleeper_slot: &str) -> String {
    match sleeper_slot {
        "FLEX" => "W/R/T",
        "REC_FLEX" => "W/T",
        "SUPER_FLEX" => "Q/W/R/T",
        "WRRB_FLEX" => "W/R",
        "TAXI" => "BN",
        other => other,
    }
    .to_string()
}

/// The starting slots, in the order `starters[]` is indexed by.
///
/// `roster_positions` lists every slot including the bench; the starters array
/// is positionally aligned with the non-bench prefix of it.
fn starting_slots(league: &Value) -> Vec<String> {
    league["roster_positions"]
        .as_array()
        .map(|a| {
            a.iter()
                .map(as_str)
                .filter(|s| !matches!(s.as_str(), "BN" | "IR" | "TAXI"))
                .map(|s| slot_label(&s))
                .collect()
        })
        .unwrap_or_default()
}

/// Build one team's roster for one week from its matchup entry.
fn roster_for(
    entry: &WeekEntry,
    slots: &[String],
    players: &HashMap<String, (String, String)>,
) -> Roster {
    let mut rows = Vec::with_capacity(entry.players.len());
    let mut seen = Vec::new();

    for (index, player_id) in entry.starters.iter().enumerate() {
        // Sleeper pads an unfilled starting slot with "0".
        if player_id == "0" || player_id.is_empty() {
            continue;
        }
        let slot = slots.get(index).cloned().unwrap_or_else(|| "BN".to_string());
        rows.push(row(player_id, &slot, entry, players));
        seen.push(player_id.clone());
    }
    for player_id in &entry.players {
        if seen.contains(player_id) {
            continue;
        }
        rows.push(row(player_id, "BN", entry, players));
    }
    Roster { players: rows }
}

fn row(
    player_id: &str,
    slot: &str,
    entry: &WeekEntry,
    players: &HashMap<String, (String, String)>,
) -> RosterPlayer {
    let (name, position) = players
        .get(player_id)
        .cloned()
        // A defense is keyed by team abbreviation ("DET"), not a numeric id, and
        // is not in the player dictionary under that key on every refresh.
        .unwrap_or_else(|| (player_id.to_string(), String::new()));
    RosterPlayer {
        name,
        position,
        slot: slot.to_string(),
        points: entry.player_points.get(player_id).copied().unwrap_or(0.0),
    }
}

// --------------------------------------------------------------------------- //
// bracket
// --------------------------------------------------------------------------- //

/// One raw bracket row.
#[derive(Debug, Clone)]
struct BracketRow {
    m: i64,
    r: i64,
    /// Placement this game decides: 1 = championship, 3 = third place, ...
    p: Option<i64>,
    t1: Option<i64>,
    t2: Option<i64>,
    /// `{"w": 3}` = winner of game 3; `{"l": 3}` = loser of game 3.
    t1_from: Option<(char, i64)>,
    t2_from: Option<(char, i64)>,
    w: Option<i64>,
    l: Option<i64>,
}

fn from_ref(v: &Value) -> Option<(char, i64)> {
    if let Some(n) = v.get("w").and_then(Value::as_i64) {
        return Some(('w', n));
    }
    v.get("l").and_then(Value::as_i64).map(|n| ('l', n))
}

fn bracket_rows(json: &Value) -> Vec<BracketRow> {
    json.as_array()
        .map(|rows| {
            rows.iter()
                .map(|g| BracketRow {
                    m: as_i64(&g["m"]),
                    r: as_i64(&g["r"]),
                    p: opt_i64(&g["p"]),
                    t1: opt_i64(&g["t1"]),
                    t2: opt_i64(&g["t2"]),
                    t1_from: g.get("t1_from").and_then(from_ref),
                    t2_from: g.get("t2_from").and_then(from_ref),
                    w: opt_i64(&g["w"]),
                    l: opt_i64(&g["l"]),
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Game ids of the championship path, earliest round first.
///
/// Walks back from the `p == 1` game through winner-feeds only. The consolation
/// games (`p` 3/5/7) run in the same weeks and are excluded, which is exactly
/// what `model::Bracket` documents.
fn title_path(rows: &[BracketRow]) -> Vec<i64> {
    let by_m: HashMap<i64, &BracketRow> = rows.iter().map(|g| (g.m, g)).collect();
    let Some(final_game) = rows.iter().find(|g| g.p == Some(1)) else {
        return Vec::new();
    };

    let mut path = Vec::new();
    let mut stack = vec![final_game.m];
    while let Some(m) = stack.pop() {
        if path.contains(&m) {
            continue;
        }
        path.push(m);
        if let Some(g) = by_m.get(&m) {
            for feed in [g.t1_from, g.t2_from].into_iter().flatten() {
                // Only winners advance toward the title; a loser-feed is the
                // consolation side of the bracket.
                if feed.0 == 'w' {
                    stack.push(feed.1);
                }
            }
        }
    }
    // Earliest round first, then game number, so the render order is stable.
    path.sort_by_key(|m| (by_m.get(m).map(|g| g.r).unwrap_or(0), *m));
    path
}

/// Human label for a round, given how far it is from the final.
fn round_label(rounds_from_final: i64) -> String {
    match rounds_from_final {
        0 => "Final".to_string(),
        1 => "Semifinal".to_string(),
        2 => "Quarterfinal".to_string(),
        n => format!("Round of {}", 1i64 << (n + 1)),
    }
}

fn build_bracket(
    rows: &[BracketRow],
    teams: &BTreeMap<i64, TeamRef>,
    week_scores: &BTreeMap<u32, HashMap<i64, f64>>,
    playoff_week_start: u32,
) -> Option<Bracket> {
    let path = title_path(rows);
    if path.is_empty() {
        return None;
    }
    // Sleeper publishes the bracket's SHAPE as soon as the league is created, so
    // a pre-playoff bracket is a set of empty slots. Emitting that would render
    // a diagram of blank boxes; leaving it None lets the generator fall back to
    // its seeding skeleton until a playoff game is actually decided.
    if !path
        .iter()
        .any(|m| rows.iter().any(|g| g.m == *m && g.w.is_some()))
    {
        return None;
    }
    let by_m: HashMap<i64, &BracketRow> = rows.iter().map(|g| (g.m, g)).collect();
    let final_round = by_m.get(&path[path.len() - 1]).map(|g| g.r).unwrap_or(0);

    // Resolve a slot that is expressed as "winner of game N" rather than a
    // roster id, which is how Sleeper fills every round past the first.
    let resolve = |slot: Option<i64>, feed: Option<(char, i64)>| -> Option<i64> {
        slot.or_else(|| {
            let (kind, m) = feed?;
            let g = by_m.get(&m)?;
            if kind == 'w' { g.w } else { g.l }
        })
    };

    let mut games = Vec::new();
    for m in &path {
        let Some(g) = by_m.get(m) else { continue };
        let week = playoff_week_start + (g.r as u32).saturating_sub(1);
        let scores = week_scores.get(&week);

        let mut match_teams = Vec::new();
        for slot in [
            resolve(g.t1, g.t1_from),
            resolve(g.t2, g.t2_from),
        ]
        .into_iter()
        .flatten()
        {
            match_teams.push(MatchTeam {
                name: teams
                    .get(&slot)
                    .map(|t| t.name.clone())
                    .unwrap_or_else(|| format!("Roster {slot}")),
                score: scores.and_then(|s| s.get(&slot)).copied().unwrap_or(0.0),
                is_winner: g.w == Some(slot),
            });
        }

        // Which game did this winner advance into? `None` for the final.
        let advances_to = rows
            .iter()
            .find(|other| {
                [other.t1_from, other.t2_from]
                    .into_iter()
                    .flatten()
                    .any(|(kind, src)| kind == 'w' && src == *m)
                    && path.contains(&other.m)
            })
            .map(|other| {
                let w = playoff_week_start + (other.r as u32).saturating_sub(1);
                format!("W{w}G{}", other.m)
            });

        games.push(BracketGame {
            id: format!("W{week}G{}", g.m),
            week: week as i64,
            round: round_label(final_round - g.r),
            teams: match_teams,
            advances_to,
        });
    }
    Some(Bracket { games })
}

/// Final playoff-adjusted finish per roster, read off the placement games.
///
/// Sleeper tags each placement game with `p`: the `p == 1` game decides 1st and
/// 2nd, `p == 3` decides 3rd and 4th, and so on. The losers bracket carries its
/// own `p` numbering, offset past the teams that made the playoffs.
fn finishes(
    winners: &[BracketRow],
    losers: &[BracketRow],
    playoff_teams: i64,
) -> BTreeMap<i64, i64> {
    let mut out = BTreeMap::new();
    let mut place = |rows: &[BracketRow], offset: i64| {
        for g in rows {
            let Some(p) = g.p else { continue };
            if let Some(w) = g.w {
                out.insert(w, offset + p);
            }
            if let Some(l) = g.l {
                out.insert(l, offset + p + 1);
            }
        }
    };
    place(winners, 0);
    place(losers, playoff_teams);
    out
}

// --------------------------------------------------------------------------- //
// season assembly
// --------------------------------------------------------------------------- //

/// Build the canonical `Season` from already-fetched payloads.
///
/// `scored_through` is the last week that has actually been played. Sleeper
/// publishes the whole schedule up front, so without this an in-progress season
/// would emit a full slate of 0-0 games as if they had been played.
pub fn build_season(p: &Payloads, scored_through: u32) -> Result<Season> {
    let league = &p.league;
    let league_id = as_str(&league["league_id"]);
    let season: u32 = as_str(&league["season"]).parse().unwrap_or(0);
    let playoff_week_start = as_i64(&league["settings"]["playoff_week_start"]).max(1) as u32;
    let playoff_teams = as_i64(&league["settings"]["playoff_teams"]);

    let teams = team_refs(p, &league_id)?;
    let slots = starting_slots(league);

    let winners = bracket_rows(&p.winners_bracket);
    let losers = bracket_rows(&p.losers_bracket);

    // The postseason runs one week per bracket round. Sleeper schedules matchups
    // for every NFL week regardless, so week 18 of an 18-week schedule is not a
    // playoff week just because it sits past `playoff_week_start`.
    let playoff_rounds = winners.iter().map(|g| g.r).max().unwrap_or(0).max(1) as u32;
    let playoff_week_end = playoff_week_start + playoff_rounds - 1;

    // ---- weekly matchups, point totals and rosters -------------------------
    let mut matchups: BTreeMap<String, Vec<Matchup>> = BTreeMap::new();
    let mut playoff_weeks: BTreeMap<String, Vec<Matchup>> = BTreeMap::new();
    let mut weeks: BTreeMap<String, Week> = BTreeMap::new();
    let mut week_scores: BTreeMap<u32, HashMap<i64, f64>> = BTreeMap::new();
    let mut points_for: HashMap<i64, f64> = HashMap::new();
    let mut points_against: HashMap<i64, f64> = HashMap::new();

    for (&week, json) in &p.matchups {
        if week > scored_through {
            continue;
        }
        let entries = week_entries(json);
        week_scores.insert(
            week,
            entries.iter().map(|e| (e.roster_id, e.points)).collect(),
        );

        let games: Vec<Matchup> = pair_week(&entries)
            .iter()
            .map(|(a, b)| {
                *points_for.entry(a.roster_id).or_default() += a.points;
                *points_for.entry(b.roster_id).or_default() += b.points;
                *points_against.entry(a.roster_id).or_default() += b.points;
                *points_against.entry(b.roster_id).or_default() += a.points;
                to_matchup(a, b, &teams)
            })
            .collect();

        if !games.is_empty() {
            matchups.insert(week.to_string(), games.clone());
            if (playoff_week_start..=playoff_week_end).contains(&week) {
                playoff_weeks.insert(week.to_string(), games);
            }
        }

        if !p.players.is_empty() {
            let rosters: BTreeMap<String, Roster> = entries
                .iter()
                .filter_map(|e| {
                    let name = teams.get(&e.roster_id)?.name.clone();
                    Some((name, roster_for(e, &slots, &p.players)))
                })
                .collect();
            if !rosters.is_empty() {
                weeks.insert(week.to_string(), Week { rosters });
            }
        }
    }

    // ---- bracket, final finish and seeds -----------------------------------
    let finish = finishes(&winners, &losers, playoff_teams);

    // Before a single game is played every team is 0-0 with 0 points, so any
    // "standings order" is just roster id wearing a rank. Rank 0 is what the
    // generator already treats as unknown, so an unplayed season renders as a
    // team list rather than a fabricated finish.
    let played = !matchups.is_empty();

    // Regular-season order, which is how Sleeper seeds the bracket: wins, then
    // points for. Used for `playoff_seed`, and as the finish for a season whose
    // bracket has not been played out yet.
    let mut seeded: Vec<&TeamRef> = teams.values().collect();
    seeded.sort_by(|a, b| {
        b.wins.cmp(&a.wins).then(
            points_for
                .get(&b.roster_id)
                .unwrap_or(&0.0)
                .total_cmp(points_for.get(&a.roster_id).unwrap_or(&0.0)),
        )
    });
    let seed_of: HashMap<i64, i64> = if played {
        seeded
            .iter()
            .enumerate()
            .map(|(index, t)| (t.roster_id, index as i64 + 1))
            .collect()
    } else {
        HashMap::new()
    };

    let bracket = build_bracket(&winners, &teams, &week_scores, playoff_week_start);

    let mut rows: Vec<Team> = teams
        .values()
        .map(|t| Team {
            // Keyed by name, not rank: parse_v2 hit collisions keying on rank.
            team_key: format!("{league_id}-{}", t.name),
            name: t.name.clone(),
            owner: t.owner.clone(),
            wins: t.wins,
            losses: t.losses,
            points_for: points_for.get(&t.roster_id).copied().unwrap_or(0.0),
            points_against: points_against.get(&t.roster_id).copied().unwrap_or(0.0),
            // The bracket is the real finish. Before it is played, fall back to
            // the standings order rather than leaving every team at rank 0.
            rank: finish
                .get(&t.roster_id)
                .copied()
                .or_else(|| seed_of.get(&t.roster_id).copied())
                .unwrap_or(0),
            // Only teams that actually made the bracket carry a seed.
            playoff_seed: seed_of
                .get(&t.roster_id)
                .copied()
                .filter(|&s| s <= playoff_teams),
        })
        .collect();
    // Name breaks the tie so an unplayed season, where every rank is 0, reads as
    // an alphabetical team list rather than Sleeper's roster-id order.
    rows.sort_by(|a, b| a.rank.cmp(&b.rank).then_with(|| a.name.cmp(&b.name)));

    // ---- champions ---------------------------------------------------------
    // Only claimed once the title game has actually been decided; an undecided
    // bracket leaves this None so the generator falls back to the league bible.
    let name_of = |roster_id: i64| {
        teams
            .get(&roster_id)
            .map(|t| t.name.clone())
            .unwrap_or_default()
    };
    let champions = winners
        .iter()
        .find(|g| g.p == Some(1))
        .and_then(|g| Some((g.w?, g.l?)))
        .map(|(champ, runner_up)| Champions {
            champion: name_of(champ),
            runner_up: name_of(runner_up),
            top_seed: seeded.first().map(|t| t.name.clone()).unwrap_or_default(),
            toilet_winner: rows.last().map(|t| t.name.clone()).unwrap_or_default(),
        });

    let standings = Standings { teams: rows };

    Ok(Season {
        season,
        standings: standings.clone(),
        teams: standings,
        draft: build_draft(p, &teams),
        playoffs: Playoffs {
            weeks: playoff_weeks,
        },
        weeks,
        matchups,
        champions,
        bracket,
    })
}

/// Assemble a player's display name from a Sleeper record.
///
/// Shared by the draft board and the player dictionary so both file a player
/// under exactly one name. A team defense has no `full_name` and splits as
/// first_name "Baltimore" / last_name "Ravens"; the Yahoo era filed defenses
/// under the nickname alone ("Ravens", "49ers"), so that is what is used here —
/// otherwise every defense gets a second player page at the platform move.
fn player_name(record: &Value, position: &str) -> String {
    if position == "DEF" {
        return as_str(&record["last_name"]);
    }
    match record.get("full_name").map(as_str) {
        Some(n) if !n.is_empty() => n,
        _ => format!(
            "{} {}",
            as_str(&record["first_name"]),
            as_str(&record["last_name"])
        )
        .trim()
        .to_string(),
    }
}

/// Draft picks. Sleeper embeds the player's name and position in each pick's
/// `metadata`, so this needs no player dictionary, and `pick_no` is already the
/// overall pick number rather than the number within the round.
fn build_draft(p: &Payloads, teams: &BTreeMap<i64, TeamRef>) -> Draft {
    let mut picks: Vec<DraftPick> = p
        .picks
        .as_array()
        .map(|rows| {
            rows.iter()
                .map(|pick| {
                    let meta = &pick["metadata"];
                    let position = as_str(&meta["position"]);
                    let roster_id = as_i64(&pick["roster_id"]);
                    DraftPick {
                        pick: as_i64(&pick["pick_no"]),
                        round: as_i64(&pick["round"]),
                        team: teams
                            .get(&roster_id)
                            .map(|t| t.name.clone())
                            .unwrap_or_else(|| format!("Roster {roster_id}")),
                        player: player_name(meta, &position),
                        position,
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    picks.sort_by_key(|pick| pick.pick);
    Draft {
        draft_results: picks,
    }
}

// --------------------------------------------------------------------------- //
// network
// --------------------------------------------------------------------------- //

async fn get_json(client: &reqwest::Client, url: &str) -> Result<Value> {
    let response = client
        .get(url)
        .send()
        .await
        .with_context(|| format!("GET {url}"))?;
    let status = response.status();
    if !status.is_success() {
        anyhow::bail!("GET {url} -> HTTP {status}");
    }
    response
        .json::<Value>()
        .await
        .with_context(|| format!("{url} did not return JSON"))
}

/// How many weeks of this league have actually been played.
///
/// A finished season is fully scored; the live season is scored through the
/// week before the one the NFL is currently in.
pub async fn scored_through(client: &reqwest::Client, league: &Value) -> Result<u32> {
    if as_str(&league["status"]) == "complete" {
        return Ok(MAX_WEEK);
    }
    let state = get_json(client, &format!("{API_BASE}/state/nfl")).await?;
    let league_season = as_str(&league["season"]);
    let state_season = as_str(&state["season"]);
    if league_season != state_season {
        // A past season that Sleeper has not flagged complete is still over.
        return Ok(if league_season < state_season {
            MAX_WEEK
        } else {
            0
        });
    }
    Ok((as_i64(&state["week"]).max(1) as u32).saturating_sub(1))
}

/// Fetch every payload for one league.
pub async fn fetch_payloads(
    client: &reqwest::Client,
    league_id: &str,
    scored: u32,
    players: HashMap<String, (String, String)>,
) -> Result<Payloads> {
    let league = get_json(client, &format!("{API_BASE}/league/{league_id}")).await?;

    let users = get_json(client, &format!("{API_BASE}/league/{league_id}/users")).await?;
    let rosters = get_json(client, &format!("{API_BASE}/league/{league_id}/rosters")).await?;
    let winners_bracket = get_json(
        client,
        &format!("{API_BASE}/league/{league_id}/winners_bracket"),
    )
    .await
    .unwrap_or(Value::Null);
    let losers_bracket = get_json(
        client,
        &format!("{API_BASE}/league/{league_id}/losers_bracket"),
    )
    .await
    .unwrap_or(Value::Null);

    // The draft id hangs off the league, so no separate /drafts call is needed.
    let draft_id = as_str(&league["draft_id"]);
    let picks = if draft_id.is_empty() {
        Value::Null
    } else {
        get_json(client, &format!("{API_BASE}/draft/{draft_id}/picks"))
            .await
            .unwrap_or(Value::Null)
    };

    let mut matchups = BTreeMap::new();
    for week in 1..=scored.min(MAX_WEEK) {
        let url = format!("{API_BASE}/league/{league_id}/matchups/{week}");
        match get_json(client, &url).await {
            Ok(json) => {
                if json.as_array().is_some_and(|a| a.is_empty()) {
                    break;
                }
                matchups.insert(week, json);
            }
            Err(err) => tracing::warn!("week {week}: {err:#}"),
        }
    }

    Ok(Payloads {
        league,
        users,
        rosters,
        winners_bracket,
        losers_bracket,
        picks,
        matchups,
        players,
    })
}

// --------------------------------------------------------------------------- //
// player dictionary
// --------------------------------------------------------------------------- //

/// `/players/nfl` is ~15 MB and Sleeper's docs ask that it be pulled at most
/// once a day, so it is trimmed to the two fields we need and cached on disk.
pub async fn load_players(
    client: &reqwest::Client,
    cache: &std::path::Path,
) -> Result<HashMap<String, (String, String)>> {
    if let Ok(text) = std::fs::read_to_string(cache) {
        if let Ok(map) = serde_json::from_str::<HashMap<String, (String, String)>>(&text) {
            if !map.is_empty() {
                return Ok(map);
            }
        }
    }

    tracing::info!("fetching Sleeper player dictionary (~15 MB, cached to {cache:?})");
    let all = get_json(client, &format!("{API_BASE}/players/nfl")).await?;
    let mut map = HashMap::new();
    for (player_id, player) in all.as_object().context("players payload is not an object")? {
        let position = as_str(&player["position"]);
        let name = match player_name(player, &position) {
            n if n.is_empty() => player_id.clone(),
            n => n,
        };
        map.insert(player_id.clone(), (name, position));
    }

    if let Some(parent) = cache.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(cache, serde_json::to_string(&map)?)
        .with_context(|| format!("writing player cache {cache:?}"))?;
    Ok(map)
}
